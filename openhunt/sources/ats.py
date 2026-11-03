"""Company career pages through their public ATS APIs (no login, no scraping).

Watchlist entries look like "greenhouse:stripe", "lever:netflix", "ashby:notion".
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from openhunt.sources.base import Query, RawJob, title_matches

log = logging.getLogger(__name__)


async def _greenhouse(client: httpx.AsyncClient, slug: str) -> list[RawJob]:
    resp = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
    resp.raise_for_status()
    return [
        RawJob(
            source=f"greenhouse:{slug}",
            url=j["absolute_url"],
            title=j["title"],
            company=slug.title(),
            location=(j.get("location") or {}).get("name", ""),
            description=j.get("content", ""),
            posted_at=datetime.fromisoformat(j["updated_at"]) if j.get("updated_at") else None,
        )
        for j in resp.json().get("jobs", [])
    ]


async def _lever(client: httpx.AsyncClient, slug: str) -> list[RawJob]:
    resp = await client.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
    resp.raise_for_status()
    jobs = []
    for j in resp.json():
        cats = j.get("categories") or {}
        created = j.get("createdAt")
        jobs.append(
            RawJob(
                source=f"lever:{slug}",
                url=j["hostedUrl"],
                title=j["text"],
                company=slug.title(),
                location=cats.get("location", ""),
                remote="remote" in (j.get("workplaceType") or "").lower(),
                description=j.get("descriptionPlain", ""),
                posted_at=datetime.fromtimestamp(created / 1000, timezone.utc) if created else None,
            )
        )
    return jobs


async def _ashby(client: httpx.AsyncClient, slug: str) -> list[RawJob]:
    resp = await client.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "true"}
    )
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs", []):
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        published = j.get("publishedAt")
        jobs.append(
            RawJob(
                source=f"ashby:{slug}",
                url=j["jobUrl"],
                title=j["title"],
                company=slug.title(),
                location=j.get("location", ""),
                remote=bool(j.get("isRemote")),
                salary=comp,
                description=j.get("descriptionPlain", ""),
                posted_at=datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None,
            )
        )
    return jobs


FETCHERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


class ATSSource:
    name = "companies"

    def __init__(self, watchlist: list[str]):
        self.watchlist = watchlist

    async def search(self, query: Query) -> list[RawJob]:
        async with httpx.AsyncClient(timeout=30) as client:
            tasks = []
            for entry in self.watchlist:
                kind, _, slug = entry.partition(":")
                if kind in FETCHERS and slug:
                    tasks.append(FETCHERS[kind](client, slug.strip()))
            results = await asyncio.gather(*tasks, return_exceptions=True)
        jobs = []
        for entry, res in zip(self.watchlist, results):
            if isinstance(res, Exception):
                log.warning("Watchlist %s failed: %s", entry, res)
                continue
            jobs.extend(j for j in res if title_matches(j.title, query.titles))
        return jobs
