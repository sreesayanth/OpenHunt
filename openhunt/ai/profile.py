"""Turn a CV (PDF / DOCX / text) or a short chat description into a structured profile."""

import io
import re

from openhunt.ai import llm

# Fallback skill list for when no AI is connected. Deliberately broad, not exhaustive.
COMMON_SKILLS = [
    "python", "java", "javascript", "typescript", "react", "node", "sql", "excel", "power bi", "tableau",
    "aws", "azure", "gcp", "docker", "kubernetes", "linux", "git", "c++", "c#", ".net", "go", "rust",
    "django", "flask", "fastapi", "spring", "angular", "vue", "html", "css", "figma", "photoshop",
    "machine learning", "deep learning", "pandas", "spark", "airflow", "dbt", "snowflake", "salesforce",
    "sap", "accounting", "marketing", "seo", "sales", "customer service", "project management", "agile",
    "scrum", "communication", "leadership", "android", "ios", "kotlin", "swift", "flutter", "php",
    "laravel", "mongodb", "postgresql", "mysql", "redis", "terraform", "jenkins", "testing", "selenium",
]

SYSTEM = """You extract a job seeker's profile from their CV or self-description.
Never invent facts that are not in the text.
JSON keys: name (string), headline (short string), years_experience (number),
skills (list of strings), titles (list of 3-5 job titles this person should search for),
locations (list of strings found in the text), languages (list of strings),
summary (2 sentences, written without he/she pronouns)."""


def extract_text(data: bytes, filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    if name.endswith(".docx"):
        import docx

        return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    return data.decode("utf-8", errors="ignore")


def guess_skills(text: str) -> list[str]:
    low = text.lower()
    return [s for s in COMMON_SKILLS if re.search(rf"(?<![a-z]){re.escape(s)}(?![a-z])", low)]


async def build_profile(text: str, use_ai: bool = True) -> dict:
    text = text.strip()[:15000]
    if use_ai and llm.is_configured():
        profile = await llm.chat_json(SYSTEM, text)
    else:
        profile = {"skills": guess_skills(text), "titles": [], "summary": text[:300]}
    profile["raw_text"] = text
    profile.setdefault("skills", [])
    profile.setdefault("titles", [])
    return profile
