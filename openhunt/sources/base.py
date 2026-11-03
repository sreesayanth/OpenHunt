"""Common types for job-source plugins.

A source is any object with a `name` and an async `search(query) -> list[RawJob]`.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class Query:
    titles: list[str]
    locations: list[str] = field(default_factory=list)
    remote: bool = False
    hours_old: int = 72
    country: str = "india"  # used by Indeed via JobSpy


@dataclass
class RawJob:
    source: str
    url: str
    title: str
    company: str = ""
    location: str = ""
    remote: bool = False
    salary: str = ""
    description: str = ""
    posted_at: datetime | None = None
    apply_url: str = ""  # direct link to the company's application page, if known

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.company, self.title, self.location)


class Source(Protocol):
    name: str

    async def search(self, query: Query) -> list[RawJob]: ...


_NOISE = re.compile(r"\b(remote|hybrid|onsite|on-site|full[- ]?time|part[- ]?time|m/f/d|f/m/d)\b")


def _norm(text: str) -> str:
    text = _NOISE.sub(" ", (text or "").lower())
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())


def fingerprint(company: str, title: str, location: str) -> str:
    """Same job posted on LinkedIn and Indeed should collapse to one fingerprint."""
    city = _norm(location).split(" ")[0] if location else ""
    key = f"{_norm(company)}|{_norm(title)}|{city}"
    return hashlib.sha1(key.encode()).hexdigest()


def title_matches(title: str, wanted: list[str]) -> bool:
    """True if every word of any wanted title appears in the job title."""
    words = set(_norm(title).split())
    return any(set(_norm(w).split()) <= words for w in wanted if w.strip())
