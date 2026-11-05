# OpenHunt Guide

Everything about OpenHunt in one place: what it does, how to install it, how to use it from Telegram,
how Autopilot applies for you, and how the code fits together.

**Contents**
1. [What OpenHunt is](#1-what-openhunt-is)
2. [Install](#2-install)
3. [First setup](#3-first-setup)
4. [Everyday use](#4-everyday-use)
5. [Autopilot: applying for you](#5-autopilot-applying-for-you)
6. [Questions and the answer memory](#6-questions-and-the-answer-memory)
7. [Job site logins](#7-job-site-logins)
8. [Telegram commands](#8-telegram-commands)
9. [Settings](#9-settings)
10. [Privacy, safety and site rules](#10-privacy-safety-and-site-rules)
11. [Troubleshooting](#11-troubleshooting)
12. [For developers](#12-for-developers)
13. [Status and known limits](#13-status-and-known-limits)

---

## 1. What OpenHunt is

A job hunter that runs on your own laptop, VM or old phone, and that you control entirely from one
Telegram chat.

- **Finds jobs** on LinkedIn, Indeed, Naukri (India), remote job boards and company career pages, on a
  schedule you pick.
- **Ranks them** against your CV with AI and explains each score in plain words (🟢 Great, 🟡 Good, ⚪ Maybe).
- **Applies for you** (Autopilot, opt-in): fills in application forms in a hidden browser and submits them.
- **Asks you only what it doesn't know**, as one chat message with buttons, and remembers your answer for
  every later form.

Your data stays on your machine. AI can be free (Gemini or Groq free tiers, OpenRouter free models,
local Ollama) or use a Claude Code or Codex subscription you already have.

---

## 2. Install

| Where | How |
|---|---|
| **Laptop** (Windows, macOS, Linux) | `pip install "openhunt[boards,apply] @ git+https://github.com/sreesayanth/OpenHunt"` then `openhunt`. Open `http://localhost:8080`. On Windows, if `openhunt` says *Access is denied*, use `python -m openhunt`. |
| **VM** (no browser) | Same install, then `openhunt setup` (paste your bot token, scan the QR code), then `openhunt --no-web` under tmux or a systemd service. |
| **Docker** | `docker build -t openhunt .` then `docker run -d --name openhunt --restart unless-stopped -p 127.0.0.1:8080:8080 -v openhunt-data:/data openhunt`. Chromium is included. |
| **Android (Termux)** | `pkg install python python-cryptography`, `pip install "openhunt @ git+https://github.com/sreesayanth/OpenHunt"`, `openhunt setup && openhunt --no-web`, and `termux-wake-lock`. Searching and alerts work. **Applying doesn't** (phones can't run the browser it uses). |

The install extras:
- `boards`: LinkedIn, Indeed and Naukri search (python-jobspy). Heavy, so it's optional.
- `apply`: the hidden browser for applying (Playwright). Optional, because OpenHunt downloads it by itself
  the first time you apply or connect a site (about 150 MB, once).

---

## 3. First setup

Two steps on the setup page (or `openhunt setup` on a VM):
1. **Telegram**: make your own bot with @BotFather and paste its token.
2. **AI**: one click with OpenRouter, a free Gemini or Groq key, local Ollama, or your Claude Code / Codex.

Then scan the QR code with your phone. Everything else is a short chat with the bot:
1. Send your CV (PDF or Word), or tap **I don't have a CV** and describe yourself in a few lines.
2. Confirm what it understood (skills, experience).
3. Job titles to search for (it suggests some).
4. Where: cities, **Remote**, or **Anywhere**.
5. Minimum salary (or skip).
6. When to search: every morning, twice a day, or every hour.
7. **"Want me to apply for you?"** Tap **Yes** for Autopilot, or **No** to apply yourself.

The first search runs right away.

---

## 4. Everyday use

Each job arrives as a card:

```
🟢 Great match · 92/100
Data Analyst
🏢 Razorpay · 📍 Bangalore
✅ SQL, Python and Power BI match
⚠️ Missing: dbt
[🤖 Apply for me] [🔗 Open]
[⭐ Save] [👎 Not for me]
```

- **🤖 Apply for me**: OpenHunt applies to this one job now, at any hour.
- **Paste any job link** in the chat (or `/apply <link>`): it applies to that job too.
- **⭐ Save** jobs, then `/saved` → **🤖 Apply to all saved**.
- Type changes in plain words at any time: *"my notice period is now 30 days"*,
  *"my expected salary is 15 LPA"*, *"I don't need visa sponsorship"*. Each comes with an **↩️ Undo** button.
- Send a new CV whenever you like. Your profile, the search and the CV attached to applications update.

---

## 5. Autopilot: applying for you

Turn it on at the end of setup or with `/autopilot`.

**What happens**
1. After every search, new jobs scoring at or above your Autopilot score (default **70**) are queued.
2. A background worker applies to them **one at a time, 1–3 minutes apart, between 9:00 and 21:00 your time**.
3. On each form it fills what it knows (§6). The AI writes "Why do you want to join us?" answers and
   cover letters from your real CV. Anything new becomes a question in the chat, and that job waits while
   others continue.
4. When you answer, the waiting jobs carry on straight away, even late at night.
5. You get **"✅ Applied: Data Analyst · Acme"** with a 🧾 Proof button (a screenshot plus every answer sent),
   or only an **evening summary** if you prefer quiet.

**Where it applies**

| Site | Login needed | Notes |
|---|---|---|
| Company career sites: Greenhouse, Lever, Ashby and most others | No | Safest. Embedded forms and "Apply" buttons are followed. |
| LinkedIn Easy Apply | Yes (`/sites`) | Multi-step pop-up. "Follow company" is unticked. Jobs with an outside **Apply** go to the company's own site. |
| Naukri | Yes (`/sites`) | Includes Naukri's question chat. |
| Indeed, Glassdoor, ZipRecruiter, Wellfound | n/a | Block bots: you get an **Apply yourself** link. |
| Workday, Taleo, iCIMS, SuccessFactors | n/a | Need an account per company: **Apply yourself** link. |

When a job board also gives the company's own application link, OpenHunt applies there instead of on
LinkedIn or Naukri: no login is needed and there's no risk to your account.

**Limits** (they protect your accounts)
- One application at a time, a few minutes apart, only during active hours (your own requests skip this).
- Per day: LinkedIn 15, Naukri 25, Greenhouse/Lever/Ashby 40, other sites 20.
- Never applies to the same job twice, even if it's posted on two sites.
- Failed attempts are retried later, up to 3 times.
- A CAPTCHA or "unusual activity" check stops that application and sends you a screenshot with
  **🔗 Open & finish it myself**, **🔁 Try again** and **⏭ Skip**.

**No CV file?** If you set up by describing yourself, OpenHunt makes a plain one-page PDF CV from what you
told it (nothing invented), attaches that, and tells you once. Send your real CV any time.

`/applied` lists every application: ✅ applied, ❓ waiting for you, ⚠️ needs you, 🔐 needs a login,
🔗 apply yourself, 🚫 closed, ❌ failed. Each has Retry, Open or Proof buttons as fits.

---

## 6. Questions and the answer memory

**Where answers come from**, in order:
1. What **you** told it in the chat, first for this company and then for every company.
2. **Your CV**: name, email, phone, city, LinkedIn/GitHub/portfolio, current job, degree, school,
   graduation year, total years and **years per skill** (worked out from job dates).
3. **Safe defaults**: diversity questions (gender, race, disability, veteran) → *Prefer not to say*;
   "How did you hear about us?" → the site name; "Were you referred?" → No.
4. The **AI may only pick one of your saved answers** for a differently worded question, at 90%+ confidence.
   It never makes up an answer, and it's never used for salary, work authorization, visa, legal or
   self-identification questions.

**Same question, any wording.** "How many years of experience do you have with Tableau?", "Tableau
experience (years)" and "How long have you used Tableau?" are one question, asked once.

**One answer fits any form.** Answers are stored as values: *2 years* fills `2` in a number box and
`2-3` in a dropdown. *45 days* notice picks `30-60 days`. *12 LPA* becomes `12` in "Expected CTC (LPA)".
*Bangalore* matches *Bengaluru*. A salary in another currency is asked separately.

**Never guessed:** years with a skill that isn't in your CV, work authorization, visa sponsorship, salary,
criminal record, consent checkboxes, and questions about a specific company. These come from you, once.

**What a question looks like**
```
❓ Razorpay · Data Analyst asks:
How many years of experience do you have with Tableau?
[0] [1] [2] [3] [4] [5]
[6] [7] [8] [9] [10+]
[⏭ Skip this job]
```
Tap a button or type the answer. Questions come one at a time. Several jobs waiting on the same question
are asked once. If a site doesn't accept your answer as one of its choices, you pick the closest choice
for that company, and your real answer is still kept for everyone else.

**`/answers` (🧠 What I know about you)** lists everything, marked 📄 from your CV, 👤 you told me, or
⚙️ my default. Tap a number to change or forget it.

---

## 7. Job site logins

`/sites` (🔐 Job sites) connects LinkedIn and Naukri, all inside the chat:
1. LinkedIn first shows a short warning: its rules don't allow bots, so your account could get limited.
2. You type your email, then your password. **The bot deletes each message as soon as it reads it.**
3. If the site sends a code, type it in the chat. If it asks you to approve in its phone app, the bot
   tells you and waits up to 3 minutes.
4. *"✅ LinkedIn connected."* Then: **🔁 Remember my password?** If you say no, it's forgotten now. If you
   say yes, it's stored encrypted on your machine, so OpenHunt can log in again by itself.

Logins are checked every 6 hours. If a site logged OpenHunt out, it logs in again with a remembered
password, or sends you a one-tap **Log in again** button. A CAPTCHA during login is shown to you as a
screenshot; try again later. "Sign in with Google" isn't supported (Google blocks automated browsers).

---

## 8. Telegram commands

You rarely need these, because buttons cover everything.

| Command | What it does |
|---|---|
| `/autopilot` | Turn applying on or off, set the score (80+/70+/60+), each-application or summary-only messages |
| `/applied` | Applications sent, with proof |
| `/apply <link>` | Apply to a job link (or just paste the link) |
| `/today` | Best jobs right now |
| `/search` | Search now |
| `/saved` | Saved jobs, with **Apply to all saved** |
| `/profile` | Change job titles, places, salary, or send a new CV |
| `/schedule` | Every morning, twice a day, or every hour |
| `/pause` / `/resume` | Stop and start searching and applying |
| `/answers` | What I know about you |
| `/sites` | Log in to LinkedIn and Naukri |
| `/ai` | Connect or change the AI |
| `/status` | AI, schedule, last search, site logins, applied today |
| `/help` | All commands |

---

## 9. Settings

**Command line**

| Command | |
|---|---|
| `openhunt` | Start (web setup page + bot) |
| `openhunt --no-web` | Telegram only (VMs, Android) |
| `openhunt setup` | Terminal setup: paste the bot token, scan the QR |
| `openhunt reset` | Delete all data (asks you to type DELETE) |
| `--host`, `--port`, `-v` | Web address and port; verbose logs |

**Environment variables**

| Variable | Default | Meaning |
|---|---|---|
| `OPENHUNT_DATA` | `~/.openhunt` | Where everything is stored |
| `OPENHUNT_HOST` / `OPENHUNT_PORT` | `127.0.0.1` / `8080` | Setup page address (local only by default) |
| `OPENHUNT_AI_RANK_LIMIT` | `25` | Jobs per search scored by the AI after the free keyword filter |
| `OPENHUNT_TZ` | from your country | Your time zone for schedules, active hours and summaries, e.g. `Asia/Kolkata` |
| `OPENHUNT_CHROMIUM` | Playwright's own | Path to a Chromium to use instead of downloading one |

**Time zone.** Searches "every morning at 8", Autopilot's 9:00–21:00 and the 20:00 summary follow your
clock even on a VM set to UTC. The zone comes from `OPENHUNT_TZ`, then the job-search country (India →
`Asia/Kolkata`), then the machine.

**Autopilot defaults:** score 70+, one message per application, hours 9–21, daily limits as in §5.

---

## 10. Privacy, safety and site rules

- **Local only.** Database, CV, answers, saved logins and proof screenshots live in `OPENHUNT_DATA`.
  No telemetry.
- **Encrypted at rest:** bot token, AI key, remembered site passwords and saved site logins (cookies),
  all with the key in `secret.key`.
- **Only your linked Telegram account** can control the bot (a one-time link code).
- **Passwords** typed in the chat are deleted right away. Telegram bot chats aren't end-to-end encrypted,
  so a password passes through Telegram's servers for a moment; turn on two-step login on the job site.
- **Honest applications.** Factual answers come only from your CV or from you. The AI only writes essay
  answers, from your real CV. Job pages are treated as data, never as instructions to the bot.
- **The browser isn't disguised** and never tries to beat a CAPTCHA.
- **Site rules.** LinkedIn and Naukri don't allow automated use; your account there could get limited.
  OpenHunt warns you, goes slowly, and keeps daily limits. Company career sites have no such risk.
- `openhunt reset` deletes everything, including saved logins, answers, files and proof.

**Files in `OPENHUNT_DATA`**

| Path | What |
|---|---|
| `openhunt.db` | Jobs, matches, applications, answers, settings |
| `secret.key` | Encryption key (keep it private; losing it means re-entering tokens and logins) |
| `files/cv/` | Your CV file (or the generated one) |
| `files/forms/` | Files you sent for form questions |
| `files/proof/` | Screenshots of submitted applications |
| `browser/<site>.state` | Saved site login, encrypted |

---

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| *"Another program is using this Telegram bot"* | Another OpenHunt (another PC, VM or terminal) runs with the same bot. Stop it, or make a new bot. |
| *"Your AI connection stopped working"* | `/ai` to reconnect or switch. Free tiers hit limits; wait a few minutes or pick another. |
| Nothing is being applied to | `/autopilot`: is it ON? Are you inside active hours? Is the job's score above the Autopilot score? `/applied` shows each job's state. |
| *"Some good jobs are on LinkedIn. Log in once…"* | Tap it, or `/sites`. Until then those jobs wait and company-site jobs continue. |
| *"I got stuck applying to…"* (with a screenshot) | The site changed, a CAPTCHA appeared, or a field wasn't understood. **Open & finish it myself** or **Try again** later. Sending the screenshot to the developers helps fix it. |
| *"Applying needs a laptop or a VM"* | You're on Android. Searching works; applying doesn't. |
| First application takes minutes | The browser is downloading (about 150 MB, once). The bot says so. |
| Old jobs vanished after changing titles or CV | Intended: they were scored for the old profile. Saved jobs stay. |
| Wrong answer was sent | `/answers` → change it. `/applied` → 🧾 Proof shows exactly what each company got. |

---

## 12. For developers

```bash
pip install -e ".[boards,apply,dev]"
playwright install chromium      # or: export OPENHUNT_CHROMIUM=/path/to/chrome
pytest                           # about 90 tests, ~3 minutes; browser tests use tests/fakesite
```

**One process** (`openhunt/runtime.py`): the Telegram bot (long polling, no public URL), the web setup
page (FastAPI), the scheduler (python-telegram-bot's JobQueue), and the Autopilot worker, all on one
asyncio loop. SQLite via SQLModel; new columns are added to old databases automatically on start.

**Map of the code**

| Area | Files |
|---|---|
| Search and ranking | `hunt.py`, `sources/` (JobSpy boards, Greenhouse/Lever/Ashby APIs, Remotive), `ai/ranker.py`, `ai/profile.py` (CV → profile) |
| AI | `ai/llm.py` (any OpenAI-compatible API), `ai/cli_providers.py` (Claude Code / Codex, locked down), `ai/openrouter.py` |
| Telegram | `bot/app.py` (onboarding, commands, cards), `bot/scheduler.py`, `bot/apply_flow.py` (questions, `/answers`), `bot/login_flow.py` (`/sites`), `bot/autopilot.py` (worker, `/autopilot`, `/applied`, summary) |
| Answer memory | `apply/intents.py` (common questions in any wording), `apply/values.py` (typed values, fitting to fields), `apply/answers.py` (resolve a field: saved → CV → default → AI pick), `apply/fields.py` |
| Applying | `apply/forms.py` (read and fill any form), `apply/engine.py` (page loop, essays, proof), `apply/adapters/` (generic, Greenhouse, Lever, Ashby, LinkedIn, Naukri), `apply/queue.py` (order, limits, hours), `apply/cvpdf.py`, `apply/essay.py` |
| Browser and logins | `apply/browser.py` (shared headless Chromium, encrypted logins), `apply/login.py` (step-by-step login driver), `apply/sites/` (LinkedIn, Naukri login details) |
| Storage | `store.py` (Job, Match, Application, Answer, PendingQuestion, encrypted settings), `config.py`, `timeutil.py` |

**How an application runs**
```
queue.next_ready() → autopilot.process()
  → BROWSER.page(site) → engine.apply(page, adapter, job)
      adapter.open()            go to the form (or "closed" / "already" / "redirect:<url>")
      loop: forms.read_form()   every question on the page
            answers.resolve()   fill | essay | skip | ask
            unknown? → Outcome("waiting", questions) → apply_flow.ask() → user answers
                     → autopilot.on_answer() requeues the job
            adapter.next()      Next / Review / Submit
            adapter.state()     done only after submit, with a thank-you and no form left
  → Outcome → autopilot.handle(): ✅ message + proof, or a question, a login nudge, or "stuck" with a screenshot
```

**Adding a site.** Most career sites work with the generic adapter. For one that doesn't, subclass
`apply/adapters/base.Adapter`: set `hosts`, and override `form_url()` (where the form lives), `open()`
(how to reach it), `next()` (its buttons) or `state()` (its success message) only as needed. Register it
in `apply/adapters/__init__.py`, add a copy of its form under `tests/fakesite/pages/` with a route in
`tests/fakesite/__init__.py`, and a test in `tests/test_engine.py`. Sites that need a login also get an
entry in `apply/sites/`.

**Adding a common question.** Add an `Intent` to `apply/intents.py` (wordings as regexes, value kind,
`sensitive=True` if it must never be AI-matched), and where it can come from the CV, a branch in
`answers._derived()`. Test the wordings in `tests/test_answers.py`.

**Rules the code keeps**
- Never submit in tests against real sites: use `engine.apply(..., dry_run=True)`.
- Never add bot-detection evasion or CAPTCHA solving.
- Facts come from the CV or the user; the AI only picks among saved answers or writes essays.

---

## 13. Status and known limits

**Working:** search and ranking, Telegram control, the answer memory, chat logins, and applying on
company career sites, LinkedIn Easy Apply and Naukri. There are about 90 automated tests.

**Not yet tested on the live sites.** Applying and logins were built and tested against local copies of
each site's form (`tests/fakesite`). Real LinkedIn, Naukri, Greenhouse, Lever and Ashby pages may differ;
if OpenHunt gets stuck it sends a screenshot, which is what's needed to fix it.

**Known limits**
- CAPTCHAs are handed to you (a screenshot plus a link); solving them inside Telegram is planned.
- Indeed, Glassdoor and account-per-company sites (Workday, Taleo, iCIMS) are left to you.
- "Sign in with Google" logins aren't supported.
- The company **watchlist** (`greenhouse:stripe`, `lever:netflix`…), the job-search **country** and a
  **time zone** preference can't be set from Telegram yet. The time zone can be set with `OPENHUNT_TZ`.
- Applying doesn't run on Android/Termux.

See [AUTO_APPLY_PLAN.md](AUTO_APPLY_PLAN.md) for the Autopilot design and [PROJECT_PLAN.md](PROJECT_PLAN.md)
for the overall roadmap.
