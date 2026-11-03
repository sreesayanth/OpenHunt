# 🎯 OpenHunt

**Your own AI job hunter. It searches jobs for you every day and sends the best ones to your Telegram.**

- Searches LinkedIn, Indeed, remote job boards and company career pages
- Reads every job with AI and tells you how well it fits *you*, in plain words
- Runs on your laptop, a VM, or an old Android phone. Your data stays with you.
- Control everything from Telegram: search, save, pause, change what you're looking for
- Free to run: use a free AI (Gemini, Groq, OpenRouter free models) or local AI (Ollama)
- Already pay for **Claude Code** or **Codex**? OpenHunt can use them, with no API key needed. They run locked down: Claude Code with every tool switched off, Codex in its read-only sandbox.

> Status: early MVP (v0.1). The tailored CV and cover letter maker is next. See [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md).

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

## Telegram commands
| | |
|---|---|
| `/search` | Search now |
| `/today` | Best jobs right now |
| `/saved` | Jobs you starred |
| `/profile` | Change jobs, places, salary, or send a new CV |
| `/schedule` | Every morning, twice a day, or every hour |
| `/pause` / `/resume` | Stop and start automatic searching |
| `/answers` | What I know about you: the answers I'll use on job forms. Change any of them, or just type *"my notice period is now 30 days"* |
| `/ai` | Connect or change AI |
| `/status` | Check everything works |

## Watch specific companies
Add company career boards to your preferences (`watchlist`), e.g. `greenhouse:stripe`, `lever:netflix`, `ashby:notion`.

## Safety
- OpenHunt **never applies, posts or sends messages for you**. You tap "Open & apply" yourself.
- It never asks for your LinkedIn password. LinkedIn and Indeed are searched publicly, at low volume, for personal use.
- Only Telegram accounts you linked with a one-time code can control your bot.
- API keys and tokens are stored encrypted in `~/.openhunt` (set `OPENHUNT_DATA` to move it).
- `openhunt reset` deletes everything.

## Development
```bash
pip install -e ".[boards,dev]"
pytest
```

MIT licensed.
