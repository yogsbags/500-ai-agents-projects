#!/usr/bin/env python3
"""Full-detail re-enrichment for Eka tier A/B (or score) shortlist."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

import requests

try:
    import scrape_projects as sp
    from resecreen_eka import resecreen_file
    from screening import EKA_TIER_ORDER
except ModuleNotFoundError:
    import maharera_scraper.scrape_projects as sp
    from maharera_scraper.resecreen_eka import resecreen_file
    from maharera_scraper.screening import EKA_TIER_ORDER


def load_projects(scrape_json: Path) -> dict[int, dict]:
    payload = json.loads(scrape_json.read_text(encoding="utf-8"))
    by_id: dict[int, dict] = {}
    for row in payload.get("projects") or []:
        pid = row.get("project_id") or ""
        if str(pid).isdigit():
            by_id[int(pid)] = row
        else:
            url = str(row.get("detail_url") or "")
            parsed = sp.project_id_from_detail_url(url)
            if parsed is not None:
                by_id[parsed] = row
    return by_id


def load_shortlist_ids(
    screening_csv: Path,
    *,
    tiers: set[str],
    min_score: int,
) -> list[int]:
    ids: list[int] = []
    with screening_csv.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            tier = row.get("eka_tier") or "—"
            score = int(row.get("pe_aif_opportunity_score") or 0)
            if tier not in tiers and score < min_score:
                continue
            pid = row.get("project_id") or ""
            if str(pid).isdigit():
                ids.append(int(pid))
    return ids


def ids_from_enrich_log(log_path: Path) -> set[int]:
    if not log_path.is_file():
        return set()
    ids: set[int] = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        match = re.search(r"enriched id (\d+):", line)
        if match:
            ids.add(int(match.group(1)))
    return ids


def full_enrich_projects_fixed(
    project_ids: list[int],
    projects_by_id: dict[int, dict],
    *,
    delay: float,
    timeout: float,
    retries: int,
    checkpoint_json: Path | None,
    existing: list[dict],
) -> list[dict]:
    bundle = sp.it_portal_ca_bundle()
    Project = sp.Project
    session = sp.make_it_portal_session(verify=bundle)
    sp.authenticate_public_view(session, referer_project_id=project_ids[0] if project_ids else 1, timeout=timeout)
    enriched: list[dict] = list(existing)
    done_ids = {int(row.get("project_id") or 0) for row in enriched if str(row.get("project_id") or "").isdigit()}
    last_at = 0.0
    for project_id in project_ids:
        if project_id in done_ids:
            continue
        base = projects_by_id.get(project_id) or {}
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            if last_at and delay > 0:
                wait = delay - (time.monotonic() - last_at)
                if wait > 0:
                    time.sleep(wait)
            try:
                project = None
                general = sp._it_portal_json(
                    session,
                    sp.PUBLIC_VIEW_URL,
                    {"projectId": project_id},
                    timeout=timeout,
                )
                if str(general.get("status")) == "1":
                    project = sp.project_from_public_view(general.get("responseObject") or {})
                if project is None:
                    project = sp.project_from_public_view(
                        {"projectId": project_id, "projectName": base.get("project_name", "")}
                    )
                if project is None:
                    break
                for key, value in base.items():
                    if key in Project.__dataclass_fields__ and value not in (None, ""):
                        setattr(project, key, value)
                sp.enrich_project_public_view(
                    session,
                    project,
                    project_id,
                    timeout=timeout,
                    delay=delay,
                    full_details=True,
                )
                last_at = time.monotonic()
                row = asdict(project)
                enriched.append(row)
                done_ids.add(project_id)
                print(
                    f"enriched id {project_id}: {project.registration_number} "
                    f"{project.project_name[:40]}",
                    file=sys.stderr,
                )
                if checkpoint_json and len(enriched) % 5 == 0:
                    checkpoint_json.write_text(
                        json.dumps({"projects": enriched}, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                last_error = None
                break
            except (
                sp.ScraperError,
                requests.Timeout,
                requests.ConnectionError,
                requests.HTTPError,
            ) as exc:
                if isinstance(exc, requests.HTTPError):
                    status = exc.response.status_code if exc.response is not None else 0
                    if status not in {429, 500, 502, 503, 504}:
                        raise
                last_error = exc
                if attempt >= retries:
                    print(f"failed id {project_id} after {retries + 1} attempts: {exc}", file=sys.stderr)
                else:
                    time.sleep(delay * (2**attempt))
        if last_error is not None:
            continue
    if checkpoint_json:
        checkpoint_json.write_text(
            json.dumps({"projects": enriched}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return enriched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Full-detail enrich Eka shortlist and re-screen.")
    parser.add_argument("--scrape-json", required=True, help="Source scrape JSON with project rows")
    parser.add_argument("--screening-csv", required=True, help="CSV with eka_tier / scores")
    parser.add_argument("--tiers", default="A,B", help="Comma-separated tiers to enrich. Default: A,B")
    parser.add_argument("--min-score", type=int, default=40, help="Also enrich when score >= this")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=3, help="Retries per project on timeout/5xx.")
    parser.add_argument(
        "--merge-existing-json",
        default="",
        help="Projects JSON to keep (resume); skipped ids also enriched again unless --skip-log is set.",
    )
    parser.add_argument(
        "--skip-log",
        default="",
        help="Enrich log file; project ids already listed as enriched id N: are skipped.",
    )
    parser.add_argument("--out-json", default="/opt/cursor/artifacts/eka-shortlist-enriched.json")
    parser.add_argument("--out-screening-csv", default="/opt/cursor/artifacts/eka-shortlist-enriched-screening.csv")
    parser.add_argument("--out-screening-json", default="/opt/cursor/artifacts/eka-shortlist-enriched-screening.json")
    args = parser.parse_args(argv)

    tiers = {part.strip() for part in args.tiers.split(",") if part.strip()}
    scrape_json = Path(args.scrape_json)
    screening_csv = Path(args.screening_csv)
    project_ids = load_shortlist_ids(screening_csv, tiers=tiers, min_score=args.min_score)
    if not project_ids:
        print("No shortlist ids matched tier/score filters.", file=sys.stderr)
        return 0
    skip = ids_from_enrich_log(Path(args.skip_log)) if args.skip_log else set()
    if skip:
        project_ids = [pid for pid in project_ids if pid not in skip]
    existing: list[dict] = []
    if args.merge_existing_json:
        existing = json.loads(Path(args.merge_existing_json).read_text(encoding="utf-8")).get("projects") or []
    projects_by_id = load_projects(scrape_json)
    enriched = full_enrich_projects_fixed(
        project_ids,
        projects_by_id,
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        checkpoint_json=Path(args.out_json),
        existing=existing,
    )
    out_json = Path(args.out_json)
    payload = {
        "source_scrape_json": str(scrape_json),
        "screening_csv": str(screening_csv),
        "tiers": sorted(tiers),
        "project_ids": project_ids,
        "projects": enriched,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resecreen_file(
        out_json,
        csv_path=Path(args.out_screening_csv),
        screening_json=Path(args.out_screening_json),
        argv=[
            "--registered-within-days",
            "9999",
            "--min-score",
            "0",
            "--min-infusion-crore",
            "500",
            "--csv",
            str(args.out_screening_csv),
            "--json",
            str(args.out_screening_json),
        ],
    )
    results = json.loads(Path(args.out_screening_json).read_text(encoding="utf-8"))["results"]
    results.sort(
        key=lambda r: (
            EKA_TIER_ORDER.get(r.get("eka_tier", "—"), 0),
            int(r.get("pe_aif_opportunity_score") or 0),
        ),
        reverse=True,
    )
    for row in results[:10]:
        print(
            row.get("eka_tier"),
            row.get("estimated_equity_gap_cr"),
            row.get("registration_number"),
            row.get("project_name", "")[:45],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
