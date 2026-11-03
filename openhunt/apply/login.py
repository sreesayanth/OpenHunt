"""Log in to a job site in the hidden browser, asking the user for anything it needs through the chat.

The driver looks at the page after every step and reacts to what it sees: a login form, a
"wrong password" message, a code box, an "approve in the app" screen, a CAPTCHA, or success.
It never tries to get past a CAPTCHA by itself.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Protocol

from openhunt.apply.sites.base import Site, first_visible

log = logging.getLogger(__name__)

APPROVAL_WAIT = 180  # seconds to wait for "tap Yes in the app"
POLL = 3


class Ask(Protocol):
    """How the login talks to the user (the Telegram chat, or a script in tests)."""

    async def text(self, prompt: str, *, secret: bool = False) -> str | None: ...  # None = cancelled
    async def say(self, text: str) -> None: ...
    async def photo(self, png: bytes, caption: str) -> None: ...


@dataclass
class LoginResult:
    status: str  # ok | cancelled | wrong_password | captcha | timeout | stuck
    email: str = ""
    password: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


async def classify(site: Site, page, after_submit: bool = False) -> str:
    """What the page is asking for right now."""
    try:
        if await site.has_session(page):
            return "logged_in"
        if site.logged_in_url and re.search(site.logged_in_url, page.url) and not await first_visible(page, site.password_fields):
            return "logged_in"
        body = (await page.locator("body").inner_text(timeout=5000)).lower()
        if await first_visible(page, site.captcha_markers) or re.search(site.captcha_text, body):
            return "captcha"
        if await first_visible(page, site.code_fields) or await page.locator("input[maxlength='1']:visible").count() >= 4:
            return "code"
        if after_submit and (await first_visible(page, site.error_fields) or re.search(site.error_text, body)):
            return "error"
        if re.search(site.approval_text, body):
            return "approval"
        if await first_visible(page, site.password_fields):
            return "password"
        if await first_visible(page, site.user_fields):
            return "user"
    except Exception as exc:  # noqa: BLE001 - usually the page navigated while we looked
        log.debug("classify: %s", exc)
    return "unknown"


async def settle(page) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(1200)


async def _submit(site: Site, page, buttons: tuple[str, ...]) -> None:
    button = await first_visible(page, buttons)
    if button:
        await button.click()
    else:
        await page.keyboard.press("Enter")
    await settle(page)


async def _enter_code(site: Site, page, code: str) -> None:
    boxes = page.locator("input[maxlength='1']:visible")
    if await boxes.count() >= 4:  # one box per digit
        await boxes.first.click()
        await page.keyboard.type(code)
    else:
        field = await first_visible(page, site.code_fields)
        await field.fill(code)
    await _submit(site, page, site.code_submit)


async def login(site: Site, page, ask: Ask, *, email: str = "", password: str = "") -> LoginResult:
    """Log in, asking for the email, password and any code through `ask`."""
    await page.goto(site.url(site.login_path), wait_until="domcontentloaded")
    await settle(page)
    wrong = codes = unknown = forms = 0
    submitted = False
    label = site.label

    for _ in range(20):
        state = await classify(site, page, after_submit=submitted)
        log.info("%s login: %s", site.name, state)

        if state == "logged_in":
            return LoginResult("ok", email, password)

        if state == "captcha":
            await ask.photo(await page.screenshot(), f"🧩 {label} wants a security check (a CAPTCHA). I can't do those for you yet, so I stopped here.")
            return LoginResult("captcha", email)

        if state == "error":
            wrong += 1
            if wrong >= 3:
                return LoginResult("wrong_password", email)
            password = await ask.text(
                f"❌ {label} says the email or password is wrong.\nSend the password again (or tap Cancel if the email was wrong).",
                secret=True,
            ) or ""
            if not password:
                return LoginResult("cancelled", email)
            field = await first_visible(page, site.password_fields)
            if field:
                await field.fill(password)
                await _submit(site, page, site.submit_buttons)
            else:
                await page.goto(site.url(site.login_path), wait_until="domcontentloaded")
                await settle(page)
                submitted = False
            continue

        if state == "code":
            codes += 1
            if codes > 3:
                return LoginResult("stuck", email)
            prompt = (f"🔢 {label} sent you a code (by email, SMS or your authenticator app). Type it here." if codes == 1
                      else f"🔢 {label} didn't accept that code. Type the newest code here.")
            code = await ask.text(prompt, secret=True)
            if not code:
                return LoginResult("cancelled", email)
            await _enter_code(site, page, re.sub(r"\s+", "", code))
            submitted = True
            continue

        if state == "approval":
            await ask.say(f"📱 Open the {label} app on your phone and tap <b>Yes</b> to approve the sign-in. I'll wait 3 minutes.")
            for _ in range(APPROVAL_WAIT // POLL):
                await asyncio.sleep(POLL)
                if await classify(site, page) != "approval":
                    break
            else:
                return LoginResult("timeout", email)
            continue

        if state in ("user", "password"):
            forms += 1
            if forms > 4:  # the form keeps coming back without saying why
                await ask.photo(await page.screenshot(), f"🤔 {label} keeps showing the login form. This is what I see.")
                return LoginResult("stuck", email)
            user_field = await first_visible(page, site.user_fields)
            if user_field:
                if not email:
                    email = await ask.text(f"📧 Send your {label} email (or phone number).", secret=True) or ""
                    if not email:
                        return LoginResult("cancelled")
                await user_field.fill(email)
            pass_field = await first_visible(page, site.password_fields)
            if pass_field:
                if not password:
                    password = await ask.text(f"🔑 Now your {label} password.", secret=True) or ""
                    if not password:
                        return LoginResult("cancelled", email)
                await pass_field.fill(password)
            await _submit(site, page, site.submit_buttons)
            submitted = True
            unknown = 0
            continue

        unknown += 1
        if unknown >= 4:
            await ask.photo(await page.screenshot(), f"🤔 I got stuck while logging in to {label}. This is what I see.")
            return LoginResult("stuck", email)
        await page.wait_for_timeout(2000)

    return LoginResult("stuck", email)
