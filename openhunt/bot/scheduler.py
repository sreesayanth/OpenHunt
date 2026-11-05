"""Scheduled hunting on top of python-telegram-bot's JobQueue (APScheduler underneath)."""

import logging
from datetime import datetime, time, timedelta

from telegram.ext import Application, ContextTypes

from openhunt import store
from openhunt.hunt import run_hunt

log = logging.getLogger(__name__)

MODES = {
    "morning": ("every morning at 8:00", [time(8, 0)]),
    "twice": ("twice a day (8:00 and 18:00)", [time(8, 0), time(18, 0)]),
    "hourly": ("every hour", []),
}
# Longest normal gap between runs, used to catch up after the laptop was off.
GAP = {"morning": timedelta(hours=24), "twice": timedelta(hours=12), "hourly": timedelta(hours=1)}


def describe() -> str:
    sched = store.get("schedule", {}) or {}
    if not sched.get("mode"):
        return "not set"
    text = MODES[sched["mode"]][0]
    return f"⏸ paused ({text})" if sched.get("paused") else text


async def _scheduled(context: ContextTypes.DEFAULT_TYPE) -> None:
    from openhunt.bot.app import report_hunt  # avoid import cycle

    try:
        result = await run_hunt()
        await report_hunt(context.bot, result, manual=False)
    except Exception:
        log.exception("Scheduled hunt failed")


def apply_schedule(app: Application, catch_up: bool = False) -> None:
    jq = app.job_queue
    for job in jq.get_jobs_by_name("hunt"):
        job.schedule_removal()

    sched = store.get("schedule", {}) or {}
    mode = sched.get("mode")
    if not mode or sched.get("paused"):
        return

    from openhunt.timeutil import user_tz

    tz = user_tz()  # the user's clock, even on a VM set to UTC
    if mode == "hourly":
        jq.run_repeating(_scheduled, interval=3600, first=60, name="hunt")
    else:
        for t in MODES[mode][1]:
            jq.run_daily(_scheduled, time=t.replace(tzinfo=tz), name="hunt")

    if catch_up and mode != "hourly":  # hourly already runs a minute after start
        last = (store.get("last_run") or {}).get("at")
        overdue = not last or datetime.now().astimezone() - datetime.fromisoformat(last) > GAP[mode]
        if overdue:
            jq.run_once(_scheduled, when=30, name="hunt")
