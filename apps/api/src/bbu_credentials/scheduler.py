"""In-process daily scheduler for the credential renewal-reminder job.

Self-contained (no external cron / secret): a background task started at app
startup runs `service.run_reminders` once a day. Safe across restarts and
multiple instances because the job is idempotent per reminder window
(last_reminder_days) — a second run simply finds nothing new to fire.
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_STARTUP_DELAY = 300      # 5 min after boot, so the app + DB are settled
_INTERVAL = 24 * 60 * 60  # daily


async def _loop():
    await asyncio.sleep(_STARTUP_DELAY)
    while True:
        try:
            from src.core.events.database import _async_session_factory
            from src.bbu_credentials import service as svc
            async with _async_session_factory() as session:
                res = await svc.run_reminders(session, org_id=1, dry=False)
            logger.info("[BBU] credential reminders ran: fired=%s", res.get("fired"))
        except Exception as e:
            logger.warning("[BBU] credential reminder loop error: %s", e)
        await asyncio.sleep(_INTERVAL)


async def start_reminder_scheduler():
    """Startup hook — spawns the daily loop as a background task. Gated by
    BBU_REMINDERS_ENABLED (default on)."""
    if os.environ.get("BBU_REMINDERS_ENABLED", "true").lower() in ("0", "false", "no"):
        return
    try:
        asyncio.create_task(_loop())
        logger.info("[BBU] credential reminder scheduler started")
    except Exception as e:
        logger.warning("[BBU] could not start reminder scheduler: %s", e)
