# 🎯 OpenHunt

**Your own AI job hunter. It searches jobs for you every day and sends the best ones to your Telegram.**

- Searches LinkedIn, Indeed, remote job boards and company career pages
- Reads every job with AI and tells you how well it fits *you*, in plain words
- Runs on your laptop, a VM, or an old Android phone. Your data stays with you.
- **🤖 Autopilot: it applies for you.** Good matches are applied to in the background. When a form asks something new, you get one question in the chat. You answer once, and every later form that asks the same thing is filled by itself.
- Control everything from Telegram: search, save, pause, change what you're looking for
- Free to run: use a free AI (Gemini, Groq, OpenRouter free models) or local AI (Ollama)
- Already pay for **Claude Code** or **Codex**? OpenHunt can use them, with no API key needed. They run locked down: Claude Code with every tool switched off, Codex in its read-only sandbox.

> Status: early MVP. Searching, ranking and applying for you (Autopilot) work. Tested against local copies of each site's form; real-site testing is in progress. See [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) and [docs/AUTO_APPLY_PLAN.md](docs/AUTO_APPLY_PLAN.md).

## Start in 3 minutes

### On your laptop
```bash
pip install "openhunt[boards] @ git+https://github.com/sreesayanth/OpenHunt"
openhunt
```
If Windows says *"Access is denied"* when you run `openhunt`, use `python -m openhunt` instead.

Open `http://localhost:8080` in your browser. Follow the two steps there:
1. **Telegram:** make your own bot with @BotFather and paste its token
2. **AI:** one click with OpenRouter, a free Gemini key, local Ollama, or your Claude Code / Codex subscription

Then scan the QR code with your phone, and the bot asks you everything else (your CV, what jobs, where, when).

### On a VM (no browser needed)
```bash
pip install "openhunt[boards] @ git+https://github.com/sreesayanth/OpenHunt"
openhunt setup        # paste your bot token, scan the QR
openhunt --no-web     # keep running (use a systemd service or tmux)
```

### With Docker
```bash
docker build -t openhunt .
docker run -d --name openhunt --restart unless-stopped -p 127.0.0.1:8080:8080 -v openhunt-data:/data openhunt
```

### On Android (Termux)
```bash
pkg install python python-cryptography
pip install "openhunt @ git+https://github.com/sreesayanth/OpenHunt"
openhunt setup && openhunt --no-web
```
Run `termux-wake-lock` so Android doesn't stop it. Use a cloud AI (not Ollama) on phones.

## Applying for you (Autopilot)
At the end of setup the bot asks *"Want me to apply for you?"*. Tap **Yes** and that's it.

- **Where:** company career sites (Greenhouse, Lever, Ashby and most others) with no login needed, plus LinkedIn Easy Apply and Naukri once you log in with `/sites` (all inside the chat).
- **What you do:** answer a question now and then (buttons, or type the answer). Your name, contact details, education and years per skill come from your CV. Diversity questions get "Prefer not to say". The AI writes "Why do you want to join us?" answers and cover letters from your real CV.
- **Any job, by hand:** tap **🤖 Apply for me** on a job card, or just paste a job link in the chat.
- **What you get:** one line per application (or only an evening summary), and `/applied` to see every application with a screenshot of what was sent.
- **Safety:** one job at a time, a few minutes apart, only 9:00–21:00, at most 15 a day on LinkedIn and 25 on Naukri. It never tries to get past a CAPTCHA. Instead it sends you a screenshot and a "finish it yourself" link.
- **No CV file?** It makes a simple one-page PDF from what you told it, and tells you so.
- Sites that block bots (Indeed, Glassdoor) or need an account per company (Workday, Taleo, iCIMS) are left to you, with an "Apply yourself" link.

## Telegram commands
| | |
|---|---|
| `/autopilot` | Turn applying for you on or off, choose the minimum match score, each-application or summary-only messages |
| `/applied` | Applications sent, with proof |
| `/apply <link>` | Apply to any job link (or just paste the link) |
| `/search` | Search now |
| `/today` | Best jobs right now |
| `/saved` | Jobs you starred |
| `/profile` | Change jobs, places, salary, or send a new CV |
| `/schedule` | Every morning, twice a day, or every hour |
| `/pause` / `/resume` | Stop and start automatic searching |
| `/sites` | Log in to LinkedIn or Naukri, all inside the chat, so I can apply there later |
| `/answers` | What I know about you: the answers I'll use on job forms. Change any of them, or just type *"my notice period is now 30 days"* |
| `/ai` | Connect or change AI |
| `/status` | Check everything works |

## Watch specific companies
Add company career boards to your preferences (`watchlist`), e.g. `greenhouse:stripe`, `lever:netflix`, `ashby:notion`.

## Safety
- Applying for you is **opt-in** (one tap at the end of setup, or `/autopilot`). It never posts or sends messages on your behalf, and it doesn't follow companies on LinkedIn. See [docs/AUTO_APPLY_PLAN.md](docs/AUTO_APPLY_PLAN.md).
- LinkedIn and Naukri don't allow bots, so your account there could get limited. OpenHunt warns you before you connect them and goes slowly. Company career sites have no such risk.
- Job searches on LinkedIn and Indeed are public, at low volume, for personal use, and need no login.
- Job site logins (`/sites`) are optional. You type your email and password in the chat, the bot deletes those messages at once, and the password is forgotten after login unless you tap "Remember it" (then it's stored encrypted). The saved login (cookies) is encrypted too. LinkedIn's rules don't allow bots, so the bot warns you before connecting it.
- Only Telegram accounts you linked with a one-time code can control your bot.
- API keys and tokens are stored encrypted in `~/.openhunt` (set `OPENHUNT_DATA` to move it).
- `openhunt reset` deletes everything.

## Development
```bash
pip install -e ".[boards,apply,dev]"
pytest   # browser tests need Chromium: `playwright install chromium`, or set OPENHUNT_CHROMIUM=/path/to/chrome
```

MIT licensed.
