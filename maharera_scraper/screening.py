"""MahaRERA Konkan mega-project screening (₹500 Cr+ / early PE–AIF signals)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable

SQM_TO_SQFT = 10.763910416709722
DEFAULT_COST_PER_SQFT_INR = 8_000
CRORE = 10_000_000  # ₹1 Cr = 1e7

KONKAN_TARGET_DISTRICTS: dict[str, int] = {
    "Mumbai City": 519,
    "Mumbai Suburban": 518,
    "Thane": 517,
}

MUMBAI_DISTRICT_IDS = {518, 519}
RESIDENTIAL_TYPE_KEYWORDS = (
    "residential",
    "mixed",
    "composite",
    "group housing",
)


# Share of construction cost often funded as promoter/project equity before CF (heuristic).
PROMOTER_CONSTRUCTION_EQUITY_SHARE = 0.25

EKA_TIER_ORDER = {"A": 3, "B": 2, "C": 1, "—": 0}


@dataclass(frozen=True)
class ScreeningThresholds:
    min_built_up_sqft: float = 650_000.0
    min_implied_project_cost_crore: float = 500.0
    min_land_premium_cost_crore: float = 150.0
    min_infusion_crore: float = 500.0
    mumbai_min_plot_sqm: float = 10_000.0
    thane_min_plot_sqm: float = 40_000.0
    min_sanctioned_buildings: int = 3
    min_highrise_floors: int = 35
    min_completion_years: float = 5.0
    cost_per_sqft_inr: float = DEFAULT_COST_PER_SQFT_INR


@dataclass
class ScreeningMetrics:
    registration_date: str = ""
    project_type: str = ""
    district: str = ""
    district_id: int | None = None
    plot_area_sqm: float | None = None
    total_built_up_sqm: float | None = None
    total_built_up_sqft: float | None = None
    sanctioned_building_count: int = 0
    max_sanctioned_floors: int | None = None
    land_subtotal_inr: float | None = None
    total_estimated_project_cost_inr: float | None = None
    implied_project_cost_inr: float | None = None
    completion_years: float | None = None
    rehab_component_present: bool = False
    lender_count: int = 0
    litigation_count: int = 0
    finance_rows_with_values: int = 0


@dataclass
class ScreeningResult:
    registration_number: str
    project_name: str
    project_id: str
    detail_url: str
    metrics: ScreeningMetrics
    phase1_eligible: bool
    phase2_physical_trigger: bool
    phase3_financial_trigger: bool
    phase4_sra_transit_trigger: bool
    phase5_capital_void_signal: bool
    pe_aif_opportunity_score: int
    total_project_cost_cr: float | None = None
    land_premium_cost_cr: float | None = None
    estimated_equity_gap_cr: float | None = None
    eka_tier: str = "—"
    eka_fund_fit: bool = False
    signals: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_row(self) -> dict[str, Any]:
        row = {
            "registration_number": self.registration_number,
            "project_name": self.project_name,
            "project_id": self.project_id,
            "detail_url": self.detail_url,
            "eka_tier": self.eka_tier,
            "eka_fund_fit": self.eka_fund_fit,
            "total_project_cost_cr": self.total_project_cost_cr,
            "land_premium_cost_cr": self.land_premium_cost_cr,
            "estimated_equity_gap_cr": self.estimated_equity_gap_cr,
            "phase1_eligible": self.phase1_eligible,
            "phase2_physical_trigger": self.phase2_physical_trigger,
            "phase3_financial_trigger": self.phase3_financial_trigger,
            "phase4_sra_transit_trigger": self.phase4_sra_transit_trigger,
            "phase5_capital_void_signal": self.phase5_capital_void_signal,
            "pe_aif_opportunity_score": self.pe_aif_opportunity_score,
            "signals": " | ".join(self.signals),
            "warnings": " | ".join(self.warnings),
        }
        row.update({f"metric_{k}": v for k, v in asdict(self.metrics).items()})
        return row


def _parse_date(value: str) -> date | None:
    text = (value or "").strip()[:10]
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def registration_within_days(registration_date: str, *, max_days: int, today: date | None = None) -> bool:
    parsed = _parse_date(registration_date)
    if parsed is None:
        return False
    today = today or date.today()
    return today - timedelta(days=max_days) <= parsed <= today


def project_type_allowed(project_type: str) -> bool:
    lowered = (project_type or "").casefold()
    if not lowered:
        return True
    if "commercial" in lowered and not any(k in lowered for k in ("mixed", "composite")):
        return False
    return any(keyword in lowered for keyword in RESIDENTIAL_TYPE_KEYWORDS)


def district_id_from_registration(registration_number: str) -> int | None:
    match = re.fullmatch(r"P(\d{3})\d{8}", (registration_number or "").strip(), re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _finance_rows(api_details: dict[str, Any]) -> list[dict[str, Any]]:
    finance = api_details.get("finance_estimated_actual_cost")
    if not isinstance(finance, dict):
        return []
    rows = finance.get("financeEstimatedActualCost")
    return rows if isinstance(rows, list) else []


def _finance_amount(rows: list[dict[str, Any]], *needles: str) -> float | None:
    for row in rows:
        name = str(row.get("fieldName") or "").casefold()
        if not all(needle in name for needle in needles):
            continue
        for key in ("estimatedCost", "actualCost"):
            value = row.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
    return None


def extract_metrics(project_row: dict[str, Any], api_details: dict[str, Any] | None) -> ScreeningMetrics:
    api_details = api_details or {}
    metrics = ScreeningMetrics(
        registration_date=str(project_row.get("registration_date") or ""),
        project_type=str(project_row.get("project_type") or ""),
        district=str(project_row.get("district") or ""),
    )
    metrics.district_id = district_id_from_registration(str(project_row.get("registration_number") or ""))

    land_header = api_details.get("land_header")
    if isinstance(land_header, dict):
        plot = land_header.get("landAreaSqmts") or land_header.get("proposedLandAreaSqmts")
        if isinstance(plot, (int, float)):
            metrics.plot_area_sqm = float(plot)
        fsi = land_header.get("totalPermissiblePlotFsi") or 0
        non_fsi = land_header.get("projectProposedNotSanctionedBuildUpArea") or 0
        if isinstance(fsi, (int, float)) or isinstance(non_fsi, (int, float)):
            total_sqm = float(fsi or 0) + float(non_fsi or 0)
            metrics.total_built_up_sqm = total_sqm
            metrics.total_built_up_sqft = total_sqm * SQM_TO_SQFT

    buildings = api_details.get("building_details")
    if isinstance(buildings, list):
        metrics.sanctioned_building_count = len(buildings)

    wings = api_details.get("building_wise_wing_details")
    floor_candidates: list[int] = []
    if isinstance(wings, list):
        metrics.sanctioned_building_count = max(metrics.sanctioned_building_count, len(wings))
        for wing in wings:
            for key in (
                "noOfBuildingWingFloorSanctioned",
                "noOfBuildingWingFloorProposed",
                "noOfBuildingWingFloorHabitable",
            ):
                value = wing.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    floor_candidates.append(int(value))
    if floor_candidates:
        metrics.max_sanctioned_floors = max(floor_candidates)

    rows = _finance_rows(api_details)
    metrics.finance_rows_with_values = sum(
        1
        for row in rows
        if isinstance(row.get("estimatedCost"), (int, float)) or isinstance(row.get("actualCost"), (int, float))
    )
    metrics.land_subtotal_inr = _finance_amount(rows, "sub-total", "land")
    metrics.total_estimated_project_cost_inr = _finance_amount(rows, "total cost", "project")
    if metrics.total_built_up_sqft:
        metrics.implied_project_cost_inr = metrics.total_built_up_sqft * DEFAULT_COST_PER_SQFT_INR

    reg = _parse_date(metrics.registration_date)
    completion = _parse_date(str(project_row.get("proposed_completion_date") or ""))
    if reg and completion and completion > reg:
        metrics.completion_years = (completion - reg).days / 365.25

    rehab = api_details.get("building_wing_rehab") or api_details.get("na_plot_rehab_structure")
    metrics.rehab_component_present = bool(rehab) and (
        (isinstance(rehab, list) and len(rehab) > 0) or (isinstance(rehab, dict) and rehab)
    )

    lenders = api_details.get("finance_bank_details")
    if isinstance(lenders, list):
        metrics.lender_count = len(lenders)

    litigation = api_details.get("litigation")
    if isinstance(litigation, list):
        metrics.litigation_count = len(litigation)

    return metrics


def estimate_equity_gap_inr(metrics: ScreeningMetrics) -> float | None:
    """Heuristic equity pool: 100% of land/premium (non-bankable) + 25% of construction."""
    total = metrics.total_estimated_project_cost_inr or metrics.implied_project_cost_inr
    land = metrics.land_subtotal_inr
    if total is None and land is None:
        return None
    total_val = float(total or 0)
    land_val = float(land or 0)
    construction = max(0.0, total_val - land_val)
    return land_val + PROMOTER_CONSTRUCTION_EQUITY_SHARE * construction


def assign_eka_tier(
    *,
    phase1: bool,
    phase3: bool,
    phase5: bool,
    score: int,
    equity_gap_cr: float | None,
    min_infusion_crore: float,
) -> str:
    if not phase1:
        return "—"
    gap = equity_gap_cr or 0.0
    if phase3 and phase5 and gap >= min_infusion_crore and score >= 70:
        return "A"
    if (phase3 or phase5) and score >= 40:
        return "B"
    if score > 0:
        return "C"
    return "—"


def score_project(
    project_row: dict[str, Any],
    api_details: dict[str, Any] | None,
    *,
    registered_within_days: int | None,
    thresholds: ScreeningThresholds | None = None,
    today: date | None = None,
) -> ScreeningResult:
    thresholds = thresholds or ScreeningThresholds()
    metrics = extract_metrics(project_row, api_details)
    signals: list[str] = []
    warnings: list[str] = []

    district_ok = metrics.district_id in set(KONKAN_TARGET_DISTRICTS.values()) or any(
        name.casefold() in (metrics.district or "").casefold()
        for name in KONKAN_TARGET_DISTRICTS
    )
    reg_ok = (
        registered_within_days is None
        or registration_within_days(metrics.registration_date, max_days=registered_within_days, today=today)
    )
    type_ok = project_type_allowed(metrics.project_type)
    phase1 = district_ok and reg_ok and type_ok
    if not district_ok:
        warnings.append("Outside Mumbai City / Mumbai Suburban / Thane guardrail.")
    if registered_within_days is not None and not reg_ok:
        warnings.append(f"Registration not within last {registered_within_days} days.")
    if not type_ok:
        warnings.append("Project type looks commercial-only.")

    plot_threshold = (
        thresholds.mumbai_min_plot_sqm
        if metrics.district_id in MUMBAI_DISTRICT_IDS
        else thresholds.thane_min_plot_sqm
    )
    plot_ok = metrics.plot_area_sqm is not None and metrics.plot_area_sqm >= plot_threshold
    building_ok = metrics.sanctioned_building_count >= thresholds.min_sanctioned_buildings
    floor_ok = (
        metrics.max_sanctioned_floors is not None
        and metrics.max_sanctioned_floors >= thresholds.min_highrise_floors
    )
    phase2 = plot_ok or building_ok or floor_ok
    if plot_ok:
        signals.append(f"Plot area ≥ {plot_threshold:,.0f} sqm")
    if building_ok:
        signals.append(f"≥ {thresholds.min_sanctioned_buildings} buildings/wings in layout")
    if floor_ok:
        signals.append(f"High-rise floor count ≥ {thresholds.min_highrise_floors}")

    built_up_ok = (
        metrics.total_built_up_sqft is not None
        and metrics.total_built_up_sqft >= thresholds.min_built_up_sqft
    )
    land_cr = (metrics.land_subtotal_inr or 0) / CRORE
    land_ok = land_cr >= thresholds.min_land_premium_cost_crore
    reported_total_cr = (metrics.total_estimated_project_cost_inr or 0) / CRORE
    implied_cr = (metrics.implied_project_cost_inr or 0) / CRORE
    cost_ok = (
        reported_total_cr >= thresholds.min_implied_project_cost_crore
        or implied_cr >= thresholds.min_implied_project_cost_crore
    )
    phase3 = built_up_ok or land_ok or cost_ok
    if built_up_ok:
        signals.append(
            f"Built-up ≥ {thresholds.min_built_up_sqft:,.0f} sq ft "
            f"({metrics.total_built_up_sqft:,.0f} sq ft)"
        )
    if land_ok:
        signals.append(f"Land / premium sub-total ≥ ₹{thresholds.min_land_premium_cost_crore:.0f} Cr")
    if cost_ok:
        signals.append(
            "Total/implied project cost ≥ ₹500 Cr "
            f"(reported ₹{reported_total_cr:.1f} Cr, implied ₹{implied_cr:.1f} Cr)"
        )

    completion_ok = (
        metrics.completion_years is not None
        and metrics.completion_years >= thresholds.min_completion_years
    )
    phase4 = metrics.rehab_component_present or completion_ok
    if metrics.rehab_component_present:
        signals.append("Rehab / SRA component present in disclosures")
    if completion_ok:
        signals.append(f"Completion runway ≥ {thresholds.min_completion_years:.0f} years")

    phase5 = metrics.lender_count == 0 and metrics.litigation_count == 0
    if phase5:
        signals.append("No listed lenders / mortgages on public finance tab (early capital structure)")

    score = sum(
        weight
        for weight, flag in (
            (15, phase1),
            (20, phase2),
            (30, phase3),
            (15, phase4),
            (20, phase5),
        )
        if flag
    )

    best_total_cr = max(reported_total_cr, implied_cr, 0.0)
    if best_total_cr <= 0 and metrics.total_estimated_project_cost_inr:
        best_total_cr = metrics.total_estimated_project_cost_inr / CRORE
    equity_gap_inr = estimate_equity_gap_inr(metrics)
    equity_gap_cr = (equity_gap_inr / CRORE) if equity_gap_inr is not None else None
    eka_tier = assign_eka_tier(
        phase1=phase1,
        phase3=phase3,
        phase5=phase5,
        score=score,
        equity_gap_cr=equity_gap_cr,
        min_infusion_crore=thresholds.min_infusion_crore,
    )
    eka_fund_fit = bool(
        phase1
        and phase3
        and equity_gap_cr is not None
        and equity_gap_cr >= thresholds.min_infusion_crore
    )
    if eka_fund_fit:
        signals.append(
            f"Eka Life fund fit: estimated equity gap ≥ ₹{thresholds.min_infusion_crore:.0f} Cr "
            f"(~₹{equity_gap_cr:.1f} Cr)"
        )
    if eka_tier == "A":
        signals.append("Eka tier A: ≥₹500 Cr scale, capital void, Konkan + product fit")

    return ScreeningResult(
        registration_number=str(project_row.get("registration_number") or ""),
        project_name=str(project_row.get("project_name") or ""),
        project_id=str(project_row.get("project_id") or ""),
        detail_url=str(project_row.get("detail_url") or ""),
        metrics=metrics,
        phase1_eligible=phase1,
        phase2_physical_trigger=phase2,
        phase3_financial_trigger=phase3,
        phase4_sra_transit_trigger=phase4,
        phase5_capital_void_signal=phase5,
        pe_aif_opportunity_score=score,
        total_project_cost_cr=round(best_total_cr, 2) if best_total_cr else None,
        land_premium_cost_cr=round(land_cr, 2) if land_cr else None,
        estimated_equity_gap_cr=round(equity_gap_cr, 2) if equity_gap_cr is not None else None,
        eka_tier=eka_tier,
        eka_fund_fit=eka_fund_fit,
        signals=signals,
        warnings=warnings,
    )


def rank_results(results: Iterable[ScreeningResult]) -> list[ScreeningResult]:
    return sorted(
        results,
        key=lambda item: (
            EKA_TIER_ORDER.get(item.eka_tier, 0),
            item.pe_aif_opportunity_score,
            item.estimated_equity_gap_cr or 0,
            item.metrics.total_estimated_project_cost_inr or 0,
        ),
        reverse=True,
    )
