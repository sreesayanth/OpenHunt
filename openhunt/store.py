"""SQLite storage: jobs, matches, and a key-value settings table (secrets encrypted)."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Session, SQLModel, create_engine, select

from openhunt.config import DB_PATH, FILES_DIR, KEY_PATH

# Settings whose values are encrypted at rest.
SECRET_KEYS = {"bot_token", "ai_api_key"}
SECRET_PREFIXES = ("login_secret:",)  # job-site passwords, only if the user chose "remember"


def is_secret(key: str) -> bool:
    return key in SECRET_KEYS or key.startswith(SECRET_PREFIXES)


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
    apply_url: str = ""  # the company's own application page, when the board gives it
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


class Application(SQLModel, table=True):
    """One job OpenHunt applies to (see openhunt/apply/engine.py and queue.py)."""

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True, unique=True)
    url: str = ""
    site: str = ""  # adapter name: greenhouse | lever | ashby | linkedin | naukri | generic
    company: str = ""
    title: str = ""
    status: str = Field(default="queued", index=True)
    # queued | running | waiting (for the user's answers) | submitted | needs_login | needs_you
    # | closed | already | unsupported | failed | skipped
    source: str = "auto"  # auto (Autopilot) | manual (the user asked)
    attempts: int = 0
    message: str = ""  # last problem, in plain words
    answers: str = "[]"  # JSON: what was filled in, for "what did I tell this company?"
    proof_path: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    submitted_at: datetime | None = None


class Answer(SQLModel, table=True):
    """Something the user told us once, reused on every later form (see openhunt/apply/answers.py)."""

    __table_args__ = (UniqueConstraint("key", "company"),)

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True)  # intent key like "years_with:tableau", or "q:<words>" for other questions
    company: str = ""  # "" = used for every company
    title: str = ""  # plain-language name shown in "What I know about you"
    question: str = ""  # the latest wording seen on a form
    value: str = "{}"  # JSON typed value, see openhunt/apply/values.py
    source: str = "chat"  # chat | cv | default
    use_count: int = 0
    last_used_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class PendingQuestion(SQLModel, table=True):
    """A form question waiting for the user's answer in Telegram."""

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True)
    company: str = ""  # set when the answer is kept for this company only
    job_company: str = ""  # shown in the question header
    job_title: str = ""
    site: str = ""
    title: str = ""
    kind: str = "text"  # value kind to ask for: num | bool | days | money | text | degree | decline | choices | file
    field: str = "{}"  # JSON FormField
    choices: str = "[]"  # JSON [[button label, value], ...]
    application_ids: str = "[]"  # JSON; every job waiting on this answer
    status: str = Field(default="waiting", index=True)  # waiting | shown | answered | skipped
    chat_id: int | None = None
    message_id: int | None = None
    answer_id: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    answered_at: datetime | None = None


engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Older databases get new columns added in place, so upgrading never loses data."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                kind = col.type.compile(dialect=engine.dialect)
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                literal = "NULL" if default is None else repr(default) if isinstance(default, str) else str(int(default) if isinstance(default, bool) else default)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {kind} DEFAULT {literal}'))


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
    if is_secret(key):
        raw = _fernet().decrypt(raw.encode()).decode()
    return json.loads(raw)


def put(key: str, value: Any) -> None:
    raw = json.dumps(value)
    if is_secret(key):
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
    import shutil

    SQLModel.metadata.drop_all(engine)
    shutil.rmtree(FILES_DIR, ignore_errors=True)
    init_db()


def save_file(name: str, data: bytes, folder: str = "") -> str:
    """Keep a file the user sent (CV, transcript…) so it can be uploaded to job forms later."""
    import re

    safe = re.sub(r"[^\w.-]+", "_", name).strip("._") or "file"
    target = FILES_DIR / folder if folder else FILES_DIR
    target.mkdir(parents=True, exist_ok=True)
    target.chmod(0o700)
    path = target / safe
    path.write_bytes(data)
    return str(path)
