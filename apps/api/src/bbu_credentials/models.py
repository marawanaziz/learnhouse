"""BBU credentials engine — data models. Clean-room (never EE).

A *credential* is the professional certification a doula holds (birth /
postpartum), distinct from a per-course certificate. It has a lifecycle:

    provisional (1yr) --mentorship OR >=15 CEU--> full (3yr) --renew(15 CEU)--> full
         |                                             |
         +-- expiry, no upgrade --> lapsed             +-- expiry, no renew --> expired

Cross-certifications are issued `full` (3yr) directly. CEUs accumulate in a
ledger and are summed toward the 15-CEU upgrade/renewal threshold.
"""
from typing import Optional
from sqlalchemy import Boolean, Column, Integer, JSON, String, Text
from sqlmodel import Field, SQLModel


class BBUCredential(SQLModel, table=True):
    __tablename__ = "bbu_credential"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(Integer, index=True))
    credential_type: str = Field(default="birth", sa_column=Column(String(16)))  # birth | postpartum
    # provisional | full | lapsed | expired
    status: str = Field(default="provisional", sa_column=Column(String(16)))
    issued_at: str = Field(default="", sa_column=Column(String(40)))
    provisional_expires_at: str = Field(default="", sa_column=Column(String(40)))
    full_effective_at: str = Field(default="", sa_column=Column(String(40)))
    full_expires_at: str = Field(default="", sa_column=Column(String(40)))
    source: str = Field(default="training", sa_column=Column(String(24)))  # training|cross_cert|manual
    source_ref: str = Field(default="", sa_column=Column(String(120)))     # course_uuid / cohort id
    # CEUs already counted toward the CURRENT full window (reset on upgrade/renew)
    renewal_ceu_baseline: int = Field(default=0)
    directory_opt_in: bool = Field(default=False)
    # last pre-expiry reminder window (days) already fired, so the scheduled
    # reminder job doesn't re-notify the same window repeatedly. 0 = none yet.
    last_reminder_days: int = Field(default=0)
    updated_at: str = Field(default="", sa_column=Column(String(40)))


class BBUCeuLedger(SQLModel, table=True):
    __tablename__ = "bbu_ceu_ledger"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(Integer, index=True))
    ceu_count: int = Field(default=0)
    source: str = Field(default="course", sa_column=Column(String(24)))    # course|mentorship|manual
    source_ref: str = Field(default="", sa_column=Column(String(120)))     # course_uuid / note
    approved: bool = Field(default=True)                                   # external CEUs need admin approval
    submitted_at: str = Field(default="", sa_column=Column(String(40)))
    approved_at: str = Field(default="", sa_column=Column(String(40)))


class BBUCredentialIssuance(SQLModel, table=True):
    """One immutable professional-credential issuance.

    ``BBUCredential`` remains the compatibility/current-state row used by the
    existing registry and reminder jobs. This table is the durable history:
    moving from a one-year credential to a three-year credential inserts a new
    row instead of rewriting the earlier certificate.
    """

    __tablename__ = "bbu_credential_issuance"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    credential_type: str = Field(
        default="birth", sa_column=Column(String(16), nullable=False, index=True)
    )
    # one_year_provisional | three_year_full
    credential_level: str = Field(
        default="one_year_provisional",
        sa_column=Column(String(32), nullable=False, index=True),
    )
    term_years: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    # issued | revoked. Active/lapsed/expired is derived from level + expires_at.
    status: str = Field(
        default="issued", sa_column=Column(String(16), nullable=False, index=True)
    )
    source: str = Field(
        default="training", sa_column=Column(String(32), nullable=False, index=True)
    )
    source_ref: str = Field(default="", sa_column=Column(String(160), index=True))
    effective_at: str = Field(default="", sa_column=Column(String(40), nullable=False))
    expires_at: str = Field(default="", sa_column=Column(String(40), nullable=False))
    public_credential_id: str = Field(
        default="",
        sa_column=Column(String(48), nullable=False, unique=True, index=True),
    )
    verification_token: str = Field(
        default="",
        sa_column=Column(String(80), nullable=False, unique=True, index=True),
    )
    supersedes_issuance_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )
    directory_opt_in: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, default=False)
    )
    issued_by_user_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: str = Field(default="", sa_column=Column(String(40), nullable=False))


class BBUCredentialApplication(SQLModel, table=True):
    __tablename__ = "bbu_credential_application"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    public_uuid: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, index=True)
    )
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    credential_type: str = Field(
        default="birth", sa_column=Column(String(16), nullable=False, index=True)
    )
    qualifying_source_type: str = Field(default="", sa_column=Column(String(40)))
    qualifying_source_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    # draft | submitted | approved | declined
    status: str = Field(
        default="draft", sa_column=Column(String(20), nullable=False, index=True)
    )
    claimed_ceu_total: int = Field(default=0)
    approved_ceu_total: int = Field(default=0)
    submitted_at: str = Field(default="", sa_column=Column(String(40)))
    reviewed_at: str = Field(default="", sa_column=Column(String(40)))
    reviewed_by_user_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    decline_reason: str = Field(default="", sa_column=Column(Text))
    approved_issuance_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, unique=True, index=True),
    )
    submission_member_notified_at: str = Field(
        default="", sa_column=Column(String(40))
    )
    submission_admin_notified_at: str = Field(
        default="", sa_column=Column(String(40))
    )
    submission_notified_at: str = Field(default="", sa_column=Column(String(40)))
    decision_notified_at: str = Field(default="", sa_column=Column(String(40)))
    notification_attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, default=0)
    )
    notification_error: str = Field(default="", sa_column=Column(Text))
    created_at: str = Field(default="", sa_column=Column(String(40), nullable=False))
    updated_at: str = Field(default="", sa_column=Column(String(40), nullable=False))


class BBUCredentialApplicationItem(SQLModel, table=True):
    __tablename__ = "bbu_credential_application_item"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True)
    )
    training_title: str = Field(
        default="", sa_column=Column(String(240), nullable=False)
    )
    provider: str = Field(default="", sa_column=Column(String(240), nullable=False))
    completion_date: str = Field(
        default="", sa_column=Column(String(20), nullable=False)
    )
    claimed_ceu: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    approved_ceu: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    admin_note: str = Field(default="", sa_column=Column(Text))
    created_at: str = Field(default="", sa_column=Column(String(40), nullable=False))
    updated_at: str = Field(default="", sa_column=Column(String(40), nullable=False))


class BBUCredentialApplicationDocument(SQLModel, table=True):
    __tablename__ = "bbu_credential_application_document"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True)
    )
    application_item_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True)
    )
    storage_key: str = Field(
        default="", sa_column=Column(String(300), nullable=False)
    )
    original_filename: str = Field(
        default="", sa_column=Column(String(300), nullable=False)
    )
    content_type: str = Field(
        default="", sa_column=Column(String(120), nullable=False)
    )
    byte_size: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    uploaded_at: str = Field(default="", sa_column=Column(String(40), nullable=False))


class BBUCredentialAuditEvent(SQLModel, table=True):
    __tablename__ = "bbu_credential_audit_event"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    actor_user_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )
    action: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    target_type: str = Field(sa_column=Column(String(40), nullable=False))
    target_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    before_data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    after_data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    reason: str = Field(default="", sa_column=Column(Text))
    created_at: str = Field(default="", sa_column=Column(String(40), nullable=False))
