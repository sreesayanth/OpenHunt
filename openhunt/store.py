"""SQLite storage: jobs, matches, and a key-value settings table (secrets encrypted)."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet
from sqlmodel import Field, Session, SQLModel, create_engine, select

from openhunt.config import DB_PATH, KEY_PATH

# Settings whose values are encrypted at rest.
SECRET_KEYS = {"bot_token", "ai_api_key"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    fingerprint: str = Field(index=True, unique=True)
    source: str
    url: str
    title: str
    company: str = ""
    location: str = ""
    remote: bool = False
    salary: str = ""
    description: str = ""
    posted_at: datetime | None = None
    scraped_at: datetime = Field(default_factory=utcnow)


class Match(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True, unique=True)
    score: int
    reasons: str = ""
    missing: str = ""  # comma separated skills
    status: str = "new"  # new | notified | saved | dismissed | applied
    created_at: datetime = Field(default_factory=utcnow)


engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def session() -> Session:
    return Session(engine, expire_on_commit=False)


def _fernet() -> Fernet:
    if not KEY_PATH.exists():
        KEY_PATH.write_bytes(Fernet.generate_key())
    return Fernet(KEY_PATH.read_bytes())


def get(key: str, default: Any = None) -> Any:
    with session() as s:
        row = s.get(Setting, key)
    if row is None:
        return default
    raw = row.value
    if key in SECRET_KEYS:
        raw = _fernet().decrypt(raw.encode()).decode()
    return json.loads(raw)


def put(key: str, value: Any) -> None:
    raw = json.dumps(value)
    if key in SECRET_KEYS:
        raw = _fernet().encrypt(raw.encode()).decode()
    with session() as s:
        s.merge(Setting(key=key, value=raw))
        s.commit()


def delete(key: str) -> None:
    with session() as s:
        row = s.get(Setting, key)
        if row:
            s.delete(row)
            s.commit()


def update(key: str, **fields: Any) -> dict:
    """Merge fields into a dict-valued setting and return the result."""
    current = get(key, {}) or {}
    current.update(fields)
    put(key, current)
    return current


def match_with_job(match_id: int) -> tuple[Match, Job] | None:
    with session() as s:
        m = s.get(Match, match_id)
        if not m:
            return None
        return m, s.get(Job, m.job_id)


def set_match_status(match_id: int, status: str) -> None:
    with session() as s:
        m = s.get(Match, match_id)
        if m:
            m.status = status
            s.add(m)
            s.commit()


def recent_matches(
    limit: int = 10, statuses: tuple[str, ...] = ("new", "notified", "saved"), days: int = 7
) -> list[tuple[Match, Job]]:
    """Best-scored matches found in the last `days` days."""
    with session() as s:
        rows = s.exec(
            select(Match, Job)
            .where(Match.job_id == Job.id, Match.status.in_(statuses))
            .where(Match.created_at >= utcnow() - timedelta(days=days))
            .order_by(Match.score.desc())
            .limit(limit)
        ).all()
    return [tuple(r) for r in rows]


def retire_matches() -> int:
    """Hide unsaved matches (e.g. after a new CV or new job titles). Saved ones stay."""
    with session() as s:
        rows = s.exec(select(Match).where(Match.status.in_(("new", "notified")))).all()
        for m in rows:
            m.status = "stale"
            s.add(m)
        s.commit()
    return len(rows)


def reset_all() -> None:
    SQLModel.metadata.drop_all(engine)
    init_db()
