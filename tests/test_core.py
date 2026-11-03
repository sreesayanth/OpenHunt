import os
import tempfile

os.environ["OPENHUNT_DATA"] = tempfile.mkdtemp()

from openhunt import store  # noqa: E402
from openhunt.ai import openrouter  # noqa: E402
from openhunt.ai.profile import guess_skills  # noqa: E402
from openhunt.ai.ranker import keyword_score, label, rank  # noqa: E402
from openhunt.hunt import _save_new, build_query  # noqa: E402
from openhunt.sources.base import RawJob, fingerprint, title_matches  # noqa: E402

store.init_db()


def job(title="Data Analyst", company="Acme", location="Bangalore, India", desc="We need strong SQL, Python and Power BI skills for reporting.", url="https://x/1"):
    return RawJob(source="test", url=url, title=title, company=company, location=location, description=desc)


def test_fingerprint_collapses_cross_site_duplicates():
    assert fingerprint("Acme Inc", "Data Analyst (Remote)", "Bangalore, KA") == fingerprint("acme inc", "Data Analyst", "Bangalore")
    assert fingerprint("Acme", "Data Analyst", "Pune") != fingerprint("Acme", "Data Analyst", "Bangalore")


def test_title_matches():
    assert title_matches("Senior Data Analyst - Finance", ["data analyst"])
    assert not title_matches("Data Engineer", ["data analyst"])


def test_settings_roundtrip_and_secret_encryption():
    store.put("bot_token", "123:abc")
    store.put("prefs", {"titles": ["x"]})
    assert store.get("bot_token") == "123:abc"
    assert store.update("prefs", remote=True) == {"titles": ["x"], "remote": True}
    with store.session() as s:
        assert "123:abc" not in s.get(store.Setting, "bot_token").value


def test_save_new_skips_duplicates():
    first = _save_new([job(url="https://a"), job(url="https://b")])  # same job on two sites
    assert len(first) == 1
    assert _save_new([job(url="https://c")]) == []


async def test_keyword_ranking_without_ai():
    profile = {"skills": ["sql", "python", "power bi"]}
    prefs = {"titles": ["Data Analyst"]}
    good, bad = job(), job(title="Chef", desc="cooking")
    assert keyword_score(good, profile, prefs)[0] > keyword_score(bad, profile, prefs)[0]
    ranked = await rank([bad, good], profile, prefs)
    assert ranked[0].job is good and ranked[0].score >= 80
    assert label(ranked[0].score).startswith("🟢")


def test_retire_matches_keeps_saved():
    jobs = _save_new([job(title="Retire A", url="https://r1"), job(title="Retire B", url="https://r2")])
    with store.session() as s:
        s.add(store.Match(job_id=jobs[0][1], score=90, status="notified"))
        s.add(store.Match(job_id=jobs[1][1], score=90, status="saved"))
        s.commit()
    store.retire_matches()
    assert [j.title for _, j in store.recent_matches(10)] == ["Retire B"]


def test_build_query_needs_titles():
    assert build_query({}, {}) is None
    q = build_query({"titles": ["A"], "locations": ["Remote", "Pune"], "remote": True}, {})
    assert q.locations == ["Pune"] and q.remote


def test_guess_skills():
    assert set(guess_skills("I know Python, SQL and Power BI. Not javascripty.")) >= {"python", "sql", "power bi"}


def test_rank_models_newest_full_then_lite_then_aliases():
    from openhunt.ai.llm import rank_models

    ids = ["models/gemini-2.5-flash", "models/gemini-3.8-flash", "models/gemini-3.5-flash-lite",
           "models/gemini-4.0-flash-preview", "models/gemini-3.8-pro", "models/gemini-flash-latest"]
    assert rank_models(ids, ("flash",)) == ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-flash-latest", "gemini-3.5-flash-lite"]
    assert rank_models(["whisper-large"], ("versatile",)) == []


def test_cli_providers_run_locked_down():
    from pathlib import Path

    from openhunt.ai import cli_providers, llm

    claude = cli_providers._claude_args("claude", "sys", "haiku")
    assert claude[claude.index("--tools") + 1] == ""  # no tools: postings are untrusted
    assert "--strict-mcp-config" in claude and "--no-session-persistence" in claude
    codex = cli_providers._codex_args("codex", Path("out.txt"), "")
    assert codex[codex.index("--sandbox") + 1] == "read-only" and codex[-1] == "-"
    store.put("ai_provider", "claude_code")
    assert llm.is_configured()  # no key needed
    store.delete("ai_provider")


def test_openrouter_pkce_url():
    url, verifier = openrouter.start("http://localhost:8080/cb")
    assert "code_challenge=" in url and "callback_url=" in url and len(verifier) > 40
