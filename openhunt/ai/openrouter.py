"""One-click AI connection via OpenRouter's OAuth PKCE flow (no key copying).

Two modes:
- Web wizard: OpenRouter redirects back to our localhost callback with ?code=...
- Headless (VM / Telegram-only): no callback; OpenRouter shows the code and the user
  pastes it into the bot.
"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://openrouter.ai/auth"
EXCHANGE_URL = "https://openrouter.ai/api/v1/auth/keys"


def start(callback_url: str | None = None) -> tuple[str, str]:
    """Return (url to open, code_verifier to keep)."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"code_challenge": challenge, "code_challenge_method": "S256", "key_label": "OpenHunt"}
    if callback_url:
        params["callback_url"] = callback_url
    return f"{AUTH_URL}?{urlencode(params)}", verifier


async def exchange(code: str, verifier: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            EXCHANGE_URL,
            json={"code": code.strip(), "code_verifier": verifier, "code_challenge_method": "S256"},
        )
    resp.raise_for_status()
    return resp.json()["key"]
