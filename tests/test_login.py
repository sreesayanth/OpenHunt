"""Logging in to job sites in the hidden browser, driven by a scripted 'user' instead of Telegram."""

import pytest

pytest.importorskip("playwright.async_api")

from openhunt import store  # noqa: E402
from openhunt.apply import browser  # noqa: E402
from openhunt.apply.browser import BROWSER  # noqa: E402
from openhunt.apply.login import login  # noqa: E402
from openhunt.apply.sites import LinkedIn  # noqa: E402
from tests import fakesite  # noqa: E402

store.init_db()


class ScriptedUser:
    """Answers the bot's questions in order and records everything it was told."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts, self.said, self.photos = [], [], []

    async def text(self, prompt, *, secret=False):
        self.prompts.append((prompt, secret))
        return self.replies.pop(0) if self.replies else None

    async def say(self, text):
        self.said.append(text)

    async def photo(self, png, caption):
        assert png.startswith(b"\x89PNG")
        self.photos.append(caption)


@pytest.fixture(scope="module")
def site():
    url, server = fakesite.start()
    yield LinkedIn(base=url)
    server.shutdown()


@pytest.fixture(autouse=True)
async def fresh():
    browser.forget_state("linkedin")
    yield
    await BROWSER.close()


async def run(site, user, **kw):
    async with BROWSER.page("linkedin", site.base) as page:
        return await login(site, page, user, **kw)


async def test_plain_login_asks_email_and_password_as_secrets(site):
    user = ScriptedUser("me@x.com", "right")
    result = await run(site, user)
    assert result.ok and result.email == "me@x.com" and result.password == "right"
    assert [secret for _, secret in user.prompts] == [True, True]
    assert "email" in user.prompts[0][0] and "password" in user.prompts[1][0]


async def test_login_is_saved_encrypted_and_reused(site):
    assert (await run(site, ScriptedUser("me@x.com", "right"))).ok
    raw = (browser.STATE_DIR / "linkedin.state").read_bytes()
    assert b"li_at" not in raw  # encrypted on disk
    user = ScriptedUser()
    async with BROWSER.page("linkedin", site.base) as page:
        assert await site.is_logged_in(page)
        assert (await login(site, page, user)).ok
    assert user.prompts == []  # nothing asked the second time


async def test_wrong_password_then_right(site):
    user = ScriptedUser("me@x.com", "wrong", "right")
    result = await run(site, user)
    assert result.ok and result.password == "right"
    assert "wrong" in user.prompts[2][0]


async def test_email_code(site):
    user = ScriptedUser("pin@x.com", "right", "123 456")
    assert (await run(site, user)).ok
    assert "code" in user.prompts[2][0] and user.prompts[2][1]


async def test_wrong_code_asks_for_newest(site):
    user = ScriptedUser("pin@x.com", "right", "000000", "123456")
    assert (await run(site, user)).ok
    assert "didn't accept" in user.prompts[3][0]


async def test_code_in_one_box_per_digit(site):
    assert (await run(site, ScriptedUser("digits@x.com", "right", "123456"))).ok


async def test_approve_in_phone_app(site, monkeypatch):
    from openhunt.apply import login as login_mod

    monkeypatch.setattr(login_mod, "POLL", 1)
    user = ScriptedUser("app@x.com", "right")
    assert (await run(site, user)).ok
    assert any("app on your phone" in s for s in user.said)


async def test_captcha_stops_and_shows_the_user(site):
    user = ScriptedUser("captcha@x.com", "right")
    result = await run(site, user)
    assert result.status == "captcha" and user.photos and "CAPTCHA" in user.photos[0]


async def test_cancel(site):
    assert (await run(site, ScriptedUser("me@x.com"))).status == "cancelled"


async def test_remembered_password_needs_no_questions(site):
    user = ScriptedUser()
    assert (await run(site, user, email="me@x.com", password="right")).ok and user.prompts == []


async def test_logged_out_on_the_server_is_detected(site):
    assert (await run(site, ScriptedUser("me@x.com", "right"))).ok
    async with BROWSER.page("linkedin", site.base) as page:
        await page.context.clear_cookies()
    async with BROWSER.page("linkedin", site.base) as page:
        assert not await site.is_logged_in(page)
