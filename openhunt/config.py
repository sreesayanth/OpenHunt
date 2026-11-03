"""Paths and process-level settings. User settings live in the database (see store.py)."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("OPENHUNT_DATA", Path.home() / ".openhunt"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "openhunt.db"
KEY_PATH = DATA_DIR / "secret.key"
# Your CV file and any files you send for job forms (uploaded to applications).
FILES_DIR = DATA_DIR / "files"

# 127.0.0.1 by default so the dashboard is never exposed by accident.
WEB_HOST = os.environ.get("OPENHUNT_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("OPENHUNT_PORT", "8080"))

# How many jobs per run get the (slower, paid) AI score after the free keyword filter.
AI_RANK_LIMIT = int(os.environ.get("OPENHUNT_AI_RANK_LIMIT", "25"))
