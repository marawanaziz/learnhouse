# ruff: noqa: E402
"""Seed BBU storefront products (idempotent). Matches migrated courses by name
and creates a BBUProduct for each, plus the Birth+Postpartum bundle. Runs on
boot from docker/start.sh after tables are ensured; skips any product that
already exists so it is safe to run repeatedly.

Pricing from the consolidation plan: trainings $675, bundle $1150 (save $200),
cross-certs $550, consumer classes $59.
"""
from sqlalchemy import create_engine, select

from cli import _to_sync_url
from config.config import get_learnhouse_config
from sqlmodel import Session
from src.db.courses.courses import Course
from src.db.organizations import Organization
from src.bbu_payments.models import BBUProduct

# name -> (price_cents, kind, description)
CATALOG = {
    "Certified Birth Doula Training": (67500, "course", "Become a nationally recognized certified birth doula. Self-paced, mentorship-eligible."),
    "Certified Postpartum Doula Training": (67500, "course", "Certified postpartum doula training — support families in the fourth trimester."),
    "Cross Certification Birth Doula Training": (55000, "course", "Cross-certify as a birth doula if you're already credentialed elsewhere."),
    "Cross Certification Postpartum Doula Training": (55000, "course", "Cross-certify as a postpartum doula."),
    "Intro to Childbirth": (5900, "course", "Evidence-based childbirth education for expecting families."),
    "Breastfeeding": (5900, "course", "Practical breastfeeding preparation and support."),
}

BUNDLE = {
    "name": "Birth + Postpartum Doula Training Bundle",
    "members": ["Certified Birth Doula Training", "Certified Postpartum Doula Training"],
    "price_cents": 115000,
    "description": "Save $200 — enroll in both the Birth and Postpartum certified doula trainings together.",
}


def main():
    config = get_learnhouse_config()
    engine = create_engine(_to_sync_url(config.database_config.sql_connection_string), pool_pre_ping=True)  # type: ignore
    with Session(engine) as s:
        org = s.exec(select(Organization).where(Organization.slug == "bbu")).scalars().first() \
            if hasattr(s, "exec") else s.execute(select(Organization).where(Organization.slug == "bbu")).scalars().first()
        if not org:
            print("BBU org not found — skipping product seed.")
            return
        org_id = org.id

        def course_uuid(name):
            c = s.execute(select(Course).where(Course.name == name, Course.org_id == org_id)).scalars().first()
            return c.course_uuid if c else None

        def exists(name):
            return s.execute(select(BBUProduct).where(BBUProduct.name == name, BBUProduct.org_id == org_id)).scalars().first()

        created = 0
        for name, (price, kind, desc) in CATALOG.items():
            if exists(name):
                continue
            uuid = course_uuid(name)
            if not uuid:
                continue
            s.add(BBUProduct(org_id=org_id, name=name, kind=kind, course_uuids=uuid,
                             price_cents=price, description=desc, public=True))
            created += 1

        if not exists(BUNDLE["name"]):
            uuids = [u for u in (course_uuid(n) for n in BUNDLE["members"]) if u]
            if len(uuids) == len(BUNDLE["members"]):
                s.add(BBUProduct(org_id=org_id, name=BUNDLE["name"], kind="bundle",
                                 course_uuids=",".join(uuids), price_cents=BUNDLE["price_cents"],
                                 description=BUNDLE["description"], public=True))
                created += 1

        s.commit()
        print(f"BBU product seed: {created} new product(s).")
    engine.dispose()


if __name__ == "__main__":
    main()
