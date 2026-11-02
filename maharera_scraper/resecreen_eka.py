#!/usr/bin/env python3
"""Re-run Eka tier screening on saved scrape JSON (no re-fetch)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

try:
    from screen_projects import SCREENING_CSV_FIELDS, build_parser, screen_payload, write_outputs
except ModuleNotFoundError:
    from maharera_scraper.screen_projects import (  # pragma: no cover
        SCREENING_CSV_FIELDS,
        build_parser,
        screen_payload,
        write_outputs,
    )


def resecreen_file(
    json_path: Path,
    *,
    csv_path: Path | None,
    screening_json: Path | None,
    argv: list[str],
) -> dict:
    projects = json.loads(json_path.read_text(encoding="utf-8"))["projects"]
    args = build_parser().parse_args(argv)
    payload = screen_payload(projects, args)
    payload["source_scrape_json"] = str(json_path)
    write_outputs(payload, str(csv_path) if csv_path else None, str(screening_json) if screening_json else None)
    return payload


def merge_scrape_jsons(sources: list[Path], dest: Path) -> int:
    merged: list[dict] = []
    for path in sources:
        if not path.is_file():
            continue
        merged.extend(json.loads(path.read_text(encoding="utf-8")).get("projects") or [])
    if not merged:
        return 0
    dest.write_text(
        json.dumps({"projects": merged, "merged_from": [str(p) for p in sources]}, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(merged)


def merge_csvs(sources: list[Path], dest: Path) -> int:
    rows: list[dict] = []
    for path in sources:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            rows.extend(csv.DictReader(handle))
    if not rows:
        return 0
    with dest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCREENING_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(
            rows,
            key=lambda r: (
                {"A": 3, "B": 2, "C": 1, "—": 0}.get(r.get("eka_tier", "—"), 0),
                int(r.get("pe_aif_opportunity_score") or 0),
                float(r.get("estimated_equity_gap_cr") or 0),
            ),
            reverse=True,
        ):
            writer.writerow(row)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-screen scrape JSON with Eka tier fields.")
    parser.add_argument("json_files", nargs="+", help="Paths to maharera-* scrape JSON files")
    parser.add_argument("--csv-prefix", default="/opt/cursor/artifacts/eka-rescreen")
    parser.add_argument("--merge-csv", default="/opt/cursor/artifacts/eka-konkan-combined-screening.csv")
    parser.add_argument("--registered-within-days", type=int, default=9999)
    parser.add_argument("--min-score", type=int, default=0)
    parser.add_argument("--min-infusion-crore", type=float, default=500.0)
    args, extra = parser.parse_known_args(argv)
    base_argv = [
        "--registered-within-days",
        str(args.registered_within_days),
        "--min-score",
        str(args.min_score),
        "--min-infusion-crore",
        str(args.min_infusion_crore),
    ]
    csv_paths: list[Path] = []
    for json_file in args.json_files:
        path = Path(json_file)
        if not path.is_file():
            print(f"skip missing {path}", file=sys.stderr)
            continue
        stem = path.stem.replace("maharera-", "")
        csv_out = Path(f"{args.csv_prefix}-{stem}.csv")
        json_out = Path(f"{args.csv_prefix}-{stem}.json")
        payload = resecreen_file(
            path,
            csv_path=csv_out,
            screening_json=json_out,
            argv=base_argv + ["--csv", str(csv_out), "--json", str(json_out)],
        )
        csv_paths.append(csv_out)
        tier_a = sum(1 for r in payload["results"] if r.get("eka_tier") == "A")
        print(f"{path.name}: {payload['project_count']} projects, tier A={tier_a} -> {csv_out}")
    if args.merge_csv and csv_paths:
        count = merge_csvs(csv_paths, Path(args.merge_csv))
        print(f"merged {count} rows -> {args.merge_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
