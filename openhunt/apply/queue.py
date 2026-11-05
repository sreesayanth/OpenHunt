"""Which job to apply to next, and the limits that keep the user's accounts safe.

- Jobs the user asked for ("Apply for me", a pasted link) go first, any time of day.
- Autopilot jobs go one at a time, a few minutes apart, only during active hours, and within a
  daily limit per site.
- A job is never applied to twice (one Application per job; cross-site duplicates already share a Job).
"""

import random
from datetime import datetime, timedelta, timezone

from sqlmodel import func, select

from openhunt import store
from openhunt.apply import adapters
from openhunt.store import Application, Job, Match, utcnow

DEFAULTS = {
    "on": False,
    "min_score": 70,
    "notify": "each",  # each: one short line per application · summary: only the daily summary
    "hours": [9, 21],  # Autopilot applies between these local hours
    "caps": {"linkedin": 15, "naukri": 25, "greenhouse": 40, "lever": 40, "ashby": 40, "generic": 20},
}
GAP_SECONDS = (60, 180)  # pause between two Autopilot applications
RETRY_AFTER = timedelta(hours=2)
MAX_ATTEMPTS = 3
ACTIVE = ("queued", "running")
OPEN = ("queued", "running", "waiting", "needs_login")


def settings() -> dict:
    saved = store.get("autopilot") or {}
    merged = {**DEFAULTS, **saved}
    merged["caps"] = {**DEFAULTS["caps"], **(saved.get("caps") or {})}
    return merged


def update(**fields) -> dict:
    current = store.get("autopilot") or {}
    current.update(fields)
    store.put("autopilot", current)
    return settings()


def choose_target(job: Job) -> tuple[str, str]:
    """(url, adapter name) to apply through, or ("", "") if OpenHunt can't apply to this job.

    A direct company link beats a LinkedIn/Naukri page: no login needed and no account risk.
    """
    main = adapters.pick(job.url)
    direct = adapters.pick(job.apply_url) if job.apply_url else None
    if direct and direct.name not in ("linkedin", "naukri") and (main is None or main.name in ("linkedin", "naukri")):
        return job.apply_url, direct.name
    if main:
        return job.url, main.name
    if direct:
        return job.apply_url, direct.name
    return "", ""


def enqueue(job_id: int, source: str = "auto") -> Application | None:
    """Add a job to the queue. Asking again for a job that failed or was skipped tries it again."""
    with store.session() as s:
        job = s.get(Job, job_id)
        if not job:
            return None
        app = s.exec(select(Application).where(Application.job_id == job_id)).first()
        if app:
            if source == "manual" and app.status in ("failed", "needs_you", "skipped", "needs_login", "unsupported", "closed"):
                if app.status == "unsupported":  # maybe it can be applied to now (e.g. a better link)
                    url, site = choose_target(job)
                    if not url:
                        return app
                    app.url, app.site = url, site
                app.status, app.source, app.attempts, app.message, app.updated_at = "queued", "manual", 0, "", utcnow()
                s.add(app)
                s.commit()
                s.refresh(app)
            elif source == "manual" and app.status == "queued" and app.source == "auto":
                app.source = "manual"  # the user asked for it: no waiting for active hours or limits
                s.add(app)
                s.commit()
                s.refresh(app)
            return app
        url, site = choose_target(job)
        app = Application(job_id=job_id, url=url or job.url, site=site, company=job.company, title=job.title,
                          source=source, status="queued" if url else "unsupported",
                          message="" if url else "I can't apply on this site. Tap Open to apply yourself.")
        s.add(app)
        s.commit()
        s.refresh(app)
        return app


def set_status(app_id: int, status: str, **fields) -> Application | None:
    with store.session() as s:
        app = s.get(Application, app_id)
        if not app:
            return None
        app.status = status
        app.updated_at = utcnow()
        for k, v in fields.items():
            setattr(app, k, v)
        s.add(app)
        if status == "submitted":
            match = s.exec(select(Match).where(Match.job_id == app.job_id)).first()
            if match:
                match.status = "applied"
                s.add(match)
        s.commit()
        s.refresh(app)
        return app


def get(app_id: int) -> Application | None:
    with store.session() as s:
        return s.get(Application, app_id)


def job_of(app: Application) -> Job | None:
    with store.session() as s:
        return s.get(Job, app.job_id)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite gives times back without a zone; they are UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


def local_midnight_utc() -> datetime:
    from openhunt.timeutil import now

    return now().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def submitted_today(site: str) -> int:
    start = local_midnight_utc()
    with store.session() as s:
        return s.exec(select(func.count()).select_from(Application).where(
            Application.site == site, Application.status == "submitted", Application.submitted_at >= start)).one()


def in_active_hours(now: datetime | None = None) -> bool:
    from openhunt import timeutil

    start, end = settings()["hours"]
    hour = (now or timeutil.now()).hour
    return start <= hour < end


def next_ready(now: datetime | None = None) -> Application | None:
    """The next application to run: the user's own requests first, then Autopilot's."""
    with store.session() as s:
        queued = s.exec(select(Application).where(Application.status == "queued").order_by(Application.updated_at)).all()
    manual = [a for a in queued if a.source == "manual"]
    if manual:
        return manual[0]
    cfg = settings()
    if not cfg["on"] or not in_active_hours(now):
        return None
    paused = store.get("sites_paused") or {}
    for app in queued:
        until = paused.get(app.site)
        if until and datetime.fromisoformat(until) > utcnow():
            continue
        if app.attempts and aware(app.updated_at) > utcnow() - RETRY_AFTER:
            continue  # failed recently: try again later
        if submitted_today(app.site) >= int(cfg["caps"].get(app.site, 20)):
            continue
        return app
    return None


def pause_site(site: str, hours: int = 24) -> None:
    paused = store.get("sites_paused") or {}
    paused[site] = (utcnow() + timedelta(hours=hours)).isoformat()
    store.put("sites_paused", paused)


def gap_seconds() -> int:
    return random.randint(*GAP_SECONDS)


def recent(limit: int = 10, statuses: tuple[str, ...] | None = None) -> list[Application]:
    with store.session() as s:
        q = select(Application).order_by(Application.updated_at.desc()).limit(limit)
        if statuses:
            q = q.where(Application.status.in_(statuses))
        return list(s.exec(q).all())


def counts_since(since: datetime) -> dict[str, int]:
    with store.session() as s:
        rows = s.exec(select(Application.status, func.count()).where(Application.updated_at >= since).group_by(Application.status)).all()
    return {status: n for status, n in rows}


def requeue_for_site(site: str) -> int:
    """After the user logs in to a site, the jobs waiting for that login go back in the queue."""
    with store.session() as s:
        apps = s.exec(select(Application).where(Application.site == site, Application.status == "needs_login")).all()
        for a in apps:
            a.status, a.updated_at = "queued", utcnow()
            s.add(a)
        s.commit()
    return len(apps)


def reset_running() -> None:
    """After a restart, anything that was 'running' is queued again."""
    with store.session() as s:
        for a in s.exec(select(Application).where(Application.status == "running")).all():
            a.status = "queued"
            s.add(a)
        s.commit()
