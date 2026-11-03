"""Autopilot: the queue, its limits, and the full loop on a fake site (bot/autopilot.py, apply/queue.py)."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import delete

from openhunt import store
from openhunt.apply import answers, queue
from openhunt.store import Answer, Application, Job, Match, PendingQuestion

store.init_db()

PROFILE = {"name": "Asha Kumar", "email": "asha@example.com", "phone": "+91 98765 43210", "skills": ["SQL"],
           "skill_years": {"SQL": 3}, "linkedin": "https://linkedin.com/in/asha", "raw_text": "Asha Kumar SQL"}


@pytest.fixture(autouse=True)
def clean(tmp_path):
    with store.session() as s:
        for table in (Application, Match, PendingQuestion, Answer, Job):
            s.exec(delete(table))
        s.commit()
    for key in ("autopilot", "sites_paused", "typing_q", "sites"):
        store.delete(key)
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    store.put("cv_file", str(cv))
    store.put("profile", PROFILE)
    store.put("prefs", {"titles": ["Data Analyst"], "locations": ["Bangalore"]})
    store.put("allowed_chats", [1])
    yield


def add_job(url, apply_url="", title="Data Analyst", company="Acme", score=None, source="linkedin") -> tuple[int, int | None]:
    with store.session() as s:
        job = Job(fingerprint=url, source=source, url=url, apply_url=apply_url, title=title, company=company, description="SQL")
        s.add(job)
        s.commit()
        s.refresh(job)
        mid = None
        if score is not None:
            m = Match(job_id=job.id, score=score, status="notified")
            s.add(m)
            s.commit()
            s.refresh(m)
            mid = m.id
        return job.id, mid


# ---------- choosing where to apply ----------

def test_company_link_beats_linkedin_and_blocked_boards_are_left_to_the_user():
    j = Job(fingerprint="a", source="linkedin", url="https://www.linkedin.com/jobs/view/123456789/", title="x",
            apply_url="https://boards.greenhouse.io/acme/jobs/1")
    assert queue.choose_target(j) == ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse")
    j = Job(fingerprint="b", source="indeed", url="https://in.indeed.com/viewjob?jk=1", title="x", apply_url="https://jobs.lever.co/acme/1")
    assert queue.choose_target(j) == ("https://jobs.lever.co/acme/1", "lever")
    j = Job(fingerprint="c", source="indeed", url="https://in.indeed.com/viewjob?jk=2", title="x")
    assert queue.choose_target(j) == ("", "")
    j = Job(fingerprint="d", source="linkedin", url="https://www.linkedin.com/jobs/view/123456789/", title="x")
    assert queue.choose_target(j) == (j.url, "linkedin")


def test_enqueue_never_twice_and_manual_retry_of_failed():
    job_id, _ = add_job("https://boards.greenhouse.io/acme/jobs/1")
    first = queue.enqueue(job_id)
    assert first.status == "queued" and first.site == "greenhouse"
    assert queue.enqueue(job_id).id == first.id
    queue.set_status(first.id, "failed", attempts=3)
    again = queue.enqueue(job_id, "manual")
    assert again.status == "queued" and again.attempts == 0 and again.source == "manual"
    blocked, _ = add_job("https://in.indeed.com/viewjob?jk=9")
    assert queue.enqueue(blocked).status == "unsupported"


def test_next_ready_order_hours_and_daily_limits():
    a, _ = add_job("https://boards.greenhouse.io/acme/jobs/1")
    b, _ = add_job("https://boards.greenhouse.io/acme/jobs/2")
    auto = queue.enqueue(a, "auto")
    noon, night = datetime.now().replace(hour=12), datetime.now().replace(hour=23)
    assert queue.next_ready(noon) is None  # Autopilot is off
    queue.update(on=True)
    assert queue.next_ready(noon).id == auto.id
    assert queue.next_ready(night) is None  # outside active hours
    manual = queue.enqueue(b, "manual")
    assert queue.next_ready(night).id == manual.id  # the user's own request goes any time
    queue.set_status(manual.id, "submitted", submitted_at=store.utcnow())
    queue.update(caps={"greenhouse": 1})
    assert queue.next_ready(noon) is None  # daily limit reached
    queue.update(caps={"greenhouse": 5})
    queue.pause_site("greenhouse", 1)
    assert queue.next_ready(noon) is None


def test_failed_jobs_wait_before_retrying():
    a, _ = add_job("https://boards.greenhouse.io/acme/jobs/1")
    app = queue.enqueue(a)
    queue.update(on=True)
    queue.set_status(app.id, "queued", attempts=1)
    assert queue.next_ready(datetime.now().replace(hour=12)) is None
    with store.session() as s:
        row = s.get(Application, app.id)
        row.updated_at = store.utcnow() - timedelta(hours=3)
        s.add(row)
        s.commit()
    assert queue.next_ready(datetime.now().replace(hour=12)).id == app.id


# ---------- Telegram side ----------

class FakeBot:
    def __init__(self):
        self.sent, self.photos, self.n = [], [], 0

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None, **kw):
        self.n += 1
        self.sent.append(SimpleNamespace(text=text, markup=reply_markup, message_id=self.n))
        return SimpleNamespace(message_id=self.n)

    async def send_photo(self, chat_id, photo, caption="", reply_markup=None, **kw):
        self.photos.append((caption, reply_markup))

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.sent.append(SimpleNamespace(text=text, markup=kw.get("reply_markup"), message_id=0))

    def texts(self):
        return "\n".join(m.text for m in self.sent)

    def buttons(self):
        out = {}
        for m in self.sent:
            if m.markup:
                out.update({b.text: (b.callback_data or b.url) for row in m.markup.inline_keyboard for b in row})
        return out


def test_hunt_results_are_queued_above_the_autopilot_score():
    from openhunt.bot import autopilot

    queue.update(on=True, min_score=70)
    _, good = add_job("https://jobs.lever.co/acme/1", score=85)
    _, meh = add_job("https://jobs.lever.co/acme/2", score=65)
    _, blocked = add_job("https://in.indeed.com/viewjob?jk=1", score=90, source="indeed")
    queued, manual = autopilot.queue_matches([good, meh, blocked])
    assert queued == [good] and manual == [blocked]


async def test_pasted_link_is_applied_to():
    from openhunt.bot import autopilot

    replies = []

    async def reply_text(t):
        replies.append(t)

    update = SimpleNamespace(message=SimpleNamespace(text="please apply https://jobs.lever.co/acme/abc-1 thanks", reply_text=reply_text))
    assert await autopilot.handle_link(update, None)
    app = queue.recent(1)[0]
    assert app.url == "https://jobs.lever.co/acme/abc-1" and app.site == "lever" and app.source == "manual" and app.company == "Acme"
    assert "Applying now" in replies[0]
    update.message.text = "no link here"
    assert not await autopilot.handle_link(update, None)


async def test_linkedin_job_without_login_asks_to_log_in_once():
    from openhunt.bot import autopilot

    autopilot._state["login_nag"].clear()
    job_id, _ = add_job("https://www.linkedin.com/jobs/view/123456789/")
    bot = FakeBot()
    app = queue.enqueue(job_id, "manual")
    await autopilot.process(bot, app.id)
    assert queue.get(app.id).status == "needs_login"
    assert "🔐 Log in to LinkedIn" in bot.buttons()
    job2, _ = add_job("https://www.linkedin.com/jobs/view/987654321/")
    await autopilot.process(bot, queue.enqueue(job2, "manual").id)
    assert bot.texts().count("Log in once") == 1  # not nagged twice
    assert queue.requeue_for_site("linkedin") == 2


async def test_show_applications_and_summary():
    from openhunt.bot import autopilot

    a, _ = add_job("https://jobs.lever.co/acme/1", title="Data Analyst", company="Acme")
    b, _ = add_job("https://in.indeed.com/viewjob?jk=3", title="BI Analyst", company="Beta", source="indeed")
    app = queue.enqueue(a, "manual")
    queue.set_status(app.id, "submitted", submitted_at=store.utcnow())
    queue.enqueue(b)
    bot = FakeBot()
    await autopilot.show_applications(bot, 1)
    assert "✅ Data Analyst · Acme" in bot.texts() and "🔗 BI Analyst · Beta" in bot.texts()
    assert any(k.startswith("🔗 Apply yourself") for k in bot.buttons())
    await autopilot.daily_summary(SimpleNamespace(bot=bot))
    assert "✅ 1 applied" in bot.texts() and "🔗 1 to apply yourself" in bot.texts()


# ---------- the whole loop on the fake site ----------

@pytest.fixture
def fake_site():
    pytest.importorskip("playwright.async_api")
    from tests import fakesite

    url, server = fakesite.start()
    fakesite.SUBMISSIONS.clear()
    yield url, fakesite
    server.shutdown()


async def test_full_loop_question_answer_resume_submit(fake_site, monkeypatch):
    from openhunt.apply.browser import BROWSER
    from openhunt.bot import apply_flow, autopilot

    url, fakesite = fake_site

    async def essay(question, job, profile, words=120):
        return "My SQL work fits Acme."

    monkeypatch.setattr("openhunt.apply.engine.write_essay", essay)
    answers.remember("work_authorized:india", {"t": "bool", "v": True})
    job_id, mid = add_job(url + "/gh/acme/jobs/1", score=88, source="greenhouse:acme")
    bot = FakeBot()
    try:
        await autopilot.apply_match(bot, 1, mid)
        assert "On it" in bot.texts()
        app = queue.next_ready()
        await autopilot.process(bot, app.id)
        assert queue.get(app.id).status == "waiting"
        question = next(m for m in bot.sent if "driver" in m.text)
        assert "Acme" in question.text

        # The user taps "Yes": the job goes straight back in the queue and is submitted.
        yes = next(b.callback_data for row in question.markup.inline_keyboard for b in row if b.text == "Yes")
        tapped = SimpleNamespace(data=yes, message=SimpleNamespace(chat=SimpleNamespace(id=1)),
                                 edit_message_reply_markup=_noop, edit_message_text=_noop)
        await apply_flow.handle_button(SimpleNamespace(callback_query=tapped), SimpleNamespace(bot=bot))
        nxt = queue.next_ready(datetime.now().replace(hour=23))  # even late at night: the user is here
        assert nxt and nxt.id == app.id
        await autopilot.process(bot, app.id)
    finally:
        await BROWSER.close()
    done = queue.get(app.id)
    assert done.status == "submitted" and done.proof_path.endswith(".png")
    assert fakesite.SUBMISSIONS["greenhouse"][0]["q_license"] == "Yes"
    assert "✅ Applied: <b>Data Analyst</b> · Acme" in bot.texts()
    with store.session() as s:
        assert s.get(Match, mid).status == "applied"
    filled = json.loads(done.answers)
    assert any(f["question"] == "First Name" and f["answer"] == "Asha" for f in filled)

    sent = []

    class ProofBot(FakeBot):
        async def send_photo(self, chat_id, photo, caption="", **kw):
            sent.append(caption)

    await autopilot.send_proof(ProofBot(), 1, app.id)
    assert "First Name: Asha" in sent[0]


async def _noop(*a, **kw):
    return None


def test_tapping_apply_on_an_autopilot_job_makes_it_go_now():
    job_id, _ = add_job("https://jobs.lever.co/acme/7")
    queue.update(on=True)
    auto = queue.enqueue(job_id, "auto")
    late = datetime.now().replace(hour=23)
    assert queue.next_ready(late) is None
    assert queue.enqueue(job_id, "manual").source == "manual"
    assert queue.next_ready(late).id == auto.id


def test_generated_cv_when_the_user_never_sent_one(tmp_path):
    from pypdf import PdfReader

    from openhunt.apply.answers import resolve_known
    from openhunt.apply.fields import FormField

    store.delete("cv_file")
    path = resolve_known(FormField("Resume/CV", "file", required=True)).fill
    assert path and path.endswith("Asha_Kumar_CV.pdf") and store.get("cv_generated")
    assert "Asha Kumar" in PdfReader(path).pages[0].extract_text()
