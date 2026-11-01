import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from screening import (
    extract_metrics,
    project_type_allowed,
    registration_within_days,
    score_project,
)


class ScreeningTests(unittest.TestCase):
    def test_registration_window(self):
        recent = (date.today() - timedelta(days=10)).isoformat()
        self.assertTrue(registration_within_days(recent, max_days=90))
        old = (date.today() - timedelta(days=200)).isoformat()
        self.assertFalse(registration_within_days(old, max_days=90))

    def test_project_type_filter(self):
        self.assertTrue(project_type_allowed("Residential / Group Housing"))
        self.assertTrue(project_type_allowed("Mixed Development"))
        self.assertFalse(project_type_allowed("Commercial Office"))

    def test_scores_large_financial_project(self):
        project = {
            "registration_number": "P51700000002",
            "project_name": "MEGA TEST",
            "project_id": "3",
            "detail_url": "https://example.com/3",
            "registration_date": date.today().isoformat(),
            "proposed_completion_date": (date.today().replace(year=date.today().year + 6)).isoformat(),
            "project_type": "Residential / Group Housing",
            "district": "Thane",
        }
        api_details = {
            "land_header": {
                "landAreaSqmts": 45000,
                "totalPermissiblePlotFsi": 70000,
                "projectProposedNotSanctionedBuildUpArea": 5000,
            },
            "building_details": [{}, {}, {}],
            "building_wise_wing_details": [
                {"noOfBuildingWingFloorSanctioned": 40},
                {"noOfBuildingWingFloorSanctioned": 42},
            ],
            "finance_estimated_actual_cost": {
                "financeEstimatedActualCost": [
                    {
                        "fieldName": "Sub-total of land costs",
                        "estimatedCost": 1600000000,
                    },
                    {
                        "fieldName": "Total Cost of Project(Estimated)",
                        "estimatedCost": 6200000000,
                    },
                ]
            },
            "finance_bank_details": [],
            "litigation": [],
            "building_wing_rehab": [{"rehab": True}],
        }
        metrics = extract_metrics(project, api_details)
        self.assertGreater(metrics.total_built_up_sqft or 0, 650_000)
        result = score_project(
            project,
            api_details,
            registered_within_days=90,
        )
        self.assertTrue(result.phase1_eligible)
        self.assertTrue(result.phase3_financial_trigger)
        self.assertTrue(result.phase5_capital_void_signal)
        self.assertGreaterEqual(result.pe_aif_opportunity_score, 70)


if __name__ == "__main__":
    unittest.main()
