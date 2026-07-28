"""Public BBU lead capture endpoints for static marketing pages."""
import logging
import os

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from src.bbu_ghl.client import GHLClient, is_configured

logger = logging.getLogger(__name__)
router = APIRouter()

_FIELD_NAMES = {
    "agency": "BBU Agency Name",
    "stage": "BBU Agency Size",
    "budget": "BBU Agency Package Budget",
    "source": "BBU Agency Package Lead Source",
}
_field_keys: dict[str, str] = {}


class AgencyPackageLead(BaseModel):
    name: str = Field(default="", max_length=120)
    email: EmailStr
    phone: str = Field(default="", max_length=40)
    agency: str = Field(default="", max_length=160)
    stage: str = Field(max_length=32)
    budget: str = Field(max_length=32)
    website: str = Field(default="", max_length=200)  # Honeypot; must be blank.


def _allowed_origins() -> set[str]:
    configured = os.environ.get("BBU_PUBLIC_LEAD_ORIGINS", "")
    values = configured.split(",") if configured else [
        "https://birthandbabyuniversity.com",
        "https://www.birthandbabyuniversity.com",
    ]
    return {value.strip().rstrip("/") for value in values if value.strip()}


async def _lead_field_keys(ghl: GHLClient) -> dict[str, str]:
    for key, name in _FIELD_NAMES.items():
        if not _field_keys.get(key):
            _field_keys[key] = await ghl.ensure_text_field(name)
    return _field_keys


@router.post("/agency-package", status_code=status.HTTP_201_CREATED)
async def capture_agency_package_lead(lead: AgencyPackageLead, request: Request):
    """Store a qualified Agency Owner Package enquiry in GoHighLevel.

    This endpoint is intentionally public for the static webinar offer page,
    but accepts requests only from the configured BBU marketing origin and uses
    a hidden honeypot to reject basic automated submissions.
    """
    origin = request.headers.get("origin", "").rstrip("/")
    if origin not in _allowed_origins():
        raise HTTPException(status_code=403, detail="This form must be submitted from the BBU website.")
    if lead.website.strip():
        raise HTTPException(status_code=400, detail="Invalid form submission.")
    if lead.stage not in {"solo", "small", "established"}:
        raise HTTPException(status_code=422, detail="Invalid agency stage.")
    if lead.budget not in {"ready", "planning"}:
        raise HTTPException(status_code=422, detail="Invalid budget selection.")
    if not is_configured():
        logger.error("Agency package lead capture requested without GHL configuration")
        raise HTTPException(status_code=503, detail="Lead capture is temporarily unavailable.")

    parts = lead.name.strip().split(None, 1)
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""
    source = "Scale Your Doula Agency webinar offer"

    try:
        async with GHLClient() as ghl:
            keys = await _lead_field_keys(ghl)
            fields = {
                keys["stage"]: lead.stage,
                keys["budget"]: lead.budget,
                keys["source"]: source,
            }
            if lead.agency.strip():
                fields[keys["agency"]] = lead.agency.strip()
            await ghl.upsert_contact(
                email=str(lead.email).lower(),
                first_name=first_name,
                last_name=last_name,
                phone=lead.phone.strip(),
                fields=fields,
                tags=[
                    "bbu-agency-package-lead",
                    "bbu-webinar-scale-jul2026",
                    f"bbu-agency-stage-{lead.stage}",
                    f"bbu-agency-budget-{lead.budget}",
                ],
            )
    except Exception:
        logger.exception("Unable to save Agency Owner Package lead")
        raise HTTPException(status_code=503, detail="Lead capture is temporarily unavailable.")

    return {"ok": True}
