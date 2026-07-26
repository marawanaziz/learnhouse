"""Sponsored access — people whose seat someone else paid for.

Grant recipients, CFD families, scholarships and staff must never touch Stripe:
a 100%-off coupon still walks them through a payment page for a $0 order, which
is confusing and, for a funder-sponsored cohort, simply the wrong model. Access
here is granted directly.

The second job is attribution. A funder (BCBS) has to be told exactly who their
money served, and that answer has to span both the historical Circle coupon data
and everything granted from now on. Every route in — bulk list, shareable link,
individual code — writes one BBUSponsoredEnrollment row, so the report is a
single query rather than three systems stitched together by hand.
"""
from typing import Optional

from sqlalchemy import Column, Integer, String
from sqlmodel import Field, SQLModel


class BBUSponsor(SQLModel, table=True):
    """Whoever is covering the cost — a grant, a partner org, or BBU itself."""
    __tablename__ = "bbu_sponsor"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    name: str = Field(default="", sa_column=Column(String(200), index=True))
    # grant | partner | scholarship | internal | clinic
    kind: str = Field(default="grant", sa_column=Column(String(20)))
    # comma-separated course_uuids this sponsorship covers
    course_uuids: str = Field(default="", sa_column=Column(String))
    # 0 = unlimited. Enforced across every route in, so a shared link cannot
    # quietly overshoot what the funder agreed to pay for.
    seat_limit: int = Field(default=0)
    # token behind the shareable /join/<token> link; blank disables that route
    join_token: str = Field(default="", sa_column=Column(String(64), index=True))
    join_enabled: bool = Field(default=False)
    # Circle coupon codes that belonged to this sponsor, comma-separated, so the
    # imported history rolls into the same report as new enrollments
    legacy_codes: str = Field(default="", sa_column=Column(String))
    notes: str = Field(default="", sa_column=Column(String))
    active: bool = Field(default=True)
    created_at: str = Field(default="", sa_column=Column(String(40)))


class BBUSponsoredEnrollment(SQLModel, table=True):
    """One person, enrolled under one sponsor, without paying."""
    __tablename__ = "bbu_sponsored_enrollment"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    sponsor_id: int = Field(sa_column=Column(Integer, index=True))
    user_id: Optional[int] = Field(default=None)
    email: str = Field(default="", sa_column=Column(String(320), index=True))
    name: str = Field(default="", sa_column=Column(String(200)))
    course_uuids: str = Field(default="", sa_column=Column(String))
    # bulk | link | code | manual
    method: str = Field(default="bulk", sa_column=Column(String(12)))
    code: str = Field(default="", sa_column=Column(String(32)))
    enrolled_at: str = Field(default="", sa_column=Column(String(40)))
