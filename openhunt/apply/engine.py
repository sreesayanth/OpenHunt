"""Apply to one job: open the form, answer every question from memory, submit, keep proof.

For each page of the form:
  read the questions → answer from memory (answers.py) → AI writes essay answers →
  anything unknown → stop and ask the user (the job waits, others continue) → fill → next/submit.
A form that complains after submit ("this field is required") is read again, so a question the
site forgot to mark as required is still answered or asked.
"""

import logging
import re
from dataclasses import dataclass, field

from openhunt import store
from openhunt.apply import answers, forms
from openhunt.apply.adapters.base import Adapter
from openhunt.apply.answers import Context, Resolution
from openhunt.apply.essay import write_essay

log = logging.getLogger(__name__)

MAX_STEPS = 15


@dataclass
class Outcome:
    status: str  # submitted | waiting | needs_login | needs_you | closed | already | unsupported | failed | ready (dry run)
    message: str = ""
    questions: list[Resolution] = field(default_factory=list)
    filled: list[dict] = field(default_factory=list)
    proof: bytes | None = None
    redirect: str = ""  # the job is applied to on another site (e.g. LinkedIn → company site)
    page_title: str = ""  # the job title as the page shows it (for links the user pasted)


@dataclass
class Job:
    url: str
    title: str = ""
    company: str = ""
    description: str = ""
    site: str = ""  # where the job was found (linkedin, naukri…), used for "How did you hear about us?"


async def fill_page(page, adapter: Adapter, job: Job, essays: dict[str, str]) -> tuple[list[dict], list[Resolution]]:
    """Answer everything on the current page. Returns (what was filled, questions for the user)."""
    ctx = Context(company=job.company, job_title=job.title, site=job.site or adapter.name)
    raws = await forms.read_form(page, adapter.form_scope, adapter.button_groups)
    filled: list[dict] = []
    missing: list[Resolution] = []
    for raw in raws:
        if raw.value and not raw.invalid:
            continue  # already answered (by the site, or by us on an earlier pass)
        f = raw.to_field()
        if raw.invalid and raw.value:
            fixed = _fix_invalid(raw.value)
            if fixed is not None:
                await forms.fill(page, raw, fixed)
                continue
        res = await answers.resolve(f, ctx)
        value = res.fill
        if res.action == "essay":
            value = essays.get(f.label)
            if value is None:
                try:
                    value = await write_essay(f.label, {"title": job.title, "company": job.company, "description": job.description},
                                              answers.profile())
                except Exception as exc:  # noqa: BLE001 - AI down: optional essays are skipped, required ones asked
                    log.info("Essay failed: %s", exc)
                    value = None
                if value:
                    essays[f.label] = value
            if not value:
                if f.required:
                    res.kind, res.action = "text", "ask"
                    missing.append(res)
                continue
        elif res.action == "skip":
            continue
        elif res.action == "ask":
            missing.append(res)
            continue
        try:
            await forms.fill(page, raw, value)
        except Exception as exc:  # noqa: BLE001 - the site didn't accept it: ask the user instead
            log.info("Couldn't fill %r: %s", f.label, exc)
            if f.required:
                res.action = "ask"
                missing.append(res)
            continue
        answers.mark_used(res.answer_id)
        filled.append({"question": f.label, "answer": value if not isinstance(value, bool) else ("Yes" if value else "No"),
                       "from": "ai essay" if res.action == "essay" else res.source})
    return filled, missing


def _fix_invalid(value: str) -> str | None:
    """Small fixes a site asks for, e.g. 'Enter a whole number' when we typed 2.5."""
    if re.fullmatch(r"\d+\.\d+", value.strip()):
        return str(round(float(value)))
    return None


async def _signature(page, adapter: Adapter) -> str:
    raws = await forms.read_form(page, adapter.form_scope, adapter.button_groups)
    return page.url + "|" + "|".join(f"{r.label}={r.value}" for r in raws)


async def apply(page, adapter: Adapter, job: Job, dry_run: bool = False) -> Outcome:
    """Apply to `job` in `page`. With dry_run, everything is filled but the last button isn't pressed."""
    if adapter.login_site:
        from openhunt.apply.sites import SITES

        site = SITES[adapter.login_site]
        if not await site.has_session(page):
            return Outcome("needs_login", f"I need to be logged in to {site.label}.")
    opened = await adapter.open(page, job.url)
    if isinstance(opened, str):
        if opened.startswith("redirect:"):
            return Outcome("redirect", redirect=opened.removeprefix("redirect:"))
        return Outcome(opened, {"closed": "The job is closed.", "already": "You already applied to this job.",
                                "unsupported": "I couldn't find an application form on this page.",
                                "needs_login": "I need to be logged in."}.get(opened, opened))
    page = opened
    page_title = await _page_title(page)
    if not job.description:  # a pasted link: the page itself describes the job (used for essay answers)
        job.description = (await adapter.body(page))[:6000]
    if not job.title or job.title == "Job you sent":
        job.title = page_title or job.title
    if hasattr(adapter, "run"):  # sites with their own flow (e.g. Naukri's question chat)
        out = await adapter.run(page, job, dry_run)
        out.page_title = page_title
        return out
    out = await _steps(page, adapter, job, dry_run)
    out.page_title = page_title
    return out


async def _page_title(page) -> str:
    try:
        h1 = page.locator("h1:visible").first
        text = (await h1.inner_text(timeout=2000)).strip() if await h1.count() else ""
        text = text or (await page.title()).strip()
    except Exception:  # noqa: BLE001
        return ""
    text = re.sub(r"^(?:apply(?: for)?|job application for)[:\s]+", "", text, flags=re.I)
    return re.split(r"\s+(?:at|@|\||-|–)\s+", text)[0][:80]


async def _steps(page, adapter: Adapter, job: Job, dry_run: bool) -> Outcome:
    essays: dict[str, str] = {}
    all_filled: list[dict] = []
    stuck = 0
    submitted = False
    for _ in range(MAX_STEPS):
        filled, missing = await fill_page(page, adapter, job, essays)
        all_filled.extend(filled)
        if missing:
            return Outcome("waiting", f"{len(missing)} question(s) need your answer.", questions=_unique(missing), filled=all_filled)
        if dry_run and await adapter.is_final_step(page):
            return Outcome("ready", "Everything is filled in. (Test run: not submitted.)", filled=all_filled,
                           proof=await page.screenshot(full_page=True))
        before = await _signature(page, adapter)
        moved = await adapter.next(page)
        if not moved:
            return Outcome("needs_you", "I couldn't find the button to continue.", filled=all_filled,
                           proof=await page.screenshot(full_page=True))
        submitted = submitted or moved == "submit"
        state = await adapter.state(page, after_submit=submitted)
        if state == "done":
            return Outcome("submitted", filled=all_filled, proof=await page.screenshot(full_page=True))
        if state in ("closed", "already"):
            return Outcome(state, filled=all_filled)
        if await _signature(page, adapter) == before:
            stuck += 1
            if stuck >= 2:
                errors = await forms.page_errors(page, adapter.form_scope)
                return Outcome("needs_you", "The form won't go on" + (f": {'; '.join(errors[:3])}" if errors else "."),
                               filled=all_filled, proof=await page.screenshot(full_page=True))
        else:
            stuck = 0
    return Outcome("needs_you", "The form has too many steps.", filled=all_filled, proof=await page.screenshot(full_page=True))


def _unique(missing: list[Resolution]) -> list[Resolution]:
    seen, out = set(), []
    for r in missing:
        if (r.key, r.company) not in seen:
            seen.add((r.key, r.company))
            out.append(r)
    return out


def save_proof(application_id: int, png: bytes | None) -> str:
    if not png:
        return ""
    return store.save_file(f"application-{application_id}.png", png, folder="proof")
