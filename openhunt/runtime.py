"""Runs the Telegram bot and the web wizard in one asyncio process."""

import logging

import httpx
import uvicorn
from telegram.error import Conflict

from openhunt import store
from openhunt.bot.app import build_application, on_started
from openhunt.config import WEB_HOST, WEB_PORT

log = logging.getLogger(__name__)


async def check_token(token: str) -> str:
    """Return the bot's @username, or raise ValueError with a friendly message."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
    except httpx.HTTPError as exc:
        raise ValueError(f"Couldn't reach Telegram ({exc}). Check your internet.") from exc
    if resp.status_code != 200 or not resp.json().get("ok"):
        raise ValueError("Telegram says this token is not valid. Copy it again from BotFather.")
    return resp.json()["result"]["username"]


class Runtime:
    def __init__(self) -> None:
        self.bot_app = None
        self.conflict = False  # another process polls the same bot

    async def start_bot(self, token: str) -> None:
        await self.stop_bot()
        app = build_application(token)
        await app.initialize()
        await app.start()
        await app.updater.start_polling(error_callback=self._polling_error)
        await on_started(app)
        self.bot_app = app
        store.put("bot_username", app.bot.username)
        log.info("Telegram bot @%s is running", app.bot.username)

    def _polling_error(self, error: Exception) -> None:
        if isinstance(error, Conflict):
            if not self.conflict:
                log.warning(
                    "Another program is using this Telegram bot at the same time. "
                    "Stop the other OpenHunt (another PC, VM or terminal), or make a new bot for this one."
                )
            self.conflict = True
        else:
            log.warning("Telegram connection problem: %s", error)

    async def stop_bot(self) -> None:
        if self.bot_app:
            await self.bot_app.updater.stop()
            await self.bot_app.stop()
            await self.bot_app.shutdown()
            self.bot_app = None

    async def serve(self, host: str = WEB_HOST, port: int = WEB_PORT, web: bool = True) -> None:
        from openhunt.web.app import create_app

        token = store.get("bot_token")
        if token:
            try:
                await self.start_bot(token)
            except Exception:
                log.exception("Could not start the Telegram bot; fix it in the setup page")
        try:
            if web:
                server = uvicorn.Server(uvicorn.Config(create_app(self), host=host, port=port, log_level="warning"))
                print(f"\n  OpenHunt is running → open http://localhost:{port}\n")
                await server.serve()
            else:
                import asyncio

                print("\n  OpenHunt is running (Telegram only). Press Ctrl+C to stop.\n")
                await asyncio.Event().wait()
        finally:
            await self.stop_bot()
            from openhunt.apply.browser import BROWSER

            await BROWSER.close()
