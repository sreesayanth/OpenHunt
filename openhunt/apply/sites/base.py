"""What OpenHunt needs to know about a job site to log in: where the fields are, what success looks like."""

import re


class Site:
    name = ""
    label = ""
    base = ""
    login_path = "/login"
    home_path = "/"
    session_cookies: tuple[str, ...] = ()  # any of these set → logged in
    logged_in_url = ""  # regex on the page address that only logged-in users reach
    warn_rules = False  # the site's terms forbid automated use; the user is warned before connecting

    user_fields = ("input[type=email]", "input[name=username]", "input[autocomplete=username]", "input[name=email]")
    password_fields = ("input[type=password]",)
    submit_buttons = ("button[type=submit]", "input[type=submit]")
    code_fields = (
        "input[autocomplete=one-time-code]", "input[name=pin]", "input[name*=otp i]", "input[id*=otp i]",
        "input[name*=verification i]", "input[name*=code i]:not([type=hidden])",
    )
    code_submit = ("button[type=submit]", "input[type=submit]")
    error_fields: tuple[str, ...] = ()
    error_text = r"(?:wrong|incorrect|invalid) (?:email|password|credentials|details|username)|password (?:is )?(?:wrong|incorrect)|couldn'?t find (?:an|your) account"
    captcha_markers = (
        "iframe[src*=arkoselabs]", "iframe[src*=funcaptcha]", "iframe[src*=recaptcha]", "iframe[src*=hcaptcha]",
        "iframe[title*=challenge i]", "#captcha-internal", "[class*=captcha i]:visible",
    )
    captcha_text = r"quick security check|verify (?:that )?you(?:'re| are) (?:a )?human|are you a robot|i'?m not a robot|let'?s confirm you"
    approval_text = r"check your [\w ]{0,20}app|approve (?:the|this|your) sign[- ]?in|open (?:the|your) [\w ]{0,20}app.{0,40}(?:approve|tap|confirm)|tap yes"

    def __init__(self, base: str = "") -> None:
        if base:
            self.base = base.rstrip("/")

    def url(self, path: str) -> str:
        return self.base + path

    async def has_session(self, page) -> bool:
        if not self.session_cookies:
            return False
        cookies = await page.context.cookies([self.base])
        return any(c["name"] in self.session_cookies and c.get("value") for c in cookies)

    async def is_logged_in(self, page) -> bool:
        """Open the site's home page and check we're really in (cookies can expire on the server)."""
        await page.goto(self.url(self.home_path), wait_until="domcontentloaded")
        if await first_visible(page, self.password_fields):
            return False
        if self.logged_in_url and not re.search(self.logged_in_url, page.url):
            return False
        return await self.has_session(page) if self.session_cookies else True


async def first_visible(page, selectors: tuple[str, ...]):
    for sel in selectors:
        loc = page.locator(sel)
        try:
            for i in range(min(await loc.count(), 5)):
                item = loc.nth(i)
                if await item.is_visible():
                    return item
        except Exception:  # noqa: BLE001 - page changed while we looked
            continue
    return None
