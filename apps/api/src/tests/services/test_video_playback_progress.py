from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlmodel import func, select
from starlette.requests import Request

from src.db.courses.blocks import Block, BlockTypeEnum
from src.db.video_playback_progress import VideoPlaybackProgress
from src.services.trail_video_progress import (
    VideoProgressWrite,
    get_video_playback_progress,
    save_video_playback_progress,
)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/trail/video-progress/activity_test",
            "headers": [],
        }
    )


class TestVideoPlaybackProgress:
    async def test_save_update_and_source_replacement(
        self,
        db,
        admin_user,
        activity,
    ):
        access_check = AsyncMock()
        with patch(
            "src.services.trail_video_progress.check_resource_access",
            access_check,
        ):
            created = await save_video_playback_progress(
                _request(),
                admin_user,
                activity.activity_uuid,
                VideoProgressWrite(
                    video_key=activity.activity_uuid,
                    source_id="lesson-v1.mp4",
                    position_seconds=42.5,
                    duration_seconds=180,
                ),
                db,
            )
            updated = await save_video_playback_progress(
                _request(),
                admin_user,
                activity.activity_uuid,
                VideoProgressWrite(
                    video_key=activity.activity_uuid,
                    source_id="lesson-v1.mp4",
                    position_seconds=75,
                    duration_seconds=180,
                ),
                db,
            )
            fetched = await get_video_playback_progress(
                _request(),
                admin_user,
                activity.activity_uuid,
                activity.activity_uuid,
                "lesson-v1.mp4",
                db,
            )
            replacement = await get_video_playback_progress(
                _request(),
                admin_user,
                activity.activity_uuid,
                activity.activity_uuid,
                "lesson-v2.mp4",
                db,
            )

        count = (
            await db.execute(select(func.count(VideoPlaybackProgress.id)))
        ).scalar_one()
        assert count == 1
        assert created.position_seconds == 42.5
        assert updated.position_seconds == 75
        assert fetched.position_seconds == 75
        assert replacement.position_seconds == 0
        assert replacement.source_id == "lesson-v2.mp4"
        assert access_check.await_count == 4

    async def test_progress_is_isolated_per_user(
        self,
        db,
        admin_user,
        regular_user,
        activity,
    ):
        with patch(
            "src.services.trail_video_progress.check_resource_access",
            new_callable=AsyncMock,
        ):
            await save_video_playback_progress(
                _request(),
                admin_user,
                activity.activity_uuid,
                VideoProgressWrite(
                    video_key=activity.activity_uuid,
                    source_id="lesson.mp4",
                    position_seconds=51,
                    duration_seconds=120,
                ),
                db,
            )
            other_user = await get_video_playback_progress(
                _request(),
                regular_user,
                activity.activity_uuid,
                activity.activity_uuid,
                "lesson.mp4",
                db,
            )

        assert other_user.position_seconds == 0

    async def test_embedded_video_must_belong_to_activity(
        self,
        db,
        admin_user,
        org,
        course,
        chapter,
        activity,
    ):
        video_block = Block(
            block_type=BlockTypeEnum.BLOCK_VIDEO,
            content={"file_id": "file-id", "file_format": "mp4"},
            org_id=org.id,
            course_id=course.id,
            chapter_id=chapter.id,
            activity_id=activity.id,
            block_uuid="block_video",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(video_block)
        await db.commit()

        with patch(
            "src.services.trail_video_progress.check_resource_access",
            new_callable=AsyncMock,
        ):
            saved = await save_video_playback_progress(
                _request(),
                admin_user,
                activity.activity_uuid,
                VideoProgressWrite(
                    video_key=video_block.block_uuid,
                    source_id="file-id.mp4",
                    position_seconds=33,
                    duration_seconds=90,
                ),
                db,
            )
            with pytest.raises(HTTPException) as exc:
                await save_video_playback_progress(
                    _request(),
                    admin_user,
                    activity.activity_uuid,
                    VideoProgressWrite(
                        video_key="block_not_in_activity",
                        source_id="other.mp4",
                        position_seconds=12,
                        duration_seconds=90,
                    ),
                    db,
                )

        assert saved.position_seconds == 33
        assert exc.value.status_code == 404

    async def test_position_is_capped_at_duration(
        self,
        db,
        admin_user,
        activity,
    ):
        with patch(
            "src.services.trail_video_progress.check_resource_access",
            new_callable=AsyncMock,
        ):
            saved = await save_video_playback_progress(
                _request(),
                admin_user,
                activity.activity_uuid,
                VideoProgressWrite(
                    video_key=activity.activity_uuid,
                    source_id="lesson.mp4",
                    position_seconds=999,
                    duration_seconds=100,
                ),
                db,
            )

        assert saved.position_seconds == 100
