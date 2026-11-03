"""Job sites OpenHunt can log in to. Form filling for each site comes in later phases."""

from openhunt.apply.sites.base import Site
from openhunt.apply.sites.linkedin import LinkedIn
from openhunt.apply.sites.naukri import Naukri

SITES: dict[str, Site] = {s.name: s for s in (LinkedIn(), Naukri())}

__all__ = ["SITES", "Site", "LinkedIn", "Naukri"]
