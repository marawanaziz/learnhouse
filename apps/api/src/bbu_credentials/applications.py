"""Versioned BBU credential issuance and CEU-application workflow.

This module is the transaction-safe source of truth for new credential work.
The legacy ``BBUCredential`` row remains a current-state projection for the
existing directory, reminders, and exports while the platform transitions to
immutable issuance history.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, time, timezone
from typing import Iterable
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_credentials import service as legacy_svc
from src.bbu_credentials.models import (
    BBUCeuLedger,
    BBUCredential,
    BBUCredentialApplication,
    BBUCredentialApplicationDocument,
    BBUCredentialApplicationItem,
    BBUCredentialAuditEvent,
    BBUCredentialIssuance,
)
from src.db.courses.certifications import CertificateUser, Certifications
from src.db.courses.courses import Course


ORG_ID = 1
CEU_THRESHOLD = 15
APPLICATION_OPEN_STATUSES = ("draft", "submitted")
APPLICATION_FINAL_STATUSES = ("approved", "declined")
CREDENTIAL_TYPES = ("birth", "postpartum")
CREDENTIAL_LEVELS = ("one_year_provisional", "three_year_full")


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _coerce_datetime(value: datetime | date | str | None) -> datetime:
    if value is None:
        return _now_dt()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    raw = str(value).strip()
    if not raw:
        return _now_dt()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(400, "Invalid effective date") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _validate_credential_type(credential_type: str) -> str:
    value = (credential_type or "").strip().lower()
    if value not in CREDENTIAL_TYPES:
        raise HTTPException(400, "Credential type must be birth or postpartum")
    return value


def _validate_completion_date(value: str) -> str:
    raw = (value or "").strip()
    try:
        completed = date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(400, "Completion date must be a valid date.") from exc
    if completed > _now_dt().date():
        raise HTTPException(400, "Completion date cannot be in the future.")
    return completed.isoformat()


def issuance_effective_status(issuance: BBUCredentialIssuance) -> str:
    if issuance.status == "revoked":
        return "revoked"
    expires = legacy_svc._parse(issuance.expires_at)
    overdue = bool(expires and expires < _now_dt())
    if issuance.credential_level == "one_year_provisional":
        return "lapsed" if overdue else "provisional"
    return "expired" if overdue else "full"


def issuance_to_dict(issuance: BBUCredentialIssuance) -> dict:
    return {
        "id": issuance.id,
        "credential_type": issuance.credential_type,
        "credential_level": issuance.credential_level,
        "term_years": issuance.term_years,
        "status": issuance_effective_status(issuance),
        "stored_status": issuance.status,
        "source": issuance.source,
        "source_ref": issuance.source_ref,
        "effective_at": issuance.effective_at,
        "expires_at": issuance.expires_at,
        "public_credential_id": issuance.public_credential_id,
        "verification_token": issuance.verification_token,
        "supersedes_issuance_id": issuance.supersedes_issuance_id,
        "directory_opt_in": bool(issuance.directory_opt_in),
        "created_at": issuance.created_at,
    }


def _public_credential_id(credential_type: str, effective_at: datetime) -> str:
    label = "BD" if credential_type == "birth" else "PPD"
    return f"BBU-{label}-{effective_at.year}-{secrets.token_hex(3).upper()}"


async def create_issuance(
    db: AsyncSession,
    *,
    org_id: int,
    user_id: int,
    credential_type: str,
    credential_level: str,
    effective_at: datetime | date | str | None,
    source: str,
    source_ref: str = "",
    supersedes_issuance_id: int | None = None,
    issued_by_user_id: int | None = None,
    directory_opt_in: bool = False,
    expires_at: datetime | date | str | None = None,
    commit: bool = True,
) -> BBUCredentialIssuance:
    """Create one immutable issuance.

    A non-empty source reference is an idempotency key within the same user,
    credential type, and source. This protects course hooks, migrations, and
    approval retries from producing duplicate certificates.
    """
    credential_type = _validate_credential_type(credential_type)
    if credential_level not in CREDENTIAL_LEVELS:
        raise HTTPException(400, "Invalid credential level")
    if source_ref:
        existing = (
            await db.execute(
                select(BBUCredentialIssuance).where(
                    BBUCredentialIssuance.org_id == org_id,
                    BBUCredentialIssuance.user_id == user_id,
                    BBUCredentialIssuance.credential_type == credential_type,
                    BBUCredentialIssuance.source == source,
                    BBUCredentialIssuance.source_ref == source_ref,
                )
            )
        ).scalars().first()
        if existing:
            return existing

    effective = _coerce_datetime(effective_at)
    term_years = 1 if credential_level == "one_year_provisional" else 3
    expiry = (
        _coerce_datetime(expires_at)
        if expires_at
        else legacy_svc._add_years(effective, term_years)
    )
    issuance = BBUCredentialIssuance(
        org_id=org_id,
        user_id=user_id,
        credential_type=credential_type,
        credential_level=credential_level,
        term_years=term_years,
        status="issued",
        source=(source or "manual").strip()[:32],
        source_ref=(source_ref or "").strip()[:160],
        effective_at=effective.isoformat(),
        expires_at=expiry.isoformat(),
        public_credential_id=_public_credential_id(credential_type, effective),
        verification_token=secrets.token_urlsafe(24),
        supersedes_issuance_id=supersedes_issuance_id,
        directory_opt_in=directory_opt_in,
        issued_by_user_id=issued_by_user_id,
        created_at=_now(),
    )
    db.add(issuance)
    if commit:
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            if source_ref:
                existing = (
                    await db.execute(
                        select(BBUCredentialIssuance).where(
                            BBUCredentialIssuance.org_id == org_id,
                            BBUCredentialIssuance.user_id == user_id,
                            BBUCredentialIssuance.credential_type
                            == credential_type,
                            BBUCredentialIssuance.source == source,
                            BBUCredentialIssuance.source_ref == source_ref,
                        )
                    )
                ).scalars().first()
                if existing:
                    return existing
            raise
        await db.refresh(issuance)
    else:
        await db.flush()
    return issuance


async def reconcile_legacy_credential(
    db: AsyncSession,
    credential: BBUCredential,
    *,
    commit: bool = True,
) -> BBUCredentialIssuance:
    """Copy a legacy current-state row into immutable history once."""
    source_ref = f"legacy:{credential.id}"
    existing = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.org_id == credential.org_id,
                BBUCredentialIssuance.user_id == credential.user_id,
                BBUCredentialIssuance.credential_type
                == credential.credential_type,
                BBUCredentialIssuance.source == "legacy",
                BBUCredentialIssuance.source_ref == source_ref,
            )
        )
    ).scalars().first()
    if existing:
        return existing

    existing_history = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.org_id == credential.org_id,
                BBUCredentialIssuance.user_id == credential.user_id,
                BBUCredentialIssuance.credential_type
                == credential.credential_type,
            )
        )
    ).scalars().all()
    if existing_history:
        # The current-state row is a compatibility projection of an issuance
        # already in history, not another credential event to copy.
        return max(existing_history, key=lambda row: row.id or 0)

    is_full = credential.status in ("full", "expired") or bool(
        credential.full_effective_at or credential.full_expires_at
    )
    level = "three_year_full" if is_full else "one_year_provisional"
    effective = (
        credential.full_effective_at
        if is_full
        else credential.issued_at
    ) or credential.issued_at or _now()
    expires = (
        credential.full_expires_at
        if is_full
        else credential.provisional_expires_at
    ) or None
    return await create_issuance(
        db,
        org_id=credential.org_id,
        user_id=credential.user_id,
        credential_type=credential.credential_type,
        credential_level=level,
        effective_at=effective,
        expires_at=expires,
        source="legacy",
        source_ref=source_ref,
        directory_opt_in=bool(credential.directory_opt_in),
        commit=commit,
    )


async def reconcile_user_credentials(
    db: AsyncSession,
    org_id: int,
    user_id: int,
    *,
    commit: bool = True,
) -> list[BBUCredentialIssuance]:
    legacy_rows = (
        await db.execute(
            select(BBUCredential).where(
                BBUCredential.org_id == org_id,
                BBUCredential.user_id == user_id,
            )
        )
    ).scalars().all()
    out = []
    for row in legacy_rows:
        out.append(await reconcile_legacy_credential(db, row, commit=False))
    if commit and legacy_rows:
        await db.commit()
    return out


async def reconciliation_report(
    db: AsyncSession, org_id: int, *, apply: bool = False
) -> dict:
    """Report or idempotently copy every legacy current-state row to history."""
    legacy_rows = (
        await db.execute(
            select(BBUCredential).where(BBUCredential.org_id == org_id)
        )
    ).scalars().all()
    history_rows = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.org_id == org_id
            )
        )
    ).scalars().all()
    migrated_refs = {
        row.source_ref
        for row in history_rows
        if row.source == "legacy" and row.source_ref.startswith("legacy:")
    }
    invalid_legacy = [
        row for row in legacy_rows if row.credential_type not in CREDENTIAL_TYPES
    ]
    represented_pairs = {
        (row.user_id, row.credential_type) for row in history_rows
    }
    pending = [
        row
        for row in legacy_rows
        if row.credential_type in CREDENTIAL_TYPES
        and (row.user_id, row.credential_type) not in represented_pairs
        and f"legacy:{row.id}" not in migrated_refs
    ]
    certificate_rows = (
        await db.execute(
            select(CertificateUser, Certifications, Course)
            .join(
                Certifications,
                Certifications.id == CertificateUser.certification_id,
            )
            .join(Course, Course.id == Certifications.course_id)
            .where(Course.org_id == org_id)
        )
    ).all()
    unmapped_courses: dict[int, dict] = {}
    invalid_course_mappings: dict[int, dict] = {}
    for _certificate_user, certification, course in certificate_rows:
        config = certification.config or {}
        mapping = (config.get("bbu_credential_type") or "").strip().lower()
        summary = {
            "course_id": course.id,
            "course_uuid": course.course_uuid,
            "course_name": course.name,
        }
        if not mapping:
            unmapped_courses[course.id] = summary
        elif mapping not in CREDENTIAL_TYPES:
            invalid_course_mappings[course.id] = {**summary, "mapping": mapping}
    by_level = {"one_year_provisional": 0, "three_year_full": 0}
    for row in pending:
        is_full = row.status in ("full", "expired") or bool(
            row.full_effective_at or row.full_expires_at
        )
        by_level["three_year_full" if is_full else "one_year_provisional"] += 1

    created = 0
    if apply:
        for row in pending:
            await reconcile_legacy_credential(db, row)
            created += 1
    return {
        "org_id": org_id,
        "dry_run": not apply,
        "legacy_rows": len(legacy_rows),
        "existing_issuances": len(history_rows),
        "pending": len(pending),
        "pending_by_level": by_level,
        "created": created,
        "exceptions": {
            "invalid_legacy_credential_ids": [
                row.id for row in invalid_legacy
            ],
            "unmapped_certificate_courses": list(unmapped_courses.values()),
            "invalid_course_mappings": list(
                invalid_course_mappings.values()
            ),
        },
    }


async def _qualifying_course_certificate(
    db: AsyncSession, org_id: int, user_id: int, credential_type: str
) -> CertificateUser | None:
    rows = (
        await db.execute(
            select(CertificateUser, Certifications)
            .join(
                Certifications,
                Certifications.id == CertificateUser.certification_id,
            )
            .join(Course, Course.id == Certifications.course_id)
            .where(
                CertificateUser.user_id == user_id,
                Course.org_id == org_id,
            )
        )
    ).all()
    for certificate_user, certification in rows:
        cfg = certification.config or {}
        if (cfg.get("bbu_credential_type") or "").strip().lower() == credential_type:
            return certificate_user
    return None


async def eligibility_for(
    db: AsyncSession, org_id: int, user_id: int, credential_type: str
) -> dict:
    credential_type = _validate_credential_type(credential_type)
    issuances = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.org_id == org_id,
                BBUCredentialIssuance.user_id == user_id,
                BBUCredentialIssuance.credential_type == credential_type,
            )
        )
    ).scalars().all()
    if issuances:
        latest = max(issuances, key=lambda row: row.id or 0)
        return {
            "eligible": True,
            "credential_type": credential_type,
            "source_type": "credential_issuance",
            "source_id": latest.id,
            "current": issuance_to_dict(latest),
        }

    legacy = (
        await db.execute(
            select(BBUCredential).where(
                BBUCredential.org_id == org_id,
                BBUCredential.user_id == user_id,
                BBUCredential.credential_type == credential_type,
            )
        )
    ).scalars().first()
    if legacy:
        return {
            "eligible": True,
            "credential_type": credential_type,
            "source_type": "legacy_credential",
            "source_id": legacy.id,
            "current": legacy_svc.to_dict(legacy),
        }

    certificate = await _qualifying_course_certificate(
        db, org_id, user_id, credential_type
    )
    if certificate:
        return {
            "eligible": True,
            "credential_type": credential_type,
            "source_type": "course_certificate",
            "source_id": certificate.id,
            "current": None,
        }
    return {
        "eligible": False,
        "credential_type": credential_type,
        "source_type": "",
        "source_id": None,
        "current": None,
    }


async def create_application(
    db: AsyncSession, *, org_id: int, user_id: int, credential_type: str
) -> BBUCredentialApplication:
    credential_type = _validate_credential_type(credential_type)
    existing = (
        await db.execute(
            select(BBUCredentialApplication).where(
                BBUCredentialApplication.org_id == org_id,
                BBUCredentialApplication.user_id == user_id,
                BBUCredentialApplication.credential_type == credential_type,
                BBUCredentialApplication.status.in_(APPLICATION_OPEN_STATUSES),
            )
        )
    ).scalars().first()
    if existing:
        return existing

    eligibility = await eligibility_for(db, org_id, user_id, credential_type)
    if not eligibility["eligible"]:
        raise HTTPException(
            403,
            "A prior BBU training or credential is required for this application.",
        )
    now = _now()
    application = BBUCredentialApplication(
        public_uuid=f"credential_application_{uuid4()}",
        org_id=org_id,
        user_id=user_id,
        credential_type=credential_type,
        qualifying_source_type=eligibility["source_type"],
        qualifying_source_id=eligibility["source_id"],
        status="draft",
        created_at=now,
        updated_at=now,
    )
    db.add(application)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(
                select(BBUCredentialApplication).where(
                    BBUCredentialApplication.org_id == org_id,
                    BBUCredentialApplication.user_id == user_id,
                    BBUCredentialApplication.credential_type == credential_type,
                    BBUCredentialApplication.status.in_(
                        APPLICATION_OPEN_STATUSES
                    ),
                )
            )
        ).scalars().first()
        if existing:
            return existing
        raise
    await db.refresh(application)
    await add_audit_event(
        db,
        org_id=org_id,
        actor_user_id=user_id,
        action="application_created",
        target_type="application",
        target_id=application.id,
        after_data={"status": "draft", "credential_type": credential_type},
        commit=True,
    )
    return application


def _require_draft(application: BBUCredentialApplication) -> None:
    if application.status != "draft":
        raise HTTPException(409, "Only draft applications can be edited.")


async def add_application_item(
    db: AsyncSession,
    application: BBUCredentialApplication,
    *,
    training_title: str,
    provider: str,
    completion_date: str,
    claimed_ceu: int,
) -> BBUCredentialApplicationItem:
    _require_draft(application)
    title = (training_title or "").strip()
    provider = (provider or "").strip()
    completion_date = (completion_date or "").strip()
    if not title or not provider or not completion_date:
        raise HTTPException(400, "Training, provider, and completion date are required.")
    completion_date = _validate_completion_date(completion_date)
    if int(claimed_ceu or 0) <= 0:
        raise HTTPException(400, "Claimed CEUs must be greater than zero.")
    now = _now()
    item = BBUCredentialApplicationItem(
        application_id=application.id,
        training_title=title[:240],
        provider=provider[:240],
        completion_date=completion_date[:20],
        claimed_ceu=int(claimed_ceu),
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def update_application_item(
    db: AsyncSession,
    application: BBUCredentialApplication,
    item: BBUCredentialApplicationItem,
    *,
    training_title: str,
    provider: str,
    completion_date: str,
    claimed_ceu: int,
) -> BBUCredentialApplicationItem:
    _require_draft(application)
    if item.application_id != application.id:
        raise HTTPException(404, "CEU item not found")
    title = (training_title or "").strip()
    provider = (provider or "").strip()
    completion_date = (completion_date or "").strip()
    if not title or not provider or not completion_date:
        raise HTTPException(400, "Training, provider, and completion date are required.")
    completion_date = _validate_completion_date(completion_date)
    if int(claimed_ceu or 0) <= 0:
        raise HTTPException(400, "Claimed CEUs must be greater than zero.")
    item.training_title = title[:240]
    item.provider = provider[:240]
    item.completion_date = completion_date[:20]
    item.claimed_ceu = int(claimed_ceu)
    item.updated_at = _now()
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def add_document_record(
    db: AsyncSession,
    application: BBUCredentialApplication,
    item: BBUCredentialApplicationItem,
    *,
    storage_key: str,
    original_filename: str,
    content_type: str,
    byte_size: int,
) -> BBUCredentialApplicationDocument:
    _require_draft(application)
    if item.application_id != application.id:
        raise HTTPException(404, "CEU item not found")
    count = len(
        (
            await db.execute(
                select(BBUCredentialApplicationDocument).where(
                    BBUCredentialApplicationDocument.application_id
                    == application.id
                )
            )
        ).scalars().all()
    )
    if count >= 10:
        raise HTTPException(400, "An application can contain at most 10 files.")
    document = BBUCredentialApplicationDocument(
        application_id=application.id,
        application_item_id=item.id,
        storage_key=storage_key,
        original_filename=(original_filename or storage_key)[:300],
        content_type=(content_type or "application/octet-stream")[:120],
        byte_size=max(0, int(byte_size or 0)),
        uploaded_at=_now(),
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def application_items(
    db: AsyncSession, application_id: int
) -> list[BBUCredentialApplicationItem]:
    return list(
        (
            await db.execute(
                select(BBUCredentialApplicationItem).where(
                    BBUCredentialApplicationItem.application_id == application_id
                )
            )
        ).scalars().all()
    )


async def application_documents(
    db: AsyncSession, application_id: int
) -> list[BBUCredentialApplicationDocument]:
    return list(
        (
            await db.execute(
                select(BBUCredentialApplicationDocument).where(
                    BBUCredentialApplicationDocument.application_id == application_id
                )
            )
        ).scalars().all()
    )


async def submit_application(
    db: AsyncSession, application: BBUCredentialApplication
) -> BBUCredentialApplication:
    if application.status == "submitted":
        return application
    _require_draft(application)
    eligibility = await eligibility_for(
        db, application.org_id, application.user_id, application.credential_type
    )
    if not eligibility["eligible"]:
        raise HTTPException(403, "This member is no longer eligible to apply.")
    items = await application_items(db, application.id)
    if not items:
        raise HTTPException(400, "Add at least one CEU training before submitting.")
    documents = await application_documents(db, application.id)
    document_item_ids = {document.application_item_id for document in documents}
    if any(item.id not in document_item_ids for item in items):
        raise HTTPException(400, "Each CEU training needs a supporting document.")
    total = sum(int(item.claimed_ceu or 0) for item in items)
    if total < CEU_THRESHOLD:
        raise HTTPException(400, f"At least {CEU_THRESHOLD} claimed CEUs are required.")
    now = _now()
    application.status = "submitted"
    application.claimed_ceu_total = total
    application.submitted_at = now
    application.updated_at = now
    db.add(application)
    await db.commit()
    await db.refresh(application)
    await add_audit_event(
        db,
        org_id=application.org_id,
        actor_user_id=application.user_id,
        action="application_submitted",
        target_type="application",
        target_id=application.id,
        before_data={"status": "draft"},
        after_data={"status": "submitted", "claimed_ceu_total": total},
        commit=True,
    )
    return application


async def review_application_item(
    db: AsyncSession,
    application: BBUCredentialApplication,
    item: BBUCredentialApplicationItem,
    *,
    approved_ceu: int,
    admin_note: str,
    reviewer_user_id: int | None = None,
) -> BBUCredentialApplicationItem:
    if application.status != "submitted":
        raise HTTPException(409, "Only submitted applications can be reviewed.")
    if item.application_id != application.id:
        raise HTTPException(404, "CEU item not found")
    approved = int(approved_ceu)
    if approved < 0 or approved > int(item.claimed_ceu or 0):
        raise HTTPException(
            400, "Approved CEUs must be between zero and the claimed amount."
        )
    before = {"approved_ceu": item.approved_ceu, "admin_note": item.admin_note}
    item.approved_ceu = approved
    item.admin_note = (admin_note or "").strip()
    item.updated_at = _now()
    db.add(item)
    await db.commit()
    await db.refresh(item)
    await add_audit_event(
        db,
        org_id=application.org_id,
        actor_user_id=reviewer_user_id,
        action="ceu_item_reviewed",
        target_type="application_item",
        target_id=item.id,
        before_data=before,
        after_data={"approved_ceu": approved, "admin_note": item.admin_note},
        commit=True,
    )
    return item


async def _latest_issuance(
    db: AsyncSession, org_id: int, user_id: int, credential_type: str
) -> BBUCredentialIssuance | None:
    rows = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.org_id == org_id,
                BBUCredentialIssuance.user_id == user_id,
                BBUCredentialIssuance.credential_type == credential_type,
            )
        )
    ).scalars().all()
    return max(rows, key=lambda row: row.id or 0) if rows else None


async def _sync_current_projection(
    db: AsyncSession,
    application: BBUCredentialApplication,
    issuance: BBUCredentialIssuance,
    approved_total: int,
) -> BBUCredential:
    credential = (
        await db.execute(
            select(BBUCredential).where(
                BBUCredential.org_id == application.org_id,
                BBUCredential.user_id == application.user_id,
                BBUCredential.credential_type == application.credential_type,
            )
        )
    ).scalars().first()
    if not credential:
        credential = BBUCredential(
            org_id=application.org_id,
            user_id=application.user_id,
            credential_type=application.credential_type,
        )
    credential.status = "full"
    if not credential.issued_at:
        credential.issued_at = issuance.effective_at
    credential.full_effective_at = issuance.effective_at
    credential.full_expires_at = issuance.expires_at
    credential.source = "ceu_application"
    credential.source_ref = application.public_uuid
    credential.renewal_ceu_baseline = approved_total
    credential.updated_at = _now()
    db.add(credential)
    return credential


async def approve_application(
    db: AsyncSession,
    application: BBUCredentialApplication,
    *,
    reviewer_user_id: int,
    effective_at: datetime | date | str | None = None,
) -> BBUCredentialIssuance:
    if application.status == "approved" and application.approved_issuance_id:
        existing = (
            await db.execute(
                select(BBUCredentialIssuance).where(
                    BBUCredentialIssuance.id == application.approved_issuance_id
                )
            )
        ).scalars().first()
        if existing:
            return existing
    if application.status != "submitted":
        raise HTTPException(409, "Only submitted applications can be approved.")
    eligibility = await eligibility_for(
        db, application.org_id, application.user_id, application.credential_type
    )
    if not eligibility["eligible"]:
        raise HTTPException(403, "This member no longer has qualifying BBU history.")
    await reconcile_user_credentials(
        db,
        application.org_id,
        application.user_id,
        commit=False,
    )
    items = await application_items(db, application.id)
    if not items or any(item.approved_ceu is None for item in items):
        raise HTTPException(400, "Review every CEU item before approval.")
    approved_total = sum(int(item.approved_ceu or 0) for item in items)
    if approved_total < CEU_THRESHOLD:
        raise HTTPException(400, f"At least {CEU_THRESHOLD} approved CEUs are required.")
    effective = _coerce_datetime(effective_at)
    if effective > _now_dt():
        raise HTTPException(400, "The effective date cannot be in the future.")

    prior = await _latest_issuance(
        db, application.org_id, application.user_id, application.credential_type
    )
    issuance = await create_issuance(
        db,
        org_id=application.org_id,
        user_id=application.user_id,
        credential_type=application.credential_type,
        credential_level="three_year_full",
        effective_at=effective,
        source="ceu_application",
        source_ref=application.public_uuid,
        supersedes_issuance_id=prior.id if prior else None,
        issued_by_user_id=reviewer_user_id,
        directory_opt_in=bool(prior and prior.directory_opt_in),
        commit=False,
    )
    existing_total = await legacy_svc.approved_ceu_total(
        db, application.org_id, application.user_id
    )
    for item in items:
        source_ref = f"ceu_application:{application.id}:item:{item.id}"
        existing_ledger = (
            await db.execute(
                select(BBUCeuLedger).where(
                    BBUCeuLedger.org_id == application.org_id,
                    BBUCeuLedger.user_id == application.user_id,
                    BBUCeuLedger.source_ref == source_ref,
                )
            )
        ).scalars().first()
        if not existing_ledger:
            db.add(
                BBUCeuLedger(
                    org_id=application.org_id,
                    user_id=application.user_id,
                    ceu_count=int(item.approved_ceu or 0),
                    source="ceu_application",
                    source_ref=source_ref,
                    approved=True,
                    submitted_at=application.submitted_at,
                    approved_at=_now(),
                )
            )

    now = _now()
    application.status = "approved"
    application.approved_ceu_total = approved_total
    application.reviewed_at = now
    application.reviewed_by_user_id = reviewer_user_id
    application.approved_issuance_id = issuance.id
    application.updated_at = now
    db.add(application)
    await _sync_current_projection(
        db, application, issuance, existing_total + approved_total
    )
    await add_audit_event(
        db,
        org_id=application.org_id,
        actor_user_id=reviewer_user_id,
        action="application_approved",
        target_type="application",
        target_id=application.id,
        before_data={"status": "submitted"},
        after_data={
            "status": "approved",
            "approved_ceu_total": approved_total,
            "issuance_id": issuance.id,
            "effective_at": issuance.effective_at,
            "expires_at": issuance.expires_at,
        },
        commit=False,
    )
    await db.commit()
    await db.refresh(application)
    await db.refresh(issuance)
    return issuance


async def decline_application(
    db: AsyncSession,
    application: BBUCredentialApplication,
    *,
    reviewer_user_id: int,
    reason: str,
) -> BBUCredentialApplication:
    if application.status == "declined":
        return application
    if application.status != "submitted":
        raise HTTPException(409, "Only submitted applications can be declined.")
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(400, "A decline reason is required.")
    now = _now()
    application.status = "declined"
    application.decline_reason = reason
    application.reviewed_at = now
    application.reviewed_by_user_id = reviewer_user_id
    application.updated_at = now
    db.add(application)
    await add_audit_event(
        db,
        org_id=application.org_id,
        actor_user_id=reviewer_user_id,
        action="application_declined",
        target_type="application",
        target_id=application.id,
        before_data={"status": "submitted"},
        after_data={"status": "declined", "decline_reason": reason},
        reason=reason,
        commit=False,
    )
    await db.commit()
    await db.refresh(application)
    return application


async def add_audit_event(
    db: AsyncSession,
    *,
    org_id: int,
    actor_user_id: int | None,
    action: str,
    target_type: str,
    target_id: int,
    before_data: dict | None = None,
    after_data: dict | None = None,
    reason: str = "",
    commit: bool = False,
) -> BBUCredentialAuditEvent:
    event = BBUCredentialAuditEvent(
        org_id=org_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_data=before_data or {},
        after_data=after_data or {},
        reason=reason,
        created_at=_now(),
    )
    db.add(event)
    if commit:
        await db.commit()
        await db.refresh(event)
    else:
        await db.flush()
    return event


async def serialize_application(
    db: AsyncSession, application: BBUCredentialApplication, include_internal: bool = False
) -> dict:
    items = await application_items(db, application.id)
    documents = await application_documents(db, application.id)
    docs_by_item: dict[int, list[dict]] = {}
    for document in documents:
        docs_by_item.setdefault(document.application_item_id, []).append(
            {
                "id": document.id,
                "filename": document.original_filename,
                "content_type": document.content_type,
                "byte_size": document.byte_size,
                "uploaded_at": document.uploaded_at,
            }
        )
    payload_items = []
    for item in items:
        row = {
            "id": item.id,
            "training_title": item.training_title,
            "provider": item.provider,
            "completion_date": item.completion_date,
            "claimed_ceu": item.claimed_ceu,
            "documents": docs_by_item.get(item.id, []),
        }
        if include_internal:
            row.update(
                {
                    "approved_ceu": item.approved_ceu,
                    "admin_note": item.admin_note,
                }
            )
        payload_items.append(row)
    result = {
        "id": application.id,
        "public_uuid": application.public_uuid,
        "credential_type": application.credential_type,
        "status": application.status,
        "claimed_ceu_total": application.claimed_ceu_total,
        "approved_ceu_total": application.approved_ceu_total,
        "submitted_at": application.submitted_at,
        "reviewed_at": application.reviewed_at,
        "decline_reason": application.decline_reason,
        "approved_issuance_id": application.approved_issuance_id,
        "created_at": application.created_at,
        "updated_at": application.updated_at,
        "items": payload_items,
    }
    if include_internal:
        result.update(
            {
                "user_id": application.user_id,
                "org_id": application.org_id,
                "qualifying_source_type": application.qualifying_source_type,
                "qualifying_source_id": application.qualifying_source_id,
                "reviewed_by_user_id": application.reviewed_by_user_id,
                "submission_member_notified_at": (
                    application.submission_member_notified_at
                ),
                "submission_admin_notified_at": (
                    application.submission_admin_notified_at
                ),
                "decision_notified_at": application.decision_notified_at,
                "notification_attempts": application.notification_attempts,
                "notification_error": application.notification_error,
            }
        )
    return result


async def list_user_issuances(
    db: AsyncSession, org_id: int, user_id: int
) -> list[BBUCredentialIssuance]:
    await reconcile_user_credentials(db, org_id, user_id)
    rows = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.org_id == org_id,
                BBUCredentialIssuance.user_id == user_id,
            )
        )
    ).scalars().all()
    return sorted(rows, key=lambda row: row.id or 0, reverse=True)


async def list_user_applications(
    db: AsyncSession, org_id: int, user_id: int
) -> list[BBUCredentialApplication]:
    rows = (
        await db.execute(
            select(BBUCredentialApplication).where(
                BBUCredentialApplication.org_id == org_id,
                BBUCredentialApplication.user_id == user_id,
            )
        )
    ).scalars().all()
    return sorted(rows, key=lambda row: row.id or 0, reverse=True)


def sum_ceu(items: Iterable[BBUCredentialApplicationItem], field: str) -> int:
    return sum(int(getattr(item, field, 0) or 0) for item in items)
