"""The hidden browser that logs in to job sites and fills in forms in the background.

- One headless Chromium, shared by every site, started when needed and closed when idle.
- Each site gets its own clean browser context, so LinkedIn and Naukri never see each other.
- A site's login (cookies) is saved encrypted in ~/.openhunt/browser/<site>.state, with the same
  key that protects the bot token. Passwords are never stored here.
- The browser is not disguised: it says it's a headless Chrome. If a site refuses it, the user is told.
- Playwright and Chromium are downloaded the first time they're needed, so users never run a command.
"""

import asyncio
import importlib
import json
import logging
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from openhunt import store
from openhunt.config import DATA_DIR

log = logging.getLogger(__name__)

STATE_DIR = DATA_DIR / "browser"
IDLE_SECONDS = 300  # close Chromium after 5 idle minutes; it uses a few hundred MB
PLAYWRIGHT_SPEC = "playwright>=1.49"

Progress = Callable[[str], Awaitable[None]]


class BrowserUnavailable(Exception):
    """A plain-language reason the browser can't run on this machine."""


def is_android() -> bool:
    return "ANDROID_ROOT" in os.environ or "com.termux" in sys.prefix


def playwright_installed() -> bool:
    try:
        importlib.import_module("playwright.async_api")
        return True
    except ImportError:
        return False


async def _run(*args: str, timeout: float = 900) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return 1, "timed out"
    return proc.returncode or 0, out.decode(errors="ignore")[-2000:]


async def ensure_ready(progress: Progress | None = None) -> None:
    """Install Playwright and Chromium if needed. Raises BrowserUnavailable with a friendly reason."""
    if is_android():
        raise BrowserUnavailable("Applying needs a laptop or a VM. Phones can't run the browser it uses. Job alerts still work here.")
    if not playwright_installed():
        if progress:
            await progress("⏳ Getting ready… downloading the browser part. This takes 1–2 minutes, once.")
        code, out = await _run(sys.executable, "-m", "pip", "install", PLAYWRIGHT_SPEC)
        importlib.invalidate_caches()
        if code or not playwright_installed():
            log.warning("pip install playwright failed: %s", out)
            raise BrowserUnavailable(f"I couldn't download the browser part. Check the internet, or run: pip install \"{PLAYWRIGHT_SPEC}\"")
    if os.environ.get("OPENHUNT_CHROMIUM") or store.get("browser_ready"):
        return
    if progress:
        await progress("⏳ Downloading the browser (about 150 MB, only once)…")
    code, out = await _run(sys.executable, "-m", "playwright", "install", "chromium")
    if code:
        log.warning("playwright install chromium failed: %s", out)
        raise BrowserUnavailable("I couldn't download the browser. Check the internet and try again.")
    store.put("browser_ready", True)


# ---------- saved logins (encrypted) ----------

def _state_path(site: str) -> Path:
    return STATE_DIR / f"{site}.state"


def load_state(site: str) -> dict | None:
    path = _state_path(site)
    if not path.exists():
        return None
    try:
        return json.loads(store._fernet().decrypt(path.read_bytes()))
    except Exception:  # noqa: BLE001 - unreadable (e.g. key changed): treat as logged out
        log.warning("Saved %s login could not be read; logging in again", site)
        return None


def save_state(site: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)
    path = _state_path(site)
    path.write_bytes(store._fernet().encrypt(json.dumps(state).encode()))
    path.chmod(0o600)


def forget_state(site: str) -> None:
    _state_path(site).unlink(missing_ok=True)


def has_state(site: str) -> bool:
    return _state_path(site).exists()


# ---------- the shared browser ----------

class Browser:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._start_lock = asyncio.Lock()
        self._site_locks: dict[str, asyncio.Lock] = {}
        self._in_use = 0
        self._idle_task: asyncio.Task | None = None

    async def _ensure(self):
        async with self._start_lock:
            if self._browser and self._browser.is_connected():
                return self._browser
            from playwright.async_api import async_playwright

            if self._pw is None:
                self._pw = await async_playwright().start()
            exe = os.environ.get("OPENHUNT_CHROMIUM") or None
            try:
                self._browser = await self._pw.chromium.launch(headless=True, executable_path=exe)
            except Exception as exc:
                if "Executable doesn't exist" in str(exc) and not exe:
                    store.delete("browser_ready")  # reinstall on next ensure_ready()
                    raise BrowserUnavailable("The browser is missing. Tap Connect again and I'll download it.") from exc
                raise
            return self._browser

    @asynccontextmanager
    async def page(self, site: str, base_url: str = "") -> AsyncIterator:
        """A page with the site's saved login loaded. The login is saved again when the block ends."""
        lock = self._site_locks.setdefault(site, asyncio.Lock())
        async with lock:
            browser = await self._ensure()
            self._in_use += 1
            if self._idle_task:
                self._idle_task.cancel()
            context = await browser.new_context(
                storage_state=load_state(site),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                base_url=base_url or None,
            )
            context.set_default_timeout(20_000)
            try:
                yield await context.new_page()
            finally:
                try:
                    save_state(site, await context.storage_state())
                finally:
                    await context.close()
                    self._in_use -= 1
                    if self._in_use == 0:
                        self._idle_task = asyncio.get_running_loop().create_task(self._close_when_idle())

    async def _close_when_idle(self) -> None:
        try:
            await asyncio.sleep(IDLE_SECONDS)
        except asyncio.CancelledError:
            return
        if self._in_use == 0:
            await self.close()

    async def close(self) -> None:
        if self._idle_task and self._idle_task is not asyncio.current_task():
            self._idle_task.cancel()
        self._idle_task = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None


BROWSER = Browser()
