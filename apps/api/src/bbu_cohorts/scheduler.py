"""In-process scheduler for cohort lifecycle and participant notifications.

Self-contained (no external cron / secret): a background task started at app
startup runs lifecycle bookkeeping and participant email delivery — flips started cohorts to
'running' (so the buy-into-cohort resolver stops enrolling into a class already
in progress) and closes cohorts past their access window. Safe across restarts
and multiple instances because both jobs are idempotent.
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_STARTUP_DELAY = 360      # 6 min after boot (offset from the reminder job)
_INTERVAL = 60 * 60       # hourly, so transient email failures retry the same day


async def _loop():
    await asyncio.sleep(_STARTUP_DELAY)
    while True:
        try:
            from src.core.events.database import _async_session_factory
            from src.bbu_cohorts import service as svc
            from src.bbu_cohorts import notifications
            async with _async_session_factory() as session:
                res = await svc.run_lifecycle(session, org_id=1, dry=False)
                notices = await notifications.run_due(session, org_id=1, dry=False)
            if res.get("started_count") or res.get("expired_count"):
                logger.info("[BBU] cohort lifecycle: started=%s expired=%s",
                            res.get("started_count"), res.get("expired_count"))
            if notices.get("sent") or notices.get("failed"):
                logger.info(
                    "[BBU] cohort notifications: sent=%s failed=%s",
                    notices.get("sent"), notices.get("failed"),
                )
        except Exception as e:
            logger.warning("[BBU] cohort lifecycle loop error: %s", e)
        await asyncio.sleep(_INTERVAL)


async def start_cohort_scheduler():
    """Startup hook — spawns the hourly loop. Gated by BBU_COHORT_LIFECYCLE_ENABLED
    (default on)."""
    if os.environ.get("BBU_COHORT_LIFECYCLE_ENABLED", "true").lower() in ("0", "false", "no"):
        return
    try:
        asyncio.create_task(_loop())
        print("[BBU] cohort lifecycle scheduler started", flush=True)
    except Exception as e:
        print(f"[BBU] could not start cohort lifecycle scheduler: {e}", flush=True)
