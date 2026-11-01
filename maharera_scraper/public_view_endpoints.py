"""Public project-view POST paths from the IT portal Angular bundle."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

PayloadFactory = Callable[[int], list[dict[str, Any]]]


def _project_id(project_id: int) -> list[dict[str, Any]]:
    return [{"projectId": project_id}]


def _uploaded_documents(project_id: int) -> list[dict[str, Any]]:
    return [
        {"projectId": project_id, "documentSectionName": "Project_Finance", "documentTypeId": [71, 72]},
        {
            "projectId": project_id,
            "documentSectionName": "Project_Technical",
            "documentTypeId": [10, 11, 12, 13, 52],
        },
        {"projectId": project_id, "documentSectionName": "Project_Technical", "documentTypeId": [31]},
    ]


def _professional_by_type(project_id: int) -> list[dict[str, Any]]:
    return [{"projectId": project_id, "professionalTypeId": type_id} for type_id in range(1, 6)]


# Each entry is (storage_key, path_suffix, payload_factory).
# storage_key is stable in JSON output; duplicates get numeric suffixes at runtime.
PUBLIC_VIEW_DETAIL_CALLS: list[tuple[str, str, PayloadFactory]] = [
    ("general_details", "/getProjectGeneralDetailsByProjectId", _project_id),
    ("land_address", "/getProjectLandAddressDetails", _project_id),
    ("promoter_and_project", "/getProjectAndAssociatedPromoterDetails", _project_id),
    ("promoter_address", "/getPromoterAddressDetails", _project_id),
    ("promoter_spoc", "/getPromoterSpocDetails", _project_id),
    ("status_preview", "/getStatusForProjectPreview", _project_id),
    ("building_details", "/getProjectBuildingDetails", _project_id),
    ("building_wise_wing_details", "/getProjectBuildingWiseWingDetails", _project_id),
    ("land_header", "/getProjectLandHeaderDetails", _project_id),
    ("means_of_finance", "/getProjectMeansOfFinance", _project_id),
    ("building_wing_rehab", "/getProjectBuildingWingRehabDetails", _project_id),
    ("na_plot_rehab_structure", "/getProjectNaPlotWithStructureForRehab", _project_id),
    ("building_module_display", "/getProjectBuildingModuleDisplay", _project_id),
    ("blank_building_wings_parking_compliance", "/getBlankBuildingWingsParkingDetailsCompliance", _project_id),
    ("finance_bank_details", "/getProjectFinaceBankDetails", _project_id),
    ("finance_designated_bank_compliance", "/getFinaceDesignatedBankComplianceDetails", _project_id),
    ("finance_balance_cost_receivables", "/getFinanceBalanceCostAndReceivablesDetails", _project_id),
    ("finance_estimated_actual_cost", "/getFinanceEstimatedActualCost", _project_id),
    ("finance_estimated_actual_cost_compliance", "/getFinanceEstimatedActualCostCompliance", _project_id),
    ("finance_inventory", "/getProjectFinanceInventoryDetails", _project_id),
    ("form_clause_master", "/getProjectFormClauseMaster", _project_id),
    ("list_of_promoters", "/getListOfPromoterDetails", _project_id),
    ("litigation", "/getProjectLitigationDetails", _project_id),
    ("na_plot_with_structure", "/getProjectNaPlotWithStructure", _project_id),
    ("na_plot_with_structure_compliance", "/getProjectNaPlotWithStructureCompliance", _project_id),
    ("na_plot_without_structure", "/getProjectNaPlotWithoutStructure", _project_id),
    ("na_plot_without_structure_compliance", "/getProjectNaPlotWithoutStructureComliance", _project_id),
    ("professionals", "/getProjectProfessional", _project_id),
    ("proforma_letters", "/getProjectProformaLetterDetails", _project_id),
    ("sold_unsold_inventory", "/getProjectSoldUnsoldInventory", _project_id),
    ("sold_unsold_inventory_compliance", "/getProjectSoldUnsoldInventoryCompliance", _project_id),
    ("sold_unsold_inventory_correction", "/getProjectSoldUnsoldInventoryCorrection", _project_id),
    ("migrated_documents", "/getMigratedDocuments", _project_id),
    ("past_experience", "/getPastExperienceProjectByProjectIdAndUserProfileId", _project_id),
    ("uploaded_documents", "/getUploadedDocuments", _uploaded_documents),
    ("professionals_by_type", "/getProjectProfessionalByType", _professional_by_type),
]
