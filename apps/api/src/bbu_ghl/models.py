"""BBU <-> GHL sync mapping.

Remembers which GHL contact / course-enrollment record each (email, course)
maps to, so re-syncs UPDATE the existing record instead of creating duplicates
in the client's live CRM. Idempotency is the whole point of this table.
"""
from typing import Optional

from sqlalchemy import Column, Integer, String
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
