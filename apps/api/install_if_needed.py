# ruff: noqa: E402
"""First-boot guard: run the LearnHouse installer only when the database is
empty. Called from docker/start.sh before services start so a fresh deploy
(e.g. Railway) self-provisions the org + admin from LEARNHOUSE_INITIAL_* env
vars, while restarts and redeploys of an installed instance are no-ops.
"""
import asyncio
import sys

from sqlalchemy import create_engine, inspect, text

from cli import _install_async, _to_sync_url
from config.config import get_learnhouse_config


def already_installed() -> bool:
    config = get_learnhouse_config()
    sql_url = _to_sync_url(config.database_config.sql_connection_string)  # type: ignore
    engine = create_engine(sql_url, echo=False, pool_pre_ping=True)
    try:
        if not inspect(engine).has_table("organization"):
            return False
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM organization")).scalar()
        return bool(count and count > 0)
    finally:
        engine.dispose()


if __name__ == "__main__":
    if already_installed():
        print("LearnHouse already installed — skipping first-boot install.")
        sys.exit(0)
    print("Empty database detected — running first-boot install...")
    asyncio.run(_install_async(short=True))
