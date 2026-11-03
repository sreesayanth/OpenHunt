"""One hunt run: fetch from all sources → drop duplicates → rank → save new matches."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timezone

from sqlmodel import select

from openhunt import store
from openhunt.ai.ranker import rank
from openhunt.sources import Query, RawJob, enabled_sources
from openhunt.store import Job, Match, utcnow

log = logging.getLogger(__name__)

_lock = asyncio.Lock()


@dataclass
class HuntResult:
    found: int = 0
    new: int = 0
    matches: list[int] = field(default_factory=list)  # match ids, best first, above min score
    errors: list[str] = field(default_factory=list)


def build_query(prefs: dict, profile: dict) -> Query | None:
    titles = prefs.get("titles") or profile.get("titles") or []
    if not titles:
        return None
    locations = [l for l in prefs.get("locations", []) if l.lower() != "remote"]
    return Query(
        titles=titles[:5],
        locations=locations[:3],
        remote=bool(prefs.get("remote")),
        country=prefs.get("country", "india"),
    )


def _save_new(jobs: list[RawJob]) -> list[tuple[RawJob, int]]:
    """Insert unseen jobs; return them with their db ids."""
    unique: dict[str, RawJob] = {}
    for j in jobs:
        unique.setdefault(j.fingerprint, j)
    with store.session() as s:
        seen = set(s.exec(select(Job.fingerprint).where(Job.fingerprint.in_(list(unique)))).all())
        saved = []
        for fp, j in unique.items():
            if fp in seen:
                continue
            if j.posted_at and j.posted_at.tzinfo is None:  # some boards give naive dates
                j.posted_at = j.posted_at.replace(tzinfo=timezone.utc)
            row = Job(fingerprint=fp, **{k: getattr(j, k) for k in RawJob.__dataclass_fields__})
            s.add(row)
            s.flush()
            saved.append((j, row.id))
        s.commit()
    return saved


async def run_hunt() -> HuntResult:
    async with _lock:  # a scheduled run and a manual /search must not overlap
        return await _run()


async def _run() -> HuntResult:
    result = HuntResult()
    prefs = store.get("prefs", {}) or {}
    profile = store.get("profile", {}) or {}
    query = build_query(prefs, profile)
    if not query:
        result.errors.append("No job titles set yet. Use /profile to set what you're looking for.")
        return result

    sources = enabled_sources()
    outcomes = await asyncio.gather(*(src.search(query) for src in sources), return_exceptions=True)
    jobs: list[RawJob] = []
    for src, out in zip(sources, outcomes):
        if isinstance(out, Exception):
            log.warning("Source %s failed: %s", src.name, out)
            result.errors.append(f"{src.name}: {out}")
        else:
            jobs.extend(out)
    result.found = len(jobs)

    new = _save_new(jobs)
    result.new = len(new)
    if new:
        ids = {id(j): job_id for j, job_id in new}
        ranked = await rank([j for j, _ in new], profile, prefs)
        min_score = int(prefs.get("min_score", 60))
        with store.session() as s:
            for r in ranked:
                m = Match(job_id=ids[id(r.job)], score=r.score, reasons=r.reasons, missing=", ".join(r.missing))
                s.add(m)
                s.flush()
                if r.score >= min_score:
                    result.matches.append(m.id)
            s.commit()

    store.put("last_run", {"at": utcnow().isoformat(), "found": result.found, "new": result.new,
                           "matches": len(result.matches), "errors": result.errors})
    return result
