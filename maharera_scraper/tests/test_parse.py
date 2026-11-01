import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrape_projects import (
    Client,
    build_listing_url,
    filter_projects,
    match_option,
    parse_listing,
    parse_options,
    project_from_public_view,
)

FIXTURE = Path(__file__).parent / "fixtures" / "listing_page.html"


class ParseListingTests(unittest.TestCase):
    def setUp(self):
        self.page = parse_listing(
            FIXTURE.read_text(encoding="utf-8"),
            "https://maharera.maharashtra.gov.in/projects-search-result?page=1",
        )

    def test_public_card_fields(self):
        self.assertTrue(self.page.is_listing_document)
        self.assertEqual(self.page.reported_total, 45030)
        self.assertEqual(self.page.reported_pages, 4503)
        self.assertEqual(self.page.current_page, 1)
        self.assertEqual(self.page.listing_status, "registered")
        self.assertIn("page=2", self.page.next_url)
        self.assertEqual(len(self.page.projects), 2)

        first = self.page.projects[0]
        self.assertEqual(first.registration_number, "P50500000005")
        self.assertEqual(first.project_name, "GREEN CITY 3")
        self.assertEqual(first.promoter_name, "GREEN SPACE INFRA VENTURES")
        self.assertEqual(first.taluka, "Nagpur (Rural)")
        self.assertEqual(first.district, "Nagpur")
        self.assertEqual(first.state, "MAHARASHTRA")
        self.assertEqual(first.pincode, "441108")
        self.assertEqual(first.last_modified, "2017-05-20")
        self.assertTrue(first.certificate_available)
        self.assertFalse(first.extension_certificate_available)
        self.assertEqual(first.latitude, "21.017065000000000")
        self.assertEqual(first.longitude, "79.058966000000000")
        self.assertEqual(
            first.detail_url,
            "https://maharerait.maharashtra.gov.in/public/project/view/1",
        )
        self.assertEqual(
            first.original_application_url,
            "https://maharerait.maharashtra.gov.in/public/project/view/1?isOriginal=true",
        )

        second = self.page.projects[1]
        self.assertEqual(second.registration_number, "P51700002065")
        self.assertEqual(second.district, "Thane")
        self.assertIsNone(second.latitude)
        self.assertTrue(second.extension_certificate_available)

    def test_district_filter_uses_card_text(self):
        kept = filter_projects(self.page.projects, "thane")
        self.assertEqual([project.registration_number for project in kept], ["P51700002065"])


class OptionTests(unittest.TestCase):
    def test_parse_and_match_options(self):
        html = """
        <select>
          <option value="">District</option>
          <option value="0">All</option>
          <option value="21">Pune</option>
          <option value="22">Thane</option>
        </select>
        """
        options = parse_options(html)
        self.assertEqual(options, [("21", "Pune"), ("22", "Thane")])
        self.assertEqual(match_option(options, "pune"), [("21", "Pune")])
        self.assertEqual(match_option(options, "Mumbai"), [])

    def test_listing_url_uses_portal_parameter_names(self):
        url = build_listing_url(
            project_name="GREEN CITY",
            project_location="411001",
            project_state="27",
            project_district="21",
            project_division="4",
            page=2,
        )
        self.assertTrue(url.startswith("https://maharera.maharashtra.gov.in/projects-search-result?"))
        for part in (
            "project_name=GREEN+CITY",
            "project_location=411001",
            "project_state=27",
            "project_district=21",
            "project_division=4",
            "page=2",
        ):
            self.assertIn(part, url)
        self.assertNotIn("project_type=", url)


class PublicViewTests(unittest.TestCase):
    def test_maps_open_general_details_and_drops_fees(self):
        project = project_from_public_view(
            {
                "projectId": 1,
                "projectName": "GREEN CITY 3",
                "projectRegistartionNo": "P50500000005",
                "projectStatusName": "Ongoing",
                "projectTypeName": "Residential / Group Housing",
                "projectLocationName": "Maharashtra",
                "reraRegistrationDate": "2017-05-20",
                "projectProposeComplitionDate": "2018-12-31",
                "registrationCertificateGenerationDate": "2017-05-20",
                "promoterName": None,
                "projectFeesPayableAmount": 82072.1,
                "userProfileId": 121110,
                "registrationCertificateDmsRefNo": "do-not-keep",
            }
        )
        self.assertIsNotNone(project)
        self.assertEqual(project.registration_number, "P50500000005")
        self.assertEqual(project.project_name, "GREEN CITY 3")
        self.assertEqual(project.listing_status, "Ongoing")
        self.assertEqual(project.state, "Maharashtra")
        self.assertEqual(project.registration_date, "2017-05-20")
        self.assertTrue(project.certificate_available)
        self.assertEqual(project.district, "")
        self.assertEqual(
            project.detail_url,
            "https://maharerait.maharashtra.gov.in/public/project/view/1",
        )
        self.assertNotIn("82072", str(project))
        self.assertNotIn("do-not-keep", str(project))
        self.assertNotIn("121110", str(project))


class ProxyTests(unittest.TestCase):
    def test_proxy_flag_is_applied_to_the_session(self):
        client = Client(delay=0, retries=0, timeout=1, proxy="http://127.0.0.1:9")
        self.assertEqual(client.session.proxies["https"], "http://127.0.0.1:9")
        self.assertEqual(client.session.proxies["http"], "http://127.0.0.1:9")


if __name__ == "__main__":
    unittest.main()
