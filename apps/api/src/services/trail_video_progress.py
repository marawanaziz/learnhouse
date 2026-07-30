from datetime import datetime

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity
from src.db.courses.blocks import Block, BlockTypeEnum
from src.db.courses.courses import Course
from src.db.users import AnonymousUser, PublicUser
from src.db.video_playback_progress import VideoPlaybackProgress
from src.security.rbac import AccessAction, check_resource_access


class VideoProgressWrite(BaseModel):
    video_key: str = Field(min_length=1, max_length=255)
    source_id: str = Field(min_length=1, max_length=512)
    position_seconds: float = Field(ge=0, le=172800)
    duration_seconds: float | None = Field(default=None, ge=0, le=172800)


class VideoProgressRead(BaseModel):
    activity_uuid: str
    video_key: str
    source_id: str
    position_seconds: float = 0
    duration_seconds: float | None = None
    update_date: str | None = None


async def _resolve_video_context(
    request: Request,
    user: PublicUser | AnonymousUser,
    activity_uuid: str,
    video_key: str,
    db_session: AsyncSession,
) -> tuple[Activity, Course]:
    if isinstance(user, AnonymousUser):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to save video progress",
        )

    activity = (
        await db_session.execute(
            select(Activity).where(Activity.activity_uuid == activity_uuid)
        )
    ).scalars().first()
    if not activity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Activity not found",
        )

    course = (
        await db_session.execute(select(Course).where(Course.id == activity.course_id))
    ).scalars().first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )

    await check_resource_access(
        request,
        db_session,
        user,
        course.course_uuid,
        AccessAction.READ,
    )

    # Standalone video activities use their own UUID. Page videos use a real
    # BLOCK_VIDEO belonging to the requested activity. This prevents arbitrary
    # checkpoint keys from being written against a course.
    if video_key != activity_uuid:
        video_block = (
            await db_session.execute(
                select(Block).where(
                    Block.block_uuid == video_key,
                    Block.activity_id == activity.id,
                    Block.block_type == BlockTypeEnum.BLOCK_VIDEO,
                )
            )
        ).scalars().first()
        if not video_block:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Video not found in this activity",
            )

    return activity, course


def _empty_progress(
    activity_uuid: str,
    video_key: str,
    source_id: str,
) -> VideoProgressRead:
    return VideoProgressRead(
        activity_uuid=activity_uuid,
        video_key=video_key,
        source_id=source_id,
    )


async def get_video_playback_progress(
    request: Request,
    user: PublicUser | AnonymousUser,
    activity_uuid: str,
    video_key: str,
    source_id: str,
    db_session: AsyncSession,
) -> VideoProgressRead:
    activity, _course = await _resolve_video_context(
        request,
        user,
        activity_uuid,
        video_key,
        db_session,
    )

    progress = (
        await db_session.execute(
            select(VideoPlaybackProgress).where(
                VideoPlaybackProgress.user_id == user.id,
                VideoPlaybackProgress.activity_id == activity.id,
                VideoPlaybackProgress.video_key == video_key,
            )
        )
    ).scalars().first()

    # Replacing the uploaded file or external video invalidates the old spot.
    if not progress or progress.source_id != source_id:
        return _empty_progress(activity_uuid, video_key, source_id)

    return VideoProgressRead(
        activity_uuid=activity_uuid,
        video_key=video_key,
        source_id=source_id,
        position_seconds=max(0, progress.position_seconds),
        duration_seconds=progress.duration_seconds,
        update_date=progress.update_date,
    )


async def save_video_playback_progress(
    request: Request,
    user: PublicUser | AnonymousUser,
    activity_uuid: str,
    payload: VideoProgressWrite,
    db_session: AsyncSession,
) -> VideoProgressRead:
    activity, course = await _resolve_video_context(
        request,
        user,
        activity_uuid,
        payload.video_key,
        db_session,
    )

    duration = payload.duration_seconds
    position = payload.position_seconds
    if duration and duration > 0:
        position = min(position, duration)

    now = str(datetime.now())
    progress = (
        await db_session.execute(
            select(VideoPlaybackProgress).where(
                VideoPlaybackProgress.user_id == user.id,
                VideoPlaybackProgress.activity_id == activity.id,
                VideoPlaybackProgress.video_key == payload.video_key,
            )
        )
    ).scalars().first()

    if progress:
        progress.source_id = payload.source_id
        progress.position_seconds = position
        progress.duration_seconds = duration
        progress.update_date = now
    else:
        progress = VideoPlaybackProgress(
            user_id=user.id,
            org_id=course.org_id,
            course_id=course.id,
            activity_id=activity.id,
            video_key=payload.video_key,
            source_id=payload.source_id,
            position_seconds=position,
            duration_seconds=duration,
            creation_date=now,
            update_date=now,
        )

    db_session.add(progress)
    try:
        await db_session.commit()
    except IntegrityError:
        # Pause, pagehide, and the periodic checkpoint can arrive together.
        # If two first writes raced, update the row won by the other request.
        await db_session.rollback()
        progress = (
            await db_session.execute(
                select(VideoPlaybackProgress).where(
                    VideoPlaybackProgress.user_id == user.id,
                    VideoPlaybackProgress.activity_id == activity.id,
                    VideoPlaybackProgress.video_key == payload.video_key,
                )
            )
        ).scalars().first()
        if not progress:
            raise
        progress.source_id = payload.source_id
        progress.position_seconds = position
        progress.duration_seconds = duration
        progress.update_date = now
        db_session.add(progress)
        await db_session.commit()

    await db_session.refresh(progress)
    return VideoProgressRead(
        activity_uuid=activity_uuid,
        video_key=payload.video_key,
        source_id=payload.source_id,
        position_seconds=progress.position_seconds,
        duration_seconds=progress.duration_seconds,
        update_date=progress.update_date,
    )
