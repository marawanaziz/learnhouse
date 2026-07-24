# ruff: noqa: E402
"""Idempotently ensure all BBU tables + columns exist. Runs on every boot from
docker/start.sh. create_all only emits DDL for missing tables, and the ALTERs
use IF NOT EXISTS, so this is a safe no-op once applied.
"""
from sqlalchemy import create_engine, text
from sqlmodel import SQLModel

from cli import _to_sync_url
from config.config import get_learnhouse_config
from src.bbu_payments.models import (  # noqa: F401
    BBUProduct, BBUOrder, BBUCoupon,
    BBUAffiliate, BBUAffiliateSettings, BBUReferralClick, BBUCommission, BBUPayout,
)
from src.bbu_ghl.models import BBUGHLSync  # noqa: F401
from src.bbu_cohorts.models import BBUCohort, BBUCohortMember, BBUCohortWaitlist  # noqa: F401
from src.bbu_credentials.models import BBUCredential, BBUCeuLedger  # noqa: F401
from src.bbu_seats.models import BBUSeatCode  # noqa: F401

# Columns added to pre-existing tables after their first creation. create_all
# never ALTERs, so additive columns are applied here explicitly.
ALTERS = [
    "ALTER TABLE bbu_order ADD COLUMN IF NOT EXISTS affiliate_ref VARCHAR(64) DEFAULT ''",
    "ALTER TABLE bbu_order ADD COLUMN IF NOT EXISTS download_token VARCHAR(64) DEFAULT ''",
    "ALTER TABLE bbu_product ADD COLUMN IF NOT EXISTS asset_path VARCHAR DEFAULT ''",
    "ALTER TABLE bbu_product ADD COLUMN IF NOT EXISTS asset_filename VARCHAR(300) DEFAULT ''",
    "ALTER TABLE bbu_product ADD COLUMN IF NOT EXISTS benefits VARCHAR DEFAULT ''",
    "ALTER TABLE bbu_product ADD COLUMN IF NOT EXISTS category VARCHAR(60) DEFAULT ''",
    "ALTER TABLE bbu_product ADD COLUMN IF NOT EXISTS bump_offer_ids VARCHAR DEFAULT ''",
    "ALTER TABLE bbu_product ADD COLUMN IF NOT EXISTS cohort_program VARCHAR(24) DEFAULT ''",
    "ALTER TABLE bbu_product ADD COLUMN IF NOT EXISTS cohort_id INTEGER",
    "ALTER TABLE bbu_product ADD COLUMN IF NOT EXISTS seat_count INTEGER DEFAULT 0",
    "ALTER TABLE bbu_seat_code ADD COLUMN IF NOT EXISTS owner_token VARCHAR(64) DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS ix_bbu_seat_owner_token ON bbu_seat_code (owner_token)",
    "ALTER TABLE bbu_cohort ADD COLUMN IF NOT EXISTS weekly_prompts VARCHAR DEFAULT ''",
    "ALTER TABLE bbu_cohort ADD COLUMN IF NOT EXISTS zoom_meeting_id VARCHAR(40) DEFAULT ''",
    "ALTER TABLE bbu_credential ADD COLUMN IF NOT EXISTS last_reminder_days INTEGER DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS ix_bbu_order_download_token ON bbu_order (download_token)",
]


def main():
    config = get_learnhouse_config()
    sql_url = _to_sync_url(config.database_config.sql_connection_string)  # type: ignore
    engine = create_engine(sql_url, echo=False, pool_pre_ping=True)
    tables = [
        BBUProduct.__table__, BBUOrder.__table__, BBUCoupon.__table__,
        BBUAffiliateSettings.__table__, BBUAffiliate.__table__,
        BBUReferralClick.__table__, BBUCommission.__table__, BBUPayout.__table__,
        BBUGHLSync.__table__,
        BBUCohort.__table__, BBUCohortMember.__table__, BBUCohortWaitlist.__table__,
        BBUCredential.__table__, BBUCeuLedger.__table__,
        BBUSeatCode.__table__,
    ]
    try:
        SQLModel.metadata.create_all(engine, tables=tables)
        with engine.begin() as conn:
            for stmt in ALTERS:
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    print(f"  alter skipped: {e}")
        print("BBU tables ensured (payments + affiliate program).")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
