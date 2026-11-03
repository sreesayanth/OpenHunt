"""Autopilot in Telegram: the background worker that applies, and the few messages the user sees.

The user's whole job: answer a question now and then. Everything else happens in the background:
good matches are queued after every search, applied to one by one, and reported in one line each
(or only in the evening summary). Problems arrive as one message with buttons.
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, time, timedelta
from html import escape

from sqlmodel import select
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import Application as TgApp
from telegram.ext import ContextTypes

from openhunt import store
from openhunt.apply import adapters, browser, engine, queue
from openhunt.apply.answers import Context
from openhunt.apply.browser import BROWSER, BrowserUnavailable
from openhunt.apply.sites import SITES
from openhunt.bot import apply_flow, login_flow
from openhunt.store import Application, Job, Match, PendingQuestion, utcnow
from openhunt.timeutil import user_tz

log = logging.getLogger(__name__)

KIND = "ap"  # callback prefix
WAKE = asyncio.Event()
SUMMARY_TIME = time(20, 0)
ICONS = {"submitted": "✅", "waiting": "❓", "queued": "⏳", "running": "🤖", "needs_login": "🔐", "needs_you": "⚠️",
         "closed": "🚫", "already": "☑️", "unsupported": "🔗", "failed": "❌", "skipped": "⏭"}
STATUS_TEXT = {"submitted": "applied", "waiting": "waiting for your answer", "queued": "in the queue", "running": "applying now",
               "needs_login": "needs a login", "needs_you": "needs you", "closed": "job closed", "already": "already applied",
               "unsupported": "apply yourself", "failed": "failed", "skipped": "skipped"}
URL_RE = re.compile(r"https?://[^\s<>\"']+")

_state = {"next_auto": None, "login_nag": {}, "browser_nag": False}


def chats() -> list[int]:
    return store.get("allowed_chats", []) or []


async def tell(bot: Bot, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    for chat in chats():
        await bot.send_message(chat, text, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True)


def wake() -> None:
    WAKE.set()


# ---------- the worker ----------

async def worker(bot: Bot) -> None:
    """Runs forever inside the bot process: one application at a time."""
    queue.reset_running()
    while True:
        try:
            app = queue.next_ready()
            if app and app.source == "auto" and _state["next_auto"]:
                wait = (_state["next_auto"] - datetime.now()).total_seconds()
                if wait > 0:  # Autopilot jobs go a few minutes apart; the user's own requests don't wait
                    await _sleep(wait)
                    continue
            if not app:
                await _sleep(60)
                continue
            if app.source == "auto":
                _state["next_auto"] = datetime.now() + timedelta(seconds=queue.gap_seconds())
            await process(bot, app.id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let one bad job stop the worker
            log.exception("Autopilot worker error")
            await asyncio.sleep(30)


async def _sleep(seconds: float) -> None:
    WAKE.clear()
    try:
        await asyncio.wait_for(WAKE.wait(), timeout=seconds)
    except TimeoutError:
        pass


def _job(app: Application) -> engine.Job:
    j = queue.job_of(app)
    return engine.Job(url=app.url, title=app.title, company=app.company, description=(j.description if j else ""),
                      site=(j.source if j else "").split(":")[0])


async def process(bot: Bot, app_id: int) -> engine.Outcome | None:
    app = queue.set_status(app_id, "running")
    if not app:
        return None
    adapter = adapters.by_name(app.site)
    if adapter.login_site and not login_flow.connected(adapter.login_site):
        queue.set_status(app.id, "needs_login", message=f"Log in to {SITES[adapter.login_site].label} so I can apply.")
        await _nag_login(bot, adapter.login_site)
        return None
    try:
        await browser.ensure_ready(progress=lambda text: tell(bot, escape(text)))
    except BrowserUnavailable as exc:
        queue.set_status(app.id, "failed", message=str(exc))
        if not _state["browser_nag"]:
            _state["browser_nag"] = True
            await tell(bot, f"❌ {escape(str(exc))}")
        return None

    outcome = None
    for _ in range(3):  # at most two hops, e.g. LinkedIn → company site
        try:
            async with BROWSER.page(adapter.login_site or "web") as page:
                outcome = await engine.apply(page, adapter, _job(app))
        except Exception as exc:  # noqa: BLE001
            log.exception("Applying to %s failed", app.url)
            outcome = engine.Outcome("failed", f"Something went wrong: {str(exc)[:150]}")
        if outcome.status != "redirect":
            break
        target = outcome.redirect
        nxt = adapters.pick(target)
        if not nxt:
            app = queue.set_status(app.id, "running", url=target or app.url)
            outcome = engine.Outcome("unsupported", "This job is applied to on a site I can't use.")
            break
        adapter = nxt
        app = queue.set_status(app.id, "running", url=outcome.redirect, site=nxt.name)
        if adapter.login_site and not login_flow.connected(adapter.login_site):
            queue.set_status(app.id, "needs_login", message=f"Log in to {SITES[adapter.login_site].label} so I can apply.")
            await _nag_login(bot, adapter.login_site)
            return None
    await handle(bot, app, outcome)
    return outcome


async def handle(bot: Bot, app: Application, out: engine.Outcome) -> None:
    if out.page_title and app.title in ("", "Job you sent"):
        app = queue.set_status(app.id, app.status, title=out.page_title)
        with store.session() as s:
            job = s.get(Job, app.job_id)
            if job and job.title == "Job you sent":
                job.title = out.page_title
                s.add(job)
                s.commit()
    title = f"<b>{escape(app.title or 'the job')}</b> · {escape(app.company or adapters.by_name(app.site).label)}"
    filled = json.dumps(out.filled, default=str)
    if store.get("cv_generated") and not store.get("cv_generated_told"):
        store.put("cv_generated_told", True)
        await tell(bot, "📄 You haven't sent me a CV file, so I made a simple one from what you told me, and I attach it "
                        "to applications. Send me your real CV (PDF or Word) any time for better results.")
    if out.status == "submitted":
        proof = engine.save_proof(app.id, out.proof)
        queue.set_status(app.id, "submitted", submitted_at=utcnow(), proof_path=proof, answers=filled, message="")
        if queue.settings()["notify"] == "each" or app.source == "manual":
            await tell(bot, f"✅ Applied: {title}", InlineKeyboardMarkup([[InlineKeyboardButton("🧾 Proof", callback_data=f"{KIND}:proof:{app.id}")]]))
        return
    if out.status == "waiting":
        queue.set_status(app.id, "waiting", answers=filled, message=out.message)
        ctx = Context(company=app.company, job_title=app.title, site=app.site)
        for q in out.questions:
            await apply_flow.ask(bot, q, ctx, application_id=app.id)
        return
    if out.status == "needs_login":
        site = adapters.by_name(app.site).login_site or app.site
        queue.set_status(app.id, "needs_login", message=out.message)
        await _nag_login(bot, site)
        return
    if out.status in ("closed", "already", "unsupported"):
        queue.set_status(app.id, out.status, message=out.message)
        if app.source == "manual":
            await tell(bot, f"{ICONS[out.status]} {title}: {escape(out.message or STATUS_TEXT[out.status])}", _open_markup(app))
        return
    if out.status == "needs_you":
        proof = engine.save_proof(app.id, out.proof)
        queue.set_status(app.id, "needs_you", message=out.message, proof_path=proof, answers=filled)
        text = f"⚠️ I got stuck applying to {title}.\n{escape(out.message)}"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Open & finish it myself", url=app.url)],
            [InlineKeyboardButton("🔁 Try again", callback_data=f"{KIND}:retry:{app.id}"),
             InlineKeyboardButton("⏭ Skip", callback_data=f"{KIND}:skip:{app.id}")],
        ])
        for chat in chats():
            if out.proof:
                await bot.send_photo(chat, InputFile(out.proof, filename="stuck.png"), caption=re.sub("<[^>]+>", "", text)[:1000], reply_markup=markup)
            else:
                await bot.send_message(chat, text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return
    # failed: try again later, then give up quietly (it shows in the summary)
    attempts = app.attempts + 1
    status = "queued" if attempts < queue.MAX_ATTEMPTS else "failed"
    queue.set_status(app.id, status, attempts=attempts, message=out.message)
    if status == "failed" and app.source == "manual":
        await tell(bot, f"❌ I couldn't apply to {title}: {escape(out.message)}", _open_markup(app))


def _open_markup(app: Application) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open & apply yourself", url=app.url)]])


async def _nag_login(bot: Bot, site: str) -> None:
    """Ask for a site login at most once a day."""
    last = _state["login_nag"].get(site)
    if last and datetime.now() - last < timedelta(hours=24):
        return
    _state["login_nag"][site] = datetime.now()
    label = SITES[site].label if site in SITES else site
    await tell(bot, f"🔐 Some good jobs are on {label}. Log in once and I'll apply to them for you.",
               InlineKeyboardMarkup([[InlineKeyboardButton(f"🔐 Log in to {label}", callback_data=f"lg:connect:{site}")],
                                     [InlineKeyboardButton("Not now", callback_data=f"{KIND}:nologin:{site}")]]))


async def on_answer(pq: PendingQuestion, answer) -> None:
    """A question was answered (or skipped): jobs that were only waiting for it carry on right away."""
    for app_id in json.loads(pq.application_ids or "[]"):
        app = queue.get(app_id)
        if not app or app.status != "waiting":
            continue
        if answer is None:
            queue.set_status(app_id, "skipped", message="You skipped a question for this job.")
            continue
        with store.session() as s:
            open_qs = s.exec(select(PendingQuestion).where(PendingQuestion.status.in_(("waiting", "shown")))).all()
        if any(app_id in json.loads(q.application_ids or "[]") for q in open_qs):
            continue
        queue.set_status(app_id, "queued", source="manual")  # the user is here now: don't wait for active hours
    wake()


apply_flow.ANSWER_LISTENERS.append(on_answer)


async def on_login(site: str) -> None:
    if queue.requeue_for_site(site):
        wake()


# ---------- after each search ----------

def autopilot_on() -> bool:
    return bool(queue.settings()["on"])


def queue_matches(match_ids: list[int]) -> tuple[list[int], list[int]]:
    """Queue Autopilot jobs. Returns (queued match ids, match ids the user must apply to themselves)."""
    cfg = queue.settings()
    queued, manual = [], []
    for mid in match_ids:
        pair = store.match_with_job(mid)
        if not pair or pair[0].score < int(cfg["min_score"]):
            continue
        app = queue.enqueue(pair[1].id, "auto")
        (manual if app and app.status == "unsupported" else queued).append(mid)
    if queued:
        wake()
    return queued, manual


async def apply_match(bot: Bot, chat_id: int, match_id: int) -> None:
    pair = store.match_with_job(match_id)
    if not pair:
        return
    app = queue.enqueue(pair[1].id, "manual")
    if not app:
        return
    if app.status == "unsupported":
        await bot.send_message(chat_id, "🔗 I can't apply on this site (it blocks bots or needs an account per company). Tap 🔗 Open on the card to apply there.")
    elif app.status == "submitted":
        await bot.send_message(chat_id, "✅ Already applied to this one.")
    elif app.status == "waiting":
        await bot.send_message(chat_id, "❓ This one is waiting for your answer above.")
    else:
        await bot.send_message(chat_id, "🤖 On it! I'll message you when it's done.")
        wake()


def job_from_link(url: str) -> int:
    """A job the user pasted: saved as a Job so it gets the same treatment as found ones."""
    url = url.rstrip(").,]")
    fp = "link:" + hashlib.sha1(url.encode()).hexdigest()
    host = re.sub(r"^https?://", "", url).split("/")[0].removeprefix("www.")
    with store.session() as s:
        job = s.exec(select(Job).where(Job.fingerprint == fp)).first()
        if not job:
            company = _company_from_url(url) or host.split(".")[0].title()
            job = Job(fingerprint=fp, source="link", url=url, title="Job you sent", company=company)
            s.add(job)
            s.commit()
            s.refresh(job)
        return job.id


def _company_from_url(url: str) -> str:
    m = re.search(r"(?:greenhouse\.io|lever\.co|ashbyhq\.com)/(?:embed/job_app\?for=)?([\w-]+)", url)
    return m.group(1).replace("-", " ").title() if m else ""


async def handle_link(update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """The user pasted a job link: apply to it. False if the message has no link."""
    found = URL_RE.search(update.message.text or "")
    if not found:
        return False
    job_id = job_from_link(found.group(0))
    app = queue.enqueue(job_id, "manual")
    if app and app.status == "unsupported":
        await update.message.reply_text("🔗 I can't apply on that site (it blocks bots or needs an account I can't use). You'll need to apply there yourself.")
    elif app and app.status == "submitted":
        await update.message.reply_text("✅ I already applied to that one.")
    else:
        await update.message.reply_text("🤖 Got it! Applying now. I'll message you when it's done, or if a question comes up.")
        wake()
    return True


# ---------- /autopilot ----------

def autopilot_text() -> str:
    cfg = queue.settings()
    start, end = cfg["hours"]
    sites = [SITES[s].label for s in SITES if login_flow.connected(s)]
    lines = [
        "🤖 <b>Autopilot</b>: " + ("<b>ON</b>. I apply to good matches for you." if cfg["on"] else "<b>OFF</b>. Tap Start and I'll apply for you."),
        f"🎯 I apply to jobs scoring <b>{cfg['min_score']}+</b>",
        f"🕘 Between {start}:00 and {end}:00, a few minutes apart",
        "🔔 " + ("A short message after each application" if cfg["notify"] == "each" else "Only an evening summary"),
        "🌐 Company career sites" + (", " + ", ".join(sites) if sites else "") + (" · Tap 🔐 Job sites to add LinkedIn or Naukri" if len(sites) < len(SITES) else ""),
    ]
    today = queue.counts_since(queue.local_midnight_utc())
    if today:
        lines.append(f"\nToday: ✅ {today.get('submitted', 0)} applied · ❓ {today.get('waiting', 0)} waiting for you")
    return "\n".join(lines)


def autopilot_markup() -> InlineKeyboardMarkup:
    cfg = queue.settings()
    score = [(f"{'• ' if cfg['min_score'] == n else ''}{n}+", f"{KIND}:score:{n}") for n in (80, 70, 60)]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏸ Pause applying" if cfg["on"] else "▶️ Start applying for me", callback_data=f"{KIND}:{'off' if cfg['on'] else 'on'}")],
        [InlineKeyboardButton(t, callback_data=d) for t, d in score],
        [InlineKeyboardButton("🔔 Each application" if cfg["notify"] != "each" else "🔕 Only evening summary", callback_data=f"{KIND}:notify")],
        [InlineKeyboardButton("📋 My applications", callback_data=f"{KIND}:list"), InlineKeyboardButton("🔐 Job sites", callback_data="menu:sites")],
    ])


async def show_autopilot(bot: Bot, chat_id: int, message=None) -> None:
    if message:
        await message.edit_text(autopilot_text(), parse_mode=ParseMode.HTML, reply_markup=autopilot_markup())
    else:
        await bot.send_message(chat_id, autopilot_text(), parse_mode=ParseMode.HTML, reply_markup=autopilot_markup())


ASK_TEXT = (
    "🤖 <b>One last thing: want me to apply for you?</b>\n"
    "I'll apply to good matches by myself and only message you when a form asks something new.\n"
    "Company career sites are safe. LinkedIn and Naukri don't allow bots, so I only use them if you log in, and I go slowly."
)


async def offer(bot: Bot, chat_id: int) -> None:
    """Asked once, at the end of onboarding."""
    store.update("autopilot", asked=True)
    await bot.send_message(chat_id, ASK_TEXT, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, apply for me", callback_data=f"{KIND}:on")],
        [InlineKeyboardButton("No, I'll apply myself", callback_data=f"{KIND}:no")],
    ]))


def offered() -> bool:
    return bool((store.get("autopilot") or {}).get("asked"))


# ---------- /applied ----------

async def show_applications(bot: Bot, chat_id: int, message=None) -> None:
    apps = queue.recent(15)
    if not apps:
        text = "📋 No applications yet. Tap 🤖 Apply for me on any job, paste a job link, or turn on /autopilot."
        await (message.edit_text(text) if message else bot.send_message(chat_id, text))
        return
    lines = ["📋 <b>Your applications</b>", ""]
    rows = []
    for a in apps:
        when = queue.aware(a.submitted_at or a.updated_at).astimezone(user_tz()).strftime("%d %b")
        lines.append(f"{ICONS.get(a.status, '•')} {escape(a.title or 'Job')} · {escape(a.company or '')} <i>({STATUS_TEXT.get(a.status, a.status)}, {when})</i>")
        if a.status in ("needs_you", "failed", "skipped", "needs_login"):
            rows.append([InlineKeyboardButton(f"🔁 Retry {a.company or 'job'}"[:40], callback_data=f"{KIND}:retry:{a.id}"),
                         InlineKeyboardButton("🔗 Open", url=a.url)])
        elif a.status == "unsupported":
            rows.append([InlineKeyboardButton(f"🔗 Apply yourself: {a.company or 'job'}"[:50], url=a.url)])
        elif a.status == "submitted" and a.proof_path:
            rows.append([InlineKeyboardButton(f"🧾 Proof: {a.company or 'job'}"[:40], callback_data=f"{KIND}:proof:{a.id}")])
    markup = InlineKeyboardMarkup(rows[:12]) if rows else None
    text = "\n".join(lines)
    if message:
        await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True)
    else:
        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True)


async def send_proof(bot: Bot, chat_id: int, app_id: int) -> None:
    app = queue.get(app_id)
    if not app:
        return
    answered = json.loads(app.answers or "[]")
    lines = [f"🧾 <b>{escape(app.title)}</b> · {escape(app.company)}"]
    if app.submitted_at:
        lines.append(f"Applied {queue.aware(app.submitted_at).astimezone(user_tz()).strftime('%d %b %Y, %H:%M')}")
    for item in answered[:25]:
        answer = str(item.get("answer", ""))
        answer = "📎 your CV" if answer.startswith("/") else answer[:120]
        lines.append(f"• {escape(str(item.get('question', ''))[:80])}: {escape(answer)}")
    text = "\n".join(lines)[:1000]
    try:
        with open(app.proof_path, "rb") as fh:
            await bot.send_photo(chat_id, InputFile(fh.read(), filename="proof.png"), caption=re.sub("<[^>]+>", "", text))
    except OSError:
        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)


# ---------- buttons ----------

async def handle_button(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    chat_id = q.message.chat.id
    bot = context.bot
    _, action, *rest = q.data.split(":")
    arg = rest[0] if rest else ""
    if action == "on":
        queue.update(on=True, asked=True)
        wake()
        not_connected = [s for s in SITES if not login_flow.connected(s)]
        text = "🤖 <b>Autopilot is on.</b> I'll apply to good matches and keep you posted."
        rows = [[InlineKeyboardButton(f"🔐 Log in to {SITES[s].label}", callback_data=f"lg:connect:{s}")] for s in not_connected]
        if rows:
            text += "\nCompany career sites work already. Log in to these too, for many more jobs:"
            rows.append([InlineKeyboardButton("Later", callback_data=f"{KIND}:menu")])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows) if rows else None)
        # Apply to the good matches already found, too.
        recent = [m.id for m, _ in store.recent_matches(30, ("new", "notified", "saved"))]
        queue_matches(recent)
    elif action == "no":
        queue.update(on=False, asked=True)
        await q.edit_message_text("👍 OK. Tap 🤖 Apply for me on any job when you want me to apply. /autopilot turns it on any time.")
    elif action == "off":
        queue.update(on=False)
        await show_autopilot(bot, chat_id, message=q.message)
    elif action == "score":
        queue.update(min_score=int(arg))
        await show_autopilot(bot, chat_id, message=q.message)
    elif action == "notify":
        queue.update(notify="summary" if queue.settings()["notify"] == "each" else "each")
        await show_autopilot(bot, chat_id, message=q.message)
    elif action == "menu":
        await show_autopilot(bot, chat_id, message=q.message)
    elif action == "list":
        await show_applications(bot, chat_id, message=q.message)
    elif action == "proof":
        await send_proof(bot, chat_id, int(arg))
    elif action == "retry":
        app = queue.get(int(arg))
        if app:
            queue.enqueue(app.job_id, "manual")
            wake()
            await bot.send_message(chat_id, "🔁 Trying again now.")
    elif action == "skip":
        queue.set_status(int(arg), "skipped", message="You skipped it.")
        await q.edit_message_reply_markup(None)
    elif action == "nologin":
        await q.edit_message_text("OK. I'll stick to company career sites. Tap /sites whenever you want to log in.")
    elif action == "saved":
        saved = [m.id for m, _ in store.recent_matches(50, ("saved",), days=365)]
        n = 0
        for mid in saved:
            pair = store.match_with_job(mid)
            app = queue.enqueue(pair[1].id, "manual") if pair else None
            n += bool(app and app.status == "queued")
        wake()
        await bot.send_message(chat_id, f"🤖 Applying to {n} saved job{'s' if n != 1 else ''}. I'll keep you posted." if n else "Nothing new to apply to in your saved jobs.")
    elif action == "unsupported":
        await show_unsupported(bot, chat_id)


async def show_unsupported(bot: Bot, chat_id: int) -> None:
    apps = queue.recent(10, ("unsupported",))
    if not apps:
        await bot.send_message(chat_id, "Nothing here.")
        return
    rows = [[InlineKeyboardButton(f"🔗 {a.title} · {a.company}"[:60], url=a.url)] for a in apps]
    await bot.send_message(chat_id, "🔗 These good jobs are on sites I can't apply on. One tap each:", reply_markup=InlineKeyboardMarkup(rows))


# ---------- evening summary ----------

async def daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    since = utcnow() - timedelta(hours=24)
    counts = queue.counts_since(since)
    if not counts:
        return
    with store.session() as s:
        waiting_q = len(s.exec(select(PendingQuestion).where(PendingQuestion.status.in_(("waiting", "shown")))).all())
    parts = [f"✅ {counts.get('submitted', 0)} applied"]
    if waiting_q:
        parts.append(f"❓ {waiting_q} question{'s' if waiting_q != 1 else ''} waiting")
    if counts.get("needs_you"):
        parts.append(f"⚠️ {counts['needs_you']} need you")
    if counts.get("unsupported"):
        parts.append(f"🔗 {counts['unsupported']} to apply yourself")
    if counts.get("closed"):
        parts.append(f"🚫 {counts['closed']} closed")
    rows = [[InlineKeyboardButton("📋 See applications", callback_data=f"{KIND}:list")]]
    if counts.get("unsupported"):
        rows.append([InlineKeyboardButton("🔗 Jobs to apply yourself", callback_data=f"{KIND}:unsupported")])
    await tell(context.bot, "📊 <b>Last 24 hours</b>\n" + " · ".join(parts), InlineKeyboardMarkup(rows))
    if waiting_q:
        await apply_flow.show_next(context.bot)


def start(app: TgApp) -> None:
    """Start the worker and the evening summary (called once the bot is running)."""
    for job in app.job_queue.get_jobs_by_name("daily_summary"):
        job.schedule_removal()
    tz = user_tz()
    app.job_queue.run_daily(daily_summary, time=SUMMARY_TIME.replace(tzinfo=tz), name="daily_summary")
    stop()
    # A plain task, not app.create_task: the bot waits for those on shutdown, and this one never ends.
    _state["worker"] = asyncio.get_running_loop().create_task(worker(app.bot), name="autopilot-worker")


def stop() -> None:
    task = _state.pop("worker", None)
    if task and not task.done():
        task.cancel()


def applied_match_ids() -> set[int]:
    with store.session() as s:
        rows = s.exec(select(Match.id, Application.status).where(Match.job_id == Application.job_id)).all()
    return {mid for mid, status in rows if status in queue.OPEN + ("submitted",)}
