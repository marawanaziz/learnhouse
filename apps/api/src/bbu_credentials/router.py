"""BBU credentials — admin + hook API (admin-key gated).
Mounted at /api/v1/bbu/credentials."""
import html
import io
import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends, File, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import (
    AnonymousUser,
    APITokenUser,
    SuperadminAPITokenUser,
    User,
)
from src.db.user_organizations import UserOrganization
from src.db.courses.courses import Course
from src.db.courses.certifications import CertificateUser, Certifications
from src.security.auth import get_current_user, resolve_acting_user_id
from src.security.org_auth import is_org_admin
from src.bbu_credentials.models import (
    BBUCredential,
    BBUCeuLedger,
    BBUCredentialApplication,
    BBUCredentialApplicationDocument,
    BBUCredentialApplicationItem,
    BBUCredentialIssuance,
)
from src.bbu_credentials import service as svc
from src.bbu_credentials import applications as app_svc
from src.services.users.identity import get_canonical_user_by_email

router = APIRouter()
ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")

# Reminder cadence (days before expiry) — the scheduled reminder job fires here.
REMINDER_DAYS = [180, 90, 60, 45, 30]


def _check(request: Request):
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key", "")
    if not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _user_by_email(db: AsyncSession, email: str) -> User:
    u = await get_canonical_user_by_email(db, email)
    if not u:
        raise HTTPException(404, "User not found")
    return u


async def _member_user(request: Request, db: AsyncSession) -> User:
    principal = await get_current_user(request, db)
    if isinstance(
        principal, (AnonymousUser, APITokenUser, SuperadminAPITokenUser)
    ):
        raise HTTPException(401, "A signed-in member account is required.")
    user_id = resolve_acting_user_id(principal)
    membership = (
        await db.execute(
            select(UserOrganization).where(
                UserOrganization.org_id == 1,
                UserOrganization.user_id == user_id,
            )
        )
    ).scalars().first()
    if not membership:
        raise HTTPException(403, "Birth & Baby University membership is required.")
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalars().first()
    if not user:
        raise HTTPException(404, "Member account not found.")
    return user


async def _owned_application(
    db: AsyncSession, public_uuid: str, user_id: int
) -> BBUCredentialApplication:
    application = (
        await db.execute(
            select(BBUCredentialApplication).where(
                BBUCredentialApplication.public_uuid == public_uuid,
                BBUCredentialApplication.user_id == user_id,
                BBUCredentialApplication.org_id == 1,
            )
        )
    ).scalars().first()
    if not application:
        raise HTTPException(404, "Credential application not found.")
    return application


async def _application_item(
    db: AsyncSession, application_id: int, item_id: int
) -> BBUCredentialApplicationItem:
    item = (
        await db.execute(
            select(BBUCredentialApplicationItem).where(
                BBUCredentialApplicationItem.id == item_id,
                BBUCredentialApplicationItem.application_id == application_id,
            )
        )
    ).scalars().first()
    if not item:
        raise HTTPException(404, "CEU training not found.")
    return item


# ===========================================================================
# Signed-in member credential hub + CEU applications
# ===========================================================================
@router.get("/me")
async def member_credential_hub(
    request: Request, db_session: AsyncSession = Depends(get_db_session)
):
    user = await _member_user(request, db_session)
    issuances = await app_svc.list_user_issuances(db_session, 1, user.id)
    applications = await app_svc.list_user_applications(db_session, 1, user.id)
    eligibility = {
        credential_type: await app_svc.eligibility_for(
            db_session, 1, user.id, credential_type
        )
        for credential_type in app_svc.CREDENTIAL_TYPES
    }
    cert_rows = (
        await db_session.execute(
            select(CertificateUser, Certifications, Course)
            .join(
                Certifications,
                Certifications.id == CertificateUser.certification_id,
            )
            .join(Course, Course.id == Certifications.course_id)
            .where(CertificateUser.user_id == user.id, Course.org_id == 1)
        )
    ).all()
    training_certificates = []
    for certificate_user, certification, course in cert_rows:
        cfg = certification.config or {}
        training_certificates.append(
            {
                "id": certificate_user.id,
                "uuid": certificate_user.user_certification_uuid,
                "course": course.name,
                "issued_at": certificate_user.created_at,
                "credential_type": (
                    cfg.get("bbu_credential_type") or ""
                ).strip().lower(),
                "is_cross_cert": bool(cfg.get("bbu_is_cross_cert")),
                "verify_url": (
                    f"/certificates/{certificate_user.user_certification_uuid}/verify"
                ),
            }
        )
    return {
        "member": {
            "id": user.id,
            "name": f"{user.first_name or ''} {user.last_name or ''}".strip()
            or user.username,
            "email": str(user.email),
        },
        "training_certificates": training_certificates,
        "issuances": app_svc.issuance_history_to_dicts(issuances),
        "eligibility": eligibility,
        "applications": [
            await app_svc.serialize_application(db_session, row)
            for row in applications
        ],
        "ceu_total": await svc.approved_ceu_total(db_session, 1, user.id),
        "ceu_threshold": app_svc.CEU_THRESHOLD,
    }


@router.post("/applications")
async def member_create_application(
    request: Request, db_session: AsyncSession = Depends(get_db_session)
):
    user = await _member_user(request, db_session)
    body = await request.json()
    application = await app_svc.create_application(
        db_session,
        org_id=1,
        user_id=user.id,
        credential_type=body.get("credential_type", ""),
    )
    return await app_svc.serialize_application(db_session, application)


@router.get("/applications/{public_uuid}")
async def member_get_application(
    public_uuid: str,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    user = await _member_user(request, db_session)
    application = await _owned_application(db_session, public_uuid, user.id)
    return await app_svc.serialize_application(db_session, application)


@router.post("/applications/{public_uuid}/items")
async def member_add_application_item(
    public_uuid: str,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    user = await _member_user(request, db_session)
    application = await _owned_application(db_session, public_uuid, user.id)
    body = await request.json()
    item = await app_svc.add_application_item(
        db_session,
        application,
        training_title=body.get("training_title", ""),
        provider=body.get("provider", ""),
        completion_date=body.get("completion_date", ""),
        claimed_ceu=int(body.get("claimed_ceu") or 0),
    )
    return {"id": item.id, "ok": True}


@router.put("/applications/{public_uuid}/items/{item_id}")
async def member_update_application_item(
    public_uuid: str,
    item_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    user = await _member_user(request, db_session)
    application = await _owned_application(db_session, public_uuid, user.id)
    item = await _application_item(db_session, application.id, item_id)
    body = await request.json()
    updated = await app_svc.update_application_item(
        db_session,
        application,
        item,
        training_title=body.get("training_title", ""),
        provider=body.get("provider", ""),
        completion_date=body.get("completion_date", ""),
        claimed_ceu=int(body.get("claimed_ceu") or 0),
    )
    return {"id": updated.id, "ok": True}


@router.delete("/applications/{public_uuid}/items/{item_id}")
async def member_delete_application_item(
    public_uuid: str,
    item_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    user = await _member_user(request, db_session)
    application = await _owned_application(db_session, public_uuid, user.id)
    app_svc._require_draft(application)
    item = await _application_item(db_session, application.id, item_id)
    documents = (
        await db_session.execute(
            select(BBUCredentialApplicationDocument).where(
                BBUCredentialApplicationDocument.application_item_id == item.id
            )
        )
    ).scalars().all()
    for document in documents:
        await db_session.delete(document)
    await db_session.delete(item)
    await db_session.commit()
    return {"ok": True}


@router.post("/applications/{public_uuid}/items/{item_id}/documents")
async def member_upload_application_document(
    public_uuid: str,
    item_id: int,
    request: Request,
    file: UploadFile = File(...),
    db_session: AsyncSession = Depends(get_db_session),
):
    user = await _member_user(request, db_session)
    application = await _owned_application(db_session, public_uuid, user.id)
    item = await _application_item(db_session, application.id, item_id)
    app_svc._require_draft(application)
    extension = os.path.splitext(file.filename or "")[1].lower()
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png"}
    allowed_content_types = {
        "application/pdf",
        "image/jpeg",
        "image/png",
    }
    if extension not in allowed_extensions or file.content_type not in allowed_content_types:
        raise HTTPException(400, "Upload a PDF, JPG, JPEG, or PNG file.")
    from src.services.utils.upload_content import upload_file

    stored_name = await upload_file(
        file,
        directory=f"credential-applications/{application.public_uuid}",
        type_of_dir="users",
        uuid=user.user_uuid,
        allowed_types=["image", "document"],
        filename_prefix=f"ceu_{item.id}",
        max_size=10 * 1024 * 1024,
    )
    document = await app_svc.add_document_record(
        db_session,
        application,
        item,
        storage_key=stored_name,
        original_filename=file.filename or stored_name,
        content_type=file.content_type or "application/octet-stream",
        byte_size=int(getattr(file, "size", 0) or 0),
    )
    return {
        "id": document.id,
        "filename": document.original_filename,
        "content_type": document.content_type,
        "byte_size": document.byte_size,
    }


@router.delete("/applications/{public_uuid}/documents/{document_id}")
async def member_delete_application_document(
    public_uuid: str,
    document_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    user = await _member_user(request, db_session)
    application = await _owned_application(db_session, public_uuid, user.id)
    app_svc._require_draft(application)
    document = (
        await db_session.execute(
            select(BBUCredentialApplicationDocument).where(
                BBUCredentialApplicationDocument.id == document_id,
                BBUCredentialApplicationDocument.application_id == application.id,
            )
        )
    ).scalars().first()
    if not document:
        raise HTTPException(404, "Document not found.")
    await db_session.delete(document)
    await db_session.commit()
    return {"ok": True}


@router.get("/applications/{public_uuid}/documents/{document_id}")
async def application_document_download(
    public_uuid: str,
    document_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    principal = await get_current_user(request, db_session)
    if isinstance(
        principal, (AnonymousUser, APITokenUser, SuperadminAPITokenUser)
    ):
        raise HTTPException(401, "Sign in required.")
    actor_user_id = resolve_acting_user_id(principal)
    application = (
        await db_session.execute(
            select(BBUCredentialApplication).where(
                BBUCredentialApplication.public_uuid == public_uuid,
                BBUCredentialApplication.org_id == 1,
            )
        )
    ).scalars().first()
    if not application:
        raise HTTPException(404, "Credential application not found.")
    if actor_user_id != application.user_id and not await is_org_admin(
        actor_user_id, 1, db_session
    ):
        raise HTTPException(403, "Forbidden")
    document = (
        await db_session.execute(
            select(BBUCredentialApplicationDocument).where(
                BBUCredentialApplicationDocument.id == document_id,
                BBUCredentialApplicationDocument.application_id == application.id,
            )
        )
    ).scalars().first()
    if not document:
        raise HTTPException(404, "Document not found.")
    owner = (
        await db_session.execute(select(User).where(User.id == application.user_id))
    ).scalars().first()
    if not owner:
        raise HTTPException(404, "Member account not found.")
    from src.services.utils.upload_content import read_content

    content = await read_content(
        directory=f"credential-applications/{application.public_uuid}",
        type_of_dir="users",
        uuid=owner.user_uuid,
        file_and_format=document.storage_key,
    )
    await app_svc.add_audit_event(
        db_session,
        org_id=1,
        actor_user_id=actor_user_id,
        action="application_document_viewed",
        target_type="application_document",
        target_id=document.id,
        commit=True,
    )
    safe_name = re.sub(r"[\r\n\"/\\\\]+", "_", document.original_filename)
    return Response(
        content,
        media_type=document.content_type,
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.post("/applications/{public_uuid}/submit")
async def member_submit_application(
    public_uuid: str,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    user = await _member_user(request, db_session)
    application = await _owned_application(db_session, public_uuid, user.id)
    submitted = await app_svc.submit_application(db_session, application)
    try:
        from src.bbu_credentials.notifications import notify_submission

        await notify_submission(request, db_session, submitted, user)
    except Exception:
        # The saved application is authoritative. Email failures are retried
        # from the admin queue and must never roll back or duplicate submission.
        pass
    return await app_svc.serialize_application(db_session, submitted)


# ===========================================================================
# Public professional credential verification
# ===========================================================================
async def _verified_issuance(
    db: AsyncSession, verification_token: str
) -> tuple[BBUCredentialIssuance, User]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", verification_token or ""):
        raise HTTPException(404, "Credential not found.")
    issuance = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.verification_token == verification_token,
                BBUCredentialIssuance.org_id == 1,
            )
        )
    ).scalars().first()
    if not issuance:
        raise HTTPException(404, "Credential not found.")
    user = (
        await db.execute(select(User).where(User.id == issuance.user_id))
    ).scalars().first()
    if not user:
        raise HTTPException(404, "Credential holder not found.")
    return issuance, user


async def _public_issuance_status(
    db: AsyncSession, issuance: BBUCredentialIssuance
) -> tuple[str, int | None]:
    replacement = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.org_id == issuance.org_id,
                BBUCredentialIssuance.supersedes_issuance_id == issuance.id,
            )
        )
    ).scalars().first()
    if replacement and issuance.status != "revoked":
        return "replaced", replacement.id
    return app_svc.issuance_effective_status(issuance), None


@router.get("/verify/{verification_token}")
async def verify_credential(
    verification_token: str,
    db_session: AsyncSession = Depends(get_db_session),
):
    issuance, user = await _verified_issuance(db_session, verification_token)
    status, replacement_id = await _public_issuance_status(db_session, issuance)
    return {
        "valid": status in ("provisional", "full"),
        "holder_name": f"{user.first_name or ''} {user.last_name or ''}".strip()
        or user.username,
        "credential_type": issuance.credential_type,
        "credential_level": issuance.credential_level,
        "term_years": issuance.term_years,
        "status": status,
        "superseded_by_issuance_id": replacement_id,
        "effective_at": issuance.effective_at,
        "expires_at": issuance.expires_at,
        "public_credential_id": issuance.public_credential_id,
    }


@router.get("/verify/{verification_token}/page", response_class=HTMLResponse)
async def verify_credential_page(
    verification_token: str,
    db_session: AsyncSession = Depends(get_db_session),
):
    issuance, user = await _verified_issuance(db_session, verification_token)
    name = html.escape(
        f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username
    )
    credential_name = (
        "Certified Birth Doula"
        if issuance.credential_type == "birth"
        else "Certified Postpartum Doula"
    )
    level = (
        "One-year provisional"
        if issuance.credential_level == "one_year_provisional"
        else "Three-year full"
    )
    status, _replacement_id = await _public_issuance_status(
        db_session, issuance
    )
    status_color = (
        "#1c7a41"
        if status in ("provisional", "full")
        else ("#a3261e" if status == "replaced" else "#8a4b13")
    )
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Verify {html.escape(issuance.public_credential_id)} · Birth &amp; Baby University</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#ebf7ff;color:#1b2733;
font-family:Arial,sans-serif;padding:32px 16px}}.card{{max-width:680px;margin:auto;
background:#fff;border-radius:22px;border:1px solid #cfe3f1;overflow:hidden;
box-shadow:0 18px 50px rgba(17,61,93,.12)}}.head{{background:#113d5d;color:#fff;
padding:34px;text-align:center}}.head h1{{font-family:Georgia,serif;margin:0 0 8px;
font-size:28px}}.body{{padding:34px}}.status{{display:inline-block;padding:7px 13px;
border-radius:999px;background:{status_color}18;color:{status_color};font-weight:700}}
dl{{display:grid;grid-template-columns:170px 1fr;gap:14px;margin:28px 0 0}}
dt{{color:#6b6f79}}dd{{margin:0;font-weight:700}}@media(max-width:520px){{
dl{{grid-template-columns:1fr;gap:5px}}dd{{margin-bottom:10px}}}}</style></head>
<body><main class=card><div class=head><h1>Birth &amp; Baby University</h1>
<div>Professional Credential Verification</div></div><div class=body>
<span class=status>{html.escape(status.title())}</span>
<dl><dt>Credential holder</dt><dd>{name}</dd>
<dt>Credential</dt><dd>{credential_name}</dd>
<dt>Level</dt><dd>{level}</dd>
<dt>Credential ID</dt><dd>{html.escape(issuance.public_credential_id)}</dd>
<dt>Effective date</dt><dd>{html.escape(issuance.effective_at[:10])}</dd>
<dt>Valid through</dt><dd>{html.escape(issuance.expires_at[:10])}</dd></dl>
</div></main></body></html>"""
    )


@router.get("/verify/{verification_token}/certificate.pdf")
async def download_credential_certificate(
    verification_token: str,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    issuance, user = await _verified_issuance(db_session, verification_token)
    status, _replacement_id = await _public_issuance_status(
        db_session, issuance
    )
    from src.bbu_credentials.certificate_pdf import (
        build_credential_certificate_pdf,
    )
    from src.bbu_payments.public_url import get_bbu_public_base_url

    base = get_bbu_public_base_url(request).rstrip("/")
    verify_url = (
        f"{base}/api/v1/bbu/credentials/verify/{verification_token}/page"
    )
    credential_name = (
        "Certified Birth Doula"
        if issuance.credential_type == "birth"
        else "Certified Postpartum Doula"
    )
    credential_level = (
        "One-year provisional"
        if issuance.credential_level == "one_year_provisional"
        else "Three-year full"
    )
    pdf = build_credential_certificate_pdf(
        holder_name=(
            f"{user.first_name or ''} {user.last_name or ''}".strip()
            or user.username
        ),
        credential_name=credential_name,
        credential_level=credential_level,
        public_credential_id=issuance.public_credential_id,
        effective_date=issuance.effective_at[:10],
        expiration_date=issuance.expires_at[:10],
        verification_url=verify_url,
        status=status,
    )
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{issuance.public_credential_id}.pdf"'
            ),
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/verify/{verification_token}/qr")
async def verification_qr(
    verification_token: str,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    await _verified_issuance(db_session, verification_token)
    try:
        import segno
    except ImportError as exc:
        raise HTTPException(503, "QR generation unavailable") from exc
    from src.bbu_payments.public_url import get_bbu_public_base_url

    base = get_bbu_public_base_url(request).rstrip("/")
    verify_url = (
        f"{base}/api/v1/bbu/credentials/verify/{verification_token}/page"
    )
    buf = io.BytesIO()
    segno.make(verify_url, error="m").save(
        buf, kind="svg", scale=8, dark="#113d5d", light=None, xmldecl=False
    )
    return Response(
        buf.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/reconciliation")
async def reconcile_credential_history(
    request: Request, db_session: AsyncSession = Depends(get_db_session)
):
    """Dry-run or apply the idempotent legacy-to-history credential backfill."""
    _check(request)
    body = await request.json()
    org_id = int(body.get("org_id", 1))
    apply = bool(body.get("apply", False))
    return await app_svc.reconciliation_report(
        db_session, org_id, apply=apply
    )


@router.get("")
async def list_credentials(request: Request, org_id: int = 1, status: str = "",
                           db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    q = select(BBUCredential).where(BBUCredential.org_id == org_id)
    rows = (await db_session.execute(q)).scalars().all()
    out = []
    for c in rows:
        eff = svc.compute_effective_status(c)
        if status and eff != status:
            continue
        total = await svc.approved_ceu_total(db_session, org_id, c.user_id)
        out.append(svc.to_dict(c, total))
    return out


@router.get("/user")
async def user_credentials(request: Request, email: str, org_id: int = 1,
                           db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    u = await _user_by_email(db_session, email)
    creds = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id, BBUCredential.user_id == u.id))).scalars().all()
    total = await svc.approved_ceu_total(db_session, org_id, u.id)
    ledger = (await db_session.execute(select(BBUCeuLedger).where(
        BBUCeuLedger.org_id == org_id, BBUCeuLedger.user_id == u.id))).scalars().all()
    return {
        "email": u.email,
        "ceu_total": total,
        "credentials": [svc.to_dict(c, total) for c in creds],
        "ledger": [{"id": r.id, "ceu": r.ceu_count, "source": r.source,
                    "ref": r.source_ref, "approved": r.approved,
                    "submitted_at": r.submitted_at} for r in ledger],
    }


@router.post("/issue")
async def issue(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Retired: use the unified Operations credential workflow."""
    _check(request)
    raise HTTPException(
        410,
        "This legacy credential action has been retired. "
        "Use Operations > Credentials to generate a new certificate.",
    )


@router.post("/award-ceu")
async def award_ceu(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Retired: CEUs must be reviewed through the application workflow."""
    _check(request)
    raise HTTPException(
        410,
        "This legacy CEU action has been retired. "
        "Use Operations > Credentials to review a CEU application.",
    )


@router.post("/approve-ceu")
async def approve_ceu(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Approve a pending external CEU. Body: {ledger_id, org_id?}"""
    _check(request)
    b = await request.json()
    row = (await db_session.execute(select(BBUCeuLedger).where(
        BBUCeuLedger.id == int(b.get("ledger_id", 0))))).scalars().first()
    if not row:
        raise HTTPException(404, "Ledger entry not found")
    row.approved = True
    row.approved_at = _now()
    db_session.add(row)
    await db_session.commit()
    total = await svc.approved_ceu_total(db_session, row.org_id, row.user_id)
    return {
        "approved": True,
        "ceu_total": total,
        "credential_changed": False,
        "note": "Credential changes require an approved CEU application.",
    }


@router.post("/renew")
async def renew(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Retired: renewals must create an immutable issuance record."""
    _check(request)
    raise HTTPException(
        410,
        "This legacy renewal action has been retired. "
        "Use Operations > Credentials to generate a new certificate.",
    )


@router.post("/on-course-complete")
async def on_course_complete(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Course-completion hook. Body: {email, course_uuid, org_id?}. Reads the
    course's certification config to decide issue/CEU/cross-cert."""
    _check(request)
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    org_id = int(b.get("org_id", 1))
    cu = (b.get("course_uuid") or "").strip()
    course = (await db_session.execute(select(Course).where(
        Course.course_uuid == cu))).scalars().first()
    if not course:
        raise HTTPException(404, "Course not found")
    cert = (await db_session.execute(select(Certifications).where(
        Certifications.course_id == course.id))).scalars().first()
    cfg = (cert.config if cert else {}) or {}
    result = await svc.on_course_complete(db_session, org_id, u.id, cu, cfg)
    return result


@router.put("/{credential_id}/directory")
async def set_directory(credential_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    b = await request.json()
    c = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.id == credential_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Credential not found")
    c.directory_opt_in = bool(b.get("opt_in", True))
    c.updated_at = _now()
    db_session.add(c)
    issuance_rows = (
        await db_session.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.org_id == c.org_id,
                BBUCredentialIssuance.user_id == c.user_id,
                BBUCredentialIssuance.credential_type == c.credential_type,
            )
        )
    ).scalars().all()
    if issuance_rows:
        latest = max(issuance_rows, key=lambda row: row.id or 0)
        latest.directory_opt_in = c.directory_opt_in
        db_session.add(latest)
    await db_session.commit()
    return {"id": c.id, "directory_opt_in": c.directory_opt_in}


@router.post("/refresh-statuses")
async def refresh_statuses(request: Request, org_id: int = 1,
                           db_session: AsyncSession = Depends(get_db_session)):
    """Recompute stored status for all credentials (lapse/expire the overdue)."""
    _check(request)
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id))).scalars().all()
    changed = 0
    for c in rows:
        eff = svc.compute_effective_status(c)
        if eff != c.status:
            c.status = eff
            c.updated_at = _now()
            db_session.add(c)
            changed += 1
    if changed:
        await db_session.commit()
    return {"checked": len(rows), "changed": changed}


# --------------------------------------------------------------------------- #
# Public certificate directory (2.4). No admin key — only opt-in credentials that
# are currently valid (provisional or full) are exposed; name + credential only.
# --------------------------------------------------------------------------- #
@router.get("/directory")
async def directory(q: str = "", org_id: int = 1,
                    db_session: AsyncSession = Depends(get_db_session)):
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id,
        BBUCredential.directory_opt_in == True,  # noqa: E712
    ))).scalars().all()
    uids = [c.user_id for c in rows]
    users = {}
    if uids:
        urows = (await db_session.execute(select(User).where(User.id.in_(uids)))).scalars().all()
        users = {u.id: u for u in urows}
    ql = (q or "").strip().lower()
    out = []
    for c in rows:
        eff = svc.compute_effective_status(c)
        if eff not in ("provisional", "full"):
            continue
        u = users.get(c.user_id)
        name = f"{getattr(u, 'first_name', '')} {getattr(u, 'last_name', '')}".strip() if u else ""
        if ql and ql not in name.lower() and ql not in c.credential_type.lower():
            continue
        label = {"birth": "Certified Birth Doula", "postpartum": "Certified Postpartum Doula"}.get(
            c.credential_type, c.credential_type.title())
        out.append({
            "name": name or "BBU Professional",
            "credential": label,
            "status": eff,
            "awarded": (c.full_effective_at or c.issued_at or "")[:10],
            "valid_through": (c.full_expires_at or c.provisional_expires_at or "")[:10],
        })
    out.sort(key=lambda x: x["name"].lower())
    return {"count": len(out), "results": out}


@router.get("/directory/page", response_class=HTMLResponse)
async def directory_page(org_id: int = 1, db_session: AsyncSession = Depends(get_db_session)):
    data = await directory(q="", org_id=org_id, db_session=db_session)
    rows_html = "".join(
        f"<tr><td>{r['name']}</td><td>{r['credential']}</td>"
        f"<td><span class='badge {r['status']}'>{r['status'].title()}</span></td>"
        f"<td>{r['awarded']}</td><td>{r['valid_through']}</td></tr>"
        for r in data["results"]
    ) or "<tr><td colspan='5' style='text-align:center;color:#8aa'>No public credentials yet.</td></tr>"
    return HTMLResponse(f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Certified Directory · Birth &amp; Baby University</title>
<style>
:root{{--navy:#113d5d;--sky:#7fb2d6;--ink:#1b2733}}
*{{box-sizing:border-box}}body{{margin:0;font-family:'Open Sans',system-ui,sans-serif;color:var(--ink);background:#f5f8fb}}
header{{background:var(--navy);color:#fff;padding:2.4rem 1.2rem;text-align:center}}
header h1{{margin:0 0 .3rem;font-family:'Playfair Display',Georgia,serif;font-weight:700;font-size:1.9rem}}
header p{{margin:0;opacity:.85}}
.wrap{{max-width:900px;margin:1.6rem auto;padding:0 1rem}}
input{{width:100%;padding:.8rem 1rem;border:1px solid #cdd9e5;border-radius:10px;font-size:1rem;margin-bottom:1rem}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(17,61,93,.08)}}
th,td{{padding:.8rem 1rem;text-align:left;border-bottom:1px solid #eef3f8;font-size:.93rem}}
th{{background:#eaf2f9;color:var(--navy);font-weight:600}}
.badge{{padding:.2rem .6rem;border-radius:20px;font-size:.78rem;font-weight:600}}
.badge.full{{background:#dff5e6;color:#1c7a41}}.badge.provisional{{background:#fff2d6;color:#8a6300}}
footer{{text-align:center;color:#8aa;font-size:.8rem;padding:2rem}}
</style></head><body>
<header><h1>Certified Professional Directory</h1><p>Verified Birth &amp; Baby University credential holders</p></header>
<div class=wrap>
<input id=q placeholder="Search by name or credential…" oninput="f()">
<table><thead><tr><th>Name</th><th>Credential</th><th>Status</th><th>Awarded</th><th>Valid through</th></tr></thead>
<tbody id=tb>{rows_html}</tbody></table>
</div>
<footer>Credentials shown are self-verified and current. Birth &amp; Baby University.</footer>
<script>
function f(){{var v=document.getElementById('q').value.toLowerCase();
document.querySelectorAll('#tb tr').forEach(function(r){{
r.style.display = r.innerText.toLowerCase().indexOf(v)>-1 ? '' : 'none';}});}}
</script></body></html>""")


@router.delete("/{credential_id}")
async def delete_credential(credential_id: int, request: Request,
                            db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    c = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.id == credential_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Credential not found")
    await db_session.delete(c)
    await db_session.commit()
    return {"deleted": credential_id}


# Accredible credential tiers -> (credential_type, tier). Anything not listed and
# not in CEU_GROUPS is ignored so an unexpected tier never silently mis-issues.
ACCREDIBLE_GROUPS = {
    "Provisional 1 Year Certified Postpartum Doula": ("postpartum", "provisional"),
    "Certified Postpartum Doula": ("postpartum", "full"),
    "Provisional 1 Year Certified Labor Doula": ("birth", "provisional"),
    "Certified Labor Doula": ("birth", "full"),
}
ACCREDIBLE_CEU_GROUPS = {
    "Breastfeeding for Perinatal Professionals": 3,
    "Newborn Care for Perinatal Professionals": 3,
    "Comfort Measures for Perinatal Professionals": 3,
}
ACCREDIBLE_PLACEHOLDER_EMAILS = {"john.doe@example.com"}


@router.post("/import-accredible")
async def import_accredible(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Backfill real credentials from an Accredible export so migrated doulas keep
    their TRUE issue/expiry dates (the platform's own clock would otherwise restart
    everyone). Body: {items:[{email,name,group_name,issued_on,expired_on}], dry_run?}.

    Per person+type the latest issuance is current, while every professional
    credential remains in immutable history. 'For Perinatal Professionals' rows
    become CEU ledger entries. Idempotent: re-running never duplicates history or
    CEUs and never replaces newer native/manual credential state with older data.
    """
    b = await request.json()
    _check(request)
    org_id = int(b.get("org_id", 1))
    dry = bool(b.get("dry_run", True))
    items = b.get("items") or []

    # 1) collapse to the latest current credential per (email, credential_type)
    best: dict = {}
    credential_rows = []
    quarantined_placeholders = 0
    ceu_rows, skipped_groups = [], {}
    for it in items:
        email = (it.get("email") or "").strip().lower()
        grp = (it.get("group_name") or "").strip()
        if not email:
            continue
        if email in ACCREDIBLE_PLACEHOLDER_EMAILS:
            quarantined_placeholders += 1
            continue
        if grp in ACCREDIBLE_CEU_GROUPS:
            ceu_rows.append((email, grp, it))
            continue
        mapped = ACCREDIBLE_GROUPS.get(grp)
        if not mapped:
            skipped_groups[grp] = skipped_groups.get(grp, 0) + 1
            continue
        ctype, tier = mapped
        credential_rows.append((email, ctype, tier, it))
        key = (email, ctype)
        cur = best.get(key)
        # The latest issuance is current. Level and expiration break ties; all
        # older rows are still retained below in immutable issuance history.
        score = (
            it.get("issued_on") or "",
            1 if tier == "full" else 0,
            it.get("expired_on") or "",
        )
        if not cur or score > cur["score"]:
            best[key] = {"score": score, "tier": tier, "ctype": ctype, "it": it}

    created = updated = current_preserved = unmatched = ceu_awarded = 0
    issuance_created = issuance_existing = issuance_unmatched = 0
    imported_credentials: list[BBUCredential] = []
    unmatched_emails = []
    for (email, ctype), rec in best.items():
        user = await get_canonical_user_by_email(db_session, email)
        if not user:
            unmatched += 1
            if len(unmatched_emails) < 25:
                unmatched_emails.append(email)
            continue
        if dry:
            continue
        it, tier = rec["it"], rec["tier"]
        issued, expires = (it.get("issued_on") or ""), (it.get("expired_on") or "")
        cred = (await db_session.execute(select(BBUCredential).where(
            BBUCredential.org_id == org_id, BBUCredential.user_id == user.id,
            BBUCredential.credential_type == ctype))).scalars().first()
        if not cred:
            cred = BBUCredential(org_id=org_id, user_id=user.id, credential_type=ctype)
            created += 1
        else:
            existing_score = (
                cred.issued_at or cred.full_effective_at or "",
                1 if cred.status == "full" else 0,
                cred.full_expires_at or cred.provisional_expires_at or "",
            )
            candidate_score = (
                issued,
                1 if tier == "full" else 0,
                expires,
            )
            if existing_score > candidate_score:
                current_preserved += 1
                continue
            updated += 1
        cred.issued_at = issued
        cred.source = "accredible"
        cred.source_ref = str(it.get("id") or "")
        if tier == "full":
            cred.status = "full"
            cred.full_effective_at = issued
            cred.full_expires_at = expires
            cred.provisional_expires_at = ""
        else:
            cred.status = "provisional"
            cred.provisional_expires_at = expires
            cred.full_effective_at = ""
            cred.full_expires_at = ""
        cred.updated_at = svc._now()
        db_session.add(cred)
        imported_credentials.append(cred)

    # Preserve every Accredible professional credential as an immutable
    # issuance. The current-state table above intentionally collapses records
    # per person/type, but the certificate history must remain one-for-one
    # with the source export. ``source_ref`` makes this idempotent.
    for email, ctype, tier, it in credential_rows:
        user = await get_canonical_user_by_email(db_session, email)
        if not user:
            issuance_unmatched += 1
            continue
        if dry:
            continue
        source_ref = str(it.get("id") or "").strip()
        existing = None
        if source_ref:
            existing = (
                await db_session.execute(
                    select(BBUCredentialIssuance).where(
                        BBUCredentialIssuance.org_id == org_id,
                        BBUCredentialIssuance.user_id == user.id,
                        BBUCredentialIssuance.credential_type == ctype,
                        BBUCredentialIssuance.source == "accredible",
                        BBUCredentialIssuance.source_ref == source_ref,
                    )
                )
            ).scalars().first()
        if existing:
            issuance_existing += 1
            continue
        await app_svc.create_issuance(
            db_session,
            org_id=org_id,
            user_id=user.id or 0,
            credential_type=ctype,
            credential_level=(
                "three_year_full" if tier == "full" else "one_year_provisional"
            ),
            effective_at=it.get("issued_on"),
            expires_at=it.get("expired_on"),
            source="accredible",
            source_ref=source_ref,
            directory_opt_in=True,
            commit=False,
        )
        issuance_created += 1

    # 2) CEU-bearing professional courses -> ledger (idempotent per accredible id)
    for email, grp, it in ceu_rows:
        user = await get_canonical_user_by_email(db_session, email)
        if not user:
            continue
        if dry:
            ceu_awarded += 1
            continue
        await svc.award_ceu(db_session, org_id, user.id, ACCREDIBLE_CEU_GROUPS[grp],
                            source="course", source_ref=f"accredible:{it.get('id')}")
        ceu_awarded += 1

    if not dry:
        await db_session.commit()
        for credential in imported_credentials:
            await app_svc.reconcile_legacy_credential(db_session, credential)
    return {"dry_run": dry, "input_rows": len(items),
            "people_with_credentials": len(best),
            "created": created, "updated": updated,
            "current_preserved": current_preserved,
            "unmatched_users": unmatched, "unmatched_sample": unmatched_emails,
            "credential_history_rows": len(credential_rows),
            "issuance_created": issuance_created,
            "issuance_existing": issuance_existing,
            "issuance_unmatched": issuance_unmatched,
            "quarantined_placeholders": quarantined_placeholders,
            "ceu_rows": len(ceu_rows), "ceu_awarded": ceu_awarded,
            "skipped_groups": skipped_groups}


@router.post("/run-reminders")
async def run_reminders(request: Request, org_id: int = 1,
                        db_session: AsyncSession = Depends(get_db_session)):
    """Scheduled reminder job (call daily via cron). For each credential entering
    a pre-expiry window (180/90/60/45/30d) it hasn't been reminded for yet, push
    the status + expiry onto the GHL contact (fields bbu__certification_status /
    _expires) so a GHL workflow can send the reminder. Idempotent per window via
    last_reminder_days. Body: {dry_run?}. Fail-soft on GHL per contact."""
    _check(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await svc.run_reminders(db_session, org_id, dry=bool(body.get("dry_run")))


@router.get("/reminders/due")
async def reminders_due(request: Request, org_id: int = 1,
                        db_session: AsyncSession = Depends(get_db_session)):
    """Which credentials fall within a reminder window (days-to-expiry near a
    REMINDER_DAYS mark, ±3 days). The scheduled job reads this then emails via
    GHL/SMTP. Read-only — safe to call from cron without side effects."""
    _check(request)
    now = svc._now_dt()
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id))).scalars().all()
    due = []
    for c in rows:
        eff = svc.compute_effective_status(c)
        exp = svc._parse(c.full_expires_at if eff == "full" else c.provisional_expires_at)
        if not exp or eff in ("lapsed", "expired"):
            continue
        days = (exp - now).days
        for mark in REMINDER_DAYS:
            if abs(days - mark) <= 3:
                due.append({"credential_id": c.id, "user_id": c.user_id,
                            "credential_type": c.credential_type, "status": eff,
                            "days_to_expiry": days, "mark": mark})
                break
    return {"count": len(due), "due": due}


@router.get("/directory/stats")
async def directory_stats(request: Request, org_id: int = 1,
                          db_session: AsyncSession = Depends(get_db_session)):
    """Diagnose why the public directory is empty: how many credentials exist,
    how many are opted in, and how many pass the effective-status filter."""
    _check(request)
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id))).scalars().all()
    by_status, by_type = {}, {}
    opted = eligible = listed = 0
    for c in rows:
        eff = svc.compute_effective_status(c)
        by_status[eff] = by_status.get(eff, 0) + 1
        by_type[c.credential_type] = by_type.get(c.credential_type, 0) + 1
        if c.directory_opt_in:
            opted += 1
        if eff in ("provisional", "full"):
            eligible += 1
            if c.directory_opt_in:
                listed += 1
    return {"total_credentials": len(rows), "opted_in": opted,
            "eligible_by_status": eligible, "currently_listed": listed,
            "by_effective_status": by_status, "by_type": by_type}


@router.post("/directory/bulk-opt-in")
async def directory_bulk_opt_in(request: Request,
                                db_session: AsyncSession = Depends(get_db_session)):
    """Opt credentials into the public directory in bulk. `directory_opt_in`
    defaults to False, so imported/auto-issued credentials never appeared in the
    public directory. Body: {org_id?, only_active?, opt_in?, dry_run?}.
    DRY-RUN by default."""
    _check(request)
    b = {}
    try:
        b = await request.json()
    except Exception:
        pass
    org_id = int(b.get("org_id") or 1)
    only_active = str(b.get("only_active", True)).lower() != "false"
    opt_in = str(b.get("opt_in", True)).lower() != "false"
    dry_run = str(b.get("dry_run", True)).lower() != "false"
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id))).scalars().all()
    changed = 0
    for c in rows:
        if only_active and svc.compute_effective_status(c) not in ("provisional", "full"):
            continue
        if bool(c.directory_opt_in) == opt_in:
            continue
        changed += 1
        if not dry_run:
            c.directory_opt_in = opt_in
            c.updated_at = svc._now()
            db_session.add(c)
    if not dry_run:
        await db_session.commit()
    return {"dry_run": dry_run, "org_id": org_id, "only_active": only_active,
            "opt_in": opt_in, "would_change" if dry_run else "changed": changed,
            "total_scanned": len(rows)}
