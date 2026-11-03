"""Job-site login through the Telegram chat (bot/login_flow.py), against the fake site."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("playwright.async_api")

from openhunt import store  # noqa: E402
from openhunt.apply import browser  # noqa: E402
from openhunt.apply.browser import BROWSER  # noqa: E402
from openhunt.apply.sites import LinkedIn  # noqa: E402
from openhunt.bot import login_flow  # noqa: E402
from tests import fakesite  # noqa: E402

store.init_db()
CHAT = 1


class FakeBot:
    def __init__(self):
        self.sent, self.photos, self.n = [], [], 0

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None, **kw):
        self.n += 1
        self.sent.append(SimpleNamespace(text=text, markup=reply_markup, message_id=self.n))
        return SimpleNamespace(message_id=self.n, edit_text=self._edit)

    async def _edit(self, text, **kw):
        self.sent.append(SimpleNamespace(text=text, markup=kw.get("reply_markup"), message_id=0))

    async def send_photo(self, chat_id, photo, caption=""):
        self.photos.append(caption)

    async def edit_message_reply_markup(self, *a, **kw):
        return True

    def texts(self) -> str:
        return "\n".join(m.text for m in self.sent)


@pytest.fixture(scope="module")
def fake_url():
    url, server = fakesite.start()
    yield url
    server.shutdown()


@pytest.fixture(autouse=True)
async def setup(fake_url, monkeypatch):
    monkeypatch.setitem(login_flow.SITES, "linkedin", LinkedIn(base=fake_url))
    browser.forget_state("linkedin")
    for key in ("sites", "login_secret:linkedin", "rules_ok:linkedin"):
        store.delete(key)
    store.put("allowed_chats", [CHAT])
    login_flow._offered.clear()
    yield
    await BROWSER.close()


async def reply(text: str) -> list[str]:
    """Type a reply in the chat once the login asks for one. Returns what happened to the message."""
    for _ in range(400):
        if login_flow.waiting_for_reply(CHAT):
            break
        await asyncio.sleep(0.05)
    events = []

    async def delete():
        events.append("deleted")

    async def reply_text(t):
        events.append(t)

    update = SimpleNamespace(effective_chat=SimpleNamespace(id=CHAT), message=SimpleNamespace(text=text, delete=delete, reply_text=reply_text))
    assert await login_flow.handle_text(update, None)
    return events


def tap(bot, data, app=None):
    async def noop(*a, **kw):
        return None

    message = SimpleNamespace(chat=SimpleNamespace(id=CHAT), edit_text=bot._edit)
    q = SimpleNamespace(data=data, message=message, edit_message_text=bot._edit, edit_message_reply_markup=noop)
    context = SimpleNamespace(bot=bot, application=app or SimpleNamespace(create_task=lambda coro, name=None: asyncio.create_task(coro)))
    return login_flow.handle_button(SimpleNamespace(callback_query=q), context)


def buttons(bot) -> dict[str, str]:
    out = {}
    for m in bot.sent:
        if m.markup:
            out.update({b.text: b.callback_data for row in m.markup.inline_keyboard for b in row})
    return out


async def test_login_in_chat_deletes_secrets_and_offers_to_remember():
    bot = FakeBot()
    task = asyncio.create_task(login_flow.run_login(bot, CHAT, "linkedin"))
    assert await reply("pin@x.com") == ["deleted"]
    assert await reply("right") == ["deleted"]
    assert await reply("123456") == ["deleted"]
    result = await task
    assert result.ok and login_flow.connected("linkedin")
    assert "✅ LinkedIn connected." in bot.texts()
    assert "email" in bot.texts() and "code" in bot.texts()

    await tap(bot, buttons(bot)["🔁 Remember it"])
    assert login_flow.remembered("linkedin") == {"email": "pin@x.com", "password": "right"}
    with store.session() as s:
        assert "right" not in s.get(store.Setting, "login_secret:linkedin").value  # encrypted

    bot2 = FakeBot()
    await login_flow.show_sites(bot2, CHAT)
    assert "logged in as pi•••@x.com" in bot2.texts() and "password remembered" in bot2.texts()
    assert any("logged in" in line for line in login_flow.status_lines())


async def test_not_remembering_forgets_the_password():
    bot = FakeBot()
    task = asyncio.create_task(login_flow.run_login(bot, CHAT, "linkedin"))
    await reply("me@x.com")
    await reply("right")
    assert (await task).ok
    await tap(bot, buttons(bot)["No, ask me"])
    assert login_flow.remembered("linkedin") is None and not login_flow._offered


async def test_logged_out_with_remembered_password_logs_in_again_by_itself():
    store.put("login_secret:linkedin", {"email": "me@x.com", "password": "right"})
    bot = FakeBot()
    assert (await login_flow.run_login(bot, CHAT, "linkedin")).ok
    assert "Remember" not in str(buttons(bot))  # already remembered: no offer

    site = login_flow.SITES["linkedin"]
    async with BROWSER.page("linkedin", site.base) as page:
        await page.context.clear_cookies()  # the site logged us out

    tasks = []
    app = SimpleNamespace(create_task=lambda coro, name=None: tasks.append(asyncio.create_task(coro)))
    bot = FakeBot()
    await login_flow.check_sites(SimpleNamespace(bot=bot, application=app))
    assert tasks
    await asyncio.gather(*tasks)
    assert "logged me out, so I logged in again" in bot.texts() and login_flow.connected("linkedin")


async def test_logged_out_without_password_asks_the_user():
    bot = FakeBot()
    task = asyncio.create_task(login_flow.run_login(bot, CHAT, "linkedin"))
    await reply("me@x.com")
    await reply("right")
    await task
    site = login_flow.SITES["linkedin"]
    async with BROWSER.page("linkedin", site.base) as page:
        await page.context.clear_cookies()
    bot = FakeBot()
    await login_flow.check_sites(SimpleNamespace(bot=bot, application=None))
    assert "LinkedIn logged me out" in bot.texts()
    assert "🔐 Log in to LinkedIn" in buttons(bot)
    assert any("logged out" in line for line in login_flow.status_lines())


async def test_linkedin_warns_about_its_rules_before_connecting():
    bot = FakeBot()
    await tap(bot, "lg:connect:linkedin")
    assert "rules don't allow bots" in bot.texts()
    assert buttons(bot)["I understand, connect"] == "lg:go:linkedin"


async def test_cancel_button_stops_the_login():
    bot = FakeBot()
    task = asyncio.create_task(login_flow.run_login(bot, CHAT, "linkedin"))
    for _ in range(400):
        if login_flow.waiting_for_reply(CHAT):
            break
        await asyncio.sleep(0.05)
    await tap(bot, "lg:cancel")
    assert (await task).status == "cancelled" and "cancelled" in bot.texts()


async def test_log_out_deletes_the_saved_login():
    bot = FakeBot()
    task = asyncio.create_task(login_flow.run_login(bot, CHAT, "linkedin"))
    await reply("me@x.com")
    await reply("right")
    await task
    assert browser.has_state("linkedin")
    await tap(bot, "lg:out:linkedin")
    assert not browser.has_state("linkedin") and not login_flow.connected("linkedin")
    assert "Logged out of LinkedIn" in bot.texts()


async def test_captcha_is_shown_and_marked():
    bot = FakeBot()
    task = asyncio.create_task(login_flow.run_login(bot, CHAT, "linkedin"))
    await reply("captcha@x.com")
    await reply("right")
    assert (await task).status == "captcha"
    assert bot.photos and login_flow.statuses()["linkedin"]["status"] == "needs_you"


async def test_phones_are_told_why_applying_cant_run(monkeypatch):
    monkeypatch.setenv("ANDROID_ROOT", "/system")
    bot = FakeBot()
    assert await login_flow.run_login(bot, CHAT, "linkedin") is None
    assert "laptop or a VM" in bot.texts()
