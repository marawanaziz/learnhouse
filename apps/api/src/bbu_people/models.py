"""BBU people / customer profiles — data model. Clean-room.

Captures quiz submissions (the platform's inline quiz blocks are client-side only
and never persist answers, so this is what makes 'see their answers + scores'
possible). Everything else a profile shows (enrollments, progress, certs,
credentials, cohorts, purchases) already lives in existing tables and is joined
at read time — no duplication.
"""
from typing import Optional
from sqlalchemy import Column, Integer, String, JSON, Boolean
from sqlmodel import Field, SQLModel


class BBUQuizSubmission(SQLModel, table=True):
    """One graded attempt at a lesson's quiz by one learner. `answers` holds the
    per-question breakdown (their choice(s), the correct choice(s), right/wrong)."""
    __tablename__ = "bbu_quiz_submission"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    activity_uuid: str = Field(default="", sa_column=Column(String(80), index=True))
    course_uuid: str = Field(default="", sa_column=Column(String(80), index=True))
    activity_name: str = Field(default="", sa_column=Column(String(300)))
    score: int = Field(default=0)               # 0..100 (%)
    passed: bool = Field(default=False, sa_column=Column(Boolean, default=False))
    correct_count: int = Field(default=0)
    total_questions: int = Field(default=0)
    attempt: int = Field(default=1)
    # [{question, options:[...], your_answers:[...], correct_answers:[...], is_correct}]
    answers: Optional[list] = Field(default=None, sa_column=Column(JSON))
    created_at: str = Field(default="", sa_column=Column(String(40)))
