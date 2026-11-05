"""How to apply on one kind of site. The generic adapter works on most career pages; others add quirks.

An adapter only knows the site: how to get to the form, which button moves on, what success looks
like. Reading questions and answering them is shared (forms.py, answers.py, engine.py).
"""

import logging
import re

log = logging.getLogger(__name__)

SUCCESS = re.compile(
    r"thank(?:s| you) for (?:applying|your application|your interest)|application (?:was |has been )?(?:submitted|received|sent|complete)"
    r"|(?:we(?:'ve| have)? )?received your application|application received|your application was sent|successfully applied|application successful"
    r"|you(?:'ve| have) applied|applied successfully",
    re.I,
)
CLOSED = re.compile(
    r"no longer accepting applications|(?:job|position|posting|role) (?:is |has )?(?:been )?(?:closed|expired|filled|no longer available)"
    r"|this job (?:has )?expired|job not found|page (?:you're looking for )?(?:was )?not found|error 404|404 not found",
    re.I,
)
ALREADY = re.compile(r"you(?:'ve| have)? already applied|already applied|application already submitted", re.I)
APPLY_BUTTON = re.compile(r"^\s*(?:easy apply|apply(?: now| here| online| for (?:this|the) (?:job|position|role)| to (?:this )?job)?|i'?m interested|start (?:your )?application)\s*$", re.I)
NEXT_BUTTON = re.compile(r"^\s*(?:next|continue|continue to next step|review|review (?:your )?application|save (?:and|&) continue|proceed)\s*$", re.I)
SUBMIT_BUTTON = re.compile(r"^\s*(?:submit(?: (?:your )?application)?|send(?: (?:my )?application)?|apply(?: now)?|finish|complete application)\s*$", re.I)


class Adapter:
    name = "generic"
    label = "the company's website"
    login_site = ""  # key in apply.sites.SITES when the site needs the user to be logged in
    form_scope = ""  # CSS selector the form lives in (e.g. a pop-up)
    button_groups = False
    hosts: tuple[str, ...] = ()  # hostnames this adapter handles
    paths: tuple[str, ...] = ()  # path patterns (used by tests' fake site)
    needs_identity = True  # only submit forms that clearly are job applications

    def matches(self, url: str) -> bool:
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        path = "/" + re.sub(r"^https?://[^/]+/?", "", url)
        return any(host == h or host.endswith("." + h) for h in self.hosts) or any(re.match(p, path) for p in self.paths)

    def form_url(self, url: str) -> str:
        return url

    async def body(self, page) -> str:
        try:
            return await page.locator("body").inner_text(timeout=5000)
        except Exception:  # noqa: BLE001
            return ""

    async def state(self, page, after_submit: bool = False) -> str:
        """done | closed | already | '' (keep going).

        "done" only counts after we pressed submit AND the form is gone: job descriptions often say
        "thank you for your interest", and a failed submit leaves that text on the page.
        """
        text = await self.body(page)
        if after_submit:
            confirm_url = re.search(r"/(?:confirmation|thank-?you|thanks|success|submitted)\b", page.url, re.I)
            no_form = not await has_form(page, self.form_scope)
            if confirm_url or (no_form and (SUCCESS.search(text) or re.search(r"\bthank(?:s| you)\b", text[:2000], re.I))):
                return "done"
        if ALREADY.search(text):
            return "already"
        if CLOSED.search(text[:3000]):
            return "closed"
        return ""

    async def open(self, page, url: str):
        """Go to the application form. Returns the page with the form (may be a new tab), or a status string."""
        await page.goto(self.form_url(url), wait_until="domcontentloaded")
        await settle(page)
        await dismiss_cookies(page)
        if st := await self.state(page):
            return st
        frame_src = await page.evaluate(
            "() => { const f = Array.from(document.querySelectorAll('iframe')).find(f => /greenhouse\\.io\\/embed|lever\\.co|ashbyhq|workable|smartrecruiters/.test(f.src)); return f ? f.src : ''; }"
        )
        if frame_src:  # the real form lives in an embedded frame: open it directly
            await page.goto(frame_src, wait_until="domcontentloaded")
            await settle(page)
        if await has_form(page, self.form_scope):
            return page
        button = await find_button(page, APPLY_BUTTON, scope="")
        if not button:
            return "unsupported"
        page = await click_maybe_new_page(page, button)
        if await has_form(page, self.form_scope):
            return page
        # Some "Apply" buttons go to a page with a second "Apply" button.
        button = await find_button(page, APPLY_BUTTON, scope="")
        if button:
            page = await click_maybe_new_page(page, button)
        return page if await has_form(page, self.form_scope) else "unsupported"

    async def _scope(self, page) -> str:
        if self.form_scope:
            return self.form_scope
        return "[data-oh-form]" if await page.locator("[data-oh-form]").count() else ""

    async def before_submit(self, page) -> None:
        """Last chance to change things on the final step (e.g. untick 'follow this company')."""

    async def next(self, page) -> str:
        """Press the button that moves the application on: 'next', 'submit', or '' if there is none."""
        await dismiss_cookies(page)
        scope = await self._scope(page)
        button = await find_button(page, NEXT_BUTTON, scope=scope)
        if button:
            await button.click()
            await settle(page)
            return "next"
        button = await find_submit(page, scope)
        if not button:
            return ""
        await self.before_submit(page)
        await button.click()
        await settle(page, 2500)
        return "submit"

    async def is_final_step(self, page) -> bool:
        scope = await self._scope(page)
        return not await find_button(page, NEXT_BUTTON, scope=scope) and bool(await find_submit(page, scope))


async def settle(page, ms: int = 1200) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(ms)


COOKIE_BUTTON = re.compile(r"^\s*(?:accept(?: all)?(?: cookies)?|allow all(?: cookies)?|i agree|agree|got it|ok|okay)\s*$", re.I)


async def dismiss_cookies(page) -> None:
    """Close a cookie banner so it doesn't cover the form's buttons."""
    try:
        banner = page.locator("[id*=cookie i]:visible, [class*=cookie i]:visible, [id*=consent i]:visible, [class*=consent i]:visible, [id*=gdpr i]:visible").first
        if not await banner.count():
            return
        buttons = banner.locator("button:visible, a[role=button]:visible")
        for i in range(min(await buttons.count(), 8)):
            b = buttons.nth(i)
            if COOKIE_BUTTON.match((await b.inner_text(timeout=1000)) or ""):
                await b.click(timeout=3000)
                await page.wait_for_timeout(400)
                return
    except Exception:  # noqa: BLE001 - no banner, or it went away by itself
        pass


async def has_form(page, scope: str = "") -> bool:
    """A real application form: some answerable fields, and a name, email or CV field among them."""
    root = scope or "body"
    try:
        n = await page.locator(f"{root} input:visible:not([type=hidden]):not([type=search]), {root} textarea:visible, {root} select:visible, {root} input[type=file]").count()
        if n < 2:
            return False
        text = (await page.locator(root).first.inner_text(timeout=3000)).lower()
    except Exception:  # noqa: BLE001
        return False
    return bool(re.search(r"e-?mail|resume|\bcv\b|first name|full name|\bname\b|phone", text))


async def _buttons(page, scope: str):
    root = scope or "body"
    return page.locator(
        f"{root} button:visible, {root} input[type=submit]:visible, {root} a[role=button]:visible, {root} a.btn:visible, "
        f"{root} a[class*=apply i]:visible, {root} a[href*=apply]:visible, {root} [role=button]:visible, {root} a:visible"
    )


async def find_button(page, pattern: re.Pattern, scope: str = ""):
    loc = await _buttons(page, scope)
    try:
        count = min(await loc.count(), 200)
    except Exception:  # noqa: BLE001
        return None
    for i in range(count):
        item = loc.nth(i)
        try:
            text = (await item.get_attribute("aria-label")) or ""
            inner = (await item.inner_text(timeout=1000)) or (await item.get_attribute("value")) or ""
        except Exception:  # noqa: BLE001
            continue
        if pattern.match(inner.strip()) or (text and pattern.match(text.strip())):
            return item
    return None


async def find_submit(page, scope: str = ""):
    root = scope or "body"
    real = page.locator(f"{root} form button[type=submit]:visible, {root} form input[type=submit]:visible")
    if await real.count():
        return real.last
    return await find_button(page, SUBMIT_BUTTON, scope)


async def click_maybe_new_page(page, button):
    """Click, and follow the new tab if the click opened one."""
    context = page.context
    before = len(context.pages)
    await button.click()
    await settle(page)
    if len(context.pages) > before:
        page = context.pages[-1]
        await settle(page)
    await dismiss_cookies(page)
    return page
