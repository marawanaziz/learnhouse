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
from sqlalchemy import Column, Integer, String
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
