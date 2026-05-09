"""Nightly memory consolidation scheduler using APScheduler."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_scheduler = None


async def nightly_consolidation():
    """Run ensure_budget for all chats that have recent memory."""
    from db.memory_repository import fetch_chats_with_recent
    from db.settings_repository import is_memory_persist_enabled
    from memory.manager import MemoryManager

    logger.info("scheduler.nightly_consolidation started")
    mgr = MemoryManager()
    chat_ids = await fetch_chats_with_recent()

    for chat_id in chat_ids:
        try:
            persist = await is_memory_persist_enabled(chat_id)
            if not persist:
                continue
            await mgr.ensure_budget(chat_id)
        except Exception as exc:
            logger.error(
                "scheduler.consolidation_error chat=%s: %s", chat_id, exc, exc_info=True
            )

    # Reflection every 3 days
    try:
        from memory.reflection import maybe_reflect_all
        await maybe_reflect_all(chat_ids)
    except Exception as exc:
        logger.error("scheduler.reflection_error: %s", exc, exc_info=True)

    logger.info("scheduler.nightly_consolidation finished chats=%d", len(chat_ids))


async def periodic_media_tmp_purge():
    """Remove stale media tmp files (default TTL: 24h, MEDIA_TMP_MAX_AGE_HOURS).

    Without this, voice/photo/video downloads accumulate indefinitely between
    bot restarts. Per-turn cleanup_downloaded_media handles successful turns,
    but failed turns (exceptions, lost references) leave orphans. Startup-
    only purge in run.py wasn't enough — bot can run for days/weeks between
    restarts.
    """
    try:
        from media.downloader import purge_stale_media_tmp
        removed = await purge_stale_media_tmp()
        logger.info("scheduler.media_tmp_purged removed=%s", removed)
    except Exception as exc:
        logger.error("scheduler.media_tmp_purge_failed: %s", exc, exc_info=True)


def start_scheduler():
    """Start the APScheduler:
    - nightly_consolidation at 02:00 UTC (memory budget rollover)
    - periodic_media_tmp_purge every 6 hours (orphan tmp cleanup)
    """
    global _scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        logger.warning("scheduler: apscheduler not installed, jobs disabled")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        nightly_consolidation,
        CronTrigger(hour=2, minute=0, timezone="UTC"),
        id="nightly_consolidation",
        replace_existing=True,
    )
    _scheduler.add_job(
        periodic_media_tmp_purge,
        IntervalTrigger(hours=6),
        id="media_tmp_purge",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "scheduler.started jobs=nightly_consolidation@02:00,media_tmp_purge@6h"
    )


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler.stopped")
