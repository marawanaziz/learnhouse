"""Credential issuance-history and CEU-application regression tests.

These tests describe the business workflow independently of the HTTP/UI layer:
one-year credentials are preserved, CEU applications require documented and
reviewed CEUs, and approval creates exactly one new three-year issuance.
"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.bbu_credentials import applications as app_svc
from src.bbu_credentials import service as credential_svc
from src.bbu_credentials.models import (
    BBUCeuLedger,
    BBUCredential,
    BBUCredentialApplication,
    BBUCredentialApplicationDocument,
    BBUCredentialApplicationItem,
    BBUCredentialIssuance,
)


UTC = timezone.utc


@pytest.mark.asyncio
async def test_one_year_and_three_year_issuances_are_separate_history_rows(
    db, regular_user
):
    one_year = await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="birth",
        credential_level="one_year_provisional",
        effective_at=datetime(2024, 2, 29, tzinfo=UTC),
        source="training",
        source_ref="course_birth",
    )
    three_year = await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="birth",
        credential_level="three_year_full",
        effective_at=datetime(2025, 3, 2, tzinfo=UTC),
        source="mentorship",
        source_ref="cohort_12",
        supersedes_issuance_id=one_year.id,
    )

    rows = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.user_id == regular_user.id
            )
        )
    ).scalars().all()

    assert len(rows) == 2
    assert one_year.term_years == 1
    assert one_year.expires_at.startswith("2025-02-28")
    assert three_year.term_years == 3
    assert three_year.expires_at.startswith("2028-03-02")
    assert three_year.supersedes_issuance_id == one_year.id
    assert one_year.public_credential_id != three_year.public_credential_id
    assert one_year.verification_token != three_year.verification_token


@pytest.mark.asyncio
async def test_legacy_reconciliation_is_idempotent_and_preserves_dates(
    db, regular_user
):
    legacy = BBUCredential(
        org_id=1,
        user_id=regular_user.id,
        credential_type="postpartum",
        status="provisional",
        issued_at="2024-04-03T00:00:00+00:00",
        provisional_expires_at="2025-04-03T00:00:00+00:00",
        source="accredible",
        source_ref="acc-42",
    )
    db.add(legacy)
    await db.commit()
    await db.refresh(legacy)

    first = await app_svc.reconcile_legacy_credential(db, legacy)
    second = await app_svc.reconcile_legacy_credential(db, legacy)

    rows = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.user_id == regular_user.id,
                BBUCredentialIssuance.credential_type == "postpartum",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert first.id == second.id
    assert first.effective_at == "2024-04-03T00:00:00+00:00"
    assert first.expires_at == "2025-04-03T00:00:00+00:00"
    assert first.credential_level == "one_year_provisional"


@pytest.mark.asyncio
async def test_application_requires_prior_matching_bbu_credential(db, regular_user):
    with pytest.raises(HTTPException) as exc:
        await app_svc.create_application(
            db, org_id=1, user_id=regular_user.id, credential_type="birth"
        )
    assert exc.value.status_code == 403

    prior = await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="birth",
        credential_level="one_year_provisional",
        effective_at=datetime(2024, 1, 1, tzinfo=UTC),
        source="training",
        source_ref="course_birth",
    )
    application = await app_svc.create_application(
        db, org_id=1, user_id=regular_user.id, credential_type="birth"
    )
    assert application.status == "draft"
    assert application.qualifying_source_type == "credential_issuance"
    assert application.qualifying_source_id == prior.id


@pytest.mark.asyncio
async def test_ceu_completion_date_must_be_valid_and_not_future(db, regular_user):
    await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="birth",
        credential_level="one_year_provisional",
        effective_at=datetime(2025, 1, 1, tzinfo=UTC),
        source="training",
        source_ref="course_birth",
    )
    application = await app_svc.create_application(
        db, org_id=1, user_id=regular_user.id, credential_type="birth"
    )
    with pytest.raises(HTTPException) as invalid:
        await app_svc.add_application_item(
            db,
            application,
            training_title="Training",
            provider="Provider",
            completion_date="not-a-date",
            claimed_ceu=15,
        )
    assert invalid.value.status_code == 400

    with pytest.raises(HTTPException) as future:
        await app_svc.add_application_item(
            db,
            application,
            training_title="Training",
            provider="Provider",
            completion_date="2099-01-01",
            claimed_ceu=15,
        )
    assert "future" in future.value.detail.lower()


@pytest.mark.asyncio
async def test_reconciliation_report_is_dry_run_then_idempotent(db, regular_user):
    db.add(
        BBUCredential(
            org_id=1,
            user_id=regular_user.id,
            credential_type="birth",
            status="provisional",
            issued_at="2025-01-01T00:00:00+00:00",
            provisional_expires_at="2026-01-01T00:00:00+00:00",
        )
    )
    await db.commit()

    dry = await app_svc.reconciliation_report(db, 1, apply=False)
    assert dry["pending"] == 1
    assert dry["created"] == 0
    assert dry["pending_by_level"]["one_year_provisional"] == 1

    applied = await app_svc.reconciliation_report(db, 1, apply=True)
    again = await app_svc.reconciliation_report(db, 1, apply=True)
    assert applied["created"] == 1
    assert again["created"] == 0


@pytest.mark.asyncio
async def test_submit_requires_fifteen_documented_claimed_ceus(db, regular_user):
    await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="birth",
        credential_level="one_year_provisional",
        effective_at=datetime(2024, 1, 1, tzinfo=UTC),
        source="training",
        source_ref="course_birth",
    )
    application = await app_svc.create_application(
        db, org_id=1, user_id=regular_user.id, credential_type="birth"
    )
    item = await app_svc.add_application_item(
        db,
        application,
        training_title="Advanced Birth Support",
        provider="Training Partner",
        completion_date="2026-06-01",
        claimed_ceu=14,
    )
    await app_svc.add_document_record(
        db,
        application,
        item,
        storage_key="proof.pdf",
        original_filename="proof.pdf",
        content_type="application/pdf",
        byte_size=1200,
    )

    with pytest.raises(HTTPException) as exc:
        await app_svc.submit_application(db, application)
    assert exc.value.status_code == 400
    assert "15" in exc.value.detail

    item.claimed_ceu = 15
    db.add(item)
    await db.commit()
    submitted = await app_svc.submit_application(db, application)
    assert submitted.status == "submitted"
    assert submitted.claimed_ceu_total == 15
    assert submitted.submitted_at


@pytest.mark.asyncio
async def test_submit_requires_document_for_every_ceu_item(db, regular_user):
    await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="postpartum",
        credential_level="three_year_full",
        effective_at=datetime(2023, 1, 1, tzinfo=UTC),
        source="cross_cert",
        source_ref="course_cross",
    )
    application = await app_svc.create_application(
        db, org_id=1, user_id=regular_user.id, credential_type="postpartum"
    )
    await app_svc.add_application_item(
        db,
        application,
        training_title="Newborn Care",
        provider="Training Partner",
        completion_date="2026-05-01",
        claimed_ceu=15,
    )

    with pytest.raises(HTTPException) as exc:
        await app_svc.submit_application(db, application)
    assert exc.value.status_code == 400
    assert "document" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_approval_requires_reviewed_total_and_is_idempotent(db, regular_user):
    prior = await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="birth",
        credential_level="one_year_provisional",
        effective_at=datetime(2025, 1, 15, tzinfo=UTC),
        source="training",
        source_ref="course_birth",
    )
    application = await app_svc.create_application(
        db, org_id=1, user_id=regular_user.id, credential_type="birth"
    )
    item_a = await app_svc.add_application_item(
        db,
        application,
        training_title="Birth Equity",
        provider="Provider A",
        completion_date="2026-01-01",
        claimed_ceu=10,
    )
    item_b = await app_svc.add_application_item(
        db,
        application,
        training_title="Trauma Informed Support",
        provider="Provider B",
        completion_date="2026-02-01",
        claimed_ceu=8,
    )
    for item in (item_a, item_b):
        await app_svc.add_document_record(
            db,
            application,
            item,
            storage_key=f"{item.id}.pdf",
            original_filename=f"{item.id}.pdf",
            content_type="application/pdf",
            byte_size=100,
        )
    await app_svc.submit_application(db, application)
    await app_svc.review_application_item(
        db, application, item_a, approved_ceu=9, admin_note=""
    )
    await app_svc.review_application_item(
        db, application, item_b, approved_ceu=6, admin_note=""
    )

    issuance = await app_svc.approve_application(
        db,
        application,
        reviewer_user_id=99,
        effective_at=datetime(2026, 3, 10, tzinfo=UTC),
    )
    again = await app_svc.approve_application(
        db,
        application,
        reviewer_user_id=99,
        effective_at=datetime(2026, 3, 10, tzinfo=UTC),
    )

    assert issuance.id == again.id
    assert issuance.credential_level == "three_year_full"
    assert issuance.term_years == 3
    assert issuance.expires_at.startswith("2029-03-10")
    assert issuance.supersedes_issuance_id == prior.id

    history = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.user_id == regular_user.id
            )
        )
    ).scalars().all()
    ledger = (
        await db.execute(
            select(BBUCeuLedger).where(BBUCeuLedger.user_id == regular_user.id)
        )
    ).scalars().all()
    assert len(history) == 2
    assert sorted(row.ceu_count for row in ledger) == [6, 9]
    assert application.status == "approved"
    assert application.approved_ceu_total == 15
    assert application.approved_issuance_id == issuance.id


@pytest.mark.asyncio
async def test_decline_requires_reason_and_does_not_change_credentials(
    db, regular_user
):
    await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="birth",
        credential_level="three_year_full",
        effective_at=datetime(2023, 1, 1, tzinfo=UTC),
        source="cross_cert",
        source_ref="cross",
    )
    application = BBUCredentialApplication(
        public_uuid="application_test",
        org_id=1,
        user_id=regular_user.id,
        credential_type="birth",
        status="submitted",
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)

    with pytest.raises(HTTPException) as exc:
        await app_svc.decline_application(
            db, application, reviewer_user_id=99, reason=""
        )
    assert exc.value.status_code == 400

    await app_svc.decline_application(
        db,
        application,
        reviewer_user_id=99,
        reason="The completion certificate is not legible.",
    )
    history = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.user_id == regular_user.id
            )
        )
    ).scalars().all()
    assert len(history) == 1
    assert application.status == "declined"
    assert application.decline_reason == "The completion certificate is not legible."


def test_application_models_use_expected_table_names():
    assert BBUCredentialApplication.__tablename__ == "bbu_credential_application"
    assert BBUCredentialApplicationItem.__tablename__ == "bbu_credential_application_item"
    assert BBUCredentialApplicationDocument.__tablename__ == "bbu_credential_application_document"


@pytest.mark.asyncio
async def test_training_issue_creates_one_year_history_and_is_idempotent(
    db, regular_user
):
    first = await credential_svc.issue_provisional(
        db, 1, regular_user.id, "birth", source_ref="course_birth"
    )
    second = await credential_svc.issue_provisional(
        db, 1, regular_user.id, "birth", source_ref="course_birth"
    )
    history = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.user_id == regular_user.id,
                BBUCredentialIssuance.credential_type == "birth",
            )
        )
    ).scalars().all()
    assert first.id == second.id
    assert len(history) == 1
    assert history[0].credential_level == "one_year_provisional"


@pytest.mark.asyncio
async def test_generic_ceu_ledger_total_never_auto_upgrades_credential(
    db, regular_user
):
    credential = await credential_svc.issue_provisional(
        db, 1, regular_user.id, "postpartum", source_ref="course_postpartum"
    )
    await credential_svc.award_ceu(
        db,
        1,
        regular_user.id,
        15,
        source="manual",
        source_ref="outside-training",
        approved=True,
    )
    await db.refresh(credential)
    history = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.user_id == regular_user.id,
                BBUCredentialIssuance.credential_type == "postpartum",
            )
        )
    ).scalars().all()
    assert credential.status == "provisional"
    assert len(history) == 1
    assert history[0].credential_level == "one_year_provisional"
