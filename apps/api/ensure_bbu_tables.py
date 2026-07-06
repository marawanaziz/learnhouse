# ruff: noqa: E402
"""Idempotently create the BBU payments tables (bbu_product, bbu_order) if they
don't exist. Runs on every boot from docker/start.sh — create_all only emits
DDL for missing tables, so this is a no-op once created.
"""
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from cli import _to_sync_url
from config.config import get_learnhouse_config
from src.bbu_payments.models import BBUProduct, BBUOrder  # noqa: F401


def main():
    config = get_learnhouse_config()
    sql_url = _to_sync_url(config.database_config.sql_connection_string)  # type: ignore
    engine = create_engine(sql_url, echo=False, pool_pre_ping=True)
    try:
        SQLModel.metadata.create_all(
            engine, tables=[BBUProduct.__table__, BBUOrder.__table__]
        )
        print("BBU payment tables ensured (bbu_product, bbu_order).")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
