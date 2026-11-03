"""Telegram side of job-site logins: everything happens in the chat.

The user types their email and password; the bot deletes both messages at once and types them
into the hidden browser. Codes and "approve in the app" prompts come to the chat as well.
Passwords are forgotten after login unless the user taps "Remember my password".
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes

from openhunt import store
from openhunt.apply import browser
from openhunt.apply.browser import BROWSER, BrowserUnavailable
from openhunt.apply.login import LoginResult, login
from openhunt.apply.sites import SITES, Site

log = logging.getLogger(__name__)

KIND = "lg"  # callback prefix handled here
ANSWER_TIMEOUT = 600  # stop waiting for a reply after 10 minutes
KEEP_OFFER_SECONDS = 600  # how long a just-used password waits for "Remember my password"
CHECK_EVERY = 6 * 3600  # check saved logins every 6 hours


@dataclass
class _Waiter:
    future: asyncio.Future
    secret: bool


_waiting: dict[int, _Waiter] = {}  # chat id → reply the login is waiting for
_running: set[str] = set()  # sites with a login in progress
_offered: dict[str, tuple[str, str]] = {}  # site → (email, password), only until the user answers
_tasks: set[asyncio.Task] = set()


# ---------- site status ----------

def statuses() -> dict:
    return store.get("sites", {}) or {}


def set_status(site: str, status: str, **extra) -> None:
    data = statuses()
    data[site] = {**data.get(site, {}), "status": status, "checked": datetime.now(timezone.utc).isoformat(), **extra}
    store.put("sites", data)


def connected(site: str) -> bool:
    return statuses().get(site, {}).get("status") == "connected" and browser.has_state(site)


def remembered(site: str) -> dict | None:
    return store.get(f"login_secret:{site}")


def mask(email: str) -> str:
    if "@" not in email:
        return email[:2] + "•••" + email[-2:] if len(email) > 4 else "•••"
    name, domain = email.split("@", 1)
    return f"{name[:2]}•••@{domain}"


def _ago(iso: str) -> str:
    try:
        minutes = int((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() // 60)
    except (TypeError, ValueError):
        return ""
    if minutes < 2:
        return "just now"
    if minutes < 120:
        return f"{minutes} min ago"
    return f"{minutes // 60} h ago" if minutes < 48 * 60 else f"{minutes // 1440} days ago"


def status_lines() -> list[str]:
    """Lines for /status, for sites the user connected at some point."""
    lines = []
    for name, site in SITES.items():
        st = statuses().get(name, {})
        if connected(name):
            lines.append(f"🔐 {site.label}: ✅ logged in (checked {_ago(st.get('checked', ''))})")
        elif st.get("status") in ("logged_out", "connected"):
            lines.append(f"🔐 {site.label}: ⚠️ logged out. Tap /sites to log in again")
        elif st.get("status") == "needs_you":
            lines.append(f"🔐 {site.label}: ⚠️ needs a security check. Tap /sites")
    return lines


# ---------- talking to the user during a login ----------

class ChatAsk:
    """The login's way to talk to the user, through the Telegram chat."""

    def __init__(self, bot: Bot, chat_id: int) -> None:
        self.bot, self.chat_id = bot, chat_id

    async def text(self, prompt: str, *, secret: bool = False) -> str | None:
        future = asyncio.get_running_loop().create_future()
        _waiting[self.chat_id] = _Waiter(future, secret)
        note = "\n🔒 <i>I'll delete your message right after reading it.</i>" if secret else ""
        msg = await self.bot.send_message(
            self.chat_id, escape(prompt) + note, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✖️ Cancel", callback_data=f"{KIND}:cancel")]]),
        )
        try:
            return await asyncio.wait_for(future, ANSWER_TIMEOUT)
        except TimeoutError:
            await self.bot.send_message(self.chat_id, "⌛ I stopped waiting. Tap /sites to try again.")
            return None
        finally:
            if _waiting.get(self.chat_id) and _waiting[self.chat_id].future is future:
                del _waiting[self.chat_id]
            try:
                await self.bot.edit_message_reply_markup(self.chat_id, msg.message_id, reply_markup=None)
            except Exception:  # noqa: BLE001
                pass

    async def say(self, text: str) -> None:
        await self.bot.send_message(self.chat_id, text, parse_mode=ParseMode.HTML)

    async def photo(self, png: bytes, caption: str) -> None:
        await self.bot.send_photo(self.chat_id, InputFile(png, filename="screen.png"), caption=caption)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """A reply the login is waiting for. Secret replies are deleted from the chat at once."""
    waiter = _waiting.get(update.effective_chat.id)
    if not waiter or waiter.future.done():
        return False
    del _waiting[update.effective_chat.id]  # one reply per question; the next prompt registers again
    if waiter.secret:
        try:
            await update.message.delete()
        except Exception:  # noqa: BLE001 - very old messages can't be deleted by bots
            await update.message.reply_text("⚠️ I couldn't delete your message. Please delete it yourself.")
    waiter.future.set_result(update.message.text.strip())
    return True


def waiting_for_reply(chat_id: int) -> bool:
    return chat_id in _waiting


# ---------- /sites ----------

async def show_sites(bot: Bot, chat_id: int, message=None) -> None:
    lines = ["🔐 <b>Job site logins</b>", "I log in for you in a hidden browser, so I can apply on these sites.", ""]
    rows = []
    for name, site in SITES.items():
        st = statuses().get(name, {})
        if connected(name):
            who = f" as {escape(mask(st.get('email', '')))}" if st.get("email") else ""
            keep = " · 🔁 password remembered" if remembered(name) else ""
            lines.append(f"✅ <b>{site.label}</b>: logged in{who}{keep}")
            rows.append([InlineKeyboardButton(f"Log out of {site.label}", callback_data=f"{KIND}:out:{name}")])
        else:
            state = {"logged_out": "⚠️ logged out", "needs_you": "⚠️ needs a security check"}.get(st.get("status"), "not connected")
            lines.append(f"{'⚠️' if state.startswith('⚠️') else '⚪'} <b>{site.label}</b>: {state.removeprefix('⚠️ ')}")
            rows.append([InlineKeyboardButton(f"🔐 Connect {site.label}", callback_data=f"{KIND}:connect:{name}")])
    lines += ["", "<i>Your password is only used to log in, then forgotten (unless you ask me to remember it).</i>"]
    markup = InlineKeyboardMarkup(rows)
    if message:
        await message.edit_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await bot.send_message(chat_id, "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=markup)


RULES_WARNING = (
    "⚠️ <b>Before I connect {label}</b>\n"
    "{label}'s rules don't allow bots or automated applying, so your account there could get limited.\n"
    "I go slowly and stop at every security check to keep the risk low, but I can't remove it.\n\n"
    "Company career sites (Greenhouse, Lever, Ashby) don't have this problem."
)


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    chat_id = q.message.chat.id
    bot = context.bot
    parts = q.data.split(":")
    action, name = parts[1], (parts[2] if len(parts) > 2 else "")
    site = SITES.get(name)

    if action == "cancel":
        waiter = _waiting.pop(chat_id, None)
        if waiter and not waiter.future.done():
            waiter.future.set_result(None)
        await q.edit_message_reply_markup(None)
    elif action == "menu":
        await show_sites(bot, chat_id, message=q.message)
    elif action == "connect" and site:
        if site.warn_rules and not store.get(f"rules_ok:{name}"):
            await q.edit_message_text(
                RULES_WARNING.format(label=site.label), parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("I understand, connect", callback_data=f"{KIND}:go:{name}")],
                                                   [InlineKeyboardButton("Not now", callback_data=f"{KIND}:menu")]]),
            )
            return
        await q.edit_message_reply_markup(None)
        start_login(context.application, bot, chat_id, name)
    elif action == "go" and site:
        store.put(f"rules_ok:{name}", True)
        await q.edit_message_reply_markup(None)
        start_login(context.application, bot, chat_id, name)
    elif action == "out" and site:
        browser.forget_state(name)
        store.delete(f"login_secret:{name}")
        set_status(name, "none")
        await q.edit_message_text(f"👋 Logged out of {site.label}. I deleted the saved login.")
    elif action in ("keep", "nokeep") and site:
        creds = _offered.pop(name, None)
        if action == "keep" and creds:
            store.put(f"login_secret:{name}", {"email": creds[0], "password": creds[1]})
            await q.edit_message_text(f"🔁 Saved (encrypted). I'll log in to {site.label} again by myself if it logs me out.")
        else:
            await q.edit_message_text("👍 Forgotten. If I'm ever logged out, I'll ask you.")


# ---------- running a login ----------

def start_login(app: Application, bot: Bot, chat_id: int, name: str, quiet: bool = False) -> None:
    if name in _running:
        return
    _running.add(name)
    # Not app.create_task: the bot would wait (up to 10 minutes) for a login on shutdown.
    task = asyncio.get_running_loop().create_task(run_login(bot, chat_id, name, quiet=quiet), name=f"login-{name}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def stop() -> None:
    for task in list(_tasks):
        task.cancel()


async def run_login(bot: Bot, chat_id: int, name: str, quiet: bool = False, site: Site | None = None) -> LoginResult | None:
    """Log in to one site through the chat. `quiet` = a background re-login with a remembered password."""
    site = site or SITES[name]
    ask = ChatAsk(bot, chat_id)
    try:
        try:
            await browser.ensure_ready(progress=ask.say)
        except BrowserUnavailable as exc:
            await ask.say(f"❌ {escape(str(exc))}")
            return None
        creds = remembered(name) or {}
        if not quiet:
            await ask.say(f"🔐 Logging in to {site.label}…")
        try:
            async with BROWSER.page(name, site.base) as page:
                result = await login(site, page, ask, email=creds.get("email", ""), password=creds.get("password", ""))
        except BrowserUnavailable as exc:
            await ask.say(f"❌ {escape(str(exc))}")
            return None
        except Exception as exc:  # noqa: BLE001 - network down, site changed…
            log.exception("%s login failed", name)
            await ask.say(f"❌ Something went wrong while logging in to {site.label} ({escape(str(exc)[:150])}). Try again later from /sites.")
            return None

        if result.ok:
            set_status(name, "connected", email=result.email)
            from openhunt.bot import autopilot  # jobs waiting for this login carry on

            await autopilot.on_login(name)
            await ask.say(f"✅ {site.label} connected." if not quiet else f"🔐 {site.label} had logged me out, so I logged in again. ✅")
            if result.password and not creds.get("password"):
                _offered[name] = (result.email, result.password)
                asyncio.get_running_loop().call_later(KEEP_OFFER_SECONDS, _offered.pop, name, None)
                await bot.send_message(
                    chat_id,
                    "Should I remember your password, so I can log in again by myself if "
                    f"{site.label} logs me out? It's stored encrypted on this computer only.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔁 Remember it", callback_data=f"{KIND}:keep:{name}"),
                        InlineKeyboardButton("No, ask me", callback_data=f"{KIND}:nokeep:{name}"),
                    ]]),
                )
        elif result.status == "wrong_password":
            if creds:
                store.delete(f"login_secret:{name}")  # the remembered password stopped working
            set_status(name, "logged_out")
            await ask.say(f"❌ {site.label} didn't accept the email and password. Tap /sites to try again.")
        elif result.status == "captcha":
            set_status(name, "needs_you")
            await ask.say("Please try again in a few hours from /sites. Security checks usually go away after a while.")
        elif result.status == "cancelled":
            await ask.say("OK, cancelled. Tap /sites whenever you want to connect.")
        elif result.status == "timeout":
            await ask.say("⌛ The approval didn't come through. Tap /sites to try again.")
        else:
            await ask.say(f"I couldn't finish logging in to {site.label}. Tap /sites to try again.")
        return result
    finally:
        _running.discard(name)


# ---------- keeping logins alive ----------

async def check_sites(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Every few hours: make sure saved logins still work, and fix or report the ones that don't."""
    if not browser.playwright_installed():
        return
    chats = store.get("allowed_chats", []) or []
    for name, site in SITES.items():
        if not connected(name) or name in _running:
            continue
        try:
            async with BROWSER.page(name, site.base) as page:
                ok = await site.is_logged_in(page)
        except Exception as exc:  # noqa: BLE001 - offline: try again next time
            log.info("Login check for %s failed: %s", name, exc)
            continue
        if ok:
            set_status(name, "connected")
            continue
        set_status(name, "logged_out")
        if remembered(name) and chats:
            start_login(context.application, context.bot, chats[0], name, quiet=True)
            continue
        for chat in chats:
            await context.bot.send_message(
                chat, f"⚠️ {site.label} logged me out. Log in again so I can keep applying there.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🔐 Log in to {site.label}", callback_data=f"{KIND}:connect:{name}")]]),
            )


def schedule_checks(app: Application) -> None:
    for job in app.job_queue.get_jobs_by_name("site_check"):
        job.schedule_removal()
    app.job_queue.run_repeating(check_sites, interval=CHECK_EVERY, first=600, name="site_check")
