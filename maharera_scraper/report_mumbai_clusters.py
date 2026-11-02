#!/usr/bin/env python3
"""Build ≥6.5L sq.ft. Mumbai list with developer/site clusters from enriched JSON."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    from filter_built_up import rows_from_enriched_json
except ModuleNotFoundError:
    from maharera_scraper.filter_built_up import rows_from_enriched_json  # pragma: no cover

CLUSTER_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"new cuffe parade|cuffe parade", re.I), "Lodha — New Cuffe Parade cluster"),
    (re.compile(r"crescent bay", re.I), "Crescent Bay (BPTP / tower-wise regs)"),
    (re.compile(r"indiabulls sky", re.I), "Indiabulls Sky Forest"),
    (re.compile(r"bombay dyeing", re.I), "Bombay Dyeing Mill (WORLI redevelopment)"),
    (re.compile(r"raheja imperia", re.I), "Raheja Imperia"),
    (re.compile(r"kalpataru avana", re.I), "Kalpataru Avana"),
    (re.compile(r"four seasons", re.I), "Four Seasons Private Residences"),
    (re.compile(r"lodha ", re.I), "Lodha (other phase)"),
    (re.compile(r"runwal ", re.I), "Runwal"),
    (re.compile(r"kalpataru ", re.I), "Kalpataru"),
    (re.compile(r"godrej ", re.I), "Godrej"),
    (re.compile(r"oberoi ", re.I), "Oberoi"),
]


def cluster_for_name(name: str) -> str:
    for pattern, label in CLUSTER_RULES:
        if pattern.search(name or ""):
            return label
    return "Other / unclustered"


def promoter_from_project(project: dict) -> str:
    api = project.get("api_details") or {}
    general = api.get("general") or api.get("project_general") or {}
    if isinstance(general, dict):
        for key in ("promoterName", "promoter_name", "organizationName"):
            val = general.get(key)
            if val:
                return str(val).strip()
    return str(project.get("promoter_name") or "").strip()


def load_projects_by_reg(enriched_json: Path) -> dict[str, dict]:
    payload = json.loads(enriched_json.read_text(encoding="utf-8"))
    by_reg: dict[str, dict] = {}
    for row in payload.get("projects") or []:
        reg = str(row.get("registration_number") or "")
        if reg:
            by_reg[reg] = row
    return by_reg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mumbai built-up report with clusters.")
    parser.add_argument("--enriched-json", required=True)
    parser.add_argument("--min-sqft", type=float, default=650_000.0)
    parser.add_argument("--csv", required=True, help="Per-project CSV output")
    parser.add_argument("--clusters-csv", required=True, help="Cluster rollup CSV")
    parser.add_argument("--markdown", default="", help="Optional markdown summary path")
    args = parser.parse_args(argv)

    enriched_path = Path(args.enriched_json)
    by_reg = load_projects_by_reg(enriched_path)
    hits = rows_from_enriched_json(enriched_path, args.min_sqft)
    for row in hits:
        reg = str(row.get("registration_number") or "")
        proj = by_reg.get(reg, {})
        row["cluster"] = cluster_for_name(str(row.get("project_name") or ""))
        row["promoter"] = promoter_from_project(proj)

    fields = list(hits[0].keys()) if hits else []
    if "cluster" not in fields:
        fields.extend(["cluster", "promoter"])

    with Path(args.csv).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(hits)

    roll: dict[str, dict] = defaultdict(lambda: {"registrations": 0, "built_up_sqft": 0.0, "cost_cr": 0.0})
    for row in hits:
        key = row.get("cluster") or "Other"
        roll[key]["registrations"] += 1
        roll[key]["built_up_sqft"] += float(row.get("total_built_up_sqft") or 0)
        roll[key]["cost_cr"] += float(row.get("total_project_cost_cr") or 0)

    cluster_rows = []
    for name, stats in sorted(roll.items(), key=lambda x: -x[1]["built_up_sqft"]):
        cluster_rows.append(
            {
                "cluster": name,
                "registrations": stats["registrations"],
                "aggregate_built_up_lakh_sqft": round(stats["built_up_sqft"] / 100_000, 2),
                "aggregate_cost_cr": round(stats["cost_cr"], 1),
            }
        )

    with Path(args.clusters_csv).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["cluster", "registrations", "aggregate_built_up_lakh_sqft", "aggregate_cost_cr"],
        )
        writer.writeheader()
        writer.writerows(cluster_rows)

    if args.markdown:
        lines = [
            "# Mumbai MahaRERA — projects ≥ 6.5 lakh sq.ft. (built-up)",
            "",
            f"Source: `{enriched_path}` · threshold **{args.min_sqft:,.0f} sq ft** · **{len(hits)}** registrations.",
            "",
            "## By registration (descending built-up)",
            "",
            "| Lakh sq.ft. | ₹ Cr (declared) | Registration | Project | Cluster |",
            "|---:|---:|---|---|---|",
        ]
        for row in hits:
            lines.append(
                f"| {row.get('total_built_up_lakh_sqft')} "
                f"| {round(float(row.get('total_project_cost_cr') or 0), 0)} "
                f"| {row.get('registration_number')} "
                f"| {str(row.get('project_name') or '')[:50]} "
                f"| {row.get('cluster')} |"
            )
        lines.extend(["", "## Developer / site clusters (rollup)", ""])
        for crow in cluster_rows:
            lines.append(
                f"- **{crow['cluster']}**: {crow['registrations']} reg(s), "
                f"~{crow['aggregate_built_up_lakh_sqft']}L sq.ft. aggregate declared cost ~₹{crow['aggregate_cost_cr']} Cr"
            )
        Path(args.markdown).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"{len(hits)} projects -> {args.csv}; {len(cluster_rows)} clusters -> {args.clusters_csv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
