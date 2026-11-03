import os
import tempfile

# Every test run gets its own empty data folder, set before openhunt.config is imported.
os.environ.setdefault("OPENHUNT_DATA", tempfile.mkdtemp())

# Use an already-installed Chromium when there is one (CI images, dev containers).
if os.path.exists("/opt/pw-browsers/chromium"):
    os.environ.setdefault("OPENHUNT_CHROMIUM", "/opt/pw-browsers/chromium")
