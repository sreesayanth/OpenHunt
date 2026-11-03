"""How jobs look in Telegram."""

from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from openhunt.ai.ranker import label
from openhunt.store import Job, Match


def job_card(m: Match, j: Job) -> tuple[str, InlineKeyboardMarkup]:
    where = escape(j.location or ("Remote" if j.remote else "—"))
    lines = [
        f"<b>{label(m.score)} · {m.score}/100</b>",
        f"<b>{escape(j.title)}</b>",
        f"🏢 {escape(j.company or 'Unknown company')} · 📍 {where}",
    ]
    if j.salary:
        lines.append(f"💰 {escape(j.salary)}")
    if m.reasons:
        lines.append(f"✅ {escape(m.reasons)}")
    if m.missing:
        lines.append(f"⚠️ Missing: {escape(m.missing)}")
    lines.append(f"<i>via {escape(j.source)}</i>")
    buttons = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔗 Open & apply", url=j.url)],
            [
                InlineKeyboardButton("⭐ Save", callback_data=f"m:save:{m.id}"),
                InlineKeyboardButton("👎 Not for me", callback_data=f"m:hide:{m.id}"),
            ],
        ]
    )
    return "\n".join(lines), buttons


def keyboard(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """keyboard([("Yes", "cb:yes"), ("No", "cb:no")], [...]) -> callback buttons."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])


SCHEDULE_BUTTONS = keyboard(
    [("🌅 Every morning", "sched:morning")],
    [("☀️🌙 Twice a day", "sched:twice")],
    [("⏰ Every hour", "sched:hourly")],
)
