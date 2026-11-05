"""Applying to jobs end to end, on a fake copy of each kind of site (nothing real is ever submitted)."""

import pytest

pytest.importorskip("playwright.async_api")

from sqlmodel import delete  # noqa: E402

from openhunt import store  # noqa: E402
from openhunt.apply import answers, browser  # noqa: E402
from openhunt.apply.adapters import GENERIC  # noqa: E402
from openhunt.apply.adapters.ats import Ashby, Greenhouse, Lever  # noqa: E402
from openhunt.apply.adapters.linkedin import LinkedInEasyApply  # noqa: E402
from openhunt.apply.adapters.naukri import Naukri  # noqa: E402
from openhunt.apply.browser import BROWSER  # noqa: E402
from openhunt.apply.engine import Job, apply  # noqa: E402
from openhunt.apply.sites import LinkedIn  # noqa: E402
from openhunt.apply.sites import Naukri as NaukriSite  # noqa: E402
from openhunt.store import Answer  # noqa: E402
from tests import fakesite  # noqa: E402

store.init_db()

PROFILE = {
    "name": "Asha Kumar", "email": "asha@example.com", "phone": "+91 98765 43210",
    "linkedin": "https://linkedin.com/in/asha-k", "skills": ["SQL", "Python"], "skill_years": {"SQL": 3, "Python": 3},
    "years_experience": 3, "current_company": "Zeta", "languages": ["English"], "city": "Bangalore",
    "raw_text": "Asha Kumar, Data Analyst at Zeta. SQL, Python.",
}


@pytest.fixture(scope="module")
def site_url():
    url, server = fakesite.start()
    yield url
    server.shutdown()


@pytest.fixture(autouse=True)
async def setup(tmp_path, monkeypatch):
    with store.session() as s:
        s.exec(delete(Answer))
        s.commit()
    cv = tmp_path / "Asha_CV.pdf"
    cv.write_bytes(b"%PDF-1.4 fake cv")
    store.put("profile", PROFILE)
    store.put("prefs", {"titles": ["Data Analyst"], "locations": ["Bangalore"], "min_salary": "12 LPA"})
    store.put("cv_file", str(cv))
    store.delete("ai_provider")
    fakesite.SUBMISSIONS.clear()

    async def essay(question, job, profile, words=120):
        return f"I'd love to join {job['company']} because my SQL and Python work fits this role."

    monkeypatch.setattr("openhunt.apply.engine.write_essay", essay)
    for site in ("fake-gh", "fake-lever", "fake-ashby", "fake-generic", "linkedin", "naukri"):
        browser.forget_state(site)
    yield
    await BROWSER.close()


async def run(site_url, adapter, path, name, dry_run=False, **job):
    async with BROWSER.page(name, site_url) as page:
        return await apply(page, adapter, Job(url=site_url + path, title=job.get("title", "Data Analyst"), company=job.get("company", "Acme"),
                                              description="SQL and Python", site=job.get("site", "")), dry_run=dry_run)


async def test_greenhouse_asks_only_the_unknown_question_then_submits(site_url):
    out = await run(site_url, Greenhouse(), "/gh/acme/jobs/1", "fake-gh")
    # Everything else comes from the CV and defaults; both unknown questions are asked together, once.
    # Work authorization is sensitive and not in the CV, so it's asked, never guessed.
    assert out.status == "waiting"
    assert [q.title for q in out.questions] == ["Allowed to work in India", "Do you have a valid driver's license?"]
    for q in out.questions:
        answers.remember(q.key, {"t": "bool", "v": True}, title=q.title)

    out = await run(site_url, Greenhouse(), "/gh/acme/jobs/1", "fake-gh")
    assert out.status == "submitted", out.message
    sent = fakesite.SUBMISSIONS["greenhouse"][0]
    assert sent["first_name"] == "Asha" and sent["last_name"] == "Kumar" and sent["email"] == "asha@example.com"
    assert sent["resume"].startswith("file:Asha_CV.pdf") and sent["q_sql_years"] == "2-4" and sent["q_auth"] == "1"
    assert sent["q_license"] == "Yes" and "SQL and Python" in sent["q_why"] and sent["gender"] == "Decline To Self Identify"
    assert sent["q_linkedin"] == "https://linkedin.com/in/asha-k"
    assert out.proof and out.proof.startswith(b"\x89PNG")
    assert {f["question"] for f in out.filled} >= {"First Name", "Why do you want to work at Acme?"}


async def test_dry_run_fills_but_never_submits(site_url):
    answers.remember("q:driver license valid", {"t": "bool", "v": True})
    answers.remember("work_authorized:india", {"t": "bool", "v": True})
    out = await run(site_url, Greenhouse(), "/gh/acme/jobs/1", "fake-gh", dry_run=True)
    assert out.status == "ready" and not fakesite.SUBMISSIONS.get("greenhouse")


async def test_lever_job_page_goes_to_the_form(site_url):
    answers.remember("notice_period", {"t": "days", "v": 30})
    out = await run(site_url, Lever(), "/lever/acme/1", "fake-lever")
    assert out.status == "waiting" and out.questions[0].key == "relocate"
    answers.remember("relocate", {"t": "bool", "v": True})
    out = await run(site_url, Lever(), "/lever/acme/1", "fake-lever")
    assert out.status == "submitted", out.message
    sent = fakesite.SUBMISSIONS["lever"][0]
    assert sent["name"] == "Asha Kumar" and sent["cards[abc][field0]"] == "Yes" and sent["cards[abc][field1]"] == "1 month"
    assert sent["org"] == "Zeta" and sent["eeo[gender]"] == "Decline to self-identify" and sent["resume"].startswith("file:")
    assert "cards[abc][field2]" not in sent  # optional and unknown: left empty, nobody asked


async def test_ashby_buttons_and_city_search(site_url):
    answers.remember("needs_sponsorship", {"t": "bool", "v": False})
    out = await run(site_url, Ashby(), "/ashby/acme/1", "fake-ashby")
    assert out.status == "submitted", out.message
    sent = fakesite.SUBMISSIONS["ashby"][0]
    assert sent == {"name": "Asha Kumar", "email": "asha@example.com", "years": "3", "resume": "Asha_CV.pdf",
                    "visa": "No", "location": "Bengaluru, Karnataka, India"}


async def test_generic_site_clicks_apply_and_asks_what_the_form_forgot_to_mark(site_url):
    answers.remember("consent", {"t": "bool", "v": True})
    out = await run(site_url, GENERIC, "/careers/job/1", "fake-generic", company="Globex")
    # "Preferred working hours" isn't marked required, but the site refuses without it: asked.
    assert out.status == "waiting" and out.questions[0].title == "Preferred working hours"
    answers.remember(out.questions[0].key, {"t": "text", "v": "9 to 6 IST"})
    out = await run(site_url, GENERIC, "/careers/job/1", "fake-generic", company="Globex")
    assert out.status == "submitted", out.message
    sent = fakesite.SUBMISSIONS["generic"][0]
    assert sent["full_name"] == "Asha Kumar" and sent["phone"] == "+91 98765 43210" and sent["hours"] == "9 to 6 IST"
    assert sent["privacy"] == "1" and "Globex" in sent["cover"]  # optional cover letter: written anyway, it helps


async def test_linkedin_easy_apply_steps_and_no_company_follow(site_url, monkeypatch):
    monkeypatch.setitem(__import__("openhunt.apply.sites", fromlist=["SITES"]).SITES, "linkedin", LinkedIn(base=site_url))
    async with BROWSER.page("linkedin", site_url) as page:
        await page.context.add_cookies([{"name": "li_at", "value": "ok", "url": site_url}])
    answers.remember("onsite", {"t": "bool", "v": True})
    answers.remember("language:english", {"t": "text", "v": "Professional"})
    answers.remember("years_with:python", {"t": "num", "v": 2.5})  # LinkedIn wants whole numbers
    out = await run(site_url, LinkedInEasyApply(), "/jobs/view/1/", "linkedin", site="linkedin")
    assert out.status == "submitted", (out.message, [(q.title, q.key, q.field) for q in out.questions])
    assert fakesite.SUBMISSIONS["linkedin"][0] == {"phone": "+91 98765 43210", "code": "India (+91)", "resume": "Asha_CV.pdf",
                                                   "python": "2", "commute": "Yes", "english": "Professional", "follow": False}


async def test_linkedin_needs_login_first(site_url, monkeypatch):
    monkeypatch.setitem(__import__("openhunt.apply.sites", fromlist=["SITES"]).SITES, "linkedin", LinkedIn(base=site_url))
    out = await run(site_url, LinkedInEasyApply(), "/jobs/view/1/", "linkedin")
    assert out.status == "needs_login"


async def test_linkedin_outside_apply_redirects_to_the_company_site(site_url, monkeypatch):
    monkeypatch.setitem(__import__("openhunt.apply.sites", fromlist=["SITES"]).SITES, "linkedin", LinkedIn(base=site_url))
    async with BROWSER.page("linkedin", site_url) as page:
        await page.context.add_cookies([{"name": "li_at", "value": "ok", "url": site_url}])
    out = await run(site_url, LinkedInEasyApply(), "/jobs/view/2/", "linkedin")
    assert out.status == "redirect" and out.redirect.endswith("/gh/acme/jobs/1")


async def test_naukri_question_chat(site_url, monkeypatch):
    sites = __import__("openhunt.apply.sites", fromlist=["SITES"]).SITES
    monkeypatch.setitem(sites, "naukri", NaukriSite(base=site_url))
    monkeypatch.setattr(NaukriSite, "has_session", lambda self, page: _true())
    answers.remember("relocate", {"t": "bool", "v": True})
    out = await run(site_url, Naukri(), "/naukri/job-listings-1", "naukri", site="naukri")
    assert out.status == "waiting" and out.questions[0].key == "current_salary:inr"  # salary: always the user's own answer
    answers.remember("current_salary:inr", {"t": "money", "v": 900000, "cur": "INR"})
    out = await run(site_url, Naukri(), "/naukri/job-listings-1", "naukri", site="naukri")
    assert out.status == "submitted", out.message
    assert fakesite.SUBMISSIONS["naukri"][0] == {
        "How many years of experience do you have in Python?": "3",
        "Are you willing to relocate to Bangalore?": "Yes",
        "What is your current CTC in lakhs?": "9",
    }


async def _true():
    return True
