"""Focused regression coverage for Project BOLD host access."""

from datetime import datetime

import pytest
from sqlmodel import select
from starlette.requests import Request

from src.bbu_migration.bold_access import (
    BOLD_COMMUNITY_NAMES,
    ensure_bold_access,
    ensure_bold_access_for_request,
    ensure_bold_course_access,
    is_bold_course,
    is_bold_host_request,
)
from src.db.communities.communities import Community
from src.db.courses.courses import Course
from src.db.trails import Trail
from src.db.trail_runs import TrailRun
from src.db.usergroup_resources import UserGroupResource
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup


def _request(host: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"host", host.encode())],
        }
    )


def _proxied_request(public_host: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (b"host", b"app-production-500b.up.railway.app"),
                (b"x-learnhouse-public-host", public_host.encode()),
            ],
        }
    )


async def _bold_access_fixture(db, org):
    now = str(datetime.now())
    groups = []
    for index, name in enumerate(BOLD_COMMUNITY_NAMES, start=1):
        group = UserGroup(
            org_id=org.id,
            name=f"BOLD group {index}",
            description=name,
            usergroup_uuid=f"usergroup_bold_{index}",
            creation_date=now,
            update_date=now,
        )
        db.add(group)
        await db.flush()
        community = Community(
            org_id=org.id,
            name=name,
            description=name,
            public=False,
            community_uuid=f"community_bold_{index}",
            creation_date=now,
            update_date=now,
        )
        db.add(community)
        await db.flush()
        db.add(
            UserGroupResource(
                usergroup_id=group.id,
                resource_uuid=community.community_uuid,
                org_id=org.id,
                creation_date=now,
                update_date=now,
            )
        )
        groups.append(group)
    await db.commit()
    return groups


def test_host_attribution_is_exact_and_bbu_host_is_unchanged():
    assert is_bold_host_request(_request("learn.boldmovement.org"))
    assert is_bold_host_request(_request("learn.boldmovement.org:443"))
    assert not is_bold_host_request(_request("learn.birthandbabyuniversity.com"))
    assert not is_bold_host_request(_request("evil-learn.boldmovement.org"))
    assert is_bold_host_request(_proxied_request("learn.boldmovement.org"))
    assert not is_bold_host_request(
        _proxied_request("learn.birthandbabyuniversity.com")
    )


def test_course_matching_is_case_insensitive():
    assert is_bold_course(Course(name="Project BOLD: Family Class"))
    assert is_bold_course(Course(name="project bold: professional class"))
    assert not is_bold_course(Course(name="Certified Birth Doula Training"))


@pytest.mark.asyncio
async def test_published_only_and_idempotent_current_and_future_access(
    db, org, regular_user
):
    groups = await _bold_access_fixture(db, org)
    now = str(datetime.now())
    current = Course(
        name="Project BOLD Current",
        description="current",
        public=False,
        published=True,
        open_to_contributors=False,
        org_id=org.id,
        course_uuid="course_bold_current",
        creation_date=now,
        update_date=now,
    )
    unpublished = Course(
        name="PROJECT bold Future Draft",
        description="draft",
        public=False,
        published=False,
        open_to_contributors=False,
        org_id=org.id,
        course_uuid="course_bold_draft",
        creation_date=now,
        update_date=now,
    )
    db.add(current)
    db.add(unpublished)
    await db.commit()

    first = await ensure_bold_access(
        db, regular_user.id, org.id, source="host_signup"
    )
    second = await ensure_bold_access(
        db, regular_user.id, org.id, source="host_login"
    )
    assert first["enrollments_added"] == 1
    assert second["enrollments_added"] == 0
    assert second["enrollments_existing"] == 1

    runs = (
        await db.execute(select(TrailRun).where(TrailRun.user_id == regular_user.id))
    ).scalars().all()
    assert [run.course_id for run in runs] == [current.id]
    memberships = (
        await db.execute(select(UserGroupUser).where(UserGroupUser.user_id == regular_user.id))
    ).scalars().all()
    assert len(memberships) == len(groups)

    future = Course(
        name="Project BOLD Future Published",
        description="future",
        public=False,
        published=True,
        open_to_contributors=False,
        org_id=org.id,
        course_uuid="course_bold_future",
        creation_date=now,
        update_date=now,
    )
    db.add(future)
    await db.commit()
    result = await ensure_bold_course_access(db, future)
    assert result["eligible"] is True
    assert result["participant_count"] == 1
    runs = (
        await db.execute(select(TrailRun).where(TrailRun.user_id == regular_user.id))
    ).scalars().all()
    assert {run.course_id for run in runs} == {current.id, future.id}
    links = (
        await db.execute(
            select(UserGroupResource).where(
                UserGroupResource.resource_uuid == future.course_uuid
            )
        )
    ).scalars().all()
    assert len(links) == len(groups)


@pytest.mark.asyncio
async def test_existing_user_request_hook_and_bbu_host_regression(
    db, org, regular_user
):
    await _bold_access_fixture(db, org)
    assert await ensure_bold_access_for_request(
        _request("learn.boldmovement.org"), db, regular_user.id, org.id
    )
    assert await ensure_bold_access_for_request(
        _request("learn.birthandbabyuniversity.com"), db, regular_user.id, org.id
    ) is None
