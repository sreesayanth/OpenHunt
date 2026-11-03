"""The user's own time zone, so "every morning at 8" and "apply 9:00-21:00" mean the user's clock,
even when OpenHunt runs on a VM set to UTC."""

import os
from datetime import datetime, tzinfo

from openhunt import store

COUNTRY_TZ = {
    "india": "Asia/Kolkata", "us": "America/New_York", "usa": "America/New_York", "uk": "Europe/London",
    "uae": "Asia/Dubai", "germany": "Europe/Berlin", "france": "Europe/Paris", "netherlands": "Europe/Amsterdam",
    "singapore": "Asia/Singapore", "australia": "Australia/Sydney", "canada": "America/Toronto",
    "ireland": "Europe/Dublin", "spain": "Europe/Madrid", "japan": "Asia/Tokyo", "saudi arabia": "Asia/Riyadh",
    "qatar": "Asia/Qatar", "pakistan": "Asia/Karachi", "bangladesh": "Asia/Dhaka", "sri lanka": "Asia/Colombo",
    "nepal": "Asia/Kathmandu", "philippines": "Asia/Manila", "malaysia": "Asia/Kuala_Lumpur",
}


def user_tz() -> tzinfo:
    """OPENHUNT_TZ, then the `timezone` preference, then the job-search country, then this machine's zone."""
    prefs = store.get("prefs") or {}
    name = os.environ.get("OPENHUNT_TZ") or prefs.get("timezone") or COUNTRY_TZ.get(str(prefs.get("country", "india")).lower())
    if name:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - e.g. Windows without the tzdata package
            pass
    return datetime.now().astimezone().tzinfo


def now() -> datetime:
    return datetime.now(user_tz())
