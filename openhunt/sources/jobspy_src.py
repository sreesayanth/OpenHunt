"""LinkedIn, Indeed, Glassdoor, Naukri... through the python-jobspy library.

Personal, low-volume use only: these sites block heavy traffic and LinkedIn's terms forbid
automation, so searching uses public listings with no login. Applying is separate and opt-in
(see openhunt/apply).
"""

import asyncio
import math
from datetime import datetime

from openhunt.sources.base import Query, RawJob

DEFAULT_SITES = ["linkedin", "indeed"]


def supports(site: str) -> bool:
    """Whether the installed python-jobspy knows this board (Naukri came in later versions)."""
    try:
        from jobspy.model import Site
    except ImportError:
        return False
    return any(m.value == site for m in Site)


def default_sites(country: str = "india") -> list[str]:
    sites = list(DEFAULT_SITES)
    if (country or "").lower() == "india" and supports("naukri"):
        sites.append("naukri")  # most Indian jobs, and OpenHunt can apply there once logged in
    return sites


def available() -> bool:
    try:
        import jobspy  # noqa: F401
    except ImportError:
        return False
    return True


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value)


def _salary(row: dict) -> str:
    lo, hi = _clean(row.get("min_amount")), _clean(row.get("max_amount"))
    if not lo and not hi:
        return ""
    cur, per = _clean(row.get("currency")), _clean(row.get("interval"))
    rng = f"{lo}–{hi}" if lo and hi else lo or hi
    return " ".join(p for p in (cur, rng, f"/{per}" if per else "") if p)


class JobSpySource:
    name = "boards"

    def __init__(self, sites: list[str] | None = None, per_search: int = 20):
        self.sites = sites or DEFAULT_SITES
        self.per_search = per_search

    def _scrape(self, title: str, location: str, query: Query) -> list[RawJob]:
        from jobspy import scrape_jobs

        df = scrape_jobs(
            site_name=self.sites,
            search_term=title,
            location=location or None,
            is_remote=query.remote and not location,
            results_wanted=self.per_search,
            hours_old=query.hours_old,
            country_indeed=query.country,
            linkedin_fetch_description="linkedin" in self.sites,
        )
        jobs = []
        for row in df.to_dict("records"):
            posted = row.get("date_posted")
            jobs.append(
                RawJob(
                    source=_clean(row.get("site")) or "boards",
                    url=_clean(row.get("job_url")),
                    title=_clean(row.get("title")),
                    company=_clean(row.get("company")),
                    location=_clean(row.get("location")),
                    remote=bool(row.get("is_remote")) if _clean(row.get("is_remote")) else False,
                    salary=_salary(row),
                    description=_clean(row.get("description")),
                    apply_url=_clean(row.get("job_url_direct")),
                    posted_at=datetime.combine(posted, datetime.min.time()) if hasattr(posted, "year") else None,
                )
            )
        return [j for j in jobs if j.url and j.title]

    async def search(self, query: Query) -> list[RawJob]:
        locations = query.locations or [""]
        tasks = [asyncio.to_thread(self._scrape, t, loc, query) for t in query.titles for loc in locations]
        jobs = []
        for res in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(res, Exception):
                raise res
            jobs.extend(res)
        return jobs
