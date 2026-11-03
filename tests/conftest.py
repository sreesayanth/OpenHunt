import os
import tempfile

# Every test run gets its own empty data folder, set before openhunt.config is imported.
os.environ.setdefault("OPENHUNT_DATA", tempfile.mkdtemp())
