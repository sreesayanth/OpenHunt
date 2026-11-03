"""Answer memory: ask once, fill every later form (openhunt/apply and bot/apply_flow.py)."""

import json
from types import SimpleNamespace

import pytest
from sqlmodel import delete

from openhunt import store
from openhunt.apply import answers, values
from openhunt.apply.answers import Context, resolve, resolve_known
from openhunt.apply.fields import FormField as F
from openhunt.apply.intents import question_key, recognize
from openhunt.bot import apply_flow
from openhunt.store import Answer, PendingQuestion

store.init_db()

PROFILE = {
    "name": "Asha Kumar",
    "raw_text": "Asha Kumar · asha@example.com · +91 98765 43210 · linkedin.com/in/asha-k\n"
                "Data Analyst at Zeta 2021-2024. SQL, Python, Power BI.",
    "skills": ["SQL", "Python", "Power BI"],
    "skill_years": {"Python": 3, "MS Excel": 4},
    "years_experience": 3,
    "highest_degree": "B.Tech in Computer Science",
    "current_company": "Zeta",
}


@pytest.fixture(autouse=True)
def clean():
    with store.session() as s:
        s.exec(delete(Answer))
        s.exec(delete(PendingQuestion))
        s.commit()
    for key in ("profile", "prefs", "typing_q", "answer_undo", "cv_file", "ai_provider", "allowed_chats"):
        store.delete(key)
    store.put("profile", PROFILE)
    store.put("prefs", {"titles": ["Data Analyst"], "locations": ["Bangalore"], "min_salary": "8 LPA"})
    apply_flow.ANSWER_LISTENERS.clear()
    yield


# ---------- recognising questions ----------

def test_same_question_in_many_wordings_has_one_key():
    wordings = [
        ("How many years of experience do you have with Tableau?", "number"),
        ("Tableau experience (years)", "text"),
        ("How long have you used Tableau?", "select"),
        ("How many years of Tableau experience do you have?", "number"),
        ("How many years of work experience do you have using Tableau in a production environment?", "number"),
    ]
    assert {recognize(q, k).key for q, k in wordings} == {"years_with:tableau"}
    assert recognize("How many years of work experience do you have?", "number").key == "years_total"
    assert recognize("Microsoft Excel experience (years)", "number").key == "years_with:excel"


def test_job_relative_questions_are_kept_per_job_title():
    rec = recognize("How many years of experience do you have in a similar role?", "number", job_title="Data Analyst")
    assert rec.key == "years_with:role:data analyst"


def test_country_matters_for_work_rights():
    assert recognize("Are you legally authorized to work in the United States?", "radio").key == "work_authorized:us"
    assert recognize("Are you authorised to work in the UK?", "radio").key == "work_authorized:uk"


def test_other_questions_get_a_wording_insensitive_key():
    assert question_key("Do you have a valid driver's license?") == question_key("Do you have a valid drivers license")
    assert question_key("Are you willing to work night shifts?") != question_key("Are you willing to work weekend shifts?")


# ---------- fitting one answer to any form ----------

@pytest.mark.parametrize("value,field,expected", [
    ({"t": "num", "v": 3}, F("Years", "number"), "3"),
    ({"t": "num", "v": 3}, F("Years", "select", ["Select an option", "0-1 years", "2-4 years", "5+ years"]), "2-4 years"),
    ({"t": "num", "v": 7}, F("Years", "radio", ["Less than 1 year", "1-3 years", "More than 5 years"]), "More than 5 years"),
    ({"t": "bool", "v": False}, F("Q", "radio", ["Yes, I am", "No, I am not"]), "No, I am not"),
    ({"t": "bool", "v": True}, F("I agree", "checkbox"), True),
    ({"t": "money", "v": 1200000, "cur": "INR"}, F("Expected CTC (in LPA)", "number"), "12"),
    ({"t": "money", "v": 1200000, "cur": "INR"}, F("Expected salary per month", "number"), "100000"),
    ({"t": "money", "v": 1200000, "cur": "INR"}, F("Expected CTC", "select", ["5-10 LPA", "10-15 LPA", "15+ LPA"]), "10-15 LPA"),
    ({"t": "money", "v": 1200000, "cur": "INR"}, F("Expected salary (USD)", "number"), None),
    ({"t": "days", "v": 45}, F("Notice", "select", ["Immediate", "Less than 30 days", "30-60 days", "60+ days"]), "30-60 days"),
    ({"t": "days", "v": 30}, F("Notice period (months)", "number"), "1"),
    ({"t": "decline"}, F("Gender", "select", ["Male", "Female", "I don't wish to answer"]), "I don't wish to answer"),
    ({"t": "degree", "v": "master"}, F("Education", "select", ["Diploma", "B.Tech", "M.Tech", "PhD"]), "M.Tech"),
    ({"t": "text", "v": "Bangalore"}, F("City", "select", ["Bengaluru, Karnataka", "Mumbai"]), "Bengaluru, Karnataka"),
    ({"t": "choices", "v": ["LinkedIn", "Job board"]}, F("Source", "select", ["Referral", "Job Board", "Other"]), "Job Board"),
])
def test_fit(value, field, expected):
    assert values.fit(value, field) == expected


def test_parse_replies():
    assert values.parse_money("12 LPA") == {"t": "money", "v": 1200000, "cur": "INR"}
    assert values.parse_money("$60k")["v"] == 60000 and values.parse_money("$60k")["cur"] == "USD"
    assert values.parse_money("80000 per month")["v"] == 960000
    assert values.parse_days("2 weeks") == 14 and values.parse_days("immediately") == 0
    assert values.parse_reply("bool", "No, I don't") == {"t": "bool", "v": False}
    assert values.parse_reply("num", "about 3 years") == {"t": "num", "v": 3.0}
    assert values.parse_reply("num", "lots") is None


# ---------- resolving from the CV, defaults and memory ----------

def test_cv_facts_fill_contact_and_experience_fields():
    ctx = Context(company="Razorpay", job_title="Data Analyst", site="linkedin")
    fill = lambda f: resolve_known(f, ctx).fill  # noqa: E731
    assert fill(F("First name", "text", required=True)) == "Asha"
    assert fill(F("Last name", "text", required=True)) == "Kumar"
    assert fill(F("Email address", "email", required=True)) == "asha@example.com"
    assert fill(F("Mobile phone number", "tel", required=True)) == "+91 98765 43210"
    assert fill(F("Phone country code", "select", ["United States (+1)", "India (+91)"], required=True)) == "India (+91)"
    assert fill(F("LinkedIn profile", "url")) == "https://linkedin.com/in/asha-k"
    assert fill(F("How many years of experience do you have with Python?", "number", required=True)) == "3"
    assert fill(F("Excel experience (years)", "select", ["0-2", "3-5", "6+"], required=True)) == "3-5"
    assert fill(F("Do you have experience with Power BI?", "radio", ["Yes", "No"], required=True)) == "Yes"
    assert fill(F("Have you completed the following level of education: Master's Degree?", "radio", ["Yes", "No"], required=True)) == "No"
    assert fill(F("Highest level of education", "select", ["High school", "Bachelor's", "Master's"], required=True)) == "Bachelor's"
    assert fill(F("Current location", "text", required=True)) == "Bangalore"
    assert fill(F("Expected CTC (LPA)", "number", required=True)) == "8"


def test_safe_defaults():
    ctx = Context(company="Razorpay", site="linkedin")
    assert resolve_known(F("Gender", "select", ["Male", "Female", "Prefer not to say"], required=True), ctx).fill == "Prefer not to say"
    assert resolve_known(F("How did you hear about us?", "select", ["LinkedIn", "Referral"], required=True), ctx).fill == "LinkedIn"
    assert resolve_known(F("Were you referred by an employee?", "radio", ["Yes", "No"], required=True), ctx).fill == "No"
    assert resolve_known(F("Have you worked at Razorpay before?", "radio", ["Yes", "No"], required=True), ctx).fill == "No"


def test_unknown_required_is_asked_optional_is_skipped_essay_is_written():
    q = "Do you have a valid driver's license?"
    assert resolve_known(F(q, "radio", ["Yes", "No"], required=True)).action == "ask"
    assert resolve_known(F(q, "radio", ["Yes", "No"])).action == "skip"
    assert resolve_known(F("Why do you want to work at Razorpay?", "textarea", required=True)).action == "essay"
    # Not in the CV: never guessed, even as "0".
    res = resolve_known(F("How many years of experience do you have with Tableau?", "number", required=True))
    assert res.action == "ask" and res.kind == "num" and res.key == "years_with:tableau"


def test_answered_once_reused_in_every_wording_and_field_type():
    res = resolve_known(F("How many years of experience do you have with Tableau?", "number", required=True))
    answers.remember(res.key, {"t": "num", "v": 2}, title=res.title)
    assert resolve_known(F("Tableau experience (years)", "text", required=True)).fill == "2"
    assert resolve_known(F("How long have you used Tableau?", "select", ["0-1", "2-3", "4+"], required=True)).fill == "2-3"
    assert resolve_known(F("Do you have experience with Tableau?", "radio", ["Yes", "No"], required=True)).fill == "Yes"
    other = F("Do you have a valid driver's license?", "radio", ["Yes", "No"], required=True)
    answers.remember(resolve_known(other).key, {"t": "bool", "v": True}, title=other.label)
    assert resolve_known(F("Do you have a valid drivers license", "select", ["Yes", "No"], required=True)).fill == "Yes"


def test_company_specific_answers_stay_with_that_company():
    f = F("Have you applied to Razorpay in the last 6 months?", "radio", ["Yes", "No"], required=True)
    res = resolve_known(f, Context(company="Razorpay"))
    assert res.company == "razorpay"
    answers.remember(res.key, {"t": "bool", "v": True}, company=res.company)
    assert resolve_known(f, Context(company="Razorpay")).fill == "Yes"
    g = F("Have you applied to Razorpay in the last 6 months?", "radio", ["Yes", "No"], required=True)
    assert resolve_known(g, Context(company="Swiggy")).action == "ask"


def test_salary_in_another_currency_is_asked_and_kept_apart():
    res = resolve_known(F("Expected salary (USD)", "number", required=True))
    assert res.action == "ask" and res.key == "expected_salary:usd"


async def test_ai_only_picks_saved_answers_and_never_for_sensitive_questions(monkeypatch):
    from openhunt.ai import llm

    saved = answers.remember("q:do driving license valid", {"t": "bool", "v": True}, question="Do you have a valid driving license?")
    store.put("ai_provider", "ollama")
    calls = []

    async def fake_chat_json(system, user):
        calls.append(json.loads(user))
        return {"id": saved.id, "confidence": 0.95}

    monkeypatch.setattr(llm, "chat_json", fake_chat_json)
    res = await resolve(F("Do you hold a valid licence to drive?", "radio", ["Yes", "No"], required=True))
    assert res.action == "fill" and res.fill == "Yes" and res.source == "ai"
    assert calls and "valid driving license" in calls[0]["answered"][0]["question"]

    calls.clear()
    res = await resolve(F("Are you legally authorized to work in Canada?", "radio", ["Yes", "No"], required=True))
    assert res.action == "ask" and not calls


async def test_low_confidence_ai_match_asks(monkeypatch):
    from openhunt.ai import llm

    saved = answers.remember("q:do driving license valid", {"t": "bool", "v": True}, question="Do you have a valid driving license?")
    store.put("ai_provider", "ollama")

    async def unsure(system, user):
        return {"id": saved.id, "confidence": 0.6}

    monkeypatch.setattr(llm, "chat_json", unsure)
    assert (await resolve(F("Do you have a driving licence for trucks?", "radio", ["Yes", "No"], required=True))).action == "ask"


# ---------- typed changes ----------

def test_parse_update():
    rec, key, value = answers.parse_update("My notice period is now 15 days")
    assert key == "notice_period" and value == {"t": "days", "v": 15}
    rec, key, value = answers.parse_update("I have 3 years of Tableau experience")
    assert key == "years_with:tableau" and value["v"] == 3
    rec, key, value = answers.parse_update("my expected salary is 15 LPA")
    assert key == "expected_salary:inr" and value["v"] == 1_500_000
    rec, key, value = answers.parse_update("I don't need visa sponsorship")
    assert key == "needs_sponsorship" and value == {"t": "bool", "v": False}
    rec, key, value = answers.parse_update("my phone number is +91 90000 11111")
    assert key == "phone" and value["v"] == "+91 90000 11111"
    assert answers.parse_update("show me jobs in Pune") is None


def test_changed_facts_flow_into_related_fields():
    answers.remember("full_name", {"t": "text", "v": "Asha R Kumar"})
    assert resolve_known(F("Last name", "text", required=True)).fill == "R Kumar"


def test_known_lists_cv_facts_and_saved_answers():
    answers.remember("notice_period", {"t": "days", "v": 30}, title="Notice period")
    items = {k.title: (k.value, k.source) for k in answers.known()}
    assert items["Notice period"] == ("1 month", "chat")
    assert items["Full name"] == ("Asha Kumar", "cv")
    assert items["Years of experience with python"] == ("3", "cv")
    assert items["Expected salary"] == ("8 LPA", "chat")


# ---------- Telegram ----------

class FakeBot:
    def __init__(self):
        self.sent, self.edits, self.n = [], [], 100

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None, **kw):
        self.n += 1
        self.sent.append(SimpleNamespace(chat_id=chat_id, text=text, markup=reply_markup, message_id=self.n))
        return SimpleNamespace(message_id=self.n)

    async def edit_message_text(self, text, chat_id=None, message_id=None, parse_mode=None, **kw):
        self.edits.append(SimpleNamespace(chat_id=chat_id, message_id=message_id, text=text))


def buttons(msg) -> dict[str, str]:
    return {b.text: b.callback_data for row in msg.markup.inline_keyboard for b in row}


def tap(bot, data):
    async def noop(*a, **kw):
        return None

    message = SimpleNamespace(chat=SimpleNamespace(id=1), edit_text=noop)
    query = SimpleNamespace(data=data, message=message, edit_message_reply_markup=noop, edit_message_text=noop)
    return apply_flow.handle_button(SimpleNamespace(callback_query=query), SimpleNamespace(bot=bot))


def typed(bot, text):
    replies = []

    async def reply(t, **kw):
        replies.append(t)

    message = SimpleNamespace(text=text, reply_html=reply, reply_text=reply)
    return apply_flow.handle_text(SimpleNamespace(message=message), SimpleNamespace(bot=bot)), replies


async def test_question_in_chat_answered_once_then_reused():
    store.put("allowed_chats", [1])
    bot, heard = FakeBot(), []

    async def listener(pq, answer):
        heard.append((pq.application_ids, answer and json.loads(answer.value)))

    apply_flow.ANSWER_LISTENERS.append(listener)
    ctx = Context(company="Razorpay", job_title="Data Analyst", site="linkedin")
    f = F("How many years of experience do you have with Tableau?", "number", required=True)

    await apply_flow.ask(bot, resolve_known(f, ctx), ctx, application_id=7)
    # Another job asks the same thing: no second message, both jobs wait on one answer.
    other = Context(company="Swiggy", job_title="BI Analyst", site="naukri")
    await apply_flow.ask(bot, resolve_known(F("Tableau experience (years)", "text", required=True), other), other, application_id=8)
    assert len(bot.sent) == 1
    msg = bot.sent[0]
    assert "Razorpay" in msg.text and "Tableau" in msg.text
    assert {"0", "2", "10+", "⏭ Skip this job"} <= set(buttons(msg))

    await tap(bot, buttons(msg)["2"])
    assert heard == [("[7, 8]", {"t": "num", "v": 2})]
    assert "Saved" in bot.edits[-1].text
    assert resolve_known(F("How long have you used Tableau?", "number", required=True), other).fill == "2"


async def test_questions_come_one_at_a_time_and_typed_answers_work():
    store.put("allowed_chats", [1])
    bot = FakeBot()
    ctx = Context(company="Acme", job_title="Analyst")
    await apply_flow.ask(bot, resolve_known(F("What is the name of your current manager?", "text", required=True), ctx), ctx)
    await apply_flow.ask(bot, resolve_known(F("How many years of experience do you have with Looker?", "number", required=True), ctx), ctx)
    assert len(bot.sent) == 1  # the second waits for the first

    handled, replies = typed(bot, "Priya Singh")
    assert await handled and not replies
    assert len(bot.sent) == 2 and "Looker" in bot.sent[1].text

    handled, replies = typed(bot, "a few")
    assert await handled and "number" in replies[0]
    handled, replies = typed(bot, "1.5")
    assert await handled
    assert resolve_known(F("Looker experience (years)", "number", required=True)).fill == "1.5"


async def test_money_question_needs_the_forms_currency():
    store.put("allowed_chats", [1])
    bot = FakeBot()
    await apply_flow.ask(bot, resolve_known(F("Expected salary (USD)", "number", required=True)), Context(company="Stripe"))
    handled, replies = typed(bot, "12 LPA")
    assert await handled and "USD" in replies[0]
    handled, replies = typed(bot, "$90k")
    assert await handled and not replies
    assert resolve_known(F("Desired salary in USD", "number", required=True)).fill == "90000"


async def test_answer_that_doesnt_match_the_form_asks_for_the_closest_choice():
    store.put("allowed_chats", [1])
    bot = FakeBot()
    f = F("How many years have you used Looker?", "select", ["0-1", "2-3", "6+"], required=True)
    ctx = Context(company="Acme")
    await apply_flow.ask(bot, resolve_known(f, ctx), ctx)
    await tap(bot, buttons(bot.sent[0])["4"])
    assert "closest" in bot.sent[-1].text
    await tap(bot, buttons(bot.sent[-1])["2-3"])
    assert resolve_known(f, ctx).fill == "2-3"  # this form, this company
    assert resolve_known(F("Looker experience (years)", "number", required=True)).fill == "4"  # the real answer, everywhere else


async def test_typed_change_with_undo():
    store.put("allowed_chats", [1])
    bot, replies = FakeBot(), []

    async def reply(t, **kw):
        replies.append((t, kw.get("reply_markup")))

    message = SimpleNamespace(text="my notice period is now 15 days", reply_html=reply)
    assert await apply_flow.handle_update_text(SimpleNamespace(message=message), SimpleNamespace(bot=bot))
    assert "15 days" in replies[0][0]
    assert resolve_known(F("Notice period", "select", ["Immediate", "15 days", "1 month"], required=True)).fill == "15 days"
    undo = replies[0][1].inline_keyboard[0][0].callback_data
    await tap(bot, undo)
    assert resolve_known(F("Notice period", "select", ["Immediate", "15 days"], required=True)).action == "ask"


async def test_change_a_cv_fact_from_what_i_know():
    store.put("allowed_chats", [1])
    bot = FakeBot()
    await apply_flow.start_change(bot, 1, "k", "phone")
    handled, _ = typed(bot, "+91 91234 56789")
    assert await handled
    assert resolve_known(F("Phone", "tel", required=True)).fill == "+91 91234 56789"


async def test_show_answers_pages_and_buttons_fit_telegram_limits():
    for n in range(12):
        answers.remember(f"q:question {n}", {"t": "text", "v": f"answer {n}"}, title=f"Question {n}")
    bot = FakeBot()
    await apply_flow.show_answers(bot, 1)
    msg = bot.sent[0]
    assert "What I know about you" in msg.text
    data = [b.callback_data for row in msg.markup.inline_keyboard for b in row]
    assert all(len(d.encode()) <= 64 for d in data) and any(d.startswith("ans:p:1") for d in data)


def test_cv_file_is_kept_for_upload():
    from pathlib import Path

    path = store.save_file("My CV (final).pdf", b"%PDF-1.4", folder="cv")
    assert Path(path).name == "My_CV_final_.pdf" and Path(path).exists()
    store.put("cv_file", path)
    assert resolve_known(F("Resume/CV", "file", required=True)).fill == path
