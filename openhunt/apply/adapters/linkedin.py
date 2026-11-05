"""LinkedIn: Easy Apply (a pop-up with a few steps). Jobs with an outside "Apply" go to the company's site."""

import re

from openhunt.apply.adapters.base import Adapter, find_button, settle


class LinkedInEasyApply(Adapter):
    name = "linkedin"
    label = "LinkedIn"
    login_site = "linkedin"
    form_scope = "[role=dialog]"
    hosts = ("linkedin.com",)
    paths = (r"/jobs/view/",)

    def form_url(self, url: str) -> str:
        m = re.search(r"(?:currentJobId=|/jobs/view/(?:[\w-]*-)?)(\d{6,})", url)
        if m and "linkedin.com" in url:
            return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
        return url

    async def open(self, page, url: str):
        await page.goto(self.form_url(url), wait_until="domcontentloaded")
        await settle(page, 1500)
        if re.search(r"/login|/authwall|/checkpoint", page.url):
            return "needs_login"
        text = await self.body(page)
        if re.search(r"\bApplied\b.{0,30}\bago\b|application was sent", text):
            return "already"
        if re.search(r"no longer accepting applications", text, re.I):
            return "closed"
        button = page.locator("button.jobs-apply-button:visible, button[aria-label*='Easy Apply' i]:visible").first
        if not await button.count():
            return "closed"
        label = (await button.get_attribute("aria-label") or await button.inner_text() or "").lower()
        if "easy apply" not in label:
            # "Apply on company website": follow it and apply there instead.
            context = page.context
            before = len(context.pages)
            await button.click()
            await settle(page, 2000)
            target = context.pages[-1] if len(context.pages) > before else page
            url = target.url
            if target is not page:
                await target.close()
            return f"redirect:{url}" if "linkedin.com" not in url or "/jobs/view" not in url else "unsupported"
        await button.click()
        await page.locator(self.form_scope).first.wait_for(timeout=10_000)
        await settle(page, 800)
        return page

    async def before_submit(self, page) -> None:
        follow = page.locator("#follow-company-checkbox")
        if await follow.count() and await follow.is_checked():
            await follow.evaluate("el => el.click()")  # don't follow companies on the user's behalf

    async def next(self, page) -> str:
        scope = self.form_scope
        submit = page.locator(f"{scope} button[aria-label='Submit application']:visible")
        if await submit.count():
            await self.before_submit(page)
            await submit.first.click()
            await settle(page, 2500)
            return "submit"
        for aria in ("Review your application", "Continue to next step"):
            button = page.locator(f"{scope} button[aria-label='{aria}']:visible")
            if await button.count():
                await button.first.click()
                await settle(page)
                return "next"
        button = await find_button(page, re.compile(r"^\s*(?:next|review|continue)\s*$", re.I), scope)
        if button:
            await button.click()
            await settle(page)
            return "next"
        return ""

    async def is_final_step(self, page) -> bool:
        return bool(await page.locator(f"{self.form_scope} button[aria-label='Submit application']:visible").count())
