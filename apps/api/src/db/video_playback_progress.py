from typing import Optional

from sqlalchemy import Column, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlmodel import Field, SQLModel


class VideoPlaybackProgress(SQLModel, table=True):
    """The last playback position for one learner and one video.

    ``video_key`` is the activity UUID for a standalone video activity and the
    block UUID for a video embedded in a page. ``source_id`` identifies the
    actual uploaded file/external video so replacing a video's media starts the
    replacement from the beginning instead of reusing a stale checkpoint.
    """

    __tablename__ = "video_playback_progress"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "activity_id",
            "video_key",
            name="uq_video_progress_user_activity_video",
        ),
        Index(
            "ix_video_progress_user_activity",
            "user_id",
            "activity_id",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    org_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    course_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("course.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    activity_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("activity.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    video_key: str = Field(sa_column=Column(String(255), nullable=False))
    source_id: str = Field(sa_column=Column(String(512), nullable=False))
    position_seconds: float = Field(
        default=0,
        sa_column=Column(Float, nullable=False, default=0),
    )
    duration_seconds: Optional[float] = Field(
        default=None,
        sa_column=Column(Float, nullable=True),
    )
    creation_date: str
    update_date: str
