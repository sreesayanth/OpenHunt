# OpenHunt — Self-Hosted AI Job Hunter (Project Plan)

> An open-source job-hunting platform that runs on your own PC or VM, searches jobs on a schedule,
> ranks them against your CV with AI, writes tailored CVs and cover letters, and is controlled from
> **Telegram** or a simple web page. Setup should feel like installing an app, not running a dev project.

---

## 1. Research summary

### 1.1 Reference project: `ai-job-search-dev/ai-job-search`
What it does well:
- Builds a profile from your CV and documents (`/setup`).
- Scrapes several job portals, removes duplicates and ranks them by fit (`/scrape`, `/rank`).
- Has an apply pipeline: checks the posting, evaluates fit, drafts a CV and cover letter, has a second AI agent review them, then compiles the PDFs and runs an ATS check (`/apply`).
- Covers interview prep, outcome tracking, Gmail and Notion sync, an HTML dashboard, skill-gap planning, and a way to add new portals.
- Has a strong "don't invent experience" rule, and treats job postings as untrusted input.

Where it falls short, and where we can do better:

| Gap in reference | Why it matters | OpenHunt answer |
|---|---|---|
| Needs a paid **Claude Code** subscription | Many people can't afford it | Works with **any LLM**: free Gemini or Groq tiers, local **Ollama** (fully free), OpenAI, or Claude |
| No scheduler | You must run it by hand | Built-in scheduler: hourly, daily, or custom cron |
| No notifications or remote control | You can't use it from your phone | **Telegram bot** as the main interface |
| Mostly Danish portals | Not global | Global sources: JobSpy (LinkedIn, Indeed, Glassdoor, Google, Naukri…), ATS APIs, remote boards |
| Needs Python, Bun, LaTeX and the CLI | Hard for non-developers | One-click install (Docker or a Windows installer) plus a web setup wizard |
| Personal data lives in git-tracked files | Easy to leak a CV | Data lives in a local database outside git |

### 1.2 Similar open-source tools
- **JobNavigator**: Docker, scrapes career pages and LinkedIn, scores jobs against your CV, sends Telegram alerts.
- **autopilot-jobhunt**: scans 130+ career pages nightly, LLM score from 0 to 100, Telegram alerts, cover letters.
- **JobHunter (kevynlad)**: JobSpy, Gemini scoring, Telegram inline buttons.

None of these combines everything: global sources, any LLM, the full apply and interview pipeline, Telegram control, and an installer that non-technical people can use. **That combination is the product.**

### 1.3 Job data sources (legal-first)
| Source | Method | Notes |
|---|---|---|
| Greenhouse | Public JSON API `boards-api.greenhouse.io/v1/boards/<co>/jobs` | No auth needed. Very reliable. |
| Lever | `api.lever.co/v0/postings/<co>?mode=json` | No auth needed |
| Ashby | `api.ashbyhq.com/posting-api/job-board/<co>` | Can include salary data |
| Workday / SmartRecruiters | Public career-site JSON | Per company |
| Adzuna | Official API with a free key | Covers about 19 countries |
| Remotive, RemoteOK, Arbeitnow, Jobicy | Public APIs or RSS | Remote jobs |
| LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter, Naukri, Bayt | `python-jobspy` library | Low volume and personal use only. These sites block heavy use. |
| Any career page | Generic scraper plugin plus AI extraction | Respect robots.txt |
| Pasted URL or text | Manual input | Fallback when a site blocks bots |

**Rule:** OpenHunt **never auto-submits** applications on LinkedIn or Indeed, because that breaks their terms and gets accounts banned. It prepares everything and sends you a one-tap "Open and apply" link instead. Optional auto-fill for plain ATS forms (Greenhouse, Lever) is a later, opt-in feature that always asks you to confirm.

> **Update:** an opt-in auto-apply mode ("Autopilot") is now planned. It is run entirely from the Telegram chat, with daily limits, and a person solves every CAPTCHA. See [AUTO_APPLY_PLAN.md](AUTO_APPLY_PLAN.md).

---

## 2. Product vision

**"Tell it what job you want once. Every morning, Telegram shows you the 5 best new jobs, each with a tailored CV ready."**

Target users: students, job seekers in any country, career switchers, and developers who want to self-host. A user must be able to start **without knowing what Docker, Python or an API key is**. There is a free local AI mode for that.

### Ease-of-use principles
1. **One install step.** Windows `.exe` installer, macOS `.dmg`, or `curl | sh` on a Linux VM, plus a Docker image.
2. **Setup wizard in the browser** (`http://localhost:8080`): upload your CV, pick job titles and locations, connect Telegram by scanning a QR code, pick an AI provider (default: free).
3. **Telegram is the remote control.** Buttons, not commands, for everything. Commands exist for power users.
4. **Plain-language settings.** "Check for jobs: every morning at 8" instead of a cron expression (cron is still available under Advanced).
5. **Safe defaults.** Nothing is sent or submitted without your tap. Your data stays on your machine.
6. **Multi-language UI** (English, Hindi, Spanish, Arabic…), since jobs are global.

---

## 2.1 UX for non-technical users (decided)

The hardest parts for normal people are **copying tokens and keys**, **terminals**, and **jargon**. Each one gets a fix:

| Pain point | Easy-UX fix |
|---|---|
| Too many setup screens | **Only 2 setup steps** (link Telegram, connect AI). Everything else happens **as a chat in Telegram**. |
| Telegram bot token | Guided BotFather steps with screenshots and a suggested bot name. The wizard **detects the token from the clipboard**, so no exact copying is needed, and validates it instantly. |
| AI API keys | **"Connect AI in one click"** through OpenRouter OAuth (log in → Allow → done, no key copying). Free Gemini (guided link) and local Ollama remain alternatives. OpenHunt checks RAM and only suggests local AI when the machine can handle it. |
| Gmail App Passwords | Optional. The easy alternative: **forward or share any job email or screenshot to the bot** and the AI updates the status. |
| No CV ready | The bot **builds a CV through chat**: about 10 simple questions, answered by text or voice note. |
| VM needs SSH tunnels | On a VM, the install script asks just one question, *"Paste your Telegram bot token"*, and all other setup happens in Telegram. No web port needed. |
| Jargon ("score 0.82", "cron") | Plain words: 🟢 Great match / 🟡 Good / ⚪ Maybe. Schedule buttons: "Every morning", "Twice a day", "Every hour". |
| "Is it working?" | The first search runs **right after setup**, so the first results appear within minutes. The bot reports problems in plain language ("Your AI connection stopped working. Tap to fix."). |
| Fear of breaking things | Nothing is ever sent or applied without a tap. **Pause** is always one tap away, and a **reset** wipes everything. |
| Language | The bot replies in the user's language and understands voice notes. |
| Laptop was asleep | Missed searches run on wake ("Your laptop was off, so I caught up: 6 new jobs"). |

**Onboarding flow (Telegram chat after linking):**
1. "Hi! Send me your CV (PDF or photo), or tap **I don't have one**."
2. "I found: *Data Analyst, 2 yrs, SQL, Power BI*. Correct? [✅ Yes] [✏️ Fix]"
3. "What jobs do you want?" (AI suggests: [Data Analyst] [BI Developer] [+ Add])
4. "Where?" [My city] [Remote] [Anywhere in India] [Type…]
5. "Minimum salary?" [Skip] [Type…]
6. "When should I send jobs?" [🌅 Every morning] [☀️🌙 Twice a day] [⏰ Every hour]
7. "Searching now… 🔎" → first job cards arrive.

## 3. Full feature list

### 3.1 Profile and onboarding
- Upload a CV (PDF, DOCX, image) and the AI extracts skills, experience, education and languages into a structured profile.
- Optionally import from a LinkedIn profile export, GitHub, or a portfolio URL (the reference project's `/expand`).
- Short chat interview to fill gaps: salary, notice period, remote preference, visa needs.
- **Deal-breakers**: e.g. "no night shifts", "minimum salary 8 LPA", "no relocation".
- Several **search profiles**, e.g. "Data Analyst – Bangalore" and "Remote Python Dev".

### 3.2 Job discovery (scheduled)
- Scheduler per search profile (every N hours, daily at a set time, or custom cron).
- Pulls from all enabled sources in parallel, with rate limits, retries and proxy support.
- **Deduplication** across sites using a fuzzy title, company and location hash plus URL normalisation.
- **Expired-posting** detection, and re-checks before you apply.
- **Company watchlist**: "alert me when Google, Zoho or Swiggy post anything matching my profile".
- **Scam and ghost-job filter**: flags fee requests, vague companies, reposted-forever jobs, and WhatsApp-only contacts.

### 3.3 AI matching and ranking
- **Two-stage ranking** keeps costs low:
  1. A cheap local embedding similarity check filters 500 jobs down to the top 50 (free, runs on CPU).
  2. An LLM scores the top 50 on 5 dimensions (skills, seniority, location, salary, growth) and returns a score with a short reason.
- Deal-breaker veto, plus a language gate (e.g. "German C1 required" when you don't have it).
- Explanations: "87/100 — strong SQL and Power BI match; missing: Airflow".
- Learns from your feedback: 👍/👎 on Telegram adjusts future ranking.

### 3.4 Application kit
- **Tailored CV**: rewrites the summary and bullet order to match the posting, without inventing experience. Every claim maps back to a profile fact.
- **Cover letter** in your writing style.
- **Drafter and reviewer loop**: a second AI pass critiques the draft and the drafter revises (from the reference project).
- **ATS check**: keyword coverage report, checks that the PDF text is extractable, and checks the layout (CV max 2 pages, cover letter 1 page).
- PDF rendering with **Typst** (a small single binary, much easier to install than LaTeX). Several templates, and custom templates can be added.
- Short answers for common form questions ("Why do you want to work here?").
- Recruiter outreach message and LinkedIn note drafts (copy-paste only, never auto-sent).

### 3.5 Tracking
- Kanban pipeline: Found → Shortlisted → Applied → Interview → Offer / Rejected / Ghosted.
- Follow-up reminders ("Applied 7 days ago with no reply. Send a follow-up?" plus a ready draft).
- **Email sync** (Gmail or IMAP, opt-in): detects interview invites and rejections, then **proposes** status changes for you to approve.
- Export to CSV, Google Sheets or Notion.

### 3.6 Interview prep
- Prep pack per interview stage: company research summary, likely questions, STAR stories mapped to your profile.
- **Mock interview over Telegram** with text or voice notes. Whisper transcribes the answer and the AI gives feedback.
- Salary negotiation notes, using your own data or public ranges.

### 3.7 Growth
- Skill-gap heatmap across all jobs you liked ("Docker appears in 62% of your matches").
- Learning plan with free resources and time estimates.

### 3.8 Dashboard (web UI)
- Today's matches, pipeline board, stats (applications per week, response rate, average score).
- Settings, sources and API keys (stored encrypted), logs, scheduler status, and a "Run now" button.
- Works on mobile.

### 3.9 Telegram bot (main remote control)
Daily digest message, one card per job:
```
🟢 92/100 · Data Analyst · Razorpay · Bangalore (Hybrid)
₹12–18 LPA · posted 3h ago · via LinkedIn
✅ SQL, Python, Power BI   ⚠️ missing: dbt
[📄 Make CV] [⭐ Save] [👎 Not for me] [🔗 Open]
```
| Command | What it does |
|---|---|
| `/start` | Link the bot to your OpenHunt (one-time code or QR) |
| `/today` | Today's best matches |
| `/search <query>` | Run a search right now |
| `/apply <url or text>` | Build a CV and cover letter for any job (paste a link) |
| `/pipeline` | Application status summary |
| `/schedule` | View or change the schedule with buttons |
| `/pause`, `/resume` | Pause or resume all scheduled hunting |
| `/profiles` | Switch or edit search profiles |
| `/interview <job>` | Prep pack plus mock interview |
| `/stats` | Weekly report |
| `/settings` | Min score, digest time, sources |
| `/status` | Health check: last run, errors, AI quota |

- Only the linked Telegram user IDs can control the bot (allowlist).
- Sends PDFs directly in chat.
- Urgent alerts ("a 95+ match was just posted") arrive instantly. Everything else goes into the digest.
- Optional Discord, Slack, email or ntfy notifications through the same notifier interface.

### 3.10 Extensibility
- **Source plugins**: one Python file per job board that implements `search(query) -> list[Job]`. There is a community plugin registry, and an AI "add a portal" helper generates a plugin from a site URL.
- **Template plugins** for CV and cover-letter designs.
- **LLM providers** through LiteLLM, so 100+ providers work with one config line.
- **MCP server**: exposes OpenHunt to Claude Desktop, Claude Code and other agents ("Claude, what are my top jobs today?"). This keeps compatibility with the reference project's workflow.
- REST API and webhooks.

---

## 4. Architecture

```
            ┌──────────── Your PC / VM (one Docker container or one app) ────────────┐
 Telegram ◄─┤  Telegram Bot ─┐                                                        │
            │                ▼                                                        │
 Browser ◄──┤  Web UI ──► FastAPI core ──► Job Service ──► Source plugins ──► Internet │
            │   (HTMX)        │    │            │           (JobSpy, ATS APIs, RSS)    │
 Claude ◄───┤  MCP server ────┘    │            ▼                                      │
            │                      │       Ranker (embeddings → LLM via LiteLLM)       │
            │   Scheduler (APScheduler) ──► jobs queue        │                       │
            │                      │                          ▼                       │
            │                      └──► SQLite DB  ◄── Document builder (Typst → PDF) │
            │                           + /data folder (CVs, PDFs, encrypted keys)    │
            └─────────────────────────────────────────────────────────────────────────┘
                       ▲ optional: Ollama (local AI) · Gmail/IMAP · Notion
```

**One process by default** (simple), with a worker mode for heavy users:
- `openhunt run` starts the web UI, bot, scheduler and worker together.
- Advanced: `docker compose` with separate `web`, `worker` and `postgres` services.

### Tech stack
| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Best scraping and AI ecosystem. JobSpy is Python. |
| API and web | FastAPI + Jinja2 + HTMX + Tailwind | No separate frontend build, so one binary is possible |
| Scheduler | APScheduler (SQLAlchemy job store) | Survives restarts and supports cron or interval |
| Database | SQLite (default) or Postgres (optional), via SQLModel | Zero setup |
| Telegram | `python-telegram-bot` v21 (long polling) | Long polling means no public URL or port forwarding, so it works behind home Wi-Fi |
| LLM | LiteLLM | Ollama, Gemini, Groq, OpenAI, Claude, OpenRouter |
| Embeddings | `fastembed` (ONNX, CPU) | Free, fast, no GPU needed |
| Scraping | python-jobspy, httpx, selectolax, optional Playwright | Covers APIs and HTML pages |
| PDF | Typst | Single binary, fast, nice templates |
| CV parsing | pypdf, python-docx, LLM structuring | |
| Voice | faster-whisper (optional) | Voice mock interviews |
| Secrets | Fernet encryption with a machine key | API keys are never stored in plain text |
| Packaging | Docker image, PyInstaller Windows installer, `pipx`, Linux install script | "Easy for everyone" |
| CI | GitHub Actions: tests, lint, image build, release | |

---

## 5. Data model (core tables)

```
User(id, name, email, telegram_chat_id, locale, timezone)
Profile(id, user_id, raw_cv_text, structured_json, deal_breakers_json, writing_style)
SearchProfile(id, user_id, name, titles[], locations[], remote, min_salary,
              sources[], schedule_cron, min_score_alert, active)
Job(id, fingerprint UNIQUE, source, url, title, company, location, remote,
    salary_min, salary_max, currency, description, posted_at, scraped_at,
    expires_at, is_scam_flag)
Match(id, job_id, search_profile_id, embed_score, llm_score, dimension_scores_json,
      reasons, missing_skills[], user_feedback, notified_at)
Application(id, job_id, status, applied_at, cv_pdf_path, cover_pdf_path,
            ats_report_json, notes, next_followup_at)
Event(id, application_id, type, date, source_email_id, details)
Run(id, search_profile_id, started_at, finished_at, jobs_found, new_jobs, errors)
Setting(key, value_encrypted)
```

---

## 6. Folder structure

```
openhunt/
├── openhunt/
│   ├── main.py              # `openhunt run` entrypoint
│   ├── config.py
│   ├── db/                  # models, migrations (alembic)
│   ├── sources/             # plugins: jobspy.py, greenhouse.py, lever.py, ashby.py,
│   │                        #          adzuna.py, remotive.py, generic_page.py
│   ├── pipeline/            # dedupe.py, scam_filter.py, ranker.py, embedder.py
│   ├── ai/                  # llm.py (LiteLLM), prompts/, guardrails.py
│   ├── documents/           # cv_builder.py, cover_letter.py, ats_check.py, templates/*.typ
│   ├── scheduler/           # jobs.py, scheduler.py
│   ├── bot/                 # telegram handlers, keyboards, digest formatter
│   ├── web/                 # FastAPI routes, templates (HTMX), static
│   ├── integrations/        # gmail.py, imap.py, notion.py, sheets.py
│   ├── interview/           # prep.py, mock.py, voice.py
│   └── mcp/                 # MCP server
├── plugins/                 # community source/template plugins
├── installer/               # windows (Inno Setup), linux install.sh, macOS
├── docker/                  # Dockerfile, docker-compose.yml
├── tests/
├── docs/
└── README.md
```

---

## 7. Installation experience (target)

**Windows or Mac (non-technical users):** download `OpenHunt-Setup.exe`, double-click, and the browser opens on the setup wizard. A tray icon shows that it is running and starts with Windows.

**Linux VM:**
```bash
curl -fsSL https://openhunt.dev/install.sh | sh
```

**Docker:**
```bash
docker run -d --name openhunt -p 8080:8080 -v openhunt-data:/data ghcr.io/openhunt/openhunt
```

**Wizard (5 steps, about 3 minutes):**
1. Upload CV → review the extracted profile.
2. What jobs? (titles, cities or remote, salary) with AI suggestions for related titles.
3. Choose AI: **Free local (Ollama)** · **Free cloud (Gemini/Groq key, with a guided link)** · Paid (OpenAI/Claude).
4. Connect Telegram: tap the link → `/start` in the bot → done (the user can make their own bot through BotFather with a guided walkthrough).
5. Schedule: "Every morning at 8:00" → **Start hunting**.

---

## 8. Safety, privacy and legal
- All data stays local, with no telemetry by default.
- Job descriptions are untrusted input. A prompt-injection guard strips instructions such as "ignore previous instructions" before text reaches the LLM.
- No fabrication: each generated claim must cite a profile fact, and the reviewer pass rejects unsupported claims.
- Rate limits per source, robots.txt respected, and a clear warning on LinkedIn and Indeed use.
- No auto-submission of applications, emails or messages without explicit approval.
- Telegram allowlist, a web UI password, and optional HTTPS with Caddy for VM exposure.
- A `reset` option wipes all personal data.

---

## 9. Roadmap

| Phase | Duration | Deliverable |
|---|---|---|
| **0. Skeleton** | Week 1 | Repo, FastAPI, SQLite models, config, Docker, CI |
| **1. MVP hunt** | Weeks 2–3 | CV upload and parsing, JobSpy + Greenhouse/Lever/Remotive sources, dedupe, embedding and LLM ranking, scheduler, **Telegram digest and core commands** |
| **2. Apply kit** | Weeks 4–5 | Tailored CV and cover letter (Typst), reviewer loop, ATS check, PDFs sent in Telegram |
| **3. Web UI and wizard** | Weeks 6–7 | Setup wizard, dashboard, pipeline board, settings |
| **4. Easy install** | Week 8 | Windows installer, install.sh, GHCR image, docs, **v1.0 release** |
| **5. Tracking+** | Weeks 9–10 | Gmail/IMAP sync, follow-ups, Notion/Sheets export, scam filter |
| **6. Interview and growth** | Weeks 11–12 | Prep packs, Telegram mock interviews (voice), skill-gap plan |
| **7. Ecosystem** | Ongoing | Plugin registry, AI "add a portal", MCP server, more languages, Discord/Slack |

**MVP definition of done:** a fresh user installs it, uploads a CV, connects Telegram, and the next morning receives ranked jobs with a one-tap "Make CV" button that returns a PDF.

---

## 10. What makes it "the best"
1. **Free to run:** local AI plus free sources, so it costs nothing.
2. **Phone-first:** the whole job hunt runs from Telegram.
3. **Global:** works in India, the US, the EU, the Gulf and for remote jobs out of the box.
4. **Honest AI:** no invented experience, explained scores, scam filter.
5. **Truly easy:** an installer and a wizard, no terminal needed.
6. **Open and extendable:** plugins, any LLM, and an MCP server for AI agents.
