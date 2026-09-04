"""Signed Zoom Events registration receiver for the BBU/GHL integration.

This receiver is intentionally narrow. It handles only the two exact Zoom
Events and their participant ticket types, records an event+email+ticket
idempotency receipt, and adds the matching GHL tag. It does not send email,
invoke a workflow, mutate Zoom, or accept arbitrary event/tag mappings.

Zoom's webhook secret is read from ``BBU_ZOOM_EVENTS_WEBHOOK_SECRET`` at request
time. The secret is never returned or written to logs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_ghl.client import GHLClient, is_configured
from src.bbu_ghl.models import BBUZoomEventRegistration
from src.core.events.database import get_db_session

logger = logging.getLogger(__name__)
router = APIRouter()

WEBHOOK_EVENT = "zoom_events.ticket_created"
MAX_TIMESTAMP_SKEW_SECONDS = 300

EVENT_CONFIG: dict[str, dict[str, str]] = {
    "6A7t3t84QBOJ1w9-Ysi35w": {
        "ticket_type_id": "m9tqwEy_Rr-hVONN0bsqmg",
        "tag": "bbu-webinar-ask-a-doula-sep03",
        "label": "Ask a Doula",
    },
    "ATHcbMq5RxqvxPW9ALkA4g": {
        "ticket_type_id": "6iPXCIoSQLmHwryaC-8uew",
        "tag": "bbu-webinar-first90-sep17",
        "label": "First 90 Days",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _signature(timestamp: str, raw_body: bytes, secret: str) -> str:
    message = b"v0:" + timestamp.encode("ascii") + b":" + raw_body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def _challenge_response(plain_token: str, secret: str) -> dict[str, str]:
    encrypted = hmac.new(
        secret.encode("utf-8"), plain_token.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {"plainToken": plain_token, "encryptedToken": encrypted}


def _normalize_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 320 or email.count("@") != 1:
        return ""
    local, domain = email.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        return ""
    return email


def _registration_identity(obj: dict[str, Any]) -> str:
    """Prefer Zoom's stable ticket ID, then documented registration IDs."""
    for key in ("ticket_id", "registration_id", "external_ticket_id"):
        value = str(obj.get(key) or "").strip()
        if value:
            return value[:160]
    return ""


async def _signed_json(request: Request) -> dict[str, Any]:
    raw_body = await request.body()
    secret = os.environ.get("BBU_ZOOM_EVENTS_WEBHOOK_SECRET", "")
    timestamp = request.headers.get("x-zm-request-timestamp", "")
    received_signature = request.headers.get("x-zm-signature", "")

    if not secret or not timestamp or not received_signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")
    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature") from exc
    if abs(int(time.time()) - timestamp_int) > MAX_TIMESTAMP_SKEW_SECONDS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expired webhook signature")
    expected = _signature(timestamp, raw_body, secret)
    if not hmac.compare_digest(received_signature, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")
    return payload


async def _find_receipt(
    db_session: AsyncSession,
    event_id: str,
    email: str,
    registration_identity: str,
) -> BBUZoomEventRegistration | None:
    statement = select(BBUZoomEventRegistration).where(
        BBUZoomEventRegistration.event_id == event_id,
        BBUZoomEventRegistration.email == email,
        BBUZoomEventRegistration.registration_identity == registration_identity,
    )
    return (await db_session.execute(statement)).scalars().first()


@router.get("/health")
async def health() -> dict[str, Any]:
    """Non-sensitive deployment/readiness projection for the exact receiver."""
    return {
        "ok": True,
        "webhook_event": WEBHOOK_EVENT,
        "secret_configured": bool(os.environ.get("BBU_ZOOM_EVENTS_WEBHOOK_SECRET")),
        "ghl_configured": is_configured(),
        "events": {
            event_id: {
                "ticket_type_id": cfg["ticket_type_id"],
                "tag": cfg["tag"],
            }
            for event_id, cfg in EVENT_CONFIG.items()
        },
    }


@router.post("/events")
async def receive_event(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Receive and idempotently apply one signed Zoom ticket-created event."""
    payload = await _signed_json(request)

    if payload.get("event") == "endpoint.url_validation":
        plain_token = str((payload.get("payload") or {}).get("plainToken") or "")
        if not plain_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing validation token")
        secret = os.environ["BBU_ZOOM_EVENTS_WEBHOOK_SECRET"]
        return _challenge_response(plain_token, secret)

    if payload.get("event") != WEBHOOK_EVENT:
        return {"ok": True, "status": "ignored", "event": payload.get("event")}

    obj = ((payload.get("payload") or {}).get("object") or {})
    if not isinstance(obj, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid event object")
    event_id = str(obj.get("event_id") or "").strip()
    cfg = EVENT_CONFIG.get(event_id)
    if not cfg:
        return {"ok": True, "status": "ignored", "reason": "event_not_configured"}
    if str(obj.get("ticket_type_id") or "").strip() != cfg["ticket_type_id"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ticket type is not configured")
    if obj.get("ticket_role_type") and obj.get("ticket_role_type") != "normal":
        return {"ok": True, "status": "ignored", "reason": "non_participant_ticket"}

    email = _normalize_email(obj.get("email"))
    registration_identity = _registration_identity(obj)
    if not email or not registration_identity:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing registration identity")
    if not is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="GHL integration unavailable")

    receipt = await _find_receipt(db_session, event_id, email, registration_identity)
    if receipt and receipt.status == "synced":
        return {
            "ok": True,
            "status": "duplicate",
            "event_id": event_id,
            "ticket_id": registration_identity,
            "contact_id": receipt.ghl_contact_id,
        }
    if receipt and receipt.status == "processing":
        return {"ok": True, "status": "already_processing", "event_id": event_id}

    if not receipt:
        receipt = BBUZoomEventRegistration(
            event_id=event_id,
            ticket_type_id=cfg["ticket_type_id"],
            email=email,
            registration_identity=registration_identity,
            tag=cfg["tag"],
            status="processing",
            received_at=_now(),
            updated_at=_now(),
        )
        db_session.add(receipt)
        try:
            await db_session.commit()
            await db_session.refresh(receipt)
        except IntegrityError:
            await db_session.rollback()
            existing = await _find_receipt(db_session, event_id, email, registration_identity)
            if existing and existing.status == "synced":
                return {
                    "ok": True,
                    "status": "duplicate",
                    "event_id": event_id,
                    "ticket_id": registration_identity,
                    "contact_id": existing.ghl_contact_id,
                }
            return {"ok": True, "status": "already_processing", "event_id": event_id}
    else:
        receipt.status = "processing"
        receipt.updated_at = _now()
        db_session.add(receipt)
        await db_session.commit()

    try:
        async with GHLClient() as ghl:
            contact = await ghl.find_contact(email)
            if contact and contact.get("id"):
                contact_id = str(contact["id"])
                if cfg["tag"] not in (contact.get("tags") or []):
                    await ghl.add_tags(contact_id, [cfg["tag"]])
            else:
                contact_id = await ghl.upsert_contact(
                    email=email,
                    first_name=str(obj.get("first_name") or "")[:120],
                    last_name=str(obj.get("last_name") or "")[:120],
                    tags=[cfg["tag"]],
                )
            if not contact_id:
                raise RuntimeError("GHL returned no contact id")
    except Exception as exc:
        receipt.status = "failed"
        receipt.updated_at = _now()
        db_session.add(receipt)
        await db_session.commit()
        logger.error(
            "Zoom registration sync failed event=%s ticket=%s error=%s",
            event_id,
            registration_identity,
            type(exc).__name__,
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Registration sync unavailable") from exc

    receipt.ghl_contact_id = contact_id
    receipt.status = "synced"
    receipt.updated_at = _now()
    db_session.add(receipt)
    await db_session.commit()
    logger.info(
        "Zoom registration synced event=%s ticket=%s contact=%s tag=%s",
        event_id,
        registration_identity,
        contact_id,
        cfg["tag"],
    )
    return {
        "ok": True,
        "status": "synced",
        "event_id": event_id,
        "ticket_id": registration_identity,
        "contact_id": contact_id,
        "tag": cfg["tag"],
    }
