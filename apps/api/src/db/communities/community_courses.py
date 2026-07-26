"""Join table: a community can carry MANY courses.

`Community.course_id` models one community -> one course, so linking a second
course silently overwrote the first. That is fine for "this community belongs to
that class", but not for grouping a set of classes in one place — e.g. every
Spanish class living in a Spanish-speaking families community instead of
cluttering the main catalogue.

`Community.course_id` is left in place and still written for the first link, so
existing screens and queries that read it keep working; this table is the full
picture and reads union the two.
"""
from typing import Optional

from sqlalchemy import Column, Integer, ForeignKey, Index
from sqlmodel import Field, SQLModel


class CommunityCourse(SQLModel, table=True):
    __tablename__ = "community_course"
    __table_args__ = (
        Index("ix_community_course_community_id", "community_id"),
        Index("ix_community_course_course_id", "course_id"),
        {"extend_existing": True},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(
        sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"))
    )
    community_id: int = Field(
        sa_column=Column(Integer, ForeignKey("community.id", ondelete="CASCADE"))
    )
    course_id: int = Field(
        sa_column=Column(Integer, ForeignKey("course.id", ondelete="CASCADE"))
    )
    creation_date: str = ""
