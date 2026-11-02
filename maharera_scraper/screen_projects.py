#!/usr/bin/env python3
"""Run the Konkan mega-project MahaRERA screening checklist."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import scrape_projects as sp
    from screening import (
        KONKAN_TARGET_DISTRICTS,
        ScreeningThresholds,
        rank_results,
        score_project,
    )
except ModuleNotFoundError:  # pragma: no cover
    import maharera_scraper.scrape_projects as sp
    from maharera_scraper.screening import (
        KONKAN_TARGET_DISTRICTS,
        ScreeningThresholds,
        rank_results,
        score_project,
    )


SCREENING_CSV_FIELDS = [
    "registration_number",
    "project_name",
    "project_id",
    "detail_url",
    "eka_tier",
    "eka_fund_fit",
    "estimated_equity_gap_cr",
    "total_project_cost_cr",
    "land_premium_cost_cr",
    "pe_aif_opportunity_score",
    "phase1_eligible",
    "phase2_physical_trigger",
    "phase3_financial_trigger",
    "phase4_sra_transit_trigger",
    "phase5_capital_void_signal",
    "signals",
    "warnings",
    "metric_registration_date",
    "metric_project_type",
    "metric_district",
    "metric_plot_area_sqm",
    "metric_total_built_up_sqft",
    "metric_sanctioned_building_count",
    "metric_max_sanctioned_floors",
    "metric_land_subtotal_inr",
    "metric_total_estimated_project_cost_inr",
    "metric_implied_project_cost_inr",
    "metric_completion_years",
    "metric_rehab_component_present",
    "metric_lender_count",
    "metric_litigation_count",
]


def _parse_districts(raw: str) -> list[str]:
    if not raw.strip():
        return list(KONKAN_TARGET_DISTRICTS.keys())
    return [part.strip() for part in raw.split(",") if part.strip()]


def collect_projects(args: argparse.Namespace) -> list[dict]:
    districts = _parse_districts(args.districts)
    collected: list[dict] = []

    if args.source == "public-view":
        scrape_args = sp.build_parser().parse_args(
            [
                "--source",
                "public-view",
                "--start-id",
                str(args.start_id),
                "--limit",
                str(args.limit),
                "--max-pages",
                str(max(1, (args.limit + 9) // 10)),
                "--project-state",
                args.project_state,
                "--delay",
                str(args.delay),
                "--timeout",
                str(args.timeout),
                "--csv",
                "-",
                "--json",
                "-",
            ]
            + (["--no-enrich-details"] if not args.enrich_details else [])
            + (["--no-full-details"] if not args.full_details else [])
        )
        payload = sp.scrape(scrape_args)
        collected.extend(payload["projects"])
    else:
        for district in districts:
            scrape_args = sp.build_parser().parse_args(
                [
                    "--source",
                    args.source,
                    "--project-division",
                    args.division,
                    "--district",
                    district,
                    "--project-state",
                    args.project_state,
                    "--max-pages",
                    str(args.max_pages),
                    "--delay",
                    str(args.delay),
                    "--timeout",
                    str(args.timeout),
                    "--retries",
                    str(args.retries),
                    "--csv",
                    "-",
                    "--json",
                    "-",
                ]
                + (["--proxy", args.proxy] if args.proxy else [])
                + (["--limit", str(args.limit)] if args.limit else [])
                + (["--no-enrich-details"] if not args.enrich_details else [])
                + (["--no-full-details"] if not args.full_details else [])
            )
            try:
                payload = sp.scrape(scrape_args)
            except sp.ScraperError as exc:
                print(f"warning: district {district!r} scrape failed: {exc}", file=sys.stderr)
                continue
            collected.extend(payload["projects"])
            if args.limit and len(collected) >= args.limit:
                collected = collected[: args.limit]
                break
    return collected


def screen_payload(projects: list[dict], args: argparse.Namespace) -> dict:
    thresholds = ScreeningThresholds(
        min_built_up_sqft=args.min_built_up_sqft,
        min_land_premium_cost_crore=args.min_land_premium_cost_crore,
        min_implied_project_cost_crore=args.min_project_cost_crore,
        min_infusion_crore=args.min_infusion_crore,
        mumbai_min_plot_sqm=args.mumbai_min_plot_sqm,
        thane_min_plot_sqm=args.thane_min_plot_sqm,
        min_sanctioned_buildings=args.min_buildings,
        min_highrise_floors=args.min_floors,
        min_completion_years=args.min_completion_years,
        cost_per_sqft_inr=args.cost_per_sqft,
    )
    results = [
        score_project(
            project,
            project.get("api_details"),
            registered_within_days=args.registered_within_days,
            thresholds=thresholds,
        )
        for project in projects
    ]
    ranked = rank_results(results)
    if args.min_score > 0:
        ranked = [item for item in ranked if item.pe_aif_opportunity_score >= args.min_score]
    return {
        "checklist": "MahaRERA Konkan mega-project / PE-AIF screening",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "division": args.division,
            "districts": _parse_districts(args.districts),
            "registered_within_days": args.registered_within_days,
            "source": args.source,
            "min_score": args.min_score,
        },
        "thresholds": thresholds.__dict__,
        "project_count": len(projects),
        "screened_count": len(ranked),
        "results": [item.to_row() for item in ranked],
        "projects": projects,
    }


def write_outputs(payload: dict, csv_path: str | None, json_path: str | None) -> None:
    if json_path:
        Path(json_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if csv_path:
        with open(csv_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=SCREENING_CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in payload["results"]:
                writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Screen MahaRERA Konkan registrations for ₹500 Cr+ scale and early "
            "project-level PE / Category II AIF signals."
        )
    )
    parser.add_argument("--division", default="Konkan", help="Listing division name. Default: Konkan.")
    parser.add_argument(
        "--districts",
        default="Mumbai City,Mumbai Suburban,Thane",
        help="Comma-separated districts (default Konkan guardrail set).",
    )
    parser.add_argument(
        "--registered-within-days",
        type=int,
        default=90,
        help="Keep projects registered within this many days (Phase 1). Default: 90.",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "listing", "public-view"),
        default="auto",
        help="Where to discover candidates before screening.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Listing pages per district (10 projects per page). Default: 10.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum projects to pull before screening (across all districts). Default: 100.",
    )
    parser.add_argument("--start-id", type=int, default=1, help="Public-view start id when --source public-view.")
    parser.add_argument("--project-state", default=sp.DEFAULT_STATE_CODE)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--proxy", default="")
    parser.add_argument(
        "--enrich-details",
        dest="enrich_details",
        action="store_true",
        default=True,
        help="Authenticate and fetch IT portal detail APIs (default: on).",
    )
    parser.add_argument(
        "--no-enrich-details",
        dest="enrich_details",
        action="store_false",
    )
    parser.add_argument(
        "--full-details",
        dest="full_details",
        action="store_true",
        default=True,
        help="Fetch all public-view detail sections used for underwriting (default: on).",
    )
    parser.add_argument(
        "--no-full-details",
        dest="full_details",
        action="store_false",
    )
    parser.add_argument("--min-score", type=int, default=40, help="Only keep rows at/above this score.")
    parser.add_argument("--min-built-up-sqft", type=float, default=650_000.0)
    parser.add_argument("--min-project-cost-crore", type=float, default=500.0)
    parser.add_argument(
        "--min-infusion-crore",
        type=float,
        default=500.0,
        help="Minimum estimated equity gap (₹ Cr) for eka_fund_fit and tier A. Default: 500.",
    )
    parser.add_argument("--min-land-premium-cost-crore", type=float, default=150.0)
    parser.add_argument("--mumbai-min-plot-sqm", type=float, default=10_000.0)
    parser.add_argument("--thane-min-plot-sqm", type=float, default=40_000.0)
    parser.add_argument("--min-buildings", type=int, default=3)
    parser.add_argument("--min-floors", type=int, default=35)
    parser.add_argument("--min-completion-years", type=float, default=5.0)
    parser.add_argument("--cost-per-sqft", type=float, default=8_000.0)
    parser.add_argument("--csv", default="maharera-screening.csv")
    parser.add_argument("--json", dest="json_path", default="maharera-screening.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    csv_path = None if args.csv == "-" else args.csv
    json_path = None if args.json_path == "-" else args.json_path
    try:
        projects = collect_projects(args)
        payload = screen_payload(projects, args)
    except sp.ScraperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    write_outputs(payload, csv_path, json_path)
    top = payload["results"][:3]
    print(
        f"screened {payload['project_count']} projects, kept {payload['screened_count']} "
        f"with score ≥ {args.min_score}"
        + (f" -> {csv_path}" if csv_path else "")
        + (f" -> {json_path}" if json_path else "")
    )
    for row in top:
        print(
            f"  score {row['pe_aif_opportunity_score']:>3} "
            f"{row['registration_number']} {row['project_name'][:48]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
