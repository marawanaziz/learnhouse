import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.bbu_ghl import public_router as leads


def _request(origin: str = "https://birthandbabyuniversity.com") -> Request:
    return Request({
        "type": "http",
        "scheme": "https",
        "path": "/api/v1/bbu/leads/agency-package",
        "headers": [(b"origin", origin.encode())],
    })


class _GHL:
    def __init__(self):
        self.field_names = []
        self.upsert = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def ensure_text_field(self, name):
        self.field_names.append(name)
        return f"field_{len(self.field_names)}"

    async def upsert_contact(self, **kwargs):
        self.upsert = kwargs
        return "contact_123"


@pytest.mark.asyncio
async def test_agency_package_lead_is_saved_to_ghl(monkeypatch):
    ghl = _GHL()
    leads._field_keys.clear()
    monkeypatch.setattr(leads, "is_configured", lambda: True)
    monkeypatch.setattr(leads, "GHLClient", lambda: ghl)
    lead = leads.AgencyPackageLead(
        name="Ada Lovelace", email="ada@example.com", phone="312-555-0100",
        agency="Analytical Doulas", stage="small", budget="ready",
    )

    assert await leads.capture_agency_package_lead(lead, _request()) == {"ok": True}
    assert ghl.upsert["email"] == "ada@example.com"
    assert ghl.upsert["first_name"] == "Ada"
    assert ghl.upsert["last_name"] == "Lovelace"
    assert ghl.upsert["phone"] == "312-555-0100"
    assert "bbu-agency-package-lead" in ghl.upsert["tags"]
    assert len(ghl.upsert["fields"]) == 4


@pytest.mark.asyncio
async def test_agency_package_lead_rejects_untrusted_origin(monkeypatch):
    lead = leads.AgencyPackageLead(email="ada@example.com", stage="small", budget="ready")

    with pytest.raises(HTTPException, match="BBU website") as exc:
        await leads.capture_agency_package_lead(lead, _request("https://attacker.example"))

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_agency_package_lead_rejects_honeypot(monkeypatch):
    lead = leads.AgencyPackageLead(
        email="ada@example.com", stage="small", budget="ready", website="spam.example",
    )

    with pytest.raises(HTTPException, match="Invalid form submission") as exc:
        await leads.capture_agency_package_lead(lead, _request())

    assert exc.value.status_code == 400
