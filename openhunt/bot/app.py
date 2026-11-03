"""Telegram bot: linking, chat onboarding, job cards, and remote control commands."""

import logging
import secrets
from functools import wraps
from html import escape

from telegram import Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import NetworkError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from openhunt import store
from openhunt.ai import cli_providers, llm, openrouter
from openhunt.ai.profile import build_profile, extract_text
from openhunt.apply import browser
from openhunt.bot import apply_flow, autopilot, login_flow, scheduler
from openhunt.bot.cards import SCHEDULE_BUTTONS, job_card, keyboard
from openhunt.hunt import HuntResult, run_hunt

log = logging.getLogger(__name__)

DIGEST_SIZE = 5

COMMANDS = [
    ("autopilot", "Apply for me automatically"),
    ("applied", "Applications I sent"),
    ("apply", "Apply to a job link"),
    ("today", "Best jobs right now"),
    ("search", "Search for new jobs now"),
    ("saved", "Jobs you saved"),
    ("profile", "What I'm searching for"),
    ("schedule", "When I search"),
    ("pause", "Pause automatic searching"),
    ("resume", "Resume automatic searching"),
    ("answers", "What I know about you"),
    ("sites", "Log in to job sites"),
    ("ai", "Connect or change AI"),
    ("status", "Is everything working?"),
    ("help", "What can I do?"),
]


# ---------- linking & access ----------

def new_link_code() -> str:
    code = secrets.token_urlsafe(8)
    store.put("link_code", code)
    return code


def allowed_chats() -> list[int]:
    return store.get("allowed_chats", []) or []


def only_owner(handler):
    """Ignore everyone who hasn't linked with a one-time code."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat or chat.id not in allowed_chats():
            if update.message:
                await update.message.reply_text("🔒 This is a private OpenHunt bot.")
            return
        return await handler(update, context)

    return wrapper


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    code = context.args[0] if context.args else ""
    if chat_id not in allowed_chats():
        if not code or code != store.get("link_code"):
            await update.message.reply_text(
                "🔒 This is a private OpenHunt bot.\nOpen the link from your OpenHunt setup screen to connect."
            )
            return
        store.put("allowed_chats", allowed_chats() + [chat_id])
        store.delete("link_code")
        name = escape(update.effective_user.first_name or "there")
        await update.message.reply_html(f"✅ <b>Linked!</b> Hi {name}, I'm your personal job hunter.")
    await continue_onboarding(update.effective_chat.id, context.bot)


# ---------- onboarding (a chat, not a form) ----------

def step() -> str | None:
    return (store.get("onboarding") or {}).get("step")


def set_step(value: str | None) -> None:
    store.update("onboarding", step=value)


async def continue_onboarding(chat_id: int, bot: Bot) -> None:
    """Ask for whatever is still missing; otherwise show the main menu."""
    prefs = store.get("prefs", {}) or {}
    if not llm.is_configured() and not (store.get("onboarding") or {}).get("ai_skipped"):
        set_step("ai")
        await bot.send_message(chat_id, "First, let's connect an AI so I can read jobs like a human. 🧠", reply_markup=ai_menu())
    elif not store.get("profile"):
        set_step("cv")
        await bot.send_message(
            chat_id,
            "📄 Send me your CV (PDF or Word file).\nNo CV? No problem, tap below and just tell me about yourself.",
            reply_markup=keyboard([("I don't have a CV", "ob:no_cv")]),
        )
    elif not prefs.get("titles"):
        await ask_titles(chat_id, bot)
    elif "locations" not in prefs:
        set_step("locations")
        await bot.send_message(
            chat_id,
            "📍 Where do you want to work? Type cities (e.g. <i>Bangalore, Chennai</i>) or tap:",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([("🏠 Remote only", "ob:remote")], [("🌍 Anywhere", "ob:anywhere")]),
        )
    elif "min_salary" not in prefs:
        set_step("salary")
        await bot.send_message(
            chat_id,
            "💰 Minimum salary you'd accept? Type it like <i>8 LPA</i> or <i>$60k</i>, or skip.",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([("Skip", "ob:salary_skip")]),
        )
    elif not (store.get("schedule") or {}).get("mode"):
        set_step("schedule")
        await bot.send_message(chat_id, "⏰ When should I look for jobs?", reply_markup=SCHEDULE_BUTTONS)
    elif not autopilot.offered() and not browser.is_android():
        set_step(None)
        await autopilot.offer(bot, chat_id)
    else:
        set_step(None)
        await bot.send_message(chat_id, menu_text(), parse_mode=ParseMode.HTML, reply_markup=main_menu())


def ai_menu() -> InlineKeyboardMarkup:
    # Only offer Claude Code / Codex when installed on the machine running OpenHunt.
    cli_rows = [[(f"🧑‍💻 {llm.LABELS[p]}", f"ai:{p}")] for p in cli_providers.installed()]
    return keyboard(
        [("⚡ Connect in 1 click (OpenRouter)", "ai:openrouter")],
        *cli_rows,
        [("🆓 Free Google Gemini key", "ai:gemini"), ("🆓 Free Groq key", "ai:groq")],
        [("💻 Local AI on this computer (Ollama)", "ai:ollama")],
        [("Skip for now (basic matching)", "ai:skip")],
    )


def main_menu() -> InlineKeyboardMarkup:
    return keyboard(
        [("🔎 Search now", "menu:search"), ("🏆 Today's best", "menu:today")],
        [("⭐ Saved", "menu:saved"), ("⚙️ Profile", "menu:profile")],
        [("🤖 Autopilot", "menu:autopilot"), ("📋 Applications", "menu:applied")],
        [("🧠 What I know about you", "menu:answers"), ("🔐 Job sites", "menu:sites")],
    )


def menu_text() -> str:
    applying = ("🤖 Autopilot is on: I apply to good matches for you.\n" if autopilot.autopilot_on()
                else "Tap 🤖 Apply for me on any job, or paste a job link, and I'll apply.\n")
    return (
        "🎯 <b>All set!</b>\n"
        f"I search {escape(scheduler.describe())} and send you the best matches.\n"
        f"{applying}"
        "Tap a button or type /help."
    )


async def ask_titles(chat_id: int, bot: Bot) -> None:
    set_step("titles")
    suggested = (store.get("profile") or {}).get("titles", [])[:5]
    if suggested:
        store.update("onboarding", suggested=suggested)
        await bot.send_message(
            chat_id,
            "🔎 I'll search for:\n• " + "\n• ".join(escape(t) for t in suggested) + "\n\nOK, or type your own (comma separated)?",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([("✅ Looks good", "ob:titles_ok")]),
        )
    else:
        await bot.send_message(chat_id, "🔎 What jobs are you looking for? e.g. <i>Data Analyst, BI Developer</i>", parse_mode=ParseMode.HTML)


async def titles_changed(chat_id: int, bot: Bot) -> None:
    """Old matches were for the old titles; once set up, search for the new ones right away."""
    store.retire_matches()
    await continue_onboarding(chat_id, bot)
    if step() is None:  # onboarding finished, so this was a change, not first setup
        await do_search(chat_id, bot)


def profile_summary(p: dict) -> str:
    skills = ", ".join(p.get("skills", [])[:12]) or "none found"
    parts = []
    if p.get("headline"):
        parts.append(f"<b>{escape(p['headline'])}</b>")
    if p.get("years_experience") not in (None, ""):
        parts.append(f"Experience: {escape(str(p['years_experience']))} years")
    parts.append(f"Skills: {escape(skills)}")
    return "\n".join(parts)


async def save_profile_from_text(chat_id: int, bot: Bot, text: str, use_ai: bool = True) -> None:
    if len(text.strip()) < 30:
        await bot.send_message(chat_id, "I couldn't read much there. Could you send a bit more detail?")
        return
    # Kept so "Try again" works without sending the CV again.
    store.put("pending_cv_text", text)
    await bot.send_message(chat_id, "📖 Reading… (this can take up to a minute)")
    try:
        profile = await build_profile(text, use_ai=use_ai)
    except Exception as exc:  # noqa: BLE001
        log.warning("Profile build failed: %s", exc)
        await bot.send_message(
            chat_id,
            f"⚠️ {llm.friendly(exc)}",
            reply_markup=keyboard([("🔁 Try again", "ob:retry_cv")], [("Continue without AI", "ob:cv_basic")]),
        )
        return
    store.delete("pending_cv_text")
    store.put("profile", profile)
    # A new CV means new job titles to search for, and old matches were scored against the old CV.
    prefs = store.get("prefs") or {}
    if prefs.pop("titles", None):
        store.put("prefs", prefs)
        store.retire_matches()
    set_step("confirm_profile")
    await bot.send_message(
        chat_id,
        "Here's what I found:\n\n" + profile_summary(profile),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard([("✅ Looks right", "ob:profile_ok")], [("✏️ Try again", "ob:profile_redo")]),
    )


# ---------- reporting jobs ----------

async def send_matches(bot: Bot, match_ids: list[int]) -> int:
    sent = 0
    for mid in match_ids[:DIGEST_SIZE]:
        pair = store.match_with_job(mid)
        if not pair:
            continue
        text, buttons = job_card(*pair)
        for chat in allowed_chats():
            await bot.send_message(chat, text, parse_mode=ParseMode.HTML, reply_markup=buttons, disable_web_page_preview=True)
        if pair[0].status == "new":
            store.set_match_status(mid, "notified")
        sent += 1
    return sent


async def report_hunt(bot: Bot, result: HuntResult, manual: bool) -> None:
    chats = allowed_chats()
    if result.matches and autopilot.autopilot_on():
        queued, _ = autopilot.queue_matches(result.matches)
        rest = [m for m in result.matches if m not in queued]
        line = f"🎯 {len(result.matches)} new matching jobs."
        if queued:
            line += f" 🤖 Applying to {len(queued)} for you."
        if rest:
            line += " The others are below." if queued else " Here are the best:"
        for chat in chats:
            await bot.send_message(chat, line)
        if rest:
            await send_matches(bot, rest)
    elif result.matches:
        for chat in chats:
            await bot.send_message(chat, f"🎯 {len(result.matches)} new matching jobs. Here are the best:")
        await send_matches(bot, result.matches)
    elif manual:
        msg = f"Checked {result.found} jobs ({result.new} new). No strong matches right now. I'll keep looking. 👀"
        for chat in chats:
            await bot.send_message(chat, msg)
    if result.errors and (manual or result.found == 0):
        text = "⚠️ Some sources had problems:\n" + "\n".join(f"• {escape(e[:150])}" for e in result.errors[:5])
        for chat in chats:
            await bot.send_message(chat, text, parse_mode=ParseMode.HTML)


# ---------- commands ----------

@only_owner
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = [f"/{c} – {d}" for c, d in COMMANDS]
    await update.message.reply_text(
        "Here's what I can do:\n\n" + "\n".join(lines) + "\n\n📄 Send a new CV any time to update your profile."
        "\n✏️ Tell me changes any time, like “my notice period is now 30 days”."
    )


@only_owner
async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await do_search(update.effective_chat.id, context.bot)


async def do_search(chat_id: int, bot: Bot) -> None:
    await bot.send_message(chat_id, "🔎 Searching job sites… this can take a minute or two.")
    result = await run_hunt()
    await report_hunt(bot, result, manual=True)


@only_owner
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_list(update.effective_chat.id, context.bot, ("new", "notified"), "No matches yet. Tap /search to look now.")


@only_owner
async def cmd_saved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_list(update.effective_chat.id, context.bot, ("saved",), "You haven't saved any jobs yet. Tap ⭐ on a job to save it.")


async def show_list(chat_id: int, bot: Bot, statuses: tuple[str, ...], empty: str) -> None:
    min_score = int((store.get("prefs") or {}).get("min_score", 60)) if "saved" not in statuses else 0
    rows = [(m, j) for m, j in store.recent_matches(DIGEST_SIZE * 2, statuses) if m.score >= min_score][:DIGEST_SIZE]
    if not rows:
        await bot.send_message(chat_id, empty)
        return
    for m, j in rows:
        text, buttons = job_card(m, j)
        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=buttons, disable_web_page_preview=True)
    if "saved" in statuses:
        await bot.send_message(chat_id, "Want me to apply to all of them?", reply_markup=keyboard([("🤖 Apply to all saved", "ap:saved")]))


@only_owner
async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_profile(update.effective_chat.id, context.bot)


async def show_profile(chat_id: int, bot: Bot) -> None:
    p = store.get("profile") or {}
    prefs = store.get("prefs") or {}
    where = ", ".join(prefs.get("locations", [])) or "anywhere"
    text = (
        f"{profile_summary(p) if p else 'No CV yet.'}\n\n"
        f"🔎 Jobs: {escape(', '.join(prefs.get('titles', [])) or 'not set')}\n"
        f"📍 Where: {escape(where)}{' + remote' if prefs.get('remote') and where != 'Remote' else ''}\n"
        f"💰 Min salary: {escape(str(prefs.get('min_salary') or 'any'))}\n"
        f"⏰ Searching: {escape(scheduler.describe())}"
    )
    await bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard(
            [("🔎 Change jobs", "edit:titles"), ("📍 Change places", "edit:locations")],
            [("💰 Change salary", "edit:salary"), ("📄 New CV", "edit:cv")],
        ),
    )


@only_owner
async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Right now I search {scheduler.describe()}. Change it:", reply_markup=SCHEDULE_BUTTONS)


@only_owner
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store.update("schedule", paused=True)
    scheduler.apply_schedule(context.application)
    applying = autopilot.autopilot_on()
    if applying:
        autopilot.queue.update(on=False, resume_on=True)
    await update.message.reply_text("⏸ Paused. I won't search" + (" or apply" if applying else "") + " until you /resume.")


@only_owner
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store.update("schedule", paused=False)
    scheduler.apply_schedule(context.application)
    again = autopilot.queue.settings().get("resume_on")
    if again:
        autopilot.queue.update(on=True, resume_on=False)
        autopilot.wake()
    await update.message.reply_text(f"▶️ Back on! I'll search {scheduler.describe()}" + (" and apply for you." if again else "."))


@only_owner
async def cmd_autopilot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await autopilot.show_autopilot(context.bot, update.effective_chat.id)


@only_owner
async def cmd_applied(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await autopilot.show_applications(context.bot, update.effective_chat.id)


@only_owner
async def cmd_apply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await autopilot.handle_link(update, context):
        await update.message.reply_text("Send a job link after /apply, or just paste the link here. I'll apply to it.")


@only_owner
async def cmd_answers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await apply_flow.show_answers(context.bot, update.effective_chat.id)


@only_owner
async def cmd_sites(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await login_flow.show_sites(context.bot, update.effective_chat.id)


@only_owner
async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"🧠 AI: {llm.describe()}\nChoose one:", reply_markup=ai_menu())


@only_owner
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    last = store.get("last_run") or {}
    ok, info = (await llm.test_connection()) if llm.is_configured() else (True, llm.describe())
    lines = [
        f"🧠 AI: {'✅ ' + escape(info) if ok else '❌ ' + escape(llm.friendly(llm.AIError(info)))}",
        f"⏰ Schedule: {escape(scheduler.describe())}",
        f"🕐 Last search: {escape(last.get('at', 'never')[:16].replace('T', ' '))}",
    ]
    if last:
        lines.append(f"   found {last.get('found', 0)} · new {last.get('new', 0)} · matches {last.get('matches', 0)}")
        for err in last.get("errors", [])[:3]:
            lines.append(f"   ⚠️ {escape(err[:120])}")
    lines += [escape(line) for line in login_flow.status_lines()]
    cfg = autopilot.queue.settings()
    today = autopilot.queue.counts_since(autopilot.queue.local_midnight_utc())
    lines.append(f"🤖 Autopilot: {'on' if cfg['on'] else 'off'} · applied today: {today.get('submitted', 0)}")
    await update.message.reply_html("\n".join(lines))


# ---------- buttons ----------

AI_KEY_HELP = {
    "gemini": "1. Open the link and sign in with Google\n2. Tap <b>Create API key</b>\n3. Copy it and paste it here",
    "groq": "1. Open the link and sign in\n2. Tap <b>Create API Key</b>\n3. Copy it and paste it here",
}


@only_owner
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat.id
    bot = context.bot
    kind, _, arg = q.data.partition(":")

    if kind in apply_flow.KINDS:
        await apply_flow.handle_button(update, context)
        return
    if kind == login_flow.KIND:
        await login_flow.handle_button(update, context)
        return
    if kind == autopilot.KIND:
        await autopilot.handle_button(update, context)
        return

    if kind == "m":
        action, _, mid = arg.partition(":")
        if action == "apply":
            await autopilot.apply_match(bot, chat_id, int(mid))
            return
        store.set_match_status(int(mid), "saved" if action == "save" else "dismissed")
        if action == "save":
            pair = store.match_with_job(int(mid))
            if pair:
                await q.edit_message_reply_markup(job_card(*pair)[1])
        else:
            await q.message.delete()
        return

    if kind == "menu":
        if arg == "search":
            await do_search(chat_id, bot)
        elif arg == "today":
            await show_list(chat_id, bot, ("new", "notified"), "No matches yet. Tap /search to look now.")
        elif arg == "saved":
            await show_list(chat_id, bot, ("saved",), "No saved jobs yet.")
        elif arg == "profile":
            await show_profile(chat_id, bot)
        elif arg == "answers":
            await apply_flow.show_answers(bot, chat_id)
        elif arg == "sites":
            await login_flow.show_sites(bot, chat_id)
        elif arg == "autopilot":
            await autopilot.show_autopilot(bot, chat_id)
        elif arg == "applied":
            await autopilot.show_applications(bot, chat_id)
        return

    if kind == "sched":
        first_time = not (store.get("schedule") or {}).get("mode")
        store.put("schedule", {"mode": arg, "paused": False})
        scheduler.apply_schedule(context.application)
        await q.edit_message_text(f"⏰ Got it, I'll search {scheduler.describe()}.")
        if first_time:
            await continue_onboarding(chat_id, bot)
            await do_search(chat_id, bot)
        return

    if kind == "ai":
        await choose_ai(chat_id, bot, arg)
        return

    if kind == "edit":
        prefs = store.get("prefs") or {}
        if arg == "titles":
            prefs.pop("titles", None)
            store.put("prefs", prefs)
            await ask_titles(chat_id, bot)
        elif arg == "locations":
            prefs.pop("locations", None)
            prefs.pop("remote", None)
            store.put("prefs", prefs)
            await continue_onboarding(chat_id, bot)
        elif arg == "salary":
            prefs.pop("min_salary", None)
            store.put("prefs", prefs)
            await continue_onboarding(chat_id, bot)
        elif arg == "cv":
            set_step("cv")
            await bot.send_message(chat_id, "📄 Send me your new CV (PDF or Word), or just type about yourself.")
        return

    if kind == "ob":
        prefs = store.get("prefs") or {}
        if arg == "no_cv":
            set_step("about")
            await bot.send_message(
                chat_id,
                "No problem! 😊 Tell me about yourself in a few lines:\n"
                "• your last job or studies\n• years of experience\n• main skills\n• what job you want",
            )
            return
        if arg in ("retry_cv", "cv_basic"):
            text = store.get("pending_cv_text")
            if not text:
                await bot.send_message(chat_id, "📄 Please send your CV again.")
                return
            await q.edit_message_reply_markup(None)
            await save_profile_from_text(chat_id, bot, text, use_ai=arg == "retry_cv")
            return
        if arg == "profile_ok":
            await continue_onboarding(chat_id, bot)
        elif arg == "profile_redo":
            store.delete("profile")
            await continue_onboarding(chat_id, bot)
        elif arg == "titles_ok":
            prefs["titles"] = (store.get("onboarding") or {}).get("suggested", [])
            store.put("prefs", prefs)
            await titles_changed(chat_id, bot)
        elif arg in ("remote", "anywhere"):
            prefs.update(locations=["Remote"] if arg == "remote" else [], remote=True)
            store.put("prefs", prefs)
            await continue_onboarding(chat_id, bot)
        elif arg == "salary_skip":
            prefs["min_salary"] = ""
            store.put("prefs", prefs)
            await continue_onboarding(chat_id, bot)


async def choose_ai(chat_id: int, bot: Bot, provider: str) -> None:
    if provider == "skip":
        store.update("onboarding", ai_skipped=True)
        await bot.send_message(chat_id, "OK, I'll use basic matching. You can connect AI later with /ai.")
        await continue_onboarding(chat_id, bot)
    elif provider == "openrouter":
        url, verifier = openrouter.start()
        store.update("onboarding", step="ai_code", or_verifier=verifier)
        await bot.send_message(
            chat_id,
            "1. Tap the button and sign in (Google login works)\n2. Tap <b>Authorize</b>\n3. Copy the code it shows and paste it here",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚡ Connect OpenRouter", url=url)]]),
        )
    elif provider in AI_KEY_HELP:
        store.update("onboarding", step="ai_key", ai_provider=provider)
        await bot.send_message(
            chat_id,
            AI_KEY_HELP[provider],
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔑 Get my free key", url=llm.PROVIDERS[provider][2])]]),
        )
    elif provider in cli_providers.CLIS:
        llm.configure(provider)
        await bot.send_message(chat_id, f"🔌 Checking {llm.LABELS[provider]}… (can take up to a minute)")
        ok, info = await llm.test_connection()
        if ok:
            await bot.send_message(chat_id, f"✅ AI connected: {info}")
            await continue_onboarding(chat_id, bot)
        else:
            store.delete("ai_provider")
            await bot.send_message(chat_id, f"❌ {llm.friendly(llm.AIError(info))}", reply_markup=ai_menu())
    elif provider == "ollama":
        llm.configure("ollama")
        ok, info = await llm.test_connection()
        if ok:
            await bot.send_message(chat_id, f"✅ Connected to local AI: {info}")
            await continue_onboarding(chat_id, bot)
        else:
            store.delete("ai_provider")
            await bot.send_message(
                chat_id,
                "❌ I couldn't find Ollama on this computer.\nInstall it from https://ollama.com, run "
                "<code>ollama pull llama3.2</code>, then try again.",
                parse_mode=ParseMode.HTML,
                reply_markup=ai_menu(),
            )


# ---------- free text & files ----------

TYPED_STEPS = ("ai_code", "ai_key", "about", "cv", "titles", "locations", "salary")


@only_owner
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # A login waiting for an email, password or code comes first: those messages are deleted at once.
    if await login_flow.handle_text(update, context):
        return
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    bot = context.bot
    current = step()
    prefs = store.get("prefs") or {}

    # A reply to a job-form question on screen, unless the user just started typing something
    # else for me (a new salary, job titles, an AI key…): that comes first.
    if current not in TYPED_STEPS and await apply_flow.handle_text(update, context):
        return

    if current in ("ai_code", "ai_key"):
        # Don't leave secrets sitting in the chat history.
        try:
            await update.message.delete()
        except Exception:  # noqa: BLE001 - bots can't always delete
            pass
        ob = store.get("onboarding") or {}
        try:
            if current == "ai_code":
                llm.configure("openrouter", await openrouter.exchange(text, ob.get("or_verifier", "")))
            else:
                llm.configure(ob["ai_provider"], text)
        except Exception as exc:  # noqa: BLE001
            await bot.send_message(chat_id, f"❌ That didn't work ({exc}). Try again:", reply_markup=ai_menu())
            return
        ok, info = await llm.test_connection()
        if not ok:
            store.delete("ai_provider")
            await bot.send_message(chat_id, f"❌ {llm.friendly(llm.AIError(info))}\nTry again, or pick another option:", reply_markup=ai_menu())
            return
        set_step(None)
        await bot.send_message(chat_id, f"✅ AI connected: {info}")
        await continue_onboarding(chat_id, bot)
    elif current in ("about", "cv"):
        await save_profile_from_text(chat_id, bot, text)
    elif current == "titles":
        prefs["titles"] = [t.strip() for t in text.split(",") if t.strip()][:5]
        store.put("prefs", prefs)
        await titles_changed(chat_id, bot)
    elif current == "locations":
        places = [t.strip() for t in text.split(",") if t.strip()]
        prefs.update(locations=places, remote=any(p.lower() == "remote" for p in places))
        store.put("prefs", prefs)
        await continue_onboarding(chat_id, bot)
    elif current == "salary":
        prefs["min_salary"] = text[:40]
        store.put("prefs", prefs)
        await continue_onboarding(chat_id, bot)
    elif await autopilot.handle_link(update, context):  # a pasted job link: apply to it
        return
    elif not await apply_flow.handle_update_text(update, context):  # "my notice period is now 15 days"
        await bot.send_message(chat_id, "Tap a button below, or type /help.", reply_markup=main_menu())


@only_owner
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await apply_flow.handle_document(update, context):  # a file a job form asked for
        return
    doc = update.message.document
    name = (doc.file_name or "").lower()
    if not name.endswith((".pdf", ".docx", ".txt")):
        await update.message.reply_text("Please send your CV as a PDF or Word (.docx) file.")
        return
    data = await (await context.bot.get_file(doc.file_id)).download_as_bytearray()
    try:
        text = extract_text(bytes(data), name)
    except Exception:  # noqa: BLE001
        log.exception("CV read failed")
        text = ""
    if len(text.strip()) < 30:
        await update.message.reply_text(
            "I couldn't read text from that file (it may be a scanned image). "
            "Try another file, or just type about yourself."
        )
        return
    # Keep the file itself: job forms ask for it as an upload.
    store.put("cv_file", store.save_file(doc.file_name or "cv.pdf", bytes(data), folder="cv"))
    store.delete("cv_generated")
    await save_profile_from_text(update.effective_chat.id, context.bot, text)


# ---------- wiring ----------

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Network hiccups are normal on home internet; log briefly and tell the user if we can."""
    err = context.error
    if isinstance(err, NetworkError):  # includes TimedOut
        log.warning("Telegram network problem: %s", err)
        return
    log.error("Bot error", exc_info=err)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(update.effective_chat.id, "⚠️ Something went wrong. Please try again.")
        except Exception:  # noqa: BLE001
            pass


def build_application(token: str) -> Application:
    app = (
        Application.builder().token(token)
        .connect_timeout(20).read_timeout(30).write_timeout(60).pool_timeout(20)
        .build()
    )
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", cmd_start))
    for name, fn in [
        ("help", cmd_help), ("search", cmd_search), ("today", cmd_today), ("saved", cmd_saved),
        ("profile", cmd_profile), ("schedule", cmd_schedule), ("pause", cmd_pause),
        ("resume", cmd_resume), ("answers", cmd_answers), ("sites", cmd_sites), ("ai", cmd_ai), ("status", cmd_status),
        ("autopilot", cmd_autopilot), ("applied", cmd_applied), ("apply", cmd_apply),
    ]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


async def on_started(app: Application) -> None:
    await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
    scheduler.apply_schedule(app, catch_up=True)
    login_flow.schedule_checks(app)
    autopilot.start(app)
