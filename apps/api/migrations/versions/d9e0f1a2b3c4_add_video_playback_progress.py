"""add video playback progress

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-07-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "video_playback_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=False),
        sa.Column("video_key", sa.String(length=255), nullable=False),
        sa.Column("source_id", sa.String(length=512), nullable=False),
        sa.Column("position_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("creation_date", sa.String(), nullable=False),
        sa.Column("update_date", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activity.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["course.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "activity_id",
            "video_key",
            name="uq_video_progress_user_activity_video",
        ),
    )
    op.create_index(
        "ix_video_progress_user_activity",
        "video_playback_progress",
        ["user_id", "activity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_video_playback_progress_activity_id"),
        "video_playback_progress",
        ["activity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_video_playback_progress_course_id"),
        "video_playback_progress",
        ["course_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_video_playback_progress_org_id"),
        "video_playback_progress",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_video_playback_progress_user_id"),
        "video_playback_progress",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_video_playback_progress_user_id"),
        table_name="video_playback_progress",
    )
    op.drop_index(
        op.f("ix_video_playback_progress_org_id"),
        table_name="video_playback_progress",
    )
    op.drop_index(
        op.f("ix_video_playback_progress_course_id"),
        table_name="video_playback_progress",
    )
    op.drop_index(
        op.f("ix_video_playback_progress_activity_id"),
        table_name="video_playback_progress",
    )
    op.drop_index(
        "ix_video_progress_user_activity",
        table_name="video_playback_progress",
    )
    op.drop_table("video_playback_progress")
