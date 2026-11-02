#!/usr/bin/env python3
"""Download public MahaRERA registered-project cards.

The official portal renders the visitor listing at
https://maharera.maharashtra.gov.in/projects-search-result
Ten cards per page. The same page's search form loads division and district
ids from two public GET endpoints. This client only calls those URLs.

It does not solve CAPTCHAs, use third-party captcha services, or open certificate modals.
Optional enrichment uses the same public-view authenticatePublic call as the IT portal page.
"""

from __future__ import annotations

import argparse
import base64
import copy
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Hash import MD5

try:
    from public_view_endpoints import PUBLIC_VIEW_DETAIL_CALLS
except ModuleNotFoundError:  # pragma: no cover - package import from repo root
    from maharera_scraper.public_view_endpoints import PUBLIC_VIEW_DETAIL_CALLS

BASE_URL = "https://maharera.maharashtra.gov.in"
IT_ORIGIN = "https://maharerait.maharashtra.gov.in"
LISTING_PATH = "/projects-search-result"
# Public "View Details" call used by /public/project/view/{id}. No login.
PUBLIC_VIEW_URL = (
    IT_ORIGIN
    + "/api/maha-rera-public-view-project-registration-service"
    + "/public/projectregistartion/getProjectGeneralDetailsByProjectId"
)
DISTRICT_LIST_URL = IT_ORIGIN + "/api/maha-rera-mdm-service/mdm/getDistrictList"
PUBLIC_VIEW_API_BASE = (
    IT_ORIGIN
    + "/api/maha-rera-public-view-project-registration-service/public/projectregistartion"
)
LOGIN_API_URL = IT_ORIGIN + "/api/maha-rera-login-service/login/authenticatePublic"
# Same passphrase and credentials as the public project-view Angular bundle.
PUBLIC_VIEW_ENCRYPT_PASSPHRASE = "sdjhfsdkjgkls74385385"
PUBLIC_VIEW_USERNAME = "@maharera_public_view"
PUBLIC_VIEW_PASSWORD = "Maharera!@$1"
# AIA CA Issuers URL on the live maharerait certificate. The server sends a
# different, older intermediate, so Python cannot build the chain until this
# one is present. It chains to GlobalSign Root R46, which is in the system store.
GLOBALSIGN_R46_OV_2025_URL = "http://secure.globalsign.com/cacert/gsgccr46ovtlsca2025.crt"
GLOBALSIGN_R46_OV_2025_CN = "GlobalSign GCC R46 OV TLS CA 2025"
DIVISION_PATH = "/get-division-data"
DISTRICT_PATH = "/div-district-data"
# Maharashtra, from the public project_state <select> on the search form.
DEFAULT_STATE_CODE = "27"
USER_AGENT = (
    "MahaRERAPublicScraper/1.0 "
    "(+https://maharera.maharashtra.gov.in/projects-search-result; "
    "public registered-projects listing; polite, low volume)"
)

CSV_FIELDS = [
    "registration_number",
    "project_name",
    "promoter_name",
    "taluka",
    "district",
    "state",
    "pincode",
    "last_modified",
    "listing_status",
    "certificate_available",
    "extension_certificate_available",
    "latitude",
    "longitude",
    "detail_url",
    "original_application_url",
    "source_page_url",
    "project_type",
    "registration_date",
    "proposed_completion_date",
    "record_source",
    "project_id",
    "acknowledgement_number",
    "project_description",
    "project_current_status",
    "project_application_date",
    "address_line",
    "street",
    "locality",
    "village",
    "boundaries_east",
    "boundaries_west",
    "boundaries_north",
    "boundaries_south",
    "promoter_contact_person",
    "promoter_office_building",
    "promoter_office_district",
    "promoter_office_taluka",
    "promoter_office_pincode",
    "promoter_mobile",
    "promoter_email",
    "user_profile_id",
    "is_building",
    "total_number_of_units",
    "total_number_of_sold_units",
    "project_fees_payable_amount",
    "registration_certificate_dms_ref_no",
    "extension_certificate_dms_ref_no",
    "receipt_file_name",
    "revised_completion_date",
    "rerasubmission_number",
]


class ScraperError(Exception):
    """A listing request or parse failed."""


class LookupError(ScraperError):
    """A public dropdown endpoint could not be read."""


@dataclass
class Project:
    registration_number: str
    project_name: str
    promoter_name: str
    taluka: str
    district: str
    state: str
    pincode: str
    last_modified: str
    listing_status: str
    certificate_available: bool
    extension_certificate_available: bool
    latitude: str | None
    longitude: str | None
    detail_url: str
    original_application_url: str
    source_page_url: str
    project_type: str = ""
    registration_date: str = ""
    proposed_completion_date: str = ""
    record_source: str = "listing"
    project_id: str = ""
    acknowledgement_number: str = ""
    project_description: str = ""
    project_current_status: str = ""
    project_application_date: str = ""
    address_line: str = ""
    street: str = ""
    locality: str = ""
    village: str = ""
    boundaries_east: str = ""
    boundaries_west: str = ""
    boundaries_north: str = ""
    boundaries_south: str = ""
    promoter_contact_person: str = ""
    promoter_office_building: str = ""
    promoter_office_district: str = ""
    promoter_office_taluka: str = ""
    promoter_office_pincode: str = ""
    promoter_mobile: str = ""
    promoter_email: str = ""
    user_profile_id: str = ""
    is_building: str = ""
    total_number_of_units: str = ""
    total_number_of_sold_units: str = ""
    project_fees_payable_amount: str = ""
    registration_certificate_dms_ref_no: str = ""
    extension_certificate_dms_ref_no: str = ""
    receipt_file_name: str = ""
    revised_completion_date: str = ""
    rerasubmission_number: str = ""
    api_details: dict[str, Any] | None = None


@dataclass
class ListingPage:
    projects: list[Project]
    reported_total: int | None
    reported_pages: int | None
    current_page: int | None
    next_url: str | None
    listing_status: str
    is_listing_document: bool


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _flag_present(column, flag: str) -> bool:
    link = column.find("a")
    if link is None:
        return False
    marker = (link.get("data-qstr-flag") or "").strip()
    label = _clean(link.get_text(" ", strip=True)).upper()
    if label == "N/A":
        return False
    return marker == flag


def _coords(href: str) -> tuple[str | None, str | None]:
    query = parse_qs(urlparse(href).query).get("query", [""])[0]
    if "," not in query:
        return None, None
    lat, lng = (part.strip() for part in query.split(",", 1))
    if not lat or not lng:
        return None, None
    return lat, lng


def _column_value(column, label: str) -> str:
    heading = column.find(class_="greyColor")
    if heading is not None:
        heading.extract()
    return _clean(column.get_text(" ", strip=True))


def parse_listing(html: str, source_page_url: str) -> ListingPage:
    """Parse one public search-result document."""
    soup = BeautifulSoup(html, "html.parser")
    is_listing = soup.select_one("#projects-search-page-form") is not None or bool(
        soup.select("div.row.shadow")
    )
    chips = [_clean(node.get_text(" ", strip=True)) for node in soup.select("a.projectSerHist")]
    listing_status = "registered"
    for chip in chips:
        lowered = chip.lower()
        if "revok" in lowered:
            listing_status = "revoked"
        elif "registered" in lowered:
            listing_status = "registered"

    reported_total = None
    reported_pages = None
    current_page = None
    counter = soup.select_one("span.pagesCount")
    if counter is not None:
        raw_total = (counter.get("data-total") or "").replace(",", "")
        raw_pages = (counter.get("data-current-data") or "").replace(",", "")
        raw_current = _clean(counter.get_text(" ", strip=True)).replace(",", "")
        if raw_total.isdigit():
            reported_total = int(raw_total)
        if raw_pages.isdigit():
            reported_pages = int(raw_pages)
        if raw_current.isdigit():
            current_page = int(raw_current)
    if reported_total is None:
        match = re.search(
            r"Showing Final\s+([\d,]+)\s+Result",
            soup.get_text(" ", strip=True),
        )
        if match:
            reported_total = int(match.group(1).replace(",", ""))

    projects: list[Project] = []
    for card in soup.select("div.row.shadow"):
        reg_node = card.select_one("p.p-0")
        reg_text = _clean(reg_node.get_text(" ", strip=True) if reg_node else "")
        if not reg_text.startswith("#"):
            continue
        registration_number = reg_text.lstrip("#").strip()
        name_node = card.select_one("h4")
        promoter_node = card.select_one("p.darkBlue")
        taluka = ""
        latitude = None
        longitude = None
        for link in card.select("ul.listingList a"):
            label = _clean(link.get_text(" ", strip=True))
            if not label or label.lower() == "find route":
                continue
            taluka = label
            latitude, longitude = _coords(link.get("href") or "")
            break

        fields: dict[str, str] = {}
        certificate_available = False
        extension_available = False
        for column in card.select("div.col-xl-4"):
            heading = column.find(class_="greyColor")
            if heading is None:
                continue
            label = _clean(heading.get_text(" ", strip=True))
            if label == "Certificate":
                certificate_available = _flag_present(column, "DocProjectCert")
            elif label == "Extension Certificate":
                extension_available = _flag_present(column, "DocProjectExtCert")
            elif label and label != "Application":
                fields[label] = _column_value(column, label)

        detail_url = ""
        original_url = ""
        for link in card.select("a[href]"):
            href = urljoin(BASE_URL, link.get("href") or "")
            if "/public/project/view/" not in href:
                continue
            if "isOriginal=true" in href:
                original_url = href
            elif not detail_url:
                detail_url = href

        projects.append(
            Project(
                registration_number=registration_number,
                project_name=_clean(name_node.get_text(" ", strip=True) if name_node else ""),
                promoter_name=_clean(
                    promoter_node.get_text(" ", strip=True) if promoter_node else ""
                ),
                taluka=taluka,
                district=fields.get("District", ""),
                state=fields.get("State", ""),
                pincode=fields.get("Pincode", ""),
                last_modified=fields.get("Last Modified", ""),
                listing_status=listing_status,
                certificate_available=certificate_available,
                extension_certificate_available=extension_available,
                latitude=latitude,
                longitude=longitude,
                detail_url=detail_url,
                original_application_url=original_url,
                source_page_url=source_page_url,
            )
        )

    next_node = soup.select_one("a.next[href]")
    next_url = urljoin(source_page_url, next_node["href"]) if next_node else None
    return ListingPage(
        projects=projects,
        reported_total=reported_total,
        reported_pages=reported_pages,
        current_page=current_page,
        next_url=next_url,
        listing_status=listing_status,
        is_listing_document=is_listing
        and (
            bool(projects)
            or reported_total is not None
            or soup.select_one("#projects-search-page-form") is not None
        ),
    )


def parse_options(html: str) -> list[tuple[str, str]]:
    """Read <option> pairs from a division or district dropdown response."""
    soup = BeautifulSoup(html, "html.parser")
    options: list[tuple[str, str]] = []
    for node in soup.select("option"):
        value = (node.get("value") or "").strip()
        label = _clean(node.get_text(" ", strip=True))
        if not value or value == "0" or not label:
            continue
        if label.casefold() in {"division", "district", "select", "select state", "select district"}:
            continue
        options.append((value, label))
    return options


def match_option(options: Iterable[tuple[str, str]], name: str) -> list[tuple[str, str]]:
    wanted = " ".join(name.split()).casefold()
    return [(value, label) for value, label in options if label.casefold() == wanted]


def listing_params(
    *,
    project_name: str = "",
    project_location: str = "",
    project_state: str = DEFAULT_STATE_CODE,
    project_district: str = "0",
    project_division: str = "",
    project_type: str | None = None,
    page: int = 1,
) -> dict[str, str]:
    """Query string used by the public pager on the search results page."""
    params = {
        "project_name": project_name,
        "project_location": project_location,
        "project_completion_date": "",
        "project_state": project_state,
        "project_district": project_district or "0",
        "carpetAreas": "",
        "completionPercentages": "",
        "project_division": project_division,
        "page": str(page),
        "op": "",
    }
    # The default public list is Registered Projects and its pager omits this.
    # Revoked Projects is the form radio project_type=1.
    if project_type:
        params["project_type"] = project_type
    return params


def build_listing_url(**kwargs) -> str:
    return f"{BASE_URL}{LISTING_PATH}?{urlencode(listing_params(**kwargs))}"


class Client:
    def __init__(
        self,
        *,
        delay: float,
        retries: int,
        timeout: float,
        proxy: str | None = None,
    ) -> None:
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en",
            }
        )
        # A forward proxy the operator already runs. The session also honors
        # HTTPS_PROXY from the environment. This is ordinary egress, not a
        # second host or a rotated address pool.
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self._last_request_at = 0.0

    def _pause(self) -> None:
        if self._last_request_at:
            wait = self.delay - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)

    def get_text(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._pause()
            try:
                response = self.session.get(url, timeout=self.timeout)
                self._last_request_at = time.monotonic()
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise ScraperError(
                        f"HTTP {response.status_code} from {response.url}"
                    )
                response.raise_for_status()
                response.encoding = response.encoding or "utf-8"
                return response.text
            except (requests.Timeout, requests.ConnectionError, ScraperError) as exc:
                last_error = exc
                self._last_request_at = time.monotonic()
                if attempt >= self.retries:
                    break
                time.sleep(self.delay * (2**attempt))
        raise ScraperError(
            f"Gave up after {self.retries + 1} attempts for {url}: {last_error}"
        ) from last_error

    def get_listing(self, url: str) -> ListingPage:
        html = self.get_text(url)
        page = parse_listing(html, url)
        if not page.is_listing_document:
            title = _clean(BeautifulSoup(html, "html.parser").title.get_text()) if "<title" in html.lower() else ""
            raise ScraperError(
                "Response was not the public projects-search-result listing"
                + (f" (title: {title})" if title else "")
            )
        return page


def _division_urls(state_code: str) -> list[str]:
    # The project-state dropdown calls the first URL. Some archived responses
    # also include the form field names, so try that public variant second.
    plain = f"{BASE_URL}{DIVISION_PATH}?{urlencode({'stateCode': state_code, 'langID': '1'})}"
    formed = (
        f"{BASE_URL}{DIVISION_PATH}?"
        + urlencode(
            {
                "stateCode": state_code,
                "langID": "1",
                "form_code": "custom_search_form",
                "field_code": "project_division",
            }
        )
    )
    return [plain, formed]


def _district_url(state_code: str, division_code: str) -> str:
    # distruct_field is the parameter name in the portal's own script.
    return (
        f"{BASE_URL}{DISTRICT_PATH}?"
        + urlencode(
            {
                "state_code": state_code,
                "lang_id": "1",
                "division_code": division_code,
                "district_form": "custom_search_form",
                "distruct_field": "project_district",
            }
        )
    )


def resolve_place_filters(
    client: Client,
    *,
    state_code: str,
    division: str,
    district: str,
) -> tuple[str, str, str | None]:
    """Map a district or division name to the ids the listing query expects.

    Returns (division_id, district_id, district_label_or_none).
    A numeric argument is sent through as an id. A name is resolved with the
    public dropdown endpoints. district_label is set when the caller asked for
    a name, so rows can be checked against the card's District text.
    """
    division_id = ""
    district_id = "0"
    district_label: str | None = None

    if division:
        if division.isdigit():
            division_id = division
        else:
            divisions = _load_divisions(client, state_code)
            found = match_option(divisions, division)
            if len(found) != 1:
                known = ", ".join(label for _, label in divisions) or "(none returned)"
                raise ScraperError(
                    f"Division {division!r} did not match one public division option. "
                    f"Known: {known}"
                )
            division_id = found[0][0]

    if not district:
        return division_id, district_id, None

    if district.isdigit():
        return division_id, district, None

    district_label = " ".join(district.split())
    divisions = [(division_id, division)] if division_id else _load_divisions(client, state_code)
    if not divisions:
        raise ScraperError(
            "The public division dropdown returned no options, so the district "
            f"name {district_label!r} could not be turned into project_district."
        )
    matches: list[tuple[str, str, str]] = []
    errors: list[str] = []
    saw_dropdown = False
    for div_id, _div_label in divisions:
        try:
            options = parse_options(client.get_text(_district_url(state_code, div_id)))
        except ScraperError as exc:
            errors.append(str(exc))
            continue
        saw_dropdown = True
        for value, label in match_option(options, district_label):
            matches.append((div_id, value, label))
    if not saw_dropdown:
        raise LookupError(
            "Could not read the public district dropdown. " + " | ".join(errors)
        )
    if len(matches) != 1:
        rendered = ", ".join(f"{label} (division {div_id}, id {value})" for div_id, value, label in matches)
        raise ScraperError(
            f"District {district_label!r} matched {len(matches)} public district options"
            + (f": {rendered}" if rendered else "")
            + ". Pass --project-division to narrow it, or pass the numeric project_district id."
        )
    division_id, district_id, district_label = matches[0]
    return division_id, district_id, district_label


def _load_divisions(client: Client, state_code: str) -> list[tuple[str, str]]:
    errors: list[str] = []
    for url in _division_urls(state_code):
        try:
            options = parse_options(client.get_text(url))
        except ScraperError as exc:
            errors.append(str(exc))
            continue
        if options:
            return options
        errors.append(f"no options in {url}")
    raise LookupError(
        "Could not read the public division dropdown. " + " | ".join(errors)
    )


def _transport_failure(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "timed out",
            "timeout",
            "handshake",
            "connection aborted",
            "connection reset",
            "failed to establish",
        )
    )


def it_portal_ca_bundle() -> str:
    """Trust store plus the intermediate the IT portal certificate ommits.

    The downloaded certificate is kept only when OpenSSL says it chains to a
    root already in the system store and its subject is the expected issuer.
    """
    import certifi

    cached = os.environ.get("MAHARERA_CA_BUNDLE", "").strip()
    if cached and os.path.isfile(cached):
        return cached

    response = requests.get(
        GLOBALSIGN_R46_OV_2025_URL,
        timeout=20,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    directory = tempfile.mkdtemp(prefix="maharera-ca-")
    der_path = f"{directory}/intermediate.crt"
    pem_path = f"{directory}/intermediate.pem"
    bundle_path = f"{directory}/ca-bundle.pem"
    with open(der_path, "wb") as handle:
        handle.write(response.content)
    subprocess.run(
        ["openssl", "x509", "-inform", "DER", "-in", der_path, "-out", pem_path],
        check=True,
        capture_output=True,
    )
    subject = subprocess.run(
        ["openssl", "x509", "-in", pem_path, "-noout", "-subject"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if GLOBALSIGN_R46_OV_2025_CN not in subject:
        raise ScraperError("GlobalSign intermediate subject did not match the IT portal issuer")
    verified = subprocess.run(["openssl", "verify", pem_path], capture_output=True, text=True)
    if verified.returncode != 0:
        raise ScraperError(
            "GlobalSign intermediate did not chain to a system trust root: "
            + (verified.stderr or verified.stdout).strip()
        )
    with open(bundle_path, "wb") as handle:
        handle.write(open(certifi.where(), "rb").read())
        handle.write(b"\n")
        handle.write(open(pem_path, "rb").read())
    return bundle_path


def _cryptojs_evp_bytes_to_key(
    password: bytes, salt: bytes, key_len: int, iv_len: int
) -> tuple[bytes, bytes]:
    derived = b""
    block = b""
    while len(derived) < key_len + iv_len:
        block = MD5.new(block + password + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len : key_len + iv_len]


def cryptojs_encrypt(plaintext: str, passphrase: str, *, salt: bytes | None = None) -> str:
    """OpenSSL-compatible AES-256-CBC encryption (CryptoJS default format)."""
    salt = salt if salt is not None else os.urandom(8)
    key, iv = _cryptojs_evp_bytes_to_key(passphrase.encode("utf-8"), salt, 32, 16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    pad = 16 - (len(plaintext) % 16)
    payload = plaintext.encode("utf-8") + bytes([pad]) * pad
    ciphertext = cipher.encrypt(payload)
    return base64.b64encode(b"Salted__" + salt + ciphertext).decode("ascii")


def project_id_from_detail_url(url: str) -> int | None:
    match = re.search(r"/public/project/view/(\d+)", url or "", re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def make_it_portal_session(*, verify: str, proxy: str | None = None) -> requests.Session:
    session = requests.Session()
    session.verify = verify
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": IT_ORIGIN,
        }
    )
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


def _it_portal_json(
    session: requests.Session,
    url: str,
    payload: dict,
    *,
    timeout: float,
) -> dict:
    response = session.post(url, json=payload, timeout=timeout)
    if response.status_code == 401:
        raise ScraperError(f"HTTP 401 from {url}")
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError as exc:
        raise ScraperError(f"Non-JSON response from {url}") from exc
    return body


def authenticate_public_view(session: requests.Session, *, referer_project_id: int, timeout: float) -> None:
    """Mint a bearer token with the shared public-view credentials from the IT portal."""
    referer = f"{IT_ORIGIN}/public/project/view/{referer_project_id}"
    session.headers["Referer"] = referer
    session.get(referer, timeout=timeout)
    body = {
        "userName": cryptojs_encrypt(PUBLIC_VIEW_USERNAME, PUBLIC_VIEW_ENCRYPT_PASSPHRASE),
        "password": cryptojs_encrypt(PUBLIC_VIEW_PASSWORD, PUBLIC_VIEW_ENCRYPT_PASSPHRASE),
    }
    auth = _it_portal_json(session, LOGIN_API_URL, body, timeout=timeout)
    if str(auth.get("status")) != "1":
        message = str(auth.get("message") or "authenticatePublic failed")
        raise ScraperError(f"Public-view authentication failed: {message}")
    token = (auth.get("responseObject") or {}).get("accessToken")
    if not token:
        raise ScraperError("Public-view authentication returned no access token")
    session.headers["Authorization"] = f"Bearer {token}"


def apply_public_view_enrichment(project: Project, *, land: dict | None, promoter: dict | None) -> None:
    if land:
        if land.get("districtName"):
            project.district = str(land["districtName"]).strip()
        if land.get("stateName"):
            project.state = str(land["stateName"]).strip()
        if land.get("talukaName"):
            project.taluka = str(land["talukaName"]).strip()
        pin = land.get("pinCode")
        if pin not in (None, ""):
            project.pincode = str(pin).strip()
    if promoter:
        name = promoter.get("promoterName")
        if name:
            project.promoter_name = str(name).strip()
        if not project.taluka and promoter.get("talukaName"):
            project.taluka = str(promoter["talukaName"]).strip()
        if not project.district and promoter.get("districtName"):
            project.district = str(promoter["districtName"]).strip()
        if not project.state and promoter.get("stateName"):
            project.state = str(promoter["stateName"]).strip()
        if not project.pincode and promoter.get("pincode") not in (None, ""):
            project.pincode = str(promoter["pincode"]).strip()


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def fetch_public_view_api_details(
    session: requests.Session,
    project_id: int,
    *,
    timeout: float,
    delay: float,
    full_details: bool,
) -> dict[str, Any]:
    """Call public-view detail endpoints and return responseObject payloads keyed by name."""
    collected: dict[str, Any] = {}
    last_request_at = 0.0
    calls = PUBLIC_VIEW_DETAIL_CALLS if full_details else [
        ("general_details", "/getProjectGeneralDetailsByProjectId", lambda pid: [{"projectId": pid}]),
        ("land_address", "/getProjectLandAddressDetails", lambda pid: [{"projectId": pid}]),
        (
            "promoter_and_project",
            "/getProjectAndAssociatedPromoterDetails",
            lambda pid: [{"projectId": pid}],
        ),
    ]

    for storage_key, path_suffix, payload_factory in calls:
        payloads = payload_factory(project_id)
        bucket: list[Any] = []
        for payload in payloads:
            if last_request_at and delay > 0:
                wait = delay - (time.monotonic() - last_request_at)
                if wait > 0:
                    time.sleep(wait)
            url = f"{PUBLIC_VIEW_API_BASE}{path_suffix}"
            try:
                body = _it_portal_json(session, url, payload, timeout=timeout)
            except ScraperError:
                last_request_at = time.monotonic()
                continue
            last_request_at = time.monotonic()
            if str(body.get("status")) != "1":
                continue
            response_object = body.get("responseObject")
            if response_object is None:
                continue
            if len(payloads) == 1:
                collected[storage_key] = response_object
            else:
                bucket.append({"request": payload, "response": response_object})
        if bucket:
            collected[storage_key] = bucket
    return collected


def apply_api_details_to_project(project: Project, api_details: dict[str, Any]) -> None:
    general = api_details.get("general_details")
    if isinstance(general, dict):
        if general.get("projectId") is not None:
            project.project_id = _scalar(general.get("projectId"))
        project.acknowledgement_number = _scalar(general.get("acknowledgementNumber"))
        project.project_description = _scalar(general.get("projectDescription"))
        project.project_current_status = _scalar(general.get("projectCurrentStatus"))
        project.project_application_date = _scalar(general.get("projectApplicationDate"))[:10]
        project.user_profile_id = _scalar(general.get("userProfileId"))
        project.is_building = _scalar(general.get("isBuilding"))
        project.total_number_of_units = _scalar(general.get("totalNumberOfUnits"))
        project.total_number_of_sold_units = _scalar(general.get("totalNumberOfSoldUnits"))
        project.project_fees_payable_amount = _scalar(general.get("projectFeesPayableAmount"))
        project.registration_certificate_dms_ref_no = _scalar(
            general.get("registrationCertificateDmsRefNo")
        )
        project.extension_certificate_dms_ref_no = _scalar(
            general.get("extensionCertificateDmsRefNo")
        )
        project.receipt_file_name = _scalar(general.get("receiptFileName"))
        project.revised_completion_date = _scalar(general.get("revisedDate"))[:10]
        project.rerasubmission_number = _scalar(general.get("rerasubmissionNumber"))
        if general.get("projectTypeName"):
            project.project_type = _scalar(general.get("projectTypeName"))
        if general.get("projectStatusName"):
            project.listing_status = _scalar(general.get("projectStatusName"))
        if general.get("reraRegistrationDate"):
            project.registration_date = _scalar(general.get("reraRegistrationDate"))[:10]
        if general.get("projectProposeComplitionDate"):
            project.proposed_completion_date = _scalar(general.get("projectProposeComplitionDate"))[:10]
        if general.get("promoterName"):
            project.promoter_name = _scalar(general.get("promoterName"))

    land = api_details.get("land_address")
    if isinstance(land, dict):
        apply_public_view_enrichment(project, land=land, promoter=None)
        project.address_line = _scalar(land.get("addressLine"))
        project.street = _scalar(land.get("street"))
        project.locality = _scalar(land.get("locality"))
        project.village = _scalar(land.get("villageName"))
        project.boundaries_east = _scalar(land.get("boundariesEast"))
        project.boundaries_west = _scalar(land.get("boundariesWest"))
        project.boundaries_north = _scalar(land.get("boundariesNorth"))
        project.boundaries_south = _scalar(land.get("boundariesSouth"))

    promoter_bundle = api_details.get("promoter_and_project")
    promoter = None
    legal_land = None
    if isinstance(promoter_bundle, dict):
        promoter = promoter_bundle.get("promoterDetails")
        project_details = promoter_bundle.get("projectDetails") or {}
        legal_land = project_details.get("projectLegalLandAddressDetails")
    apply_public_view_enrichment(project, land=legal_land, promoter=promoter)
    if isinstance(promoter, dict):
        project.promoter_contact_person = _scalar(promoter.get("contactPersonName"))
        project.promoter_office_building = _scalar(promoter.get("buildingName"))
        project.promoter_office_district = _scalar(promoter.get("districtName"))
        project.promoter_office_taluka = _scalar(promoter.get("talukaName"))
        project.promoter_office_pincode = _scalar(promoter.get("pincode"))
        project.promoter_mobile = _scalar(promoter.get("mobileNo"))
        project.promoter_email = _scalar(promoter.get("emailId"))


def enrich_project_public_view(
    session: requests.Session,
    project: Project,
    project_id: int,
    *,
    timeout: float,
    delay: float,
    full_details: bool,
) -> None:
    api_details = fetch_public_view_api_details(
        session,
        project_id,
        timeout=timeout,
        delay=delay,
        full_details=full_details,
    )
    project.api_details = api_details or None
    apply_api_details_to_project(project, api_details)


def project_from_public_view(payload: dict) -> Project | None:
    """Map the public general-details object. Document ids and fees are left out."""
    if not payload:
        return None
    registration = str(
        payload.get("projectRegistartionNo") or payload.get("projectRegistrationNo") or ""
    ).strip()
    name = str(payload.get("projectName") or "").strip()
    if not registration and not name:
        return None
    project_id = payload.get("projectId")
    detail_url = f"{IT_ORIGIN}/public/project/view/{project_id}" if project_id else ""
    project_id_text = _scalar(project_id)
    certificate_date = str(payload.get("registrationCertificateGenerationDate") or "").strip()
    extension_name = payload.get("extensionCertificateFileName")
    return Project(
        registration_number=registration,
        project_name=name,
        promoter_name=str(payload.get("promoterName") or "").strip(),
        taluka="",
        district="",
        state=str(payload.get("projectLocationName") or "").strip(),
        pincode="",
        last_modified="",
        listing_status=str(payload.get("projectStatusName") or "").strip(),
        certificate_available=bool(certificate_date),
        extension_certificate_available=bool(extension_name),
        latitude=None,
        longitude=None,
        detail_url=detail_url,
        original_application_url="",
        source_page_url=detail_url,
        project_type=str(payload.get("projectTypeName") or "").strip(),
        registration_date=str(payload.get("reraRegistrationDate") or "")[:10],
        proposed_completion_date=str(payload.get("projectProposeComplitionDate") or "")[:10],
        record_source="public-view",
        project_id=project_id_text,
    )


def district_id_from_registration(registration_number: str) -> int | None:
    """Older MahaRERA numbers are P + a 3-digit district id + 8 digits.

    P51700000002 is district id 517. Newer PR/PM/PC/PP numbers do not use this.
    """
    match = re.fullmatch(r"P(\d{3})\d{8}", (registration_number or "").strip(), re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def apply_registration_district(project: Project, districts_by_id: dict[int, str]) -> None:
    if project.district:
        return
    district_id = district_id_from_registration(project.registration_number)
    if district_id is None:
        return
    name = districts_by_id.get(district_id)
    if name:
        project.district = name


def fetch_district_names(session: requests.Session, state_id: str, timeout: float) -> dict[int, str]:
    response = session.post(
        DISTRICT_LIST_URL,
        json={"stateId": int(state_id)},
        timeout=timeout,
    )
    if response.status_code == 401:
        raise ScraperError("Public district list returned HTTP 401.")
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError as exc:
        raise ScraperError("Public district list was not JSON") from exc
    names: dict[int, str] = {}
    for row in body.get("responseObject") or []:
        try:
            names[int(row["districtId"])] = str(row["districtName"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
    if not names:
        raise ScraperError("Public district list was empty")
    return names


def scrape_public_view(args: argparse.Namespace) -> dict:
    """Sample projects from the public project-view API on the IT portal."""
    bundle = it_portal_ca_bundle()
    session = make_it_portal_session(verify=bundle, proxy=args.proxy or None)
    if args.enrich_details:
        authenticate_public_view(session, referer_project_id=args.start_id, timeout=args.timeout)
    districts_by_id = fetch_district_names(session, args.project_state, args.timeout)
    district_label = " ".join(args.project_district.split()) if args.project_district else ""
    wanted = args.limit if args.limit is not None else args.max_pages * 10
    # Sequential project ids are sparse; scan more ids when a district filter drops rows.
    scan_multiplier = 50 if district_label else 10
    default_scan = max(500 if district_label else 5000, wanted * scan_multiplier)
    max_attempts = args.max_id_scan if args.max_id_scan is not None else default_scan
    max_attempts = max(max_attempts, wanted)
    collected: list[Project] = []
    project_id = args.start_id
    attempts = 0
    last_request_at = 0.0
    while len(collected) < wanted and attempts < max_attempts:
        if last_request_at:
            wait = args.delay - (time.monotonic() - last_request_at)
            if wait > 0:
                time.sleep(wait)
        attempts += 1
        try:
            response = session.post(
                PUBLIC_VIEW_URL,
                json={"projectId": project_id},
                timeout=args.timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise ScraperError(f"Public project view failed for id {project_id}: {exc}") from exc
        last_request_at = time.monotonic()
        if response.status_code == 401:
            raise ScraperError(
                "Public project view returned HTTP 401. This client does not log in."
            )
        project = None
        if response.status_code == 200:
            try:
                body = response.json()
            except ValueError:
                body = {}
            if str(body.get("status")) == "1":
                project = project_from_public_view(body.get("responseObject") or {})
        if project is not None:
            apply_registration_district(project, districts_by_id)
            if district_label and not filter_projects([project], district_label):
                print(
                    f"public view id {project_id}: {project.registration_number} "
                    f"{project.district or 'unknown district'} (skipped district filter)",
                    file=sys.stderr,
                )
            else:
                if args.enrich_details:
                    if last_request_at:
                        wait = args.delay - (time.monotonic() - last_request_at)
                        if wait > 0:
                            time.sleep(wait)
                    try:
                        enrich_project_public_view(
                            session,
                            project,
                            project_id,
                            timeout=args.timeout,
                            delay=args.delay,
                            full_details=args.full_details,
                        )
                    except (requests.Timeout, requests.ConnectionError, ScraperError) as exc:
                        raise ScraperError(
                            f"Public-view enrichment failed for id {project_id}: {exc}"
                        ) from exc
                    last_request_at = time.monotonic()
                collected.append(project)
                print(
                    f"public view id {project_id}: {project.registration_number} "
                    f"{project.project_name} ({project.district or 'no district'})",
                    file=sys.stderr,
                )
        else:
            print(f"public view id {project_id}: no public project", file=sys.stderr)
        project_id += 1
    return {
        "source": PUBLIC_VIEW_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "project_name": args.project_name,
            "project_state": args.project_state,
            "start_id": args.start_id,
            "limit": wanted,
            "district_name": district_label,
            "project_type": args.project_type,
        },
        "reported_total": None,
        "reported_pages": None,
        "pages_fetched": attempts,
        "listing_status": "public-view",
        "projects": [asdict(project) for project in collected],
    }


def filter_projects(projects: list[Project], district_label: str | None) -> list[Project]:
    if not district_label:
        return projects
    wanted = district_label.casefold()
    return [project for project in projects if project.district.casefold() == wanted]


def scrape_listing(args: argparse.Namespace) -> dict:
    client = Client(
        delay=args.delay,
        retries=args.retries,
        timeout=args.timeout,
        proxy=args.proxy or None,
    )
    project_type = None
    if args.project_type == "revoked":
        project_type = "1"

    try:
        division_id, district_id, district_label = resolve_place_filters(
            client,
            state_code=args.project_state,
            division=args.project_division,
            district=args.project_district,
        )
    except LookupError as exc:
        if args.project_district and not args.project_district.isdigit():
            print(
                f"warning: {exc} Filtering cards by District text instead.",
                file=sys.stderr,
            )
            division_id = args.project_division if args.project_division.isdigit() else ""
            district_id = "0"
            district_label = " ".join(args.project_district.split())
        else:
            raise
    page_number = args.start_page
    url = build_listing_url(
        project_name=args.project_name,
        project_location=args.project_location,
        project_state=args.project_state,
        project_district=district_id,
        project_division=division_id,
        project_type=project_type,
        page=page_number,
    )
    collected: list[Project] = []
    reported_total = None
    reported_pages = None
    pages_fetched = 0
    listing_status = args.project_type

    while url and pages_fetched < args.max_pages:
        if args.limit is not None and len(collected) >= args.limit:
            break
        page = client.get_listing(url)
        pages_fetched += 1
        reported_total = page.reported_total
        reported_pages = page.reported_pages
        listing_status = page.listing_status or listing_status
        rows = filter_projects(page.projects, district_label)
        collected.extend(rows)
        print(
            f"page {page.current_page or page_number}: {len(page.projects)} cards, "
            f"{len(rows)} kept, running total {len(collected)}",
            file=sys.stderr,
        )
        if not page.projects:
            break
        url = page.next_url
        page_number += 1
        if reported_pages is not None and page_number > reported_pages:
            break

    if args.limit is not None:
        collected = collected[: args.limit]

    if args.enrich_details and collected:
        bundle = it_portal_ca_bundle()
        enrich_session = make_it_portal_session(verify=bundle, proxy=args.proxy or None)
        first_id = project_id_from_detail_url(collected[0].detail_url) or 1
        authenticate_public_view(
            enrich_session, referer_project_id=first_id, timeout=args.timeout
        )
        last_enrich_at = 0.0
        for project in collected:
            project_id = project_id_from_detail_url(project.detail_url)
            if project_id is None:
                continue
            if last_enrich_at:
                wait = args.delay - (time.monotonic() - last_enrich_at)
                if wait > 0:
                    time.sleep(wait)
            enrich_project_public_view(
                enrich_session,
                project,
                project_id,
                timeout=args.timeout,
                delay=args.delay,
                full_details=args.full_details,
            )
            last_enrich_at = time.monotonic()

    return {
        "source": f"{BASE_URL}{LISTING_PATH}",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "project_name": args.project_name,
            "project_location": args.project_location,
            "project_state": args.project_state,
            "project_division": division_id,
            "project_district": district_id,
            "district_name": district_label,
            "project_type": args.project_type,
            "start_page": args.start_page,
            "max_pages": args.max_pages,
        },
        "reported_total": reported_total,
        "reported_pages": reported_pages,
        "pages_fetched": pages_fetched,
        "listing_status": listing_status,
        "projects": [asdict(project) for project in collected],
    }


def scrape(args: argparse.Namespace) -> dict:
    if args.source == "public-view":
        return scrape_public_view(args)
    listing_args = args
    if args.source == "auto":
        listing_args = copy.copy(args)
        listing_args.retries = 0
        listing_args.timeout = min(12.0, args.timeout)
    try:
        return scrape_listing(listing_args)
    except ScraperError as exc:
        if args.source == "auto" and _transport_failure(exc):
            sample = args.limit if args.limit is not None else args.max_pages * 10
            print(
                "warning: the HTML listing host did not finish a connection "
                f"({exc}). Falling back to sequential public-view ids on {IT_ORIGIN} "
                f"(about {sample} projects, not the full ~45k listing). For the "
                "complete catalog, run with --source listing from a network that "
                "reaches maharera.maharashtra.gov.in or use --proxy.",
                file=sys.stderr,
            )
            return scrape_public_view(args)
        raise


def write_outputs(payload: dict, csv_path: str | None, json_path: str | None) -> None:
    projects = payload["projects"]
    if json_path:
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    if csv_path:
        with open(csv_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for project in projects:
                row = dict(project)
                row["certificate_available"] = str(bool(row["certificate_available"])).lower()
                row["extension_certificate_available"] = str(
                    bool(row["extension_certificate_available"])
                ).lower()
                for key, value in list(row.items()):
                    if value is None:
                        row[key] = ""
                writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Save a small sample of the public MahaRERA registered-projects "
            "listing (https://maharera.maharashtra.gov.in/projects-search-result)."
        )
    )
    parser.add_argument("--project-name", default="", help="Project name or registration number. Portal field project_name.")
    parser.add_argument(
        "--project-location",
        default="",
        help="Pincode. Portal field project_location (the form placeholder is Pincode).",
    )
    parser.add_argument(
        "--project-state",
        default=DEFAULT_STATE_CODE,
        help="Numeric project_state id. 27 is Maharashtra, the public default. Default: 27.",
    )
    parser.add_argument(
        "--project-division",
        default="",
        help="Division id, or division name resolved via the public division dropdown.",
    )
    parser.add_argument(
        "--project-district",
        "--district",
        dest="project_district",
        default="",
        help=(
            "District name (for example Pune) or numeric project_district id. "
            "A name is resolved with the public district dropdown, then checked against each card."
        ),
    )
    parser.add_argument(
        "--project-type",
        choices=("registered", "revoked"),
        default="registered",
        help="Registered Projects (default public list) or Revoked Projects (project_type=1).",
    )
    parser.add_argument("--start-page", type=int, default=1, help="1-based page, matching the public pager. Default: 1.")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Maximum listing pages to request. Default: 1 (10 projects).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Stop after this many kept projects.")
    parser.add_argument("--delay", type=float, default=1.5, help="Seconds between requests. Default: 1.5.")
    parser.add_argument("--retries", type=int, default=3, help="Retries for timeout, connection errors, and HTTP 429/5xx. Default: 3.")
    parser.add_argument("--timeout", type=float, default=45.0, help="Per-request timeout in seconds. Default: 45.")
    parser.add_argument(
        "--source",
        choices=("auto", "listing", "public-view"),
        default="auto",
        help=(
            "auto tries the HTML listing, then the public project-view API if that "
            "host does not connect. listing stays on the HTML search. public-view "
            "reads getProjectGeneralDetailsByProjectId."
        ),
    )
    enrich = parser.add_mutually_exclusive_group()
    enrich.add_argument(
        "--enrich-details",
        dest="enrich_details",
        action="store_true",
        default=True,
        help=(
            "After each project is found, call the IT portal public-view APIs for "
            "land address and promoter (default: on)."
        ),
    )
    enrich.add_argument(
        "--no-enrich-details",
        dest="enrich_details",
        action="store_false",
        help="Skip authenticatePublic and the land/promoter detail APIs.",
    )
    full = parser.add_mutually_exclusive_group()
    full.add_argument(
        "--full-details",
        dest="full_details",
        action="store_true",
        default=True,
        help=(
            "With enrichment, call every public-view detail endpoint from the "
            "portal bundle and store raw payloads under api_details in JSON "
            "(default: on)."
        ),
    )
    full.add_argument(
        "--no-full-details",
        dest="full_details",
        action="store_false",
        help="Only fetch general, land, and promoter endpoints (faster).",
    )
    parser.add_argument(
        "--start-id",
        type=int,
        default=1,
        help="First project id for --source public-view. Default: 1.",
    )
    parser.add_argument(
        "--max-id-scan",
        type=int,
        default=None,
        help=(
            "For --source public-view only: stop after this many sequential "
            "projectId attempts (found or empty). Default: max(500, wanted×50) "
            "with a district name filter, else max(5000, wanted×10)."
        ),
    )
    parser.add_argument(
        "--proxy",
        default="",
        help=(
            "Forward proxy URL for both HTTP and HTTPS, for example "
            "http://proxy.example:8080. When omitted, HTTPS_PROXY in the "
            "environment is used. The proxy must be one you operate."
        ),
    )
    parser.add_argument("--csv", default="maharera-projects.csv", help="CSV output path. Use - to skip.")
    parser.add_argument("--json", dest="json_path", default="maharera-projects.json", help="JSON output path. Use - to skip.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    if args.start_page < 1:
        parser.error("--start-page must be at least 1")
    if args.start_id < 1:
        parser.error("--start-id must be at least 1")
    if args.max_id_scan is not None and args.max_id_scan < 1:
        parser.error("--max-id-scan must be at least 1")
    if args.delay < 0:
        parser.error("--delay must be >= 0")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    csv_path = None if args.csv == "-" else args.csv
    json_path = None if args.json_path == "-" else args.json_path
    if csv_path is None and json_path is None:
        parser.error("Choose a --csv path, a --json path, or both")
    try:
        payload = scrape(args)
    except ScraperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    write_outputs(payload, csv_path, json_path)
    print(
        f"wrote {len(payload['projects'])} projects"
        + (f" (portal reports {payload['reported_total']})" if payload["reported_total"] is not None else "")
        + (f" -> {csv_path}" if csv_path else "")
        + (f" -> {json_path}" if json_path else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
