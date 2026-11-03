# OpenHunt Autopilot: apply to jobs from Telegram (Plan)

> **Goal:** OpenHunt logs in to job sites in a real browser, fills in application forms by itself,
> and applies, all controlled from Telegram. When a form asks something it doesn't know yet,
> the question appears **in the Telegram chat**. You answer it **once**. After that, the same
> question is filled in and submitted automatically every time, with no need for you.

This plan builds on what OpenHunt v0.1 already has: the Telegram bot (`openhunt/bot/app.py`),
the settings and jobs database (`openhunt/store.py`), the hunt pipeline (`openhunt/hunt.py`)
and the any-LLM client (`openhunt/ai/llm.py`).

> ⚠️ **This changes an existing promise.** The README and `PROJECT_PLAN.md` say OpenHunt
> *never applies for you*. Autopilot is therefore **opt-in**, **off by default**, and shows a
> clear warning when it's turned on (see [§9 Risks](#9-risks-and-safety-rules)). The README's
> Safety section has to be updated in the same release that ships this feature.

---

## 1. What the user experiences

### 1.1 One-time setup (about 5 minutes, all in Telegram)
1. `/autopilot` → *"I can apply for you. LinkedIn and some sites don't allow bots, and your
   account could be limited. Start in 👀 Review mode (I ask before every submit)?"*
   `[✅ Turn on (Review mode)]` `[Not now]`
2. **Log in to sites:** `/browser` → `[🔗 LinkedIn]` `[🔗 Naukri]` `[🔗 Indeed]` `[➕ Other site]`.
   A real browser window opens (or a live view, on a VM; see §4.2). **You type your own password.**
   OpenHunt never sees or stores it. It only keeps the logged-in session, like your normal browser does.
3. **Quick answer pack:** the bot asks the ~15 questions almost every form asks, pre-filled
   from your CV so you mostly tap ✅:
   phone, email, current city, notice period, expected and current salary, work authorization,
   need for sponsorship, willing to relocate, years of experience per main skill, highest degree,
   LinkedIn / GitHub / portfolio URLs, English level, earliest start date,
   and the "diversity" questions (default: *Prefer not to say*).

### 1.2 Applying
From any job card, a new button:
```
🟢 92/100 · Data Analyst · Razorpay · Bangalore (Hybrid)
...
[🤖 Apply for me] [🔗 Open] [⭐ Save] [👎 Not for me]
```
Or paste any link: `/apply https://boards.greenhouse.io/acme/jobs/123`.
Or let it run by itself (§1.4).

### 1.3 When the form asks something new: the question comes to the chat
```
🤖 Applying: Data Analyst · Razorpay (LinkedIn Easy Apply)
Page 2 of 4 · I need 2 answers from you

❓ 1/2  How many years of experience do you have with Tableau?
[0] [1] [2] [3] [4] [5+] [✏️ Type]
💾 Remember: For all jobs ▸        [⏭ Skip this job]
```
```
❓ 2/2  Are you comfortable working from our Bangalore office 3 days a week?
[Yes] [No]
💾 Remember: For all jobs ▸
```
- Choice questions (dropdown, radio, yes/no, checkbox) → **buttons with the site's own options**.
- Text and number questions → just **type the reply** in the chat.
- File questions ("Upload transcript") → **send the file** in the chat.
- Long questions ("Why do you want to work here?") → the AI writes a draft from your CV and the job.
  You tap `[✅ Use it]` `[✏️ Edit]` `[🔁 Rewrite]`.
- `💾 Remember` cycles through: **For all jobs** · **Only for this company** · **Just this once**.

As soon as the last answer arrives, the bot carries on, then shows the review:
```
📋 Ready to submit: Data Analyst · Razorpay
[photo: screenshot of the final review page]
📚 14 answers from memory · 👤 2 from you just now · 🧠 1 AI draft
[✅ Submit] [✏️ Change an answer] [❌ Cancel]
```
→ `✅ Applied! (proof saved). /applied to see all.`

### 1.4 Fully automatic for repeat questions
The next time **any** form asks "years of experience with Tableau", in any wording
("Tableau experience (years)", "How long have you used Tableau?"), OpenHunt fills it from
memory. **When every field on a form is known, nobody is asked anything.**

Three modes (`/autopilot`):
| Mode | What happens |
|---|---|
| 👀 **Review** (default) | Fills everything, asks you only for new questions, then waits for your `✅ Submit`. |
| ⚡ **Auto-submit known forms** | If every answer came from memory with high confidence, it submits without asking and tells you afterwards. If anything is new, it asks first. |
| 🚀 **Full autopilot** | Also applies **by itself** to new matches above a score you choose (e.g. ≥ 85), within daily limits. You get one summary per day: *"Applied to 9 jobs today. 2 are waiting for your answers."* |

Recommendation: keep Review mode for the first ~10 applications on each site, then step up.
The bot suggests this itself: *"Your last 10 LinkedIn forms needed no changes. Switch LinkedIn to ⚡ Auto-submit?"*

---

## 2. Architecture

```
 Telegram ◄──► bot/apply_flow.py ──┐        (questions, review cards, /answers, /browser)
                                   ▼
                     apply/queue.py  (one application at a time, daily caps, retries)
                                   │
                                   ▼
                     apply/engine.py  ── loop per form page:
                        1. adapter.read_page()  → list[FormField]
                        2. answers.resolve(fields) → filled / unknown
                        3. unknown? → ask in Telegram, wait (pause & resume)
                        4. adapter.fill(), adapter.next()
                        5. last page → review card or auto-submit
                                   │
            ┌──────────────────────┼──────────────────────┐
            ▼                      ▼                      ▼
   apply/browser.py         apply/adapters/*         apply/answers.py
   Playwright Chromium      linkedin, greenhouse,    Answer bank + question
   persistent profile       lever, ashby, indeed,    matching (rules → fuzzy →
   per site, login,         naukri, workday,         AI), typed values,
   screenshots, live view   generic (AI-driven)      option mapping
                                   │
                                   ▼
                     store.py: Application, Answer, PendingQuestion, SiteSession
```

It runs **inside the existing single asyncio process** (`runtime.py`) using Playwright's async
API, so the bot, scheduler, web page and browser share one event loop. Nothing new to start.

### New files
```
openhunt/apply/
├── __init__.py
├── browser.py        # launch/reuse Chromium, one persistent profile per site, login check, screenshots
├── fields.py         # FormField model + DOM → fields extraction (labels, options, required)
├── answers.py        # answer bank: normalize question → intent/key → stored typed value → fit to field
├── intents.py        # catalogue of common questions (regex + slot extraction, e.g. years_with(skill))
├── engine.py         # the page loop, pause/resume, review, submit, proof capture
├── queue.py          # apply queue worker, caps, pacing, active hours
├── guard.py          # CAPTCHA / checkpoint / "already applied" / logged-out detection
└── adapters/
    ├── base.py       # Adapter protocol
    ├── greenhouse.py
    ├── lever.py
    ├── ashby.py
    ├── linkedin.py   # Easy Apply modal only; external "Apply" links are routed to other adapters
    ├── indeed.py
    ├── naukri.py
    ├── workday.py
    └── generic.py    # unknown sites: AI reads the page and maps fields
openhunt/bot/apply_flow.py   # Telegram handlers for everything above
openhunt/web/browser_view.py # live remote browser view for VM users (§4.2)
```

### Adapter interface
```python
class Adapter(Protocol):
    name: str                       # "linkedin", "greenhouse", ...
    needs_login: bool

    def matches(self, url: str) -> bool: ...
    async def open(self, page: Page, job_url: str) -> None:          # go to job, click "Apply"
    async def read_page(self, page: Page) -> list[FormField]: ...     # fields on the current step
    async def fill(self, page: Page, field: FormField, value: Value) -> None: ...
    async def next(self, page: Page) -> StepResult:                   # NEXT | REVIEW | SUBMITTED | ERROR
    async def submit(self, page: Page) -> bool: ...
    async def is_logged_in(self, page: Page) -> bool: ...
```
Site-specific adapters handle the known layouts precisely and quickly. `generic.py` is the
fallback for any other site: it reads the accessibility tree, asks the LLM to label fields and
find the Next and Submit buttons, then uses the same answer bank. This is how "any other website"
is supported without writing code for each one.

---

## 3. The answer bank (the heart of "answer once, never again")

### 3.1 Every field becomes a `FormField`
```python
@dataclass
class FormField:
    label: str                 # "How many years of experience do you have with Tableau?"
    kind: str                  # text | textarea | number | select | radio | checkbox | file | date
    options: list[str]         # for select/radio/checkbox, exactly as the site shows them
    required: bool
    current: str | None        # some sites pre-fill (e.g. LinkedIn phone)
    locator: str               # how the adapter finds it again
    context: str               # section heading / help text, used for matching
```

### 3.2 Questions are matched by meaning, not exact wording
`answers.resolve(field)` tries these in order and stops at the first confident hit:

1. **Known intent (rules, free, instant).** `intents.py` maps common wordings to an intent
   with slots, e.g.
   - "years of experience with Tableau" / "Tableau experience (yrs)" → `years_with(skill="tableau")`
   - "notice period" / "how soon can you join" → `notice_period`
   - "require sponsorship" / "need a visa" → `needs_sponsorship(country=…)`
   - "legally authorized to work in India" → `work_authorized(country="india")`
   - "expected CTC" / "salary expectations" → `expected_salary`
2. **Exact question seen before**: normalized text hash (lowercase, no punctuation or numbers,
   stop-words removed) matches a saved `Answer.key`.
3. **Fuzzy match** to saved questions (`rapidfuzz` token-set ratio ≥ 92, same field kind).
4. **AI match**: the LLM gets the question, the options, and a short list of the closest saved
   questions, and replies `{intent or saved_id, confidence}`. It **only chooses among saved
   answers**. It never invents a factual answer.
5. Otherwise → **unknown** → asked in Telegram.

### 3.3 Answers are stored as typed values, then fitted to each form
Saving `"3"` as text breaks when the next site shows a dropdown `0-1 / 2-4 / 5+`. So answers are
stored as **values with a type** and adapted per field:

| Stored value | Field on the next site | Filled with |
|---|---|---|
| `years: 3` | number input | `3` |
| `years: 3` | dropdown `0-1, 2-4, 5+` | `2-4` |
| `bool: true` | radio `Yes / No` | `Yes` |
| `bool: true` | checkbox "I am authorized…" | checked |
| `money: 1200000 INR/yr` | text "Expected CTC (LPA)" | `12` |
| `text: "30 days"` | dropdown `Immediate, 15 days, 1 month, 2+ months` | `1 month` (AI picks the closest option) |

If the stored value can't be fitted to the options with confidence, the question is asked
instead of guessing.

### 3.4 Confidence decides what happens
| How it was matched | Review mode | Auto-submit mode |
|---|---|---|
| Intent rule / exact / profile fact | fill | fill |
| Fuzzy ≥ 92 | fill, mark 📚 in review | fill |
| AI match ≥ 0.9 | fill, mark 🧠 in review | fill, listed in the "after" report |
| AI match < 0.9 or no fit | **ask** | **ask** (no auto-submit for that form) |
| Free-text essay (why us, cover letter) | AI draft, you approve | AI draft auto-used **only if** you turned on "auto-approve AI drafts" |
| Sensitive (gender, race, disability, veteran, age) | from your saved choice only, never AI | same |

### 3.5 Scope and editing
- Each answer has a scope: **global**, **per company**, or **one-off**.
  Company answers win over global ones.
- `/answers` lists everything it has learned, grouped by topic, with search, edit and delete.
  It also shows where each answer is used: *"Used 23 times · last on Swiggy, 2 days ago"*.
- Answers are also **exported and imported** as one file (back up, or move to a new machine).
- When you send a new CV, answers derived from the old CV (years of experience, skills) are
  flagged for a quick re-check, but nothing is deleted.

---

## 4. Browser and logins

### 4.1 Engine
- **Playwright + Chromium**, with one **persistent profile directory per site** in
  `~/.openhunt/browser/<site>/` (folder permissions 700). Logins survive restarts, just like a normal browser.
- A new optional install extra: `pip install "openhunt[boards,apply]"`, then `openhunt browser install`
  (wraps `playwright install chromium`). The Docker image gets an `apply` variant with Chromium included.
- Runs **headless** by default and **headed** when you log in or ask to watch.
- **Not supported on Android/Termux** (Chromium can't run there). Termux users can still use
  everything else. The bot says so instead of failing.

### 4.2 Logging in (you type the password, never the bot)
| Where OpenHunt runs | How you log in |
|---|---|
| Your laptop | `/browser` → `[🔗 LinkedIn]` → a real browser window opens on the laptop. Log in normally; the bot notices and says `✅ LinkedIn connected`. |
| A VM / server | `/browser` → the bot sends a link to a **live browser view** in the OpenHunt web page (`/browser`, built on Chrome's screencast with clicks and typing passed through). Open it through your SSH tunnel or Tailscale, then log in. |
| Either | **Move a login:** log in on your laptop, run `openhunt browser export linkedin`, then `openhunt browser import` on the VM (an encrypted file). |

- **2-step codes (OTP)** during login or apply: the bot asks *"LinkedIn sent you a code. Type it here."*
  The code you type is passed to the page and then deleted from the chat.
- **Health check**: before each batch, and in `/status`, OpenHunt checks each site is still logged
  in. If not: *"LinkedIn logged you out. Tap to log in again."*

### 4.3 When a human is needed
`guard.py` checks every page for:
- **CAPTCHA / "are you a robot" / security checkpoint** → **stop**, send a screenshot plus the live-view
  link, and pause that site. OpenHunt **never tries to solve or bypass CAPTCHAs**.
- **"Already applied"** → mark as applied, skip.
- **Job closed / page missing** → mark as expired.
- **Logged out** → pause the site and ask you to log in again.
- **Unknown layout / stuck for 3 tries on the same page** → screenshot to Telegram:
  `[👀 Finish it myself (live view)] [⏭ Skip] [🐞 Save debug info]`.

---

## 5. Pause and resume: waiting for your answer

A form shouldn't hold a browser tab open for hours while you're busy. So:
1. Unknown questions → saved as `PendingQuestion` rows → sent to Telegram. The application is marked
   `waiting_for_you`.
2. The tab stays open for **10 minutes**. If you answer in time, it continues on the same page.
3. After that, the tab closes. When you answer later, the application is **started again from the
   beginning**. Because all earlier answers are in the answer bank, it goes straight through to the
   point it reached before, and further.
4. Meanwhile the queue **moves on to other jobs**. One unanswered question never blocks the others.
5. Several jobs asking the same new question → **asked once**, and all of them continue after one answer.

---

## 6. Data model (new tables in `store.py`)

```
Application(id, job_id → Job UNIQUE, site, url, status, mode, score_at_apply,
            created_at, submitted_at, attempts, last_error,
            answers_snapshot_json,        # exactly what was submitted
            proof_path)                   # screenshot of the confirmation page
  status: queued | running | waiting_for_you | ready_for_review | submitted |
          skipped | expired | failed | needs_human

Answer(id, key UNIQUE(key, scope, company), intent, slots_json, question_text,
       kind, value_json, scope: global|company|once, company,
       source: user|profile|ai_draft, use_count, last_used_at, created_at, needs_recheck)

PendingQuestion(id, application_id, field_json, asked_message_id, created_at,
                answered_at, answer_id)

SiteSession(site, status: ok|logged_out|blocked, last_check_at, daily_count, day,
            mode: review|auto|autopilot, paused)
```
The existing `Match.status` already has `applied`. It is set when an `Application` is submitted.
Proof screenshots go in `~/.openhunt/proof/`. `openhunt reset` wipes them, the browser profiles and the answer bank.

---

## 7. Telegram commands and buttons (new)

| Command | What it does |
|---|---|
| `/autopilot` | Turn on/off, choose mode per site, minimum score, daily limit, active hours |
| `/browser` | Log in to sites, see which are connected, open the live view |
| `/apply <link>` | Apply to any job link |
| `/queue` | What's waiting, running and needs you, with `[▶️ Resume]` `[⏸ Pause]` |
| `/answers` | See, search, edit and delete learned answers |
| `/applied` | Applications sent, with proof screenshots and status |

Job card: add `🤖 Apply for me`. Saved jobs: `🤖 Apply to all saved`.
Daily summary (with the existing digest): *"✅ 7 applied · ⏳ 2 need your answers · ⚠️ 1 needs you to log in"*.

Optional later: a **Telegram Mini App** that shows a whole form page as a real form inside Telegram.
This needs a public HTTPS address, so the chat-question flow above stays the default.

---

## 8. Pacing and limits (keeps accounts safe and the queue sane)
- **One browser, one application at a time.** No parallel tabs on the same site.
- **Human-like pace:** a random 1–4 s between actions, typing speed variation, a 1–3 min gap
  between applications, and only during the **active hours** you choose (default 9:00–21:00).
- **Daily caps per site** (editable): LinkedIn 15, Naukri 25, Indeed 15, ATS sites
  (Greenhouse/Lever/Ashby) 40, generic sites 20.
- **Never apply twice**: one `Application` per job fingerprint, plus "already applied" detection on the page.
- **Back off automatically:** a CAPTCHA or checkpoint pauses that site for 24 h and tells you.

---

## 9. Risks and safety rules
1. **Site rules.** LinkedIn's and Indeed's user agreements forbid bots and automated activity.
   Accounts can be restricted. Autopilot is opt-in, shows this warning when turned on, recommends
   starting with ATS sites (Greenhouse, Lever and Ashby forms are public and don't need a login),
   and uses the caps above. The user carries this risk, and the UI says so plainly.
2. **No passwords stored.** You log in yourself; only the browser session is kept, locally.
3. **No CAPTCHA solving or bot-detection evasion.** A human always handles those.
4. **Honest answers.** AI never invents facts (years, degrees, authorizations). Factual answers
   come only from your profile or from you. AI only drafts essay answers, from your real CV.
5. **Job pages are untrusted.** Form text and job descriptions go to the LLM as data, inside the
   existing prompt-injection guard. A form can't make the bot change settings or reveal data.
   AI output is only ever used to *choose among options* or *draft text* for review.
6. **Sensitive questions** (diversity/EEO, disability, age, salary history where illegal):
   only your saved choice is used, default *Prefer not to say*.
7. **Audit trail.** Every submit saves exactly what was sent plus a screenshot, so you can
   always answer *"what did I tell this company?"*.
8. **Only linked Telegram accounts** can trigger applications (the existing `only_owner` guard),
   and the live browser view requires the web password.

---

## 10. Build phases

| Phase | Deliverable | Done when |
|---|---|---|
| **A. Answer bank + chat Q&A** (≈1 wk) | `fields.py`, `answers.py`, `intents.py`, tables, `/answers`, quick answer pack, question cards in Telegram | Unit tests: the same question in 5 wordings resolves to one answer; values fit number, dropdown and radio fields |
| **B. Browser + logins** (≈1 wk) | `browser.py`, persistent profiles, `/browser`, login detection, OTP relay, health check, `openhunt[apply]` extra, Docker variant | You can log in to LinkedIn from Telegram and `/status` shows ✅ |
| **C. ATS adapters + Review mode** (≈1.5 wk) | Greenhouse, Lever, Ashby, `engine.py`, review card with screenshot, proof capture, `/applied` | A real Greenhouse job is applied to end-to-end from one tap, with you only answering new questions |
| **D. LinkedIn Easy Apply** (≈1.5 wk) | `linkedin.py` (multi-step modal, resume pick, follow-company checkbox off), `guard.py` | 10 Easy Apply jobs in a row; the second batch needs zero answers from you |
| **E. Queue, pause/resume, modes** (≈1 wk) | `queue.py`, waiting/resume, ⚡ Auto-submit, 🚀 Autopilot from hunt results, caps, active hours, daily summary | Autopilot applies to new ≥ 85 matches overnight within caps and sends a morning summary |
| **F. More sites** (ongoing) | Naukri, Indeed, Workday, `generic.py` AI adapter, live browser view for VMs | An unknown career site is completed with the generic adapter |
| **G. Polish** | Telegram Mini App form view, answer import/export, the "switch to Auto?" suggestion, README/Safety update | — |

**Tests:** saved HTML copies of each site's form under `tests/fixtures/forms/`, filled by the real
adapters in headless Chromium (no network), plus unit tests for matching and value fitting.
Live-site checks are a manual script (`openhunt apply --dry-run <url>` fills the form but never submits),
because sites change and CI must not apply to real jobs.

---

## 11. Decisions needed from you
1. **Where will it mostly run?** Laptop (simplest login) or VM (needs the live view in Phase F to come earlier)?
2. **First site to support:** LinkedIn Easy Apply (most jobs, most risk) or ATS forms first (safer and
   steadier; recommended)?
3. **Default mode for new users:** 👀 Review (recommended) or ⚡ Auto-submit?
4. **Daily caps**: keep the defaults in §8?
