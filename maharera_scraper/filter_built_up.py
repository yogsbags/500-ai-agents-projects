#!/usr/bin/env python3
"""Filter screening CSV or enriched JSON by minimum total built-up sq.ft."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

try:
    from screening import extract_metrics
except ModuleNotFoundError:
    from maharera_scraper.screening import extract_metrics  # pragma: no cover


def rows_from_enriched_json(path: Path, min_sqft: float) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    projects = payload.get("projects") or []
    out: list[dict] = []
    for project in projects:
        metrics = extract_metrics(project, project.get("api_details"))
        sqft = metrics.total_built_up_sqft or 0.0
        if sqft < min_sqft:
            continue
        out.append(
            {
                "registration_number": project.get("registration_number"),
                "project_name": project.get("project_name"),
                "project_id": project.get("project_id"),
                "district": project.get("district") or metrics.district,
                "total_built_up_sqft": round(sqft, 2),
                "total_built_up_lakh_sqft": round(sqft / 100_000, 2),
                "plot_area_sqm": metrics.plot_area_sqm,
                "total_project_cost_cr": (metrics.total_estimated_project_cost_inr or 0) / 1e7,
                "sanctioned_building_count": metrics.sanctioned_building_count,
                "max_sanctioned_floors": metrics.max_sanctioned_floors,
            }
        )
    out.sort(key=lambda r: float(r["total_built_up_sqft"]), reverse=True)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List projects at or above a built-up sq.ft. threshold.")
    parser.add_argument("--enriched-json", required=True, help="Full-detail enrich output JSON")
    parser.add_argument("--min-sqft", type=float, default=650_000.0, help="Minimum total built-up sq.ft.")
    parser.add_argument("--csv", default="-", help="Output CSV path (- for stdout)")
    args = parser.parse_args(argv)

    rows = rows_from_enriched_json(Path(args.enriched_json), args.min_sqft)
    fields = list(rows[0].keys()) if rows else [
        "registration_number",
        "project_name",
        "project_id",
        "district",
        "total_built_up_sqft",
        "total_built_up_lakh_sqft",
        "plot_area_sqm",
        "total_project_cost_cr",
        "sanctioned_building_count",
        "max_sanctioned_floors",
    ]
    if args.csv == "-":
        writer = csv.DictWriter(sys.stdout, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    else:
        out = Path(args.csv)
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"{len(rows)} projects >= {args.min_sqft:,.0f} sq ft -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
