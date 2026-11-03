"""Tiny client for any OpenAI-compatible chat API, plus local Claude Code / Codex CLIs.

Every API provider (OpenRouter, Gemini, Groq, Ollama, OpenAI, Anthropic) exposes an
OpenAI-compatible endpoint, so we avoid heavy SDKs and stay installable on Android/Termux.
"""

import asyncio
import json
import logging
import re

import httpx

from openhunt import store
from openhunt.ai import cli_providers

log = logging.getLogger(__name__)

# provider -> (base url, default model, where to get a key)
PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1", "openrouter/auto", "https://openrouter.ai/keys"),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-3.8-flash",
        "https://aistudio.google.com/apikey",
    ),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "https://console.groq.com/keys"),
    "ollama": ("http://localhost:11434/v1", "llama3.2", ""),
    "openai": ("https://api.openai.com/v1", "gpt-4.1-mini", "https://platform.openai.com/api-keys"),
    "anthropic": ("https://api.anthropic.com/v1", "claude-haiku-5-5", "https://console.anthropic.com/settings/keys"),
    # Local CLIs that use the user's own subscription (see cli_providers.py). Haiku keeps
    # Claude usage limits low; Codex uses its own default model.
    "claude_code": ("", "haiku", "https://claude.com/claude-code"),
    "codex": ("", "", "https://developers.openai.com/codex"),
}

LABELS = {
    "openrouter": "OpenRouter",
    "gemini": "Google Gemini (free tier)",
    "groq": "Groq (free tier)",
    "ollama": "Local AI (Ollama)",
    "openai": "OpenAI",
    "anthropic": "Claude",
    "claude_code": "Claude Code (your subscription)",
    "codex": "Codex (your ChatGPT plan)",
}

KEYLESS = {"ollama", *cli_providers.CLIS}


class AIError(Exception):
    pass


def configure(provider: str, api_key: str = "", model: str = "") -> None:
    store.put("ai_provider", provider)
    store.put("ai_api_key", api_key)
    store.put("ai_model", model or PROVIDERS[provider][1])


def is_configured() -> bool:
    provider = store.get("ai_provider")
    return bool(provider) and (provider in KEYLESS or bool(store.get("ai_api_key")))


def describe() -> str:
    provider = store.get("ai_provider")
    if not is_configured():
        return "not connected (using basic keyword matching)"
    model = store.get("ai_model")
    return f"{LABELS.get(provider, provider)} · {model}" if model else LABELS.get(provider, provider)


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        found = re.search(r"\{.*\}", text, re.S)
        if not found:
            raise AIError(f"AI did not return JSON: {text[:200]}")
        return json.loads(found.group(0))


async def chat(system: str, user: str, *, json_mode: bool = False, timeout: float = 90, retries: int = 2) -> str:
    provider = store.get("ai_provider")
    if not provider:
        raise AIError("No AI connected")
    if provider in cli_providers.CLIS:
        try:
            return await cli_providers.run(provider, system, user, store.get("ai_model") or "", timeout=max(timeout, 120))
        except cli_providers.CLIError as exc:
            raise AIError(str(exc)) from exc
    base = PROVIDERS[provider][0]
    headers = {"Content-Type": "application/json"}
    key = store.get("ai_api_key")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if provider == "openrouter":
        headers["X-Title"] = "OpenHunt"
    body = {
        "model": store.get("ai_model") or PROVIDERS[provider][1],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
    }
    if json_mode and provider in {"openai", "openrouter", "groq", "gemini", "ollama"}:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=timeout) as client:

        async def send(retries: int) -> httpx.Response | None:
            """POST with retries for busy/rate-limited answers. None means it timed out."""
            for attempt in range(retries + 1):
                try:
                    resp = await client.post(f"{base}/chat/completions", headers=headers, json=body)
                except httpx.TimeoutException:
                    resp = None
                status = resp.status_code if resp is not None else 0
                if (resp is not None and status not in RETRY_STATUS) or attempt == retries:
                    return resp
                # Free tiers allow few requests per minute (429) and get overloaded (503).
                wait = float(resp.headers.get("retry-after", 0) or 0) if resp is not None else 0
                await asyncio.sleep(min(wait or (20 if status == 429 else 5) * (attempt + 1), 60))
            return None

        resp = await send(retries)
        # Model retired, overloaded or outside the free plan: switch to another current model.
        if (resp is None or resp.status_code in SWITCH_STATUS) and provider in MODEL_PICK:
            try:
                others = [m for m in await list_models() if m != body["model"]][:MAX_TRIES]
            except httpx.HTTPError:
                others = []
            for model in others:
                body["model"] = model
                candidate = await send(0)
                if candidate is not None and candidate.status_code < 400:
                    resp = candidate
                    store.put("ai_model", model)
                    log.info("Switched AI model to %s", model)
                    break

    if resp is None:
        raise AIError(f"{LABELS.get(provider, provider)} took too long to answer (status timeout)")
    if resp.status_code >= 400:
        raise AIError(f"{LABELS.get(provider, provider)} error {resp.status_code}: {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"] or ""


def friendly(exc: Exception) -> str:
    """Plain-language version of an AI error for non-technical users."""
    text = str(exc)
    if " 503" in text or "high demand" in text or "timeout" in text:
        return "The AI service is very busy right now. Please try again in a minute."
    if " 429" in text:
        return "You've reached your free AI limit for now. Wait a few minutes, or use /ai to switch to another AI."
    if " 401" in text or " 403" in text:
        return "Your AI key stopped working. Use /ai to connect again."
    if "not installed" in text:
        return "Claude Code / Codex isn't installed on the computer running OpenHunt. Use /ai to pick another AI."
    if "login" in text.lower() or "log in" in text.lower() or "auth" in text.lower():
        return "Claude Code / Codex isn't logged in. Open it once on the computer and log in, then try again."
    if "limit" in text.lower():
        return "You've reached your subscription's usage limit for now. Try again later, or use /ai to switch."
    return f"The AI had a problem: {text[:200]}"


async def chat_json(system: str, user: str) -> dict:
    return _parse_json(await chat(system + "\nReply with a single JSON object only.", user, json_mode=True))


# Providers retire models often, and free tiers don't cover every model, so for these we list
# the models that exist and try them newest-first until one answers.
MODEL_PICK = {"gemini": ("flash",), "groq": ("versatile",)}
AVOID = ("image", "tts", "audio", "live", "embed", "vision", "preview", "exp", "thinking", "guard", "whisper")
MAX_TRIES = 5
RETRY_STATUS = {429, 500, 502, 503, 504}  # worth waiting and asking again
SWITCH_STATUS = {404, 429, 500, 503}  # worth trying a different model


def rank_models(ids: list[str], want: tuple[str, ...]) -> list[str]:
    """Matching models, best first: newest full models, then newest 'lite' ones, then aliases."""
    ids = [i.removeprefix("models/") for i in ids]
    matches = [i for i in ids if all(w in i for w in want) and not any(a in i for a in AVOID)]

    def key(i: str):
        version = tuple(int(n) for n in re.findall(r"\d+", i))
        return ("lite" not in i, bool(version), version)

    return sorted(matches, key=key, reverse=True)


async def list_models() -> list[str]:
    provider = store.get("ai_provider")
    if provider not in MODEL_PICK:
        return []
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{PROVIDERS[provider][0]}/models", headers={"Authorization": f"Bearer {store.get('ai_api_key')}"}
        )
    if resp.status_code >= 400:
        return []
    return rank_models([m.get("id", "") for m in resp.json().get("data", [])], MODEL_PICK[provider])


async def test_connection() -> tuple[bool, str]:
    try:
        await chat("You are a health check.", "Reply with the word OK.", timeout=20, retries=0)
        return True, describe()
    except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
        return False, str(exc) or type(exc).__name__
