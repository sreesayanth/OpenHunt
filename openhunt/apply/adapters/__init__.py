"""Pick the right adapter for a job link."""

import re

from openhunt.apply.adapters.ats import Ashby, Greenhouse, Lever
from openhunt.apply.adapters.base import Adapter
from openhunt.apply.adapters.linkedin import LinkedInEasyApply
from openhunt.apply.adapters.naukri import Naukri

ADAPTERS: list[Adapter] = [Greenhouse(), Lever(), Ashby(), LinkedInEasyApply(), Naukri()]
GENERIC = Adapter()

# Sites that block automated browsers or need an account we don't support: the user applies there.
UNSUPPORTED_HOSTS = ("indeed.", "glassdoor.", "ziprecruiter.", "monster.", "wellfound.com", "angel.co", "instahyre.com")


def pick(url: str) -> Adapter | None:
    """The adapter for this link, or None if OpenHunt can't apply there."""
    host = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    if not host or any(h in host for h in UNSUPPORTED_HOSTS):
        return None
    for adapter in ADAPTERS:
        if adapter.matches(url):
            return adapter
    return GENERIC


def by_name(name: str) -> Adapter:
    return next((a for a in ADAPTERS if a.name == name), GENERIC)


__all__ = ["ADAPTERS", "GENERIC", "pick", "by_name", "Adapter"]
