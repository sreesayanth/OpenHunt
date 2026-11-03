"""Use the AI subscription a user already has through Claude Code or Codex installed on this machine.

Job postings are untrusted text from the internet, so the CLIs run locked down:
- Claude Code: every tool switched off (`--tools ""`), no MCP servers, no skills, no saved session.
- Codex: its read-only sandbox, no saved session.
Both run in an empty temporary folder, and the prompt goes in through stdin.
"""

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

# provider -> executable name
CLIS = {"claude_code": "claude", "codex": "codex"}


class CLIError(Exception):
    pass


def available(provider: str) -> bool:
    return shutil.which(CLIS[provider]) is not None


def installed() -> list[str]:
    return [p for p in CLIS if available(p)]


def _claude_args(exe: str, system: str, model: str) -> list[str]:
    args = [
        exe, "-p", "--output-format", "json", "--system-prompt", system,
        "--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
    ]
    return args + (["--model", model] if model else [])


def _codex_args(exe: str, out_file: Path, model: str) -> list[str]:
    args = [exe, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral", "-o", str(out_file)]
    return args + (["--model", model] if model else []) + ["-"]


async def run(provider: str, system: str, user: str, model: str = "", timeout: float = 180) -> str:
    exe = shutil.which(CLIS[provider])
    if not exe:
        raise CLIError(f"'{CLIS[provider]}' is not installed on this computer (or not on PATH).")

    with tempfile.TemporaryDirectory(prefix="openhunt-") as cwd:
        out_file = Path(cwd) / "answer.txt"
        if provider == "claude_code":
            args, prompt = _claude_args(exe, system, model), user
        else:
            args, prompt = _codex_args(exe, out_file, model), f"{system}\n\n{user}"

        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise CLIError(f"{CLIS[provider]} took too long to answer (timeout)") from None

        stdout, stderr = out.decode(errors="replace"), err.decode(errors="replace")
        if provider == "claude_code":
            # Failures inside the run (e.g. not logged in) come back as the JSON result.
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                raise CLIError(f"claude failed: {(stderr or stdout).strip()[:300]}") from None
            if data.get("is_error") or proc.returncode:
                raise CLIError(f"claude failed: {str(data.get('result', ''))[:300]}")
            return data.get("result", "")

        if proc.returncode or not out_file.exists():
            raise CLIError(f"codex failed: {(stderr or stdout).strip()[-300:]}")
        return out_file.read_text(encoding="utf-8", errors="replace")
