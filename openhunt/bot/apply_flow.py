"""Telegram side of the answer memory.

- A job form asks something new → one chat message with buttons (or "type your answer").
- The answer is saved and reused on every later form, so the same question is never asked twice.
- "🧠 What I know about you" lists every answer, with change and forget buttons.
- Typing "my notice period is now 15 days" updates the answer directly.
"""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from html import escape

from sqlmodel import select
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from openhunt import store
from openhunt.apply import answers, values
from openhunt.apply.answers import Context, Resolution
from openhunt.apply.fields import FormField
from openhunt.apply.intents import BY_NAME, degree_level, norm
from openhunt.store import Answer, PendingQuestion, utcnow

log = logging.getLogger(__name__)

KINDS = ("aq", "ans")  # callback prefixes handled here

# Called after every answer (or skip, with None) so waiting applications can continue.
AnswerListener = Callable[[PendingQuestion, Answer | None], Awaitable[None]]
ANSWER_LISTENERS: list[AnswerListener] = []

EDIT = "edit"  # PendingQuestion.site for changes started from "What I know about you"
PAGE = 8
SOURCE_ICON = {"chat": "👤", "cv": "📄", "default": "⚙️", "ai": "🧠"}
TYPED_ONLY = {"money", "text", "file"}

HINTS = {
    "num": "Or type a number.",
    "days": "Or type it, like <i>45 days</i>.",
    "money": "Type it like <i>12 LPA</i>, <i>₹80,000 a month</i> or <i>$60k</i>.",
    "text": "Type your answer here.",
    "file": "Send the file here (PDF or Word).",
    "degree": "Or type it.",
    "decline": "Or type your answer.",
    "choices": "Type your answer here.",
}
RETRY = {
    "num": "Please type a number, like <i>3</i>.",
    "bool": "Please tap Yes or No.",
    "days": "Please type how long, like <i>30 days</i> or <i>2 months</i>, or <i>immediately</i>.",
    "money": "Please type an amount, like <i>12 LPA</i> or <i>$60k</i>.",
}


def chats() -> list[int]:
    return store.get("allowed_chats", []) or []


def _get(pid: int) -> PendingQuestion | None:
    with store.session() as s:
        return s.get(PendingQuestion, pid)


def _save(pq: PendingQuestion) -> PendingQuestion:
    with store.session() as s:
        s.add(pq)
        s.commit()
        s.refresh(pq)
        return pq


# ---------- building a question ----------

def build_choices(kind: str, f: FormField) -> list[list[list]]:
    """Button rows: [[label, value], ...] per row."""
    if kind == "bool":
        return [[["Yes", {"t": "bool", "v": True}], ["No", {"t": "bool", "v": False}]]]
    if kind == "num":
        nums = [[str(n), {"t": "num", "v": n}] for n in range(11)]
        nums[-1][0] = "10+"
        return [nums[:6], nums[6:]]
    if kind == "days":
        opts = [["Immediately", 0], ["15 days", 15], ["1 month", 30], ["2 months", 60], ["3 months", 90]]
        row = [[label, {"t": "days", "v": d}] for label, d in opts]
        return [row[:3], row[3:]]
    if kind == "degree" and not f.is_choice:
        row = [[label, {"t": "degree", "v": v}] for label, v in
               [("High school", "high school"), ("Diploma", "diploma"), ("Bachelor's", "bachelor"), ("Master's", "master"), ("PhD", "phd")]]
        return [row[:3], row[3:]]
    if kind == "decline" and not f.is_choice:
        return [[["Prefer not to say", {"t": "decline"}]]]
    if f.is_choice:
        buttons = []
        for o in f.options[:12]:
            if kind == "decline" and values.DECLINE.search(norm(o)):
                buttons.append([o[:60], {"t": "decline"}])
            elif kind == "degree" and degree_level(o):
                buttons.append([o[:60], {"t": "degree", "v": degree_level(o)}])
            else:
                buttons.append([o[:60], {"t": "text", "v": o}])
        per_row = 2 if all(len(b[0]) <= 18 for b in buttons) else 1
        return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    return []


def _typed(pq: PendingQuestion) -> bool:
    return not json.loads(pq.choices)


def question_text(pq: PendingQuestion) -> str:
    f = FormField.from_dict(json.loads(pq.field))
    if pq.site == EDIT:
        lines = [f"✏️ <b>{escape(pq.title)}</b>", "What should I use from now on?"]
    else:
        where = f"<b>{escape(pq.job_company)}</b> · {escape(pq.job_title)}" if pq.job_company else "A job form"
        lines = [f"❓ {where} asks:", f"<b>{escape(f.label)}</b>"]
        if pq.company:
            lines.append(f"<i>I'll use this answer for {escape(pq.job_company or pq.company)} only.</i>")
    hint = HINTS.get(pq.kind, "") if (_typed(pq) or pq.kind in ("num", "days")) else ""
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def question_buttons(pq: PendingQuestion) -> InlineKeyboardMarkup | None:
    rows, i = [], 0
    for row in json.loads(pq.choices):
        rows.append([InlineKeyboardButton(label, callback_data=f"aq:{pq.id}:{i + n}") for n, (label, _) in enumerate(row)])
        i += len(row)
    extra = []
    if rows and pq.kind not in ("bool", "num", "days"):
        extra.append(InlineKeyboardButton("✏️ Type my answer", callback_data=f"aq:{pq.id}:type"))
    extra.append(InlineKeyboardButton("✖️ Cancel" if pq.site == EDIT else "⏭ Skip this job", callback_data=f"aq:{pq.id}:skip"))
    rows.append(extra)
    return InlineKeyboardMarkup(rows)


# ---------- asking ----------

async def ask(bot: Bot, res: Resolution, ctx: Context, application_id: int | None = None) -> PendingQuestion:
    """Ask the user a form question. The same open question is never sent twice."""
    with store.session() as s:
        open_q = s.exec(
            select(PendingQuestion).where(
                PendingQuestion.key == res.key, PendingQuestion.company == res.company,
                PendingQuestion.status.in_(("waiting", "shown")), PendingQuestion.site != EDIT,
            )
        ).first()
    if open_q:
        ids = json.loads(open_q.application_ids)
        if application_id and application_id not in ids:
            open_q.application_ids = json.dumps(ids + [application_id])
            open_q = _save(open_q)
        return open_q
    pq = _save(PendingQuestion(
        key=res.key, company=res.company, job_company=ctx.company, job_title=ctx.job_title, site=ctx.site,
        title=res.title, kind=res.kind, field=json.dumps(res.field.to_dict()),
        choices=json.dumps(build_choices(res.kind, res.field)),
        application_ids=json.dumps([application_id] if application_id else []),
    ))
    await show_next(bot)
    return pq


async def show_next(bot: Bot) -> None:
    """Questions come one at a time, so the chat never fills up with open questions."""
    with store.session() as s:
        busy = s.exec(select(PendingQuestion).where(PendingQuestion.status == "shown", PendingQuestion.site != EDIT)).first()
        nxt = None if busy else s.exec(
            select(PendingQuestion).where(PendingQuestion.status == "waiting").order_by(PendingQuestion.created_at)
        ).first()
    if nxt:
        await _send(bot, nxt)


async def _send(bot: Bot, pq: PendingQuestion) -> None:
    for chat in chats():
        msg = await bot.send_message(chat, question_text(pq), parse_mode=ParseMode.HTML, reply_markup=question_buttons(pq))
        pq.chat_id, pq.message_id = chat, msg.message_id
    pq.status = "shown"
    _save(pq)
    store.put("typing_q", pq.id)  # a typed reply answers the question on screen


async def _close_message(bot: Bot, pq: PendingQuestion, text: str) -> None:
    if not (pq.chat_id and pq.message_id):
        return
    try:
        await bot.edit_message_text(text, chat_id=pq.chat_id, message_id=pq.message_id, parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001 - message too old or already changed
        pass


async def save_answer(bot: Bot, pq: PendingQuestion, value: dict) -> None:
    f = FormField.from_dict(json.loads(pq.field))
    if pq.site != EDIT and f.is_choice and values.fit(value, f) in (None, []):
        # True, but not one of this form's choices: keep it, and ask for the closest choice for this company.
        answers.remember(pq.key, value, title=pq.title, question=f.label)
        pq.company = norm(pq.job_company)
        pq.choices = json.dumps(build_choices("text", f))
        pq.kind = "text"
        _save(pq)
        if store.get("typing_q") == pq.id:
            store.delete("typing_q")
        await _close_message(bot, pq, question_text(pq).split("\n")[0] + f"\n<b>{escape(f.label)}</b>\n✅ {escape(values.describe(value))}, saved.")
        for chat in chats():
            msg = await bot.send_message(chat, "This form only allows these. Pick the closest one:", reply_markup=question_buttons(pq))
            pq.chat_id, pq.message_id = chat, msg.message_id
        _save(pq)
        return

    answer = answers.remember(pq.key, value, title=pq.title, question=f.label if pq.site != EDIT else "", company=pq.company)
    pq.status, pq.answer_id, pq.answered_at = "answered", answer.id, utcnow()
    _save(pq)
    if store.get("typing_q") == pq.id:
        store.delete("typing_q")
    scope = f"for {escape(pq.job_company or pq.company)}" if pq.company else "on every form"
    await _close_message(bot, pq, f"✅ <b>{escape(pq.title)}</b>: {escape(values.describe(value))}\n<i>Saved. I'll use this {scope}.</i>")
    await _notify(pq, answer)
    await show_next(bot)


async def skip(bot: Bot, pq: PendingQuestion) -> None:
    pq.status, pq.answered_at = "skipped", utcnow()
    _save(pq)
    if store.get("typing_q") == pq.id:
        store.delete("typing_q")
    await _close_message(bot, pq, "✖️ Cancelled." if pq.site == EDIT else "⏭ Skipped. I won't apply to this job.")
    await _notify(pq, None)
    await show_next(bot)


async def _notify(pq: PendingQuestion, answer: Answer | None) -> None:
    for listener in ANSWER_LISTENERS:
        try:
            await listener(pq, answer)
        except Exception:  # noqa: BLE001 - one broken listener must not lose the answer
            log.exception("Answer listener failed")


# ---------- handlers (wired in bot/app.py, all behind only_owner) ----------

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    bot = context.bot
    chat_id = q.message.chat.id
    parts = q.data.split(":")
    if parts[0] == "aq":
        pq = _get(int(parts[1]))
        if not pq or pq.status not in ("waiting", "shown"):
            await q.edit_message_reply_markup(None)
            return
        action = parts[2]
        if action == "type":
            store.put("typing_q", pq.id)
            await bot.send_message(chat_id, HINTS.get(pq.kind, HINTS["text"]), parse_mode=ParseMode.HTML)
        elif action == "skip":
            await skip(bot, pq)
        else:
            flat = [choice for row in json.loads(pq.choices) for choice in row]
            idx = int(action)
            if 0 <= idx < len(flat):
                await save_answer(bot, pq, flat[idx][1])
        return

    # "ans:..." = What I know about you
    action, rest = parts[1], parts[2:]
    if action == "p":
        await show_answers(bot, chat_id, page=int(rest[0]), message=q.message)
    elif action == "a":
        await show_saved(q, int(rest[0]))
    elif action == "k":
        await show_fact(q, ":".join(rest))
    elif action == "c":
        await start_change(bot, chat_id, rest[0], ":".join(rest[1:]))
    elif action == "d":
        a = answers.forget(int(rest[0]))
        text = f"🗑 Forgot <b>{escape(a.title)}</b>. I'll ask again when a form needs it." if a else "Already gone."
        await q.edit_message_text(text, parse_mode=ParseMode.HTML)
    elif action == "u":
        await undo(q, int(rest[0]))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """A typed reply to the question on screen. False if no question is waiting for typing."""
    pid = store.get("typing_q")
    if not pid:
        return False
    pq = _get(pid)
    if not pq or pq.status != "shown":
        store.delete("typing_q")
        return False
    text = update.message.text.strip()
    asks_for_link = re.search(r"link|url|linkedin|github|portfolio|website|profile|blog", f"{pq.title} {pq.field}", re.I)
    if re.fullmatch(r"https?://\S+", text) and not asks_for_link:
        return False  # a pasted job link, not an answer: let the link handler apply to it
    if pq.kind == "file":
        await update.message.reply_text("Please send the file here (PDF or Word), or tap Skip.")
        return True
    kind = pq.kind
    currency = pq.key.rsplit(":", 1)[-1].upper() if pq.kind == "money" else answers.default_currency()
    value = values.parse_reply(kind, text, currency)
    if value is None:
        await update.message.reply_html(RETRY.get(pq.kind, "Please type your answer."))
        return True
    if value.get("t") == "money" and value.get("cur") != currency:
        await update.message.reply_html(f"This form asks in {escape(currency)}. Please type the amount in {escape(currency)}.")
        return True
    await save_answer(context.bot, pq, value)
    return True


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """A file sent for a form question (e.g. a transcript). False if no file was asked for."""
    pid = store.get("typing_q")
    pq = _get(pid) if pid else None
    if not pq or pq.status != "shown" or pq.kind != "file":
        return False
    doc = update.message.document
    data = await (await context.bot.get_file(doc.file_id)).download_as_bytearray()
    path = store.save_file(doc.file_name or "file", bytes(data), folder="forms")
    await save_answer(context.bot, pq, {"t": "file", "v": path})
    return True


async def handle_update_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """'my notice period is now 15 days' → update that answer, with an Undo button."""
    text = update.message.text.strip()
    parsed = answers.parse_update(text)
    if not parsed:
        return False
    rec, key, value = parsed
    with store.session() as s:
        old = s.exec(select(Answer).where(Answer.key == key, Answer.company == "")).first()
    old_value = json.loads(old.value) if old else None
    a = answers.remember(key, value, title=rec.title, source="chat")
    store.put("answer_undo", {"id": a.id, "old": old_value})
    await update.message.reply_html(
        f"✅ Updated: <b>{escape(rec.title)}</b> → {escape(values.describe(value))}\nI'll use this on every form from now on.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Undo", callback_data=f"ans:u:{a.id}")]]),
    )
    return True


async def undo(q, answer_id: int) -> None:
    saved = store.get("answer_undo") or {}
    if saved.get("id") != answer_id:
        await q.edit_message_reply_markup(None)
        return
    a = answers.get_answer(answer_id)
    if a and saved.get("old"):
        answers.remember(a.key, saved["old"], title=a.title, company=a.company)
    elif a:
        answers.forget(answer_id)
    store.delete("answer_undo")
    await q.edit_message_text("↩️ Undone. Nothing changed.")


# ---------- What I know about you ----------

def _cb(data: str) -> str | None:
    return data if len(data.encode()) <= 64 else None  # Telegram's limit for button data


async def show_answers(bot: Bot, chat_id: int, page: int = 0, message=None) -> None:
    items = answers.known()
    if not items:
        await bot.send_message(chat_id, "🧠 I don't know anything about you yet. Send me your CV and I'll learn the rest from job forms.")
        return
    pages = max(1, -(-len(items) // PAGE))
    page = max(0, min(page, pages - 1))
    chunk = items[page * PAGE:(page + 1) * PAGE]
    lines = ["🧠 <b>What I know about you</b>", "I use this to fill in job forms. Tap a number to change it.", ""]
    buttons = []
    for n, k in enumerate(chunk, start=page * PAGE + 1):
        company = f" <i>({escape(k.company)} only)</i>" if k.company else ""
        lines.append(f"{n}. {escape(k.title)}: <b>{escape(k.value)}</b> {SOURCE_ICON.get(k.source, '')}{company}")
        data = _cb(f"ans:a:{k.answer_id}") if k.answer_id else _cb(f"ans:k:{k.key}")
        if data:
            buttons.append(InlineKeyboardButton(str(n), callback_data=data))
    lines += ["", "📄 from your CV · 👤 you told me · ⚙️ my default",
              "<i>You can also just type a change, like “my notice period is now 30 days”.</i>"]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Back", callback_data=f"ans:p:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(f"More ▶️ ({page + 2}/{pages})", callback_data=f"ans:p:{page + 1}"))
    if nav:
        rows.append(nav)
    markup = InlineKeyboardMarkup(rows)
    if message:
        await message.edit_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await bot.send_message(chat_id, "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=markup)


async def show_saved(q, answer_id: int) -> None:
    a = answers.get_answer(answer_id)
    if not a:
        await q.edit_message_text("That answer is gone.")
        return
    company = f"\nOnly for: {escape(a.company)}" if a.company else ""
    used = f"\nUsed on {a.use_count} form{'s' if a.use_count != 1 else ''}" if a.use_count else ""
    rows = [[InlineKeyboardButton("✏️ Change", callback_data=f"ans:c:a:{a.id}"),
             InlineKeyboardButton("🗑 Forget", callback_data=f"ans:d:{a.id}")],
            [InlineKeyboardButton("◀️ Back", callback_data="ans:p:0")]]
    await q.edit_message_text(
        f"<b>{escape(a.title)}</b>\nNow: {escape(values.describe(json.loads(a.value)))}{company}{used}",
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows),
    )


async def show_fact(q, key: str) -> None:
    k = next((k for k in answers.known() if k.key == key and not k.answer_id), None)
    if not k:
        await q.edit_message_text("I don't have that any more.")
        return
    source = {"cv": "from your CV", "default": "my default", "chat": "from our chat"}.get(k.source, "")
    rows = []
    if change := _cb(f"ans:c:k:{key}"):
        rows.append([InlineKeyboardButton("✏️ Change", callback_data=change)])
    rows.append([InlineKeyboardButton("◀️ Back", callback_data="ans:p:0")])
    await q.edit_message_text(
        f"<b>{escape(k.title)}</b>\nNow: {escape(k.value)} <i>({source})</i>",
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows),
    )


async def start_change(bot: Bot, chat_id: int, how: str, ref: str) -> None:
    """Ask for a new value for a saved answer ("a", answer id) or a CV fact/default ("k", key)."""
    if how == "a":
        a = answers.get_answer(int(ref))
        if not a:
            return
        key, title, company = a.key, a.title, a.company
        kind = _kind_for(key, json.loads(a.value))
    else:
        k = next((k for k in answers.known() if k.key == ref), None)
        if not k:
            return
        key, title, company, kind = k.key, k.title, "", k.kind
    if kind in ("choices", "essay"):
        kind = "text"
    f = FormField(label=title, kind="text")
    pq = _save(PendingQuestion(key=key, company=company, site=EDIT, title=title, kind=kind,
                               field=json.dumps(f.to_dict()), choices=json.dumps(build_choices(kind, f))))
    await _send(bot, pq)


def _kind_for(key: str, value: dict) -> str:
    intent = BY_NAME.get(key.split(":")[0])
    if intent:
        return intent.kind
    return {"num": "num", "bool": "bool", "days": "days", "money": "money", "degree": "degree", "decline": "decline"}.get(value.get("t"), "text")
