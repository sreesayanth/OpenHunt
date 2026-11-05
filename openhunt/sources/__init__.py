"""Job-source plugins. `enabled_sources()` builds the list from the user's settings."""

from openhunt import store
from openhunt.sources import jobspy_src
from openhunt.sources.ats import ATSSource
from openhunt.sources.base import Query, RawJob, Source
from openhunt.sources.remotive import RemotiveSource

__all__ = ["Query", "RawJob", "Source", "enabled_sources"]


def enabled_sources() -> list[Source]:
    prefs = store.get("prefs", {}) or {}
    sources: list[Source] = [RemotiveSource()]
    if jobspy_src.available():
        sites = prefs.get("board_sites") or jobspy_src.default_sites(prefs.get("country", "india"))
        sources.append(jobspy_src.JobSpySource(sites))
    if prefs.get("watchlist"):
        sources.append(ATSSource(prefs["watchlist"]))
    return sources
