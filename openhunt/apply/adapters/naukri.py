"""Naukri: one "Apply" button; some jobs then ask a few questions in a chat-style panel."""

import logging
import re

from openhunt.apply import answers
from openhunt.apply.adapters.base import Adapter, settle
from openhunt.apply.fields import FormField

log = logging.getLogger(__name__)

DRAWER = ".chatbot_Drawer"
APPLIED = re.compile(r"successfully applied|you have applied|application sent|already applied", re.I)


class Naukri(Adapter):
    name = "naukri"
    label = "Naukri"
    login_site = "naukri"
    hosts = ("naukri.com",)
    paths = (r"/naukri/",)

    async def open(self, page, url: str):
        await page.goto(url, wait_until="domcontentloaded")
        await settle(page, 1500)
        if re.search(r"/nlogin|/login", page.url):
            return "needs_login"
        text = await self.body(page)
        if re.search(r"\balready applied\b", text, re.I) or await page.locator("#already-applied:visible").count():
            return "already"
        if re.search(r"job (?:has )?expired|no longer accepting", text, re.I):
            return "closed"
        button = page.locator("#apply-button:visible, button.apply-button:visible").first
        if not await button.count():
            company = page.locator("#company-site-button:visible, button.company-site-button:visible").first
            if await company.count():
                context = page.context
                before = len(context.pages)
                await company.click()
                await settle(page, 2000)
                if len(context.pages) > before:
                    target = context.pages[-1]
                    url = target.url
                    await target.close()
                    return f"redirect:{url}"
            return "unsupported"
        return page

    async def run(self, page, job, dry_run: bool = False):
        from openhunt.apply.engine import Outcome

        ctx = answers.Context(company=job.company, job_title=job.title, site="naukri")
        if dry_run:
            return Outcome("ready", "Test run: not pressing Apply.")
        await page.locator("#apply-button:visible, button.apply-button:visible").first.click()
        await settle(page, 1500)
        filled: list[dict] = []
        asked: set[str] = set()
        for _ in range(25):
            if APPLIED.search(await self.body(page)) and not await page.locator(f"{DRAWER}:visible").count():
                return Outcome("submitted", filled=filled, proof=await page.screenshot(full_page=True))
            if not await page.locator(f"{DRAWER}:visible").count():
                await settle(page, 1500)
                if APPLIED.search(await self.body(page)):
                    return Outcome("submitted", filled=filled, proof=await page.screenshot(full_page=True))
                return Outcome("needs_you", "Naukri didn't confirm the application.", filled=filled, proof=await page.screenshot(full_page=True))
            question = (await page.locator(f"{DRAWER} .botMsg").last.inner_text()).strip()
            if question in asked:  # Naukri asked again: the answer wasn't accepted
                return Outcome("needs_you", f"Naukri didn't accept my answer to: {question}", filled=filled,
                               proof=await page.screenshot(full_page=True))
            asked.add(question)
            radios = page.locator(f"{DRAWER} input[type=radio], {DRAWER} input[type=checkbox]")
            options = []
            for i in range(await radios.count()):
                rid = await radios.nth(i).get_attribute("id")
                lab = page.locator(f"{DRAWER} label[for='{rid}']") if rid else None
                options.append((await lab.inner_text()).strip() if lab is not None and await lab.count() else await radios.nth(i).get_attribute("value"))
            kind = "radio" if options else "text"
            f = FormField(label=question, kind=kind, options=options, required=True)
            res = await answers.resolve(f, ctx)
            if res.action == "essay":
                res.kind, res.action = "text", "ask"
            if res.action != "fill":
                return Outcome("waiting", "A question needs your answer.", questions=[res], filled=filled)
            if options:
                idx = options.index(res.fill) if res.fill in options else 0
                await radios.nth(idx).evaluate("el => el.click()")
            else:
                box = page.locator(f"{DRAWER} .textArea[contenteditable=true], {DRAWER} input[type=text], {DRAWER} textarea").last
                await box.click()
                await box.fill(str(res.fill)) if await box.evaluate("el => el.tagName !== 'DIV'") else await page.keyboard.type(str(res.fill))
            answers.mark_used(res.answer_id)
            filled.append({"question": question, "answer": res.fill, "from": res.source})
            await page.locator(f"{DRAWER} .sendMsg").first.click()
            await settle(page, 1200)
        return Outcome("needs_you", "Naukri kept asking questions.", filled=filled, proof=await page.screenshot(full_page=True))
