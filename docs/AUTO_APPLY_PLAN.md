# OpenHunt Autopilot: the app applies for you, you only chat (Plan)

> **Goal:** you open **one Telegram chat** and nothing else. OpenHunt finds jobs, logs in to job
> sites, fills in every form and submits it, all **in the background**. The only thing you ever do
> is answer a question in the chat when a form asks something new. You answer it **once**. Every
> later form that asks the same thing is filled and submitted automatically.

This plan builds on what OpenHunt v0.1 already has: the Telegram bot (`openhunt/bot/app.py`),
the database (`openhunt/store.py`), the hunt pipeline (`openhunt/hunt.py`) and the any-LLM
client (`openhunt/ai/llm.py`).

## 0. Design rules

1. **Telegram is the only screen.** No browser window pops up, no web page, no "open this link".
   The browser runs hidden (headless) in the background.
2. **The app does the work.** It decides which jobs to apply to, clicks through the forms and submits.
3. **No forms for the user, ever.** No setup questionnaire. Everything that can be read from the
   CV is read from the CV. You're only asked a question when a real application needs it, and
   the question arrives as **one chat message with buttons**.
4. **Ask once, remember forever.** Every answer is saved and reused in any wording, on any site.
5. **Quiet by default.** No message per click. You get the questions it needs and one daily
   summary, plus a short message when something truly needs you (a login code, a CAPTCHA).

> ⚠️ **This changes an existing promise.** The README and `PROJECT_PLAN.md` say OpenHunt
> *never applies for you*. Autopilot is turned on with **one tap**, after one short warning
> (see [§8](#8-risks-and-safety-rules)). The README's Safety section is updated in the same release.

---

## 1. What the user experiences (all inside the chat)

### 1.1 Turning it on: 3 messages
```
🤖 Want me to apply to jobs for you?
I'll apply to good matches by myself and only message you
when a form asks something I don't know yet.
Note: LinkedIn and Indeed don't allow bots, so your account
there could get limited. I go slowly to keep the risk low.
[✅ Yes, apply for me]  [Not now]
```
```
Which sites should I apply on?
[✅ Company career sites (safest)]  [✅ LinkedIn]  [✅ Naukri]  [☐ Indeed]
[Done]
```
```
🔐 To apply on LinkedIn I need to log in once.
Send your LinkedIn email.
```
→ you send the email → *"Now your password. I'll delete your message right after."* → you send it
→ the bot deletes both messages at once → *"LinkedIn sent a code to your email. Type it here."* →
`✅ LinkedIn connected. I'll start applying.`

That's all. There's no answer questionnaire. Your phone, email, city, degree, skills and years
of experience are already in your CV, so OpenHunt uses them.

### 1.2 What you see from then on
**When a form asks something new** (the only time you're needed):
```
❓ Razorpay · Data Analyst asks:
How many years have you worked with Tableau?
[0] [1] [2] [3] [4] [5+]
```
You tap `2`, and that's it. The application continues and is submitted in the background.
The next time any company asks about Tableau experience, in any wording, the answer is `2`.

- Yes/no and choice questions → **buttons** with the site's own options.
- Number and text questions → **type the reply**.
- "Upload your transcript" → **send the file** in the chat.
- "Why do you want to join us?" → the AI writes it from your CV and the job by itself.
  It's never sent to you. You can turn on "show me AI-written answers first" if you want to check them.
- Several jobs waiting on the same new question → **asked once**, and all of them continue.

**When something applies** (it doesn't flood you): either one line per job or none at all, your choice.
```
✅ Applied: Data Analyst · Razorpay (LinkedIn)
```

**Once a day** (with the existing morning digest):
```
📊 Yesterday: ✅ 11 applied · ❓ 1 question waiting · ⏭ 2 skipped (jobs closed)
[❓ Answer now]  [📋 See applications]
```

### 1.3 The controls (buttons, rarely needed)
- `⏸ Pause applying` / `▶️ Resume`
- `🎯 Only apply to jobs above 80 / 70 / 60` (default: the same "good match" level as the job alerts)
- `📋 Applications`: what was sent where, with what answers and a proof screenshot
- `🧠 What I know about you`: see or change any saved answer ("Change my notice period to 30 days")
- Job cards still have a `🤖 Apply now` button, to apply to one specific job straight away.

You can also just **type** what you want: *"stop applying on LinkedIn"*, *"don't apply to Swiggy"*,
*"my expected salary is now 15 LPA"*. The AI turns it into the right setting.

---

## 2. Logging in without leaving Telegram

| Situation | What happens in the chat |
|---|---|
| Email + password | You type them. The bot **deletes both messages right away** and types them into the hidden browser. |
| Code by email / SMS / authenticator | *"Type the code LinkedIn sent you."* You type it, and it's deleted after use. |
| "Approve on your phone" (LinkedIn app) | *"Tap Yes in the LinkedIn app on your phone."* The bot waits and continues. |
| Google / "Sign in with Google" login | Same as above: email, password and code in the chat, deleted after use. |
| CAPTCHA / "are you a robot" | See §2.2. |
| Logged out weeks later | *"LinkedIn logged me out. Send your password again?"* The password is the only thing asked. |

### 2.1 What happens to your password
- **Default:** the password is used once to log in and is **never saved**. Only the login session
  (cookies) is kept, encrypted, in `~/.openhunt`. LinkedIn sessions usually last months, so
  you rarely get asked again.
- **Optional:** `🔁 Remember my password so I never ask again` stores it encrypted, the same way
  OpenHunt already stores your bot token and AI key (`store.SECRET_KEYS`).
- Honest note for users: Telegram bot chats are not end-to-end encrypted, so the password passes
  through Telegram's servers for a moment before being deleted. The bot says this in one line and
  suggests turning on two-step login on the job site.

### 2.2 CAPTCHAs, still inside Telegram
OpenHunt never tries to trick or solve CAPTCHAs by itself. A person solves them, without leaving the chat:
- **Picture/text CAPTCHA** → the bot sends the image: *"Type the letters you see."*
- **Click-type checks** ("select all traffic lights", "press and hold") → the bot sends a
  `[🧩 Solve it here]` button that opens a **Telegram Mini App**. This is a small screen that
  opens *inside* Telegram, on top of the chat, showing the live hidden browser page. You do the
  check with your finger, the screen closes, and you're back in the chat.
  - It works from home Wi-Fi and VMs with no setup: OpenHunt opens a temporary secure tunnel
    (Cloudflare quick tunnel) only while the check is open and closes it afterwards.
  - Only you can open it: every request is checked with Telegram's signed Mini App data, which
    proves it comes from your linked Telegram account (HMAC with the bot token).
- If CAPTCHAs keep coming on a site, OpenHunt **pauses that site for a day** and tells you.
  Repeated CAPTCHAs mean the site is suspicious, and pushing on risks the account.

---

## 3. Who decides what to apply to

```
hunt (existing) ─► new match ≥ your level? ─► not applied before? ─► site enabled + under daily cap?
                                                                     │
                                                                     ▼
                                                              apply queue ─► background browser
```
- Runs after every scheduled hunt and empties the queue slowly through the day (see §7).
- **Skips by itself:** jobs already applied to (on any site), closed jobs, companies you blocked,
  and jobs whose form needs something it must never guess (see §5.4) until you answer.
- The external "Apply on company website" links on LinkedIn are followed too. The job is applied to
  on the company's own form, which is usually Greenhouse, Lever, Ashby or Workday.

---

## 4. Architecture

```
 Telegram chat ◄──► bot/apply_flow.py   (questions, logins, codes, controls, daily summary)
                          │
                          ▼
                  apply/queue.py   one application at a time · daily caps · pacing · retries
                          │
                          ▼
                  apply/engine.py  for each form page:
                     read fields → answer from memory → unknown? ask in chat & park the job
                     → fill → next → … → submit → proof screenshot
                          │
        ┌─────────────────┼────────────────────┬─────────────────────┐
        ▼                 ▼                    ▼                     ▼
 apply/browser.py   apply/adapters/*     apply/answers.py      apply/miniapp.py
 hidden Chromium,   linkedin, naukri,    answer memory,        Mini App + temporary
 saved logins,      indeed, greenhouse,  question matching,    tunnel, only for
 login via chat     lever, ashby,        fitting answers to    CAPTCHA checks
                    workday, generic(AI) each form
```
Everything runs **inside the existing single process** (`runtime.py`), using Playwright's async API.
There is nothing new for the user to start or install, beyond one automatic browser download (§9).

### New files
```
openhunt/apply/
├── browser.py      # headless Chromium, one saved session per site, chat-driven login
├── fields.py       # read any form into FormField objects (label, kind, options, required)
├── answers.py      # answer memory: match question → saved answer → fit to this form's field
├── intents.py      # common questions in many wordings (years_with(skill), notice_period, …)
├── engine.py       # page loop, park/resume, submit, proof
├── queue.py        # picks jobs, caps, pacing, active hours
├── guard.py        # CAPTCHA, login challenge, "already applied", closed job, stuck page
├── miniapp.py      # Telegram Mini App view + temporary tunnel (CAPTCHA only)
└── adapters/
    ├── base.py
    ├── linkedin.py  naukri.py  indeed.py
    ├── greenhouse.py  lever.py  ashby.py  workday.py
    └── generic.py  # any other site: AI finds the fields and buttons
openhunt/bot/apply_flow.py
```

### Adapter interface
```python
class Adapter(Protocol):
    name: str
    def matches(self, url: str) -> bool: ...
    async def login(self, page: Page, ask: AskUser) -> bool: ...   # asks email/password/code via chat
    async def is_logged_in(self, page: Page) -> bool: ...
    async def open(self, page: Page, job_url: str) -> None: ...    # click "Apply" / "Easy Apply"
    async def read_page(self, page: Page) -> list[FormField]: ...
    async def fill(self, page: Page, field: FormField, value: Value) -> None: ...
    async def next(self, page: Page) -> StepResult: ...             # NEXT | SUBMITTED | ERROR
```
`AskUser` is the bridge to the chat. The adapter calls `await ask.text("Type the code LinkedIn sent you")`
and gets your reply back, so every site's login and every question goes through Telegram.

---

## 5. Answer memory (how it never asks twice)

### 5.1 Filled in automatically, with nothing asked
On day one, before any form, the memory is filled from things OpenHunt already has:
- **From the CV** (already parsed in `ai/profile.py`, extended): name, email, phone, city,
  LinkedIn/GitHub/portfolio links, degree, college, graduation year, total years of experience,
  **years per skill** (worked out from the CV's job dates), languages, current job title and company.
- **From the chat so far:** job titles, locations, minimum salary (→ expected salary).
- **Safe defaults:** diversity questions (gender, race, disability, veteran) → *Prefer not to say*;
  "How did you hear about us?" → the site name (e.g. *LinkedIn*); "Follow this company" → unticked.
- **The CV file itself** is uploaded wherever a form asks for a résumé.

### 5.2 Matching any wording
For each form field, in order, stopping at the first confident match:
1. **Common question rules** (`intents.py`, instant): "Tableau experience (yrs)", "How long have you
   used Tableau?" and "Years of experience with Tableau" all → `years_with(tableau)`.
2. **Same question seen before** (normalized text).
3. **Very similar question** (fuzzy match ≥ 92%, same kind of field).
4. **AI match**: the AI may only *pick one of your saved answers*. It never makes one up.
5. Still unknown → **one chat question**, then saved.

### 5.3 One answer fits every form
Answers are saved as values, not just text, so the same answer fits different forms:
`3 years` → `3` in a number box, `2-4` in a dropdown · `yes` → `Yes` radio or a ticked box ·
`12 LPA` → `1200000` in a ₹ field or `12` in an "LPA" field. If an answer can't be fitted to the
options with confidence, it's asked instead of guessed.

### 5.4 Never guessed (always from your CV or from you)
Years of experience with a skill not in the CV · work authorization and visa · degrees and
certificates · criminal record or background checks · salary history · anything legal ("I confirm…").
For these, the AI never fills an answer that isn't already in your CV or your saved answers.

### 5.5 Changing answers
Type it naturally: *"my notice period is now 15 days"* → `✅ Updated. I'll use 15 days from now on.`
Or `🧠 What I know about you` lists everything, with a button to change each one.
A new CV refreshes everything taken from the CV automatically.

---

## 6. Parking a job while you're busy
- An unknown question **parks** that application and the bot asks you. The background browser
  **moves on** to the next job, so nothing waits for you.
- When you answer (minutes or days later), the parked job **starts again from the beginning**. All
  earlier answers are in memory, so it goes straight through and submits.
- Parked jobs that close before you answer are dropped quietly.
- Unanswered questions are repeated once, in the daily summary, never as repeated pings.

---

## 7. Pacing and limits (protects your accounts, invisible to you)
- One hidden browser, **one application at a time**.
- Human-like speed: random pauses between clicks, natural typing speed, a few minutes between
  applications, and only between 9:00 and 21:00 your time.
- Daily limits per site: LinkedIn 15 · Naukri 25 · Indeed 15 · company career sites 40 · other sites 20.
  The user only sees them if they ask.
- **Never applies twice** to the same job, even if it's posted on two sites.
- CAPTCHA or "unusual activity" warning → that site pauses for 24 h, and you get one message.

---

## 8. Risks and safety rules
1. **Site rules.** LinkedIn and Indeed forbid automated applying, and accounts can be restricted.
   The user is told once, in plain words, when turning Autopilot on. Company career sites
   (Greenhouse/Lever/Ashby/Workday) are the safest and are always on by default. The slow pacing
   and limits above stay on and can't be turned off.
2. **Passwords** are deleted from the chat right away and not stored unless the user opts in (§2.1).
3. **No CAPTCHA tricks.** A person solves every check (§2.2).
4. **Honest applications.** Factual answers come only from the CV or the user (§5.4). The AI
   only writes essay answers, from the real CV.
5. **Job pages are untrusted.** Form text is handled as data, never as instructions to the bot.
   A form can't change settings or pull out other saved answers.
6. **Only the linked Telegram account** controls the bot (existing `only_owner`), and only it can
   open the Mini App (signed by Telegram).
7. **Proof of everything:** every submission saves exactly what was sent plus a screenshot.
8. `openhunt reset` deletes saved logins, answers and proof.

---

## 9. Install impact
- Autopilot needs Chromium. On the first `✅ Yes, apply for me`, OpenHunt downloads it by itself
  (about 150 MB) and says *"Getting ready… 1 minute"*. There's no command for the user to run.
- Docker image: Chromium included.
- Android/Termux can't run Chromium. The bot says *"Applying needs a laptop or VM; job alerts still work here"*.

---

## 10. Data model (new tables in `store.py`)
```
Application(id, job_id → Job UNIQUE, site, url, status, created_at, submitted_at,
            attempts, last_error, answers_snapshot_json, proof_path)
  status: queued | running | parked | submitted | skipped | expired | failed | needs_you

Answer(id, key, intent, slots_json, question_text, value_json,
       scope: global|company, company, source: cv|chat|default|ai_essay,
       use_count, last_used_at)

PendingQuestion(id, key, field_json, application_ids_json, telegram_message_id,
                created_at, answered_at)

SiteLogin(site, status: ok|logged_out|paused, paused_until, daily_count, day,
          password_encrypted NULL)          # only if the user opted in
```
Browser sessions: `~/.openhunt/browser/<site>/` (folder permissions 700, cookies encrypted at rest).
When a job is submitted, the existing `Match.status` becomes `applied`.

---

## 11. Build phases

| Phase | Deliverable | Done when |
|---|---|---|
| **A. Answer memory** ✅ done | `fields.py`, `answers.py`, `intents.py`, tables, CV → answers, chat questions with buttons, "what I know about you", typed changes | One question in 5 wordings → asked once; answers fit number, dropdown and radio fields |
| **B. Hidden browser + chat login** | `browser.py`, automatic Chromium download, login by chat (email, password, code, app approval), messages deleted, sessions saved | LinkedIn and Naukri log in entirely from the chat |
| **C. Company career sites** | Greenhouse, Lever, Ashby adapters, `engine.py`, parking, proof | A real Greenhouse job is applied to in the background; the user only answers new questions |
| **D. LinkedIn Easy Apply + Naukri** | adapters, `guard.py`, following external apply links | 10 jobs in a row; the second 10 need no questions |
| **E. Autopilot** | `queue.py`, auto-pick from hunts, limits, pacing, daily summary, pause/resume, typed commands | Applies overnight within limits and sends one morning summary |
| **F. CAPTCHA in Telegram** | `miniapp.py`, temporary tunnel, signed access, picture-CAPTCHA by chat | A CAPTCHA is solved without leaving Telegram |
| **G. More sites** | Indeed, Workday, `generic.py` AI adapter | An unknown career site is completed by the AI adapter |

**Testing:** saved copies of each site's forms in `tests/fixtures/forms/`, filled by the real
adapters in headless Chromium without network access. A developer-only `--dry-run` mode fills
everything but never presses Submit, for checking live sites safely.

---

## 12. Settled
- Telegram only: no links, windows or web pages for the user.
- The app applies by itself by default; the user only answers new questions.
- No setup questionnaire: answers come from the CV first, then from questions inside real applications.
- Login happens through the chat; passwords are not stored unless the user opts in.
