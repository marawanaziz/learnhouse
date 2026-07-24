"""BBU cohorts (mentorship) — data models. Clean-room (never EE).

A cohort is a time-boxed group running one course + (optional) community with a
schedule. Access is granted through a native LearnHouse usergroup — the same
mechanism course-gating uses — so cohort membership unlocks the cohort's course
and nothing else. Completing a cohort feeds the credentials engine (bbu_credentials).
"""
from typing import Optional
from sqlalchemy import Column, Integer, String
from sqlmodel import Field, SQLModel


class BBUCohort(SQLModel, table=True):
    __tablename__ = "bbu_cohort"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    name: str = Field(default="", sa_column=Column(String(300)))
    program: str = Field(default="doula", sa_column=Column(String(24)))   # doula | agency | other
    course_uuid: str = Field(default="", sa_column=Column(String(80)))
    community_id: Optional[int] = Field(default=None)
    usergroup_id: Optional[int] = Field(default=None)                     # cohort access group
    start_date: str = Field(default="", sa_column=Column(String(40)))    # ISO date
    end_date: str = Field(default="", sa_column=Column(String(40)))
    capacity: int = Field(default=0)                                     # 0 = unlimited
    status: str = Field(default="open", sa_column=Column(String(16)))    # open|full|running|closed
    access_months: int = Field(default=6)                               # 6 doula / 12 agency
    zoom_link: str = Field(default="", sa_column=Column(String))
    workbook_url: str = Field(default="", sa_column=Column(String))
    # which credential a completion upgrades: birth | postpartum | both | "" (none)
    credential_type: str = Field(default="", sa_column=Column(String(16)))
    recordings: str = Field(default="", sa_column=Column(String))        # newline-separated links
    # JSON list of weekly discussion prompts auto-seeded from the program template;
    # dripped one/week into the cohort community. Each: {week,title,content,emoji,posted_at}
    weekly_prompts: str = Field(default="", sa_column=Column(String))
    # numeric Zoom meeting/webinar ID for the cohort's recurring series (for
    # auto-registering members + pulling recordings); zoom_link is the join URL.
    zoom_meeting_id: str = Field(default="", sa_column=Column(String(40)))
    created_at: str = Field(default="", sa_column=Column(String(40)))
    updated_at: str = Field(default="", sa_column=Column(String(40)))


class BBUCohortWaitlist(SQLModel, table=True):
    """Pre-purchase interest list: when every upcoming cohort of a program is
    full, the storefront collects a prospect here (no charge) instead of selling.
    When a seat frees, the earliest 'waiting' entries are notified to come buy."""
    __tablename__ = "bbu_cohort_waitlist"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    program: str = Field(default="doula", sa_column=Column(String(24), index=True))
    product_id: Optional[int] = Field(default=None)
    email: str = Field(default="", sa_column=Column(String(320), index=True))
    name: str = Field(default="", sa_column=Column(String(200)))
    phone: str = Field(default="", sa_column=Column(String(40)))
    # waiting | notified | converted | cancelled
    status: str = Field(default="waiting", sa_column=Column(String(16), index=True))
    created_at: str = Field(default="", sa_column=Column(String(40)))
    notified_at: str = Field(default="", sa_column=Column(String(40)))


class BBUCohortMember(SQLModel, table=True):
    __tablename__ = "bbu_cohort_member"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    cohort_id: int = Field(sa_column=Column(Integer, index=True))
    user_id: int = Field(sa_column=Column(Integer, index=True))
    # active | completed | removed | waitlisted
    status: str = Field(default="active", sa_column=Column(String(16)))
    joined_at: str = Field(default="", sa_column=Column(String(40)))
    completed_at: str = Field(default="", sa_column=Column(String(40)))
