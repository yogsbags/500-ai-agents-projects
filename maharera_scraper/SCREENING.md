# Konkan mega-project screening (₹500 Cr+ / PE–AIF)

Operationalizes the five-phase checklist for **early-stage, project-level equity** opportunities on MahaRERA.

## Eka Life — maiden Category II PERE mandate

This pipeline is tuned for **Eka Life’s first Category II AIF (PERE)** use case: find Maharashtra developers who need **project-level equity** at **₹500 crore+ scale**, not small ticket lending or late-stage construction finance.

| Fund lens | What the screener approximates |
| --- | --- |
| **Ticket size (≥ ₹500 Cr)** | Phase 3: total estimated project cost, implied cost from built-up × ₹8,000/sq ft, or land/premium sub-total ≥ ₹150 Cr (Form 3–style gap where bank debt cannot fund land/FSI) |
| **Early capital structure** | Phase 5: no listed lenders/mortgages on the public RERA finance tab — registration done, **construction finance not yet attached** |
| **Konkan origination focus** | Phase 1: Konkan division guardrail — Mumbai City, Mumbai Suburban, Thane |
| **Fresh registrations** | `--registered-within-days 30`–`90` — teams still freezing equity/debt mix |
| **Product fit** | Residential / mixed — avoids pure commercial shells |

**Suggested outreach tiers (from `pe_aif_opportunity_score`):**

- **≥ 70** — Phase 3 financial trigger **and** Phase 5 capital void; prioritize partner review.
- **40–69** — Partial fit (scale *or* void *or* SRA complexity); analyst pass on Form 3 / encumbrance UI.
- **&lt; 40** — Deprioritize unless strategic relationship.

Automated output is **triage only**. Eka Life IC / legal still needs promoter diligence, title, encumbrance certificates, and confirmation that equity is actually sought at the project SPV level.

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
  --limit 100 \
  --max-pages 20 \
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
