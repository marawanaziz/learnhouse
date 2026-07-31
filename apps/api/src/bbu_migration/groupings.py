"""Anna's class groupings — audience segmentation, Bold copies, Spanish communities.

From her 26 Jul brief: professionals should see professional and doula trainings,
families should see family classes, Project BOLD cohorts should see only their own
labelled versions, and the Spanish classes should live in their own community
rather than clutter the main catalogue.

Three provisioning steps, each idempotent and each with a dry run, because they
mutate the live catalogue:

  POST /groupings/audiences   create the audiences + their usergroups, tag products
  POST /groupings/clone-bold  duplicate the named courses into Project BOLD versions
  POST /groupings/communities create the Spanish communities and attach courses
  GET  /groupings/plan        what the tagging pass *would* do, changing nothing

Tagging is by name rule with an explicit override map. Names change, so `plan`
exists to be read by a human before anything is written — a misfiled product
disappears from a storefront, which is exactly the kind of silent breakage that
is hard to notice and easy to avoid.
"""
import os
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_payments.models import BBUAudience, BBUProduct
from src.core.events.database import get_db_session
from src.db.communities.communities import Community
from src.db.courses.courses import Course
from src.db.usergroups import UserGroup

router = APIRouter()
ORG = 1
ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")

# slug, display name, is_public_default, cross_sell, order
AUDIENCES = [
    ("family", "Expecting Families", True, False, 10),
    ("professional", "Perinatal Professionals", False, True, 20),
    ("bold_professional", "Project BOLD — Professionals", False, False, 30),
    ("bold_family", "Project BOLD — Families", False, False, 40),
    ("spanish_family", "Spanish-Speaking Families", False, False, 50),
    ("bold_spanish_family", "Project BOLD — Spanish-Speaking Families", False, False, 60),
]

AUDIENCE_GROUP_NAMES = {
    "family": "Family",
    "professional": "BBU Professionals",
    "bold_professional": "Bold Perinatal Professionals",
    "bold_family": "Bold Families",
    "spanish_family": "Spanish-Speaking Families",
    "bold_spanish_family": "Project BOLD — Spanish-Speaking Families",
}

# A product is professional if its name matches any of these.
PRO_MARKERS = ("doula training", "perinatal professional", "mentorship",
               "agency owner", "cross certification")
# Spanish catalogue (names are Spanish, so match on the actual titles).
ES_MARKERS = ("atención", "atencion", "introducción", "introduccion",
              "lactancia", "preparándose", "preparandose", "pase virtual")
# Explicit wins over the rules — for anything the markers get wrong.
OVERRIDES: dict = {
    "all access class pass": "family",
    "birth prep ebook & guide": "family",
    "newborn care basics ebook & guide": "family",
    "one-on-one consultation": "family,professional",
    "bbu test guide (qa)": "",          # internal QA item, leave untagged
}

# Courses Anna asked to duplicate for Project BOLD.
BOLD_SOURCES = [
    "Breastfeeding for Perinatal Professionals",
    "Comfort Measures for Perinatal Professionals",
    "Newborn Care for Perinatal Professionals",
]
BOLD_PREFIX = "Project BOLD — "


def _check(request: Request, body: dict | None = None):
    if not ADMIN_KEY:
        raise HTTPException(503, "Migration key not configured")
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key") \
        or (body or {}).get("key") or ""
    if key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


def _now() -> str:
    return str(datetime.now())


def classify(name: str) -> str:
    """Product name -> comma-separated audience slugs."""
    n = (name or "").strip().lower()
    if n in OVERRIDES:
        return OVERRIDES[n]
    if n.startswith(BOLD_PREFIX.strip().lower()) or "project bold" in n:
        return "bold_professional" if any(m in n for m in PRO_MARKERS) else "bold_family"
    if any(m in n for m in ES_MARKERS):
        return "spanish_family"
    if any(m in n for m in PRO_MARKERS):
        return "professional"
    return "family"


async def _ensure_usergroup(db: AsyncSession, name: str, description: str) -> UserGroup:
    grp = (await db.execute(select(UserGroup).where(
        UserGroup.org_id == ORG, UserGroup.name == name))).scalars().first()
    if grp:
        return grp
    grp = UserGroup(org_id=ORG, name=name, description=description,
                    usergroup_uuid=f"usergroup_{uuid4()}",
                    creation_date=_now(), update_date=_now())
    db.add(grp)
    await db.commit()
    await db.refresh(grp)
    return grp


@router.get("/groupings/plan")
async def plan(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """What the tagging pass would do. Read this before applying."""
    _check(request)
    rows = (await db_session.execute(select(BBUProduct).where(
        BBUProduct.org_id == ORG).order_by(BBUProduct.name))).scalars().all()
    out, buckets = [], {}
    for p in rows:
        tags = classify(p.name)
        out.append({"id": p.id, "name": p.name, "current": p.audiences or "(none)",
                    "proposed": tags or "(none — visible to all)"})
        buckets[tags or "(none)"] = buckets.get(tags or "(none)", 0) + 1
    return {"products": len(rows), "by_audience": buckets, "plan": out}


@router.post("/groupings/audiences")
async def provision_audiences(request: Request,
                              db_session: AsyncSession = Depends(get_db_session)):
    """Create the audiences (+ a usergroup each) and tag every product."""
    body = await request.json() if await request.body() else {}
    _check(request, body)
    dry = bool(body.get("dry_run"))

    made, linked = [], []
    for slug, name, is_default, cross, order in AUDIENCES:
        a = (await db_session.execute(select(BBUAudience).where(
            BBUAudience.org_id == ORG, BBUAudience.slug == slug))).scalars().first()
        if a is None:
            a = BBUAudience(org_id=ORG, slug=slug)
            made.append(slug)
        a.name, a.is_public_default, a.cross_sell, a.sort_order = name, is_default, cross, order
        a.active = True
        if not dry:
            grp = await _ensure_usergroup(
                    db_session, AUDIENCE_GROUP_NAMES[slug],
                    f"Audience segment '{slug}': controls catalogue and "
                    f"community access. Managed from Members.")
            if a.usergroup_id != grp.id:
                a.usergroup_id = grp.id or 0
                linked.append({"audience": slug, "usergroup_id": a.usergroup_id})
            db_session.add(a)

    tagged = []
    rows = (await db_session.execute(select(BBUProduct).where(
        BBUProduct.org_id == ORG))).scalars().all()
    for p in rows:
        want = classify(p.name)
        if (p.audiences or "") != want:
            tagged.append({"product": p.name, "from": p.audiences or "(none)",
                           "to": want or "(none)"})
            if not dry:
                p.audiences = want
                db_session.add(p)
    if not dry:
        await db_session.commit()
    return {"dry_run": dry, "audiences_created": made, "usergroups_linked": linked,
            "products_retagged": len(tagged), "changes": tagged}


@router.post("/groupings/clone-bold")
async def clone_bold(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Duplicate the professional courses Anna named into Project BOLD versions.

    Uses the platform's own course clone (chapters, activities, blocks, files) and
    then renames — the built-in clone appends "(Copy)", which is not a name to put
    in front of a cohort. Clones land unpublished so nothing goes live half-named.
    """
    body = await request.json() if await request.body() else {}
    _check(request, body)
    dry = bool(body.get("dry_run"))
    names = body.get("courses") or BOLD_SOURCES

    from src.db.user_organizations import UserOrganization
    from src.db.users import PublicUser, User
    from src.security.org_auth import ADMIN_OR_MAINTAINER_ROLE_IDS
    from src.services.courses.courses import clone_course

    # clone_course is RBAC-gated on a real session user, and this endpoint
    # authenticates with the admin key instead. Act as an actual org admin
    # rather than weakening the check — an anonymous caller is correctly
    # refused ("Resource is not public or not published") because the courses
    # being copied are access-gated.
    admin_row = None
    memberships = (await db_session.execute(select(UserOrganization).where(
        UserOrganization.org_id == ORG,
        UserOrganization.role_id.in_(list(ADMIN_OR_MAINTAINER_ROLE_IDS))
    ))).scalars().all()
    if memberships:
        admin_row = (await db_session.execute(select(User).where(
            User.id == memberships[0].user_id))).scalars().first()
    if not admin_row:
        raise HTTPException(500, "No org admin found to perform the clone")
    acting = PublicUser.model_validate(admin_row.model_dump())

    results = []
    for src_name in names:
        course = (await db_session.execute(select(Course).where(
            Course.org_id == ORG, Course.name == src_name))).scalars().first()
        if not course:
            results.append({"source": src_name, "status": "source not found"})
            continue
        target = f"{BOLD_PREFIX}{src_name}"
        if (await db_session.execute(select(Course).where(
                Course.org_id == ORG, Course.name == target))).scalars().first():
            results.append({"source": src_name, "status": "already exists", "name": target})
            continue
        if dry:
            results.append({"source": src_name, "status": "would clone", "name": target})
            continue
        try:
            cloned = await clone_course(request, course.course_uuid, acting, db_session)
            row = (await db_session.execute(select(Course).where(
                Course.course_uuid == cloned.course_uuid))).scalars().first()
            if row:
                row.name = target
                row.public = False
                row.update_date = _now()
                db_session.add(row)
                await db_session.commit()
            results.append({"source": src_name, "status": "cloned", "name": target,
                            "course_uuid": cloned.course_uuid})
        except Exception as e:
            results.append({"source": src_name, "status": f"error: {str(e)[:160]}"})
    return {"dry_run": dry, "acting_as": getattr(acting, "email", "?"),
            "acting_id": getattr(acting, "id", 0), "results": results}


def _block_snapshot(block) -> dict:
    return {
        "id": block.id,
        "block_type": block.block_type.value,
        "content": block.content,
        "org_id": block.org_id,
        "course_id": block.course_id,
        "chapter_id": block.chapter_id,
        "activity_id": block.activity_id,
        "block_uuid": block.block_uuid,
        "creation_date": block.creation_date,
        "update_date": block.update_date,
    }


def _repair_cloned_activity_content(
    source_activity,
    target_activity,
    source_blocks,
    target_blocks,
):
    """Rebind a clone's Tiptap media snapshots to its copied block records."""
    from src.services.courses.courses import (
        _replace_cloned_block_objects,
        _replace_uuids_in_content,
    )

    if len(source_blocks) != len(target_blocks):
        return target_activity.content, (
            f"block count differs ({len(source_blocks)} source, "
            f"{len(target_blocks)} target)"
        )

    uuid_replacements = {
        source_activity.activity_uuid: target_activity.activity_uuid,
    }
    object_replacements = {}
    for source_block, target_block in zip(source_blocks, target_blocks):
        snapshot = _block_snapshot(target_block)
        uuid_replacements[source_block.block_uuid] = target_block.block_uuid
        source_file_id = (source_block.content or {}).get("file_id")
        target_file_id = (target_block.content or {}).get("file_id")
        if source_file_id and target_file_id:
            uuid_replacements[source_file_id] = target_file_id
        # Existing clones vary: some embedded snapshots still have the source
        # block UUID, while others have the new UUID but stale activity/file data.
        object_replacements[source_block.block_uuid] = snapshot
        object_replacements[target_block.block_uuid] = snapshot

    repaired = _replace_cloned_block_objects(
        target_activity.content, object_replacements
    )
    repaired = _replace_uuids_in_content(repaired, uuid_replacements)
    return repaired, ""


@router.post("/groupings/repair-bold-media")
async def repair_bold_media(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    """Repair the three existing Project BOLD clones created before the clone fix."""
    from src.db.courses.activities import Activity, ActivityTypeEnum
    from src.db.courses.blocks import Block
    from src.db.courses.chapter_activities import ChapterActivity
    from src.db.courses.course_chapters import CourseChapter

    body = await request.json() if await request.body() else {}
    _check(request, body)
    dry = bool(body.get("dry_run", True))

    async def ordered_activities(course_id: int):
        return (
            await db_session.execute(
                select(Activity)
                .join(ChapterActivity, ChapterActivity.activity_id == Activity.id)
                .join(
                    CourseChapter,
                    CourseChapter.chapter_id == ChapterActivity.chapter_id,
                )
                .where(CourseChapter.course_id == course_id)
                .order_by(CourseChapter.order, ChapterActivity.order)
            )
        ).scalars().all()

    results = []
    changed = 0
    for source_name in body.get("courses") or BOLD_SOURCES:
        source = (
            await db_session.execute(
                select(Course).where(Course.org_id == ORG, Course.name == source_name)
            )
        ).scalars().first()
        target_name = f"{BOLD_PREFIX}{source_name}"
        target = (
            await db_session.execute(
                select(Course).where(Course.org_id == ORG, Course.name == target_name)
            )
        ).scalars().first()
        if not source or not target:
            results.append({
                "source": source_name,
                "target": target_name,
                "status": "course missing",
            })
            continue

        source_activities = await ordered_activities(source.id)
        target_activities = await ordered_activities(target.id)
        if len(source_activities) != len(target_activities):
            results.append({
                "source": source_name,
                "target": target_name,
                "status": "activity count differs",
                "source_activities": len(source_activities),
                "target_activities": len(target_activities),
            })
            continue

        course_changed = 0
        errors = []
        for source_activity, target_activity in zip(
            source_activities, target_activities
        ):
            if source_activity.activity_type != ActivityTypeEnum.TYPE_DYNAMIC:
                continue
            source_blocks = (
                await db_session.execute(
                    select(Block)
                    .where(Block.activity_id == source_activity.id)
                    .order_by(Block.id)
                )
            ).scalars().all()
            target_blocks = (
                await db_session.execute(
                    select(Block)
                    .where(Block.activity_id == target_activity.id)
                    .order_by(Block.id)
                )
            ).scalars().all()
            repaired, error = _repair_cloned_activity_content(
                source_activity, target_activity, source_blocks, target_blocks
            )
            if error:
                errors.append(f"{target_activity.name}: {error}")
                continue
            if repaired != target_activity.content:
                course_changed += 1
                changed += 1
                if not dry:
                    target_activity.content = repaired
                    target_activity.update_date = _now()
                    db_session.add(target_activity)
        results.append({
            "source": source_name,
            "target": target_name,
            "status": "would repair" if dry and course_changed else "repaired" if course_changed else "already healthy",
            "activities_changed": course_changed,
            "errors": errors,
        })

    if not dry:
        await db_session.commit()
    return {"dry_run": dry, "activities_changed": changed, "results": results}


@router.post("/groupings/communities")
async def provision_communities(request: Request,
                                db_session: AsyncSession = Depends(get_db_session)):
    """Create the Spanish-speaking communities and attach the Spanish courses.

    Anna's reasoning: demand is low enough that a dedicated community is a
    tidier home for these than another row in everyone's catalogue.
    """
    body = await request.json() if await request.body() else {}
    _check(request, body)
    dry = bool(body.get("dry_run"))

    from src.db.communities.community_courses import CommunityCourse

    wanted = body.get("communities") or [
        {"name": "Spanish-Speaking Families",
         "description": "Clases en español para familias que esperan un bebé.",
         "match": ES_MARKERS, "bold": False},
        {"name": "Project BOLD — Spanish-Speaking Families",
         "description": "Clases en español para las familias de Project BOLD.",
         "match": ES_MARKERS, "bold": True},
    ]

    courses = (await db_session.execute(select(Course).where(
        Course.org_id == ORG))).scalars().all()

    out = []
    for spec in wanted:
        existing = (await db_session.execute(select(Community).where(
            Community.org_id == ORG, Community.name == spec["name"]))).scalars().first()
        targets = [c for c in courses
                   if any(m in (c.name or "").lower() for m in spec["match"])
                   and (("project bold" in (c.name or "").lower()) == bool(spec["bold"]))]
        entry = {"community": spec["name"],
                 "status": "exists" if existing else "would create",
                 "courses_matched": [c.name for c in targets]}
        if not dry:
            if not existing:
                existing = Community(
                    org_id=ORG, name=spec["name"], description=spec["description"],
                    public=False, community_uuid=f"community_{uuid4()}",
                    creation_date=_now(), update_date=_now())
                db_session.add(existing)
                await db_session.commit()
                await db_session.refresh(existing)
                entry["status"] = "created"
            # write the join rows directly: the service call is RBAC-gated on a
            # session user, and this endpoint authenticates with the admin key
            linked = 0
            for c in targets:
                dupe = (await db_session.execute(select(CommunityCourse).where(
                    CommunityCourse.community_id == existing.id,
                    CommunityCourse.course_id == c.id))).scalars().first()
                if dupe:
                    continue
                db_session.add(CommunityCourse(
                    org_id=ORG, community_id=existing.id or 0,
                    course_id=c.id or 0, creation_date=_now()))
                linked += 1
            if not existing.course_id and targets:
                existing.course_id = targets[0].id
                db_session.add(existing)
            await db_session.commit()
            entry["courses_linked"] = linked
        out.append(entry)
    return {"dry_run": dry, "communities": out}


@router.post("/groupings/access")
async def provision_access_mapping(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    """Apply Anna's group/course/community map as one idempotent migration.

    The default is a dry run. Pass ``{"dry_run": false}`` only after reviewing
    the returned target map. Existing memberships and access links are kept;
    canonical groups absorb legacy audience-group members rather than deleting
    history.
    """
    from src.bbu_payments.models import BBUCoupon
    from src.db.communities.community_courses import CommunityCourse
    from src.db.user_organizations import UserOrganization
    from src.db.usergroup_resources import UserGroupResource
    from src.db.usergroup_user import UserGroupUser

    body = await request.json() if await request.body() else {}
    _check(request, body)
    dry = bool(body.get("dry_run", True))

    target_communities = [
        ("Families Connect & Learn", "Family"),
        ("Doulas Connect & Learn", "BBU Professionals"),
        ("Project BOLD for Perinatal Professionals", "Bold Perinatal Professionals"),
        ("Project BOLD Families", "Bold Families"),
        ("Spanish-Speaking Families", "Spanish-Speaking Families"),
        (
            "Project BOLD — Spanish-Speaking Families",
            "Project BOLD — Spanish-Speaking Families",
        ),
        ("CFD Birth Families", "CFD Birth Families"),
        ("CFD Postpartum Families", "CFD Postpartum Families"),
        ("CFD Doulas", "CFD Doulas"),
    ]
    clone_names = [f"{BOLD_PREFIX}{name}" for name in BOLD_SOURCES]
    bold_spanish_names = [
        "Project BOLD — Introducción al Parto",
        "Project BOLD — Atención del Recién Nacido",
        "Project BOLD — Lactancia Materna",
    ]
    spanish_names = [
        "Introducción al Parto",
        "Atención del Recién Nacido",
        "Lactancia Materna",
    ]
    postpartum_names = [
        "Intro to Childbirth",
        "Preparing for Your Hospital Birth in Chicago",
        "Preparing for Your VBAC",
        "Bringing Home Baby",
        "Breastfeeding",
        "Newborn Care 101",
    ]
    required_groups = list(dict.fromkeys([
        *AUDIENCE_GROUP_NAMES.values(),
        "CFD Birth Families",
        "CFD Postpartum Families",
        "CFD Doulas",
    ]))

    current_groups = {
        g.name: g
        for g in (
            await db_session.execute(
                select(UserGroup).where(UserGroup.org_id == ORG)
            )
        ).scalars().all()
    }
    current_communities = {
        c.name: c
        for c in (
            await db_session.execute(
                select(Community).where(Community.org_id == ORG)
            )
        ).scalars().all()
    }
    all_courses = (
        await db_session.execute(select(Course).where(Course.org_id == ORG))
    ).scalars().all()
    courses_by_name = {c.name: c for c in all_courses}
    missing_requested_courses = [
        name
        for name in [*clone_names, *bold_spanish_names]
        if name not in courses_by_name
    ]

    plan = {
        "group_renames": [
            {"from": "Chicago Family Doulas Families", "to": "CFD Birth Families"}
        ],
        "groups_to_create": [name for name in required_groups if name not in current_groups],
        "communities_to_create": [
            name for name, _group in target_communities
            if name not in current_communities
            and not (
                name == "CFD Birth Families"
                and "Chicago Family Doulas Families" in current_communities
            )
        ],
        "community_groups": [
            {"community": name, "group": group}
            for name, group in target_communities
        ],
        "courses_to_publish": [
            name for name in [*clone_names, *bold_spanish_names]
            if courses_by_name.get(name) and not courses_by_name[name].published
        ],
        "missing_requested_courses": missing_requested_courses,
        "postpartum_discount_products": postpartum_names,
        "preserved_public_community": "Expecting Families Explore Courses!",
    }
    if dry:
        org_member_ids = set(
            (
                await db_session.execute(
                    select(UserOrganization.user_id).where(
                        UserOrganization.org_id == ORG
                    )
                )
            ).scalars().all()
        )
        professional_ids: set[int] = set()
        for group_name in (
            "BBU Professionals",
            "Audience — Perinatal Professionals",
            "Bold Perinatal Professionals",
        ):
            group = current_groups.get(group_name)
            if group and group.id:
                professional_ids.update(
                    (
                        await db_session.execute(
                            select(UserGroupUser.user_id).where(
                                UserGroupUser.usergroup_id == group.id
                            )
                        )
                    ).scalars().all()
                )
        plan["member_backfill_preview"] = {
            "org_members": len(org_member_ids),
            "professional_members": len(professional_ids),
            "family_candidates": len(org_member_ids - professional_ids),
        }
        return {"dry_run": True, "plan": plan}
    if missing_requested_courses:
        raise HTTPException(
            409,
            "Required cloned courses are missing: "
            + ", ".join(missing_requested_courses),
        )

    now = _now()
    changes = {
        "groups_created": 0,
        "groups_renamed": 0,
        "members_added": 0,
        "resource_links_added": 0,
        "community_links_removed": 0,
        "communities_created": 0,
        "communities_renamed": 0,
        "community_course_links_added": 0,
        "courses_published": 0,
        "products_created": 0,
        "audiences_relinked": 0,
    }
    member_cache: dict[int, set[int]] = {}
    resource_cache: dict[int, set[str]] = {}

    # Rename the existing CFD family group/community in place so every current
    # membership and resource link survives.
    old_group = current_groups.get("Chicago Family Doulas Families")
    new_group = current_groups.get("CFD Birth Families")
    if old_group and not new_group:
        old_group.name = "CFD Birth Families"
        old_group.update_date = now
        db_session.add(old_group)
        current_groups["CFD Birth Families"] = old_group
        changes["groups_renamed"] += 1
    old_community = current_communities.get("Chicago Family Doulas Families")
    new_community = current_communities.get("CFD Birth Families")
    if old_community and not new_community:
        old_community.name = "CFD Birth Families"
        old_community.update_date = now
        db_session.add(old_community)
        current_communities["CFD Birth Families"] = old_community
        changes["communities_renamed"] += 1
    await db_session.commit()

    async def ensure_group(name: str) -> UserGroup:
        group = current_groups.get(name)
        if group:
            return group
        group = await _ensure_usergroup(
            db_session,
            name,
            f"BBU access group: {name}",
        )
        current_groups[name] = group
        changes["groups_created"] += 1
        return group

    async def add_member(group: UserGroup, user_id: int):
        if not group.id or not user_id:
            return
        if group.id not in member_cache:
            member_cache[group.id] = set(
                (
                    await db_session.execute(
                        select(UserGroupUser.user_id).where(
                            UserGroupUser.usergroup_id == group.id
                        )
                    )
                ).scalars().all()
            )
        if user_id in member_cache[group.id]:
            return
        db_session.add(
            UserGroupUser(
                usergroup_id=group.id,
                user_id=user_id,
                org_id=ORG,
                creation_date=now,
                update_date=now,
            )
        )
        member_cache[group.id].add(user_id)
        changes["members_added"] += 1

    async def add_resource(group: UserGroup, resource_uuid: str):
        if not group.id or not resource_uuid:
            return
        if group.id not in resource_cache:
            resource_cache[group.id] = set(
                (
                    await db_session.execute(
                        select(UserGroupResource.resource_uuid).where(
                            UserGroupResource.usergroup_id == group.id
                        )
                    )
                ).scalars().all()
            )
        if resource_uuid in resource_cache[group.id]:
            return
        db_session.add(
            UserGroupResource(
                usergroup_id=group.id,
                resource_uuid=resource_uuid,
                org_id=ORG,
                creation_date=now,
                update_date=now,
            )
        )
        resource_cache[group.id].add(resource_uuid)
        changes["resource_links_added"] += 1

    for group_name in required_groups:
        await ensure_group(group_name)

    # Point audience presentation at the canonical access groups, absorbing
    # members/resources from the old "Audience — …" duplicates.
    for slug, name, is_default, cross, order in AUDIENCES:
        target = current_groups[AUDIENCE_GROUP_NAMES[slug]]
        audience = (
            await db_session.execute(
                select(BBUAudience).where(
                    BBUAudience.org_id == ORG,
                    BBUAudience.slug == slug,
                )
            )
        ).scalars().first()
        if not audience:
            audience = BBUAudience(org_id=ORG, slug=slug)
        if audience.usergroup_id != target.id:
            changes["audiences_relinked"] += 1
        audience.name = name
        audience.usergroup_id = target.id or 0
        audience.is_public_default = is_default
        audience.cross_sell = cross
        audience.sort_order = order
        audience.active = True
        db_session.add(audience)

        legacy = current_groups.get(f"Audience — {name}")
        if legacy and legacy.id and legacy.id != target.id:
            legacy_members = (
                await db_session.execute(
                    select(UserGroupUser.user_id).where(
                        UserGroupUser.usergroup_id == legacy.id
                    )
                )
            ).scalars().all()
            for user_id in legacy_members:
                await add_member(target, user_id)
            legacy_resources = (
                await db_session.execute(
                    select(UserGroupResource.resource_uuid).where(
                        UserGroupResource.usergroup_id == legacy.id
                    )
                )
            ).scalars().all()
            for resource_uuid in legacy_resources:
                await add_resource(target, resource_uuid)
    await db_session.commit()

    community_group_map: dict[int, UserGroup] = {}
    for community_name, group_name in target_communities:
        community = current_communities.get(community_name)
        if not community:
            community = Community(
                org_id=ORG,
                name=community_name,
                description=f"{community_name} classes and community.",
                public=False,
                community_uuid=f"community_{uuid4()}",
                creation_date=now,
                update_date=now,
            )
            db_session.add(community)
            await db_session.commit()
            await db_session.refresh(community)
            current_communities[community_name] = community
            changes["communities_created"] += 1
        community.public = False
        community.update_date = now
        db_session.add(community)
        group = current_groups[group_name]
        community_group_map[community.id or 0] = group

        # A mapped community has exactly one access group. Course links remain
        # as content shown inside it; they are not used for authorization.
        existing_links = (
            await db_session.execute(
                select(UserGroupResource).where(
                    UserGroupResource.resource_uuid == community.community_uuid
                )
            )
        ).scalars().all()
        for link in existing_links:
            if link.usergroup_id != group.id:
                await db_session.delete(link)
                changes["community_links_removed"] += 1
        await add_resource(group, community.community_uuid)
    await db_session.commit()

    bold_professional_courses = [
        courses_by_name[name] for name in clone_names if name in courses_by_name
    ]
    bold_spanish_courses = [
        courses_by_name[name] for name in bold_spanish_names if name in courses_by_name
    ]
    spanish_courses = [
        courses_by_name[name] for name in spanish_names if name in courses_by_name
    ]
    for course in [*bold_professional_courses, *bold_spanish_courses]:
        if not course.published:
            course.published = True
            course.update_date = now
            db_session.add(course)
            changes["courses_published"] += 1

    for course in bold_professional_courses:
        await add_resource(current_groups["Bold Perinatal Professionals"], course.course_uuid)
        await add_resource(current_groups["CFD Doulas"], course.course_uuid)
    for course in bold_spanish_courses:
        await add_resource(
            current_groups["Project BOLD — Spanish-Speaking Families"],
            course.course_uuid,
        )
    for course in spanish_courses:
        await add_resource(
            current_groups["Spanish-Speaking Families"],
            course.course_uuid,
        )
    await db_session.commit()

    # Show every course carried by a mapped group inside its community.
    for community_id, group in community_group_map.items():
        resource_uuids = (
            await db_session.execute(
                select(UserGroupResource.resource_uuid).where(
                    UserGroupResource.usergroup_id == group.id
                )
            )
        ).scalars().all()
        linked_courses = [
            course for course in all_courses
            if course.course_uuid in set(resource_uuids)
        ]
        for course in linked_courses:
            exists = (
                await db_session.execute(
                    select(CommunityCourse).where(
                        CommunityCourse.community_id == community_id,
                        CommunityCourse.course_id == course.id,
                    )
                )
            ).scalars().first()
            if not exists:
                db_session.add(
                    CommunityCourse(
                        org_id=ORG,
                        community_id=community_id,
                        course_id=course.id or 0,
                        creation_date=now,
                    )
                )
                changes["community_course_links_added"] += 1

    # Backfill canonical cohort/language groups from the individual course
    # access groups learners already have.
    async def members_with_course_access(courses: list[Course]) -> set[int]:
        uuids = [course.course_uuid for course in courses]
        if not uuids:
            return set()
        group_ids = (
            await db_session.execute(
                select(UserGroupResource.usergroup_id).where(
                    UserGroupResource.resource_uuid.in_(uuids)
                )
            )
        ).scalars().all()
        if not group_ids:
            return set()
        return set(
            (
                await db_session.execute(
                    select(UserGroupUser.user_id).where(
                        UserGroupUser.usergroup_id.in_(group_ids)
                    )
                )
            ).scalars().all()
        )

    bold_family_group = current_groups["Bold Families"]
    bold_professional_group = current_groups["Bold Perinatal Professionals"]
    bold_professional_resource_uuids = (
        await db_session.execute(
            select(UserGroupResource.resource_uuid).where(
                UserGroupResource.usergroup_id == bold_professional_group.id
            )
        )
    ).scalars().all()
    all_bold_professional_courses = [
        course for course in all_courses
        if course.course_uuid in set(bold_professional_resource_uuids)
    ]
    bold_family_resource_uuids = (
        await db_session.execute(
            select(UserGroupResource.resource_uuid).where(
                UserGroupResource.usergroup_id == bold_family_group.id
            )
        )
    ).scalars().all()
    bold_family_courses = [
        course for course in all_courses
        if course.course_uuid in set(bold_family_resource_uuids)
    ]
    for group, courses in (
        (bold_professional_group, all_bold_professional_courses),
        (current_groups["Bold Families"], bold_family_courses),
        (
            current_groups["Project BOLD — Spanish-Speaking Families"],
            bold_spanish_courses,
        ),
        (current_groups["Spanish-Speaking Families"], spanish_courses),
    ):
        for user_id in await members_with_course_access(courses):
            await add_member(group, user_id)

    # Existing BBU members predate the registration question. Treat every org
    # member who is not in the professional cohort as Family so making the
    # Families community private does not lock them out.
    org_members = set(
        (
            await db_session.execute(
                select(UserOrganization.user_id).where(
                    UserOrganization.org_id == ORG
                )
            )
        ).scalars().all()
    )
    professional_members: set[int] = set()
    for group_name in ("BBU Professionals", "Bold Perinatal Professionals"):
        professional_members.update(
            (
                await db_session.execute(
                    select(UserGroupUser.user_id).where(
                        UserGroupUser.usergroup_id
                        == current_groups[group_name].id
                    )
                )
            ).scalars().all()
        )
    for user_id in org_members - professional_members:
        await add_member(current_groups["Family"], user_id)
    await db_session.commit()

    # The CFD postpartum list names the Chicago-specific hospital class. It
    # existed as a course but not as a sellable product, so provision it at the
    # same price/category as the general hospital-birth class.
    chicago_course = courses_by_name.get("Preparing for Your Hospital Birth in Chicago")
    chicago_product = (
        await db_session.execute(
            select(BBUProduct).where(
                BBUProduct.org_id == ORG,
                BBUProduct.name == "Preparing for Your Hospital Birth in Chicago",
            )
        )
    ).scalars().first()
    if chicago_course and not chicago_product:
        source_product = (
            await db_session.execute(
                select(BBUProduct).where(
                    BBUProduct.org_id == ORG,
                    BBUProduct.name == "Preparing for Your Hospital Birth",
                )
            )
        ).scalars().first()
        chicago_product = BBUProduct(
            org_id=ORG,
            name="Preparing for Your Hospital Birth in Chicago",
            kind="course",
            course_uuids=chicago_course.course_uuid,
            price_cents=source_product.price_cents if source_product else 9700,
            currency=source_product.currency if source_product else "usd",
            public=True,
            description=source_product.description if source_product else "",
            image_url=source_product.image_url if source_product else "",
            benefits=source_product.benefits if source_product else "",
            category="Birth Classes",
            audiences="family",
        )
        db_session.add(chicago_product)
        await db_session.commit()
        await db_session.refresh(chicago_product)
        changes["products_created"] += 1

    postpartum_products = (
        await db_session.execute(
            select(BBUProduct).where(
                BBUProduct.org_id == ORG,
                BBUProduct.name.in_(postpartum_names),
            )
        )
    ).scalars().all()
    missing_postpartum_products = sorted(
        set(postpartum_names) - {product.name for product in postpartum_products}
    )
    if missing_postpartum_products:
        raise HTTPException(
            409,
            "Required CFD Postpartum products are missing: "
            + ", ".join(missing_postpartum_products),
        )
    postpartum_product_ids = sorted(
        product.id for product in postpartum_products if product.id
    )
    coupon = (
        await db_session.execute(
            select(BBUCoupon).where(
                BBUCoupon.org_id == ORG,
                BBUCoupon.code == "CFDPOSTPARTUM50",
            )
        )
    ).scalars().first()
    if not coupon:
        coupon = BBUCoupon(
            org_id=ORG,
            code="CFDPOSTPARTUM50",
            kind="percent",
            percent_off=50,
            applies_to=",".join(str(pid) for pid in postpartum_product_ids),
            active=True,
            created_at=now,
        )
    else:
        coupon.kind = "percent"
        coupon.percent_off = 50
        coupon.applies_to = ",".join(str(pid) for pid in postpartum_product_ids)
        coupon.active = True
    db_session.add(coupon)
    await db_session.commit()

    return {
        "dry_run": False,
        "plan": plan,
        "changes": changes,
        "postpartum_product_ids": postpartum_product_ids,
    }


@router.post("/groupings/links")
async def provision_dedicated_links(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    """Create/reuse the four persistent group-linked signup URLs."""
    from src.db.user_organizations import UserOrganization
    from src.db.users import PublicUser, User
    from src.security.org_auth import ADMIN_OR_MAINTAINER_ROLE_IDS
    from src.services.orgs.invites import create_invite_code, get_invite_codes

    body = await request.json() if await request.body() else {}
    _check(request, body)
    dry = bool(body.get("dry_run", True))
    specs = [
        ("bold-professionals", "Bold Perinatal Professionals"),
        ("bold-families", "Bold Families"),
        ("cfd-birth", "CFD Birth Families"),
        ("cfd-postpartum", "CFD Postpartum Families"),
    ]

    groups = {
        group.name: group
        for group in (
            await db_session.execute(
                select(UserGroup).where(UserGroup.org_id == ORG)
            )
        ).scalars().all()
    }
    missing = [group_name for _slug, group_name in specs if group_name not in groups]
    if missing:
        raise HTTPException(409, f"Run groupings/access first; missing: {', '.join(missing)}")
    if dry:
        return {
            "dry_run": True,
            "links": [
                {"slug": slug, "group": group_name, "status": "would create or reuse"}
                for slug, group_name in specs
            ],
        }

    membership = (
        await db_session.execute(
            select(UserOrganization).where(
                UserOrganization.org_id == ORG,
                UserOrganization.role_id.in_(list(ADMIN_OR_MAINTAINER_ROLE_IDS)),
            )
        )
    ).scalars().first()
    admin = (
        await db_session.execute(select(User).where(User.id == membership.user_id))
    ).scalars().first() if membership else None
    if not admin:
        raise HTTPException(500, "No org admin found to create invite links")
    acting = PublicUser.model_validate(admin.model_dump())

    existing_codes = await get_invite_codes(
        request, ORG, acting, db_session
    )
    base_url = (
        body.get("base_url")
        or os.environ.get("LEARNHOUSE_DOMAIN")
        or str(request.base_url).rstrip("/")
    )
    if not base_url.startswith(("http://", "https://")):
        base_url = f"https://{base_url}"
    links = []
    for slug, group_name in specs:
        group = groups[group_name]
        code_data = next(
            (
                code for code in existing_codes
                if code.get("usergroup_id") == group.id
            ),
            None,
        )
        status = "reused"
        if not code_data:
            code_data = await create_invite_code(
                request,
                ORG,
                acting,
                db_session,
                group.id,
            )
            existing_codes.append(code_data)
            status = "created"
        links.append(
            {
                "slug": slug,
                "group": group_name,
                "status": status,
                "url": f"{base_url.rstrip('/')}/signup?inviteCode={code_data['invite_code']}",
                "expires_in_seconds": code_data.get("invite_code_expires"),
            }
        )
    return {"dry_run": False, "links": links}
