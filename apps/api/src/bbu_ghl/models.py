"""BBU <-> GHL sync mapping.

Remembers which GHL contact / course-enrollment record each (email, course)
maps to, so re-syncs UPDATE the existing record instead of creating duplicates
in the client's live CRM. Idempotency is the whole point of this table.
"""
from typing import Optional

from sqlalchemy import Column, Index, Integer, String, UniqueConstraint
from sqlmodel import Field, SQLModel


class BBUGHLSync(SQLModel, table=True):
    __tablename__ = "bbu_ghl_sync"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    email: str = Field(default="", sa_column=Column(String(320), index=True))
    # "" for the contact-level row; course_uuid for a per-course enrollment row
    course_uuid: str = Field(default="", sa_column=Column(String(80), index=True))
    ghl_contact_id: str = Field(default="", sa_column=Column(String(64), index=True))
    ghl_record_id: str = Field(default="", sa_column=Column(String(64)))
    last_status: str = Field(default="", sa_column=Column(String(32)))
    updated_at: str = Field(default="", sa_column=Column(String(40)))


class BBUZoomEventRegistration(SQLModel, table=True):
    """Durable idempotency receipts for the two BBU Zoom Events.

    A Zoom retry must not cause another GHL mutation. The compound key is
    deliberately event + normalized email + Zoom ticket/registration identity;
    it permits two distinct registrations by one email while collapsing only a
    replay of the same registration.
    """

    __tablename__ = "bbu_zoom_event_registration"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "email",
            "registration_identity",
            name="uq_bbu_zoom_event_registration_key",
        ),
        Index(
            "ix_bbu_zoom_event_registration_event_email",
            "event_id",
            "email",
        ),
        {"extend_existing": True},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: str = Field(default="", sa_column=Column(String(80), nullable=False))
    ticket_type_id: str = Field(default="", sa_column=Column(String(100), nullable=False))
    email: str = Field(default="", sa_column=Column(String(320), nullable=False))
    registration_identity: str = Field(
        default="", sa_column=Column(String(160), nullable=False)
    )
    ghl_contact_id: str = Field(default="", sa_column=Column(String(64), nullable=False))
    tag: str = Field(default="", sa_column=Column(String(120), nullable=False))
    status: str = Field(default="processing", sa_column=Column(String(24), nullable=False))
    received_at: str = Field(default="", sa_column=Column(String(40), nullable=False))
    updated_at: str = Field(default="", sa_column=Column(String(40), nullable=False))
