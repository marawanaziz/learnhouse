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
    BBUProduct, BBUOrder,
    BBUAffiliate, BBUAffiliateSettings, BBUReferralClick, BBUCommission, BBUPayout,
)

# Columns added to pre-existing tables after their first creation. create_all
# never ALTERs, so additive columns are applied here explicitly.
ALTERS = [
    "ALTER TABLE bbu_order ADD COLUMN IF NOT EXISTS affiliate_ref VARCHAR(64) DEFAULT ''",
]


def main():
    config = get_learnhouse_config()
    sql_url = _to_sync_url(config.database_config.sql_connection_string)  # type: ignore
    engine = create_engine(sql_url, echo=False, pool_pre_ping=True)
    tables = [
        BBUProduct.__table__, BBUOrder.__table__,
        BBUAffiliateSettings.__table__, BBUAffiliate.__table__,
        BBUReferralClick.__table__, BBUCommission.__table__, BBUPayout.__table__,
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
