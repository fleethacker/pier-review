from fastapi import APIRouter

from mooring import qualification
from mooring.core.schemas import CapabilityRow, CatalogAudit

router = APIRouter(tags=["M2 Reference data"])


@router.get("/qualification", response_model=CatalogAudit, summary="Catalog integrity and per-asset qualification level")
def catalog_audit():
    return qualification.audit_catalog()


@router.get("/capabilities", response_model=list[CapabilityRow],
            summary="What each capability is qualified for today, with limitations and blockers")
def capabilities():
    return qualification.capability_matrix()
