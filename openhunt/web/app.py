"""Web setup wizard + tiny dashboard. Two steps, then everything continues in Telegram."""

from html import escape

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from openhunt import store
from openhunt.ai import cli_providers, llm, openrouter
from openhunt.ai.ranker import label
from openhunt.bot import scheduler
from openhunt.bot.app import allowed_chats, new_link_code
from openhunt.hunt import run_hunt
from openhunt.web.layout import page


def qr_svg(data: str) -> str:
    return qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8).to_string(encoding="unicode")


def ai_done() -> bool:
    return llm.is_configured() or bool((store.get("onboarding") or {}).get("ai_skipped"))


def create_app(runtime) -> FastAPI:
    app = FastAPI(title="OpenHunt", docs_url=None, redoc_url=None)

    def go(path: str = "/") -> RedirectResponse:
        return RedirectResponse(path, status_code=303)

    @app.get("/", response_class=HTMLResponse)
    async def home():
        if not store.get("bot_token"):
            return page("Step 1 of 2 · Telegram", telegram_step())
        warn = (
            '<p class="error">⚠️ Another program is using this Telegram bot at the same time, so messages may get '
            "lost. Stop the other OpenHunt (another PC, VM or terminal), or make a new bot for this one.</p>"
            if runtime.conflict else ""
        )
        if not ai_done():
            return page("Step 2 of 2 · AI", warn + ai_step())
        if not allowed_chats():
            return page("Last step · Link your phone", warn + link_step())
        return page("Dashboard", warn + dashboard())

    # ----- step 1: telegram -----

    @app.post("/setup/telegram")
    async def save_token(token: str = Form(...)):
        from openhunt.runtime import check_token

        token = token.strip()
        try:
            await check_token(token)
        except ValueError as exc:
            return page("Step 1 of 2 · Telegram", telegram_step(error=str(exc)))
        store.put("bot_token", token)
        await runtime.start_bot(token)
        return go()

    # ----- step 2: AI -----

    @app.get("/ai/openrouter")
    async def openrouter_start(request: Request):
        callback = str(request.url_for("openrouter_callback"))
        url, verifier = openrouter.start(callback)
        store.update("onboarding", web_or_verifier=verifier)
        return RedirectResponse(url)

    @app.get("/ai/openrouter/callback", name="openrouter_callback")
    async def openrouter_callback(code: str = ""):
        verifier = (store.get("onboarding") or {}).get("web_or_verifier", "")
        try:
            llm.configure("openrouter", await openrouter.exchange(code, verifier))
        except Exception as exc:  # noqa: BLE001
            return page("Step 2 of 2 · AI", ai_step(error=f"OpenRouter connection failed: {exc}"))
        return await finish_ai()

    @app.post("/ai/key")
    async def ai_key(provider: str = Form(...), key: str = Form("")):
        if provider not in llm.PROVIDERS:
            return go()
        llm.configure(provider, key.strip())
        return await finish_ai()

    @app.post("/ai/skip")
    async def ai_skip():
        store.update("onboarding", ai_skipped=True)
        return go()

    async def finish_ai():
        ok, info = await llm.test_connection()
        if not ok:
            store.delete("ai_provider")
            return page("Step 2 of 2 · AI", ai_step(error=f"The AI didn't answer: {info[:300]}"))
        return go()

    # ----- dashboard actions -----

    @app.get("/api/linked")
    async def linked():
        return JSONResponse({"linked": bool(allowed_chats())})

    @app.post("/run")
    async def run_now():
        result = await run_hunt()
        if runtime.bot_app:
            from openhunt.bot.app import report_hunt

            await report_hunt(runtime.bot_app.bot, result, manual=True)
        return go()

    @app.post("/pause")
    async def toggle_pause():
        sched = store.get("schedule") or {}
        store.update("schedule", paused=not sched.get("paused"))
        if runtime.bot_app:
            scheduler.apply_schedule(runtime.bot_app)
        return go()

    @app.post("/relink")
    async def relink():
        return page("Link another phone", link_step())

    return app


# ---------- page bodies ----------

def telegram_step(error: str = "") -> str:
    err = f'<p class="error">⚠️ {escape(error)}</p>' if error else ""
    return f"""
<h1>Connect Telegram</h1>
<p class="lead">Telegram is how OpenHunt talks to you. You'll make your own private bot. It takes about 1 minute.</p>
<ol class="steps">
  <li>Open <a href="https://t.me/BotFather" target="_blank" rel="noopener"><b>@BotFather</b></a> in Telegram (it's Telegram's official bot maker).</li>
  <li>Send <code>/newbot</code>.</li>
  <li>Give it any name, like <i>My Job Hunter</i>, and a username ending in <code>bot</code>, like <i>myname_jobs_bot</i>.</li>
  <li>BotFather replies with a long code, the <b>token</b>. Copy it, then tap <b>Paste</b> below.</li>
</ol>
{err}
<form method="post" action="/setup/telegram" id="tokform">
  <input name="token" id="token" placeholder="123456789:ABCdef..." autocomplete="off" required>
  <div class="row">
    <button type="button" class="secondary" id="paste">📋 Paste</button>
    <button type="submit">Continue →</button>
  </div>
</form>
<script>
const re = /\\d{{6,}}:[A-Za-z0-9_-]{{30,}}/;
const input = document.getElementById('token');
function tryToken(text) {{
  const m = (text || '').match(re);
  if (m) {{ input.value = m[0]; document.getElementById('tokform').submit(); }}
}}
document.getElementById('paste').onclick = async () => {{
  try {{ tryToken(await navigator.clipboard.readText()); }} catch (e) {{ input.focus(); }}
}};
input.addEventListener('paste', e => setTimeout(() => tryToken(input.value), 0));
</script>"""


def ai_step(error: str = "") -> str:
    err = f'<p class="error">⚠️ {escape(error)}</p>' if error else ""
    key_forms = "".join(
        f"""
<details class="card">
  <summary>🆓 {escape(llm.LABELS[p])}</summary>
  <p><a href="{llm.PROVIDERS[p][2]}" target="_blank" rel="noopener">Get your free key here</a>, sign in, create a key, then paste it:</p>
  <form method="post" action="/ai/key"><input type="hidden" name="provider" value="{p}">
    <input name="key" placeholder="Paste key" autocomplete="off" required><button type="submit">Connect</button></form>
</details>"""
        for p in ("gemini", "groq")
    )
    return f"""
<h1>Connect an AI</h1>
<p class="lead">The AI reads each job and tells you how well it fits you, like a career advisor.</p>
{err}
<a class="big" href="/ai/openrouter">⚡ Connect in 1 click <small>with OpenRouter · sign in with Google</small></a>
{key_forms}
{cli_card()}
<details class="card">
  <summary>💻 Local AI on this computer (free, private, needs 8 GB+ RAM)</summary>
  <p>Install <a href="https://ollama.com" target="_blank" rel="noopener">Ollama</a>, run <code>ollama pull llama3.2</code>, then:</p>
  <form method="post" action="/ai/key"><input type="hidden" name="provider" value="ollama"><button type="submit">Use local AI</button></form>
</details>
<details class="card">
  <summary>🔑 I have an OpenAI or Claude key</summary>
  <form method="post" action="/ai/key">
    <select name="provider"><option value="openai">OpenAI</option><option value="anthropic">Claude</option></select>
    <input name="key" placeholder="Paste key" autocomplete="off" required><button type="submit">Connect</button></form>
</details>
<form method="post" action="/ai/skip"><button class="link" type="submit">Skip for now (basic keyword matching)</button></form>"""


def cli_card() -> str:
    found = cli_providers.installed()
    if found:
        buttons = "".join(
            f'<form method="post" action="/ai/key"><input type="hidden" name="provider" value="{p}">'
            f'<button type="submit">Use {escape(llm.LABELS[p])}</button></form>'
            for p in found
        )
        body = f'<p>Found on this computer. It uses your existing plan, with no key needed.</p><div class="row">{buttons}</div>'
    else:
        body = (
            "<p>Install <b>Claude Code</b> or <b>Codex</b> on this computer and log in once, then reload this page. "
            "OpenHunt will use your existing subscription.</p>"
        )
    return f'<details class="card"{" open" if found else ""}><summary>🧑‍💻 I have Claude Code or Codex</summary>{body}</details>'


def link_step() -> str:
    username = store.get("bot_username", "")
    url = f"https://t.me/{username}?start={new_link_code()}"
    return f"""
<h1>Open your bot on your phone</h1>
<p class="lead">Scan with your phone camera, or tap the button. Then press <b>Start</b> in Telegram.</p>
<div class="qr">{qr_svg(url)}</div>
<a class="big" href="{escape(url)}" target="_blank" rel="noopener">Open @{escape(username)} in Telegram</a>
<p class="muted" id="wait">Waiting for you to press Start…</p>
<script>
setInterval(async () => {{
  const r = await fetch('/api/linked'); const d = await r.json();
  if (d.linked) {{ document.getElementById('wait').textContent = '✅ Linked! Continue in Telegram.'; setTimeout(() => location.href = '/', 1500); }}
}}, 2000);
</script>"""


def dashboard() -> str:
    last = store.get("last_run") or {}
    sched = store.get("schedule") or {}
    rows = "".join(
        f"""<tr><td><span class="pill">{m.score}</span></td>
<td><a href="{escape(j.url)}" target="_blank" rel="noopener">{escape(j.title)}</a><br><small>{escape(j.company)} · {escape(j.location)}</small></td>
<td><small>{escape(label(m.score))}<br>{escape(m.reasons)}</small></td></tr>"""
        for m, j in store.recent_matches(20)
    ) or '<tr><td colspan="3" class="muted">No jobs yet. Finish setup in Telegram, or press "Search now".</td></tr>'
    return f"""
<h1>Your job hunt</h1>
<div class="stats">
  <div><b>{escape(scheduler.describe())}</b><small>Schedule</small></div>
  <div><b>{escape(llm.describe().split(' · ')[0] if llm.is_configured() else 'Basic (no AI)')}</b><small>AI</small></div>
  <div><b>{escape(last.get('at', 'never')[:16].replace('T', ' '))}</b><small>Last search · {last.get('new', 0)} new</small></div>
</div>
<div class="row">
  <form method="post" action="/run"><button type="submit">🔎 Search now</button></form>
  <form method="post" action="/pause"><button class="secondary" type="submit">{'▶️ Resume' if sched.get('paused') else '⏸ Pause'}</button></form>
  <form method="post" action="/relink"><button class="secondary" type="submit">📱 Link another phone</button></form>
</div>
<table>{rows}</table>
<p class="muted">Tip: everything here also works from Telegram. Send <code>/help</code> to your bot.</p>"""
