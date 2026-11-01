# Konkan mega-project screening (₹500 Cr+ / PE–AIF)

Operationalizes the five-phase checklist for **early-stage, project-level equity** opportunities on MahaRERA.

## Phase 1 — Live filters (listing discovery)

| Checklist item | CLI / scraper mapping |
| --- | --- |
| Division: Konkan | `--division Konkan` |
| Districts: Mumbai City, Mumbai Suburban, Thane | `--districts "Mumbai City,Mumbai Suburban,Thane"` (default) |
| Registration: last 30–90 days | `--registered-within-days 90` (uses `reraRegistrationDate` after enrichment) |
| Residential / mixed | Excludes pure commercial types in `screening.project_type_allowed` |

The public HTML search does **not** expose a registration-date filter. The screener applies the date window **after** `getProjectGeneralDetailsByProjectId` enrichment.

## Phase 2–5 — Automated signals

| Phase | Source API sections | Trigger logic (defaults) |
| --- | --- | --- |
| 2 Physical | `land_header`, `building_details`, `building_wise_wing_details` | Plot ≥ 10k sqm (Mumbai) / 40k sqm (Thane); ≥ 3 buildings; ≥ 35 floors |
| 3 Financial | `land_header`, `finance_estimated_actual_cost` | Built-up ≥ 6.5 Lakh sq ft **or** land sub-total ≥ ₹150 Cr **or** total/implied cost ≥ ₹500 Cr |
| 4 SRA / transit | `building_wing_rehab`, completion dates | Rehab payload present **or** registration→completion ≥ 5 years |
| 5 Capital void | `finance_bank_details`, `litigation` | Zero lenders and zero litigation rows on the public profile |

Each row gets a **`pe_aif_opportunity_score`** (0–100) and human-readable `signals` / `warnings`.

## Run

```bash
python3 -m pip install -r maharera_scraper/requirements.txt

# Konkan districts via listing (falls back to public-view in --source auto)
python3 maharera_scraper/screen_projects.py \
  --source auto \
  --max-pages 2 \
  --limit 15 \
  --registered-within-days 90 \
  --min-score 40

# Direct public-view sample (when HTML listing host times out)
python3 maharera_scraper/screen_projects.py \
  --source public-view \
  --start-id 8000 \
  --limit 5 \
  --registered-within-days 365 \
  --min-score 0
```

Outputs:

- `maharera-screening.csv` — ranked checklist columns
- `maharera-screening.json` — full `projects` plus `results` and threshold snapshot

## Manual follow-up

Automated screening is a **triage layer**. Confirm Form 3 land/premium lines, encumbrance declarations, and lender attachments in the IT portal UI before outreach.
