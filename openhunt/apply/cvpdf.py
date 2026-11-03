"""A plain one-page PDF CV for people who never sent one, built only from what they told the bot.

No PDF library needed: it writes the few PDF objects a text page needs. Only facts from the
profile are used; nothing is invented.
"""

import textwrap
from pathlib import Path

from openhunt import store

PAGE_W, PAGE_H, MARGIN = 595, 842, 56  # A4 in points


def _esc(text: str) -> str:
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _lines(profile: dict) -> list[tuple[str, int, str]]:
    """(text, font size, font) rows, top to bottom."""
    out: list[tuple[str, int, str]] = []
    name = str(profile.get("name") or "").strip() or "Curriculum Vitae"
    out.append((name, 20, "F2"))
    if profile.get("headline"):
        out.append((str(profile["headline"]), 12, "F1"))
    contact = " · ".join(str(profile[k]) for k in ("email", "phone", "city", "linkedin", "github", "portfolio") if profile.get(k))
    if contact:
        out.append((contact, 10, "F1"))
    out.append(("", 8, "F1"))

    def section(title: str, body: str | list[str]) -> None:
        items = body if isinstance(body, list) else [body]
        items = [str(i).strip() for i in items if str(i).strip()]
        if not items:
            return
        out.append((title.upper(), 11, "F2"))
        for item in items:
            for row in textwrap.wrap(item, 95) or [""]:
                out.append((row, 10, "F1"))
        out.append(("", 6, "F1"))

    section("Summary", profile.get("summary", ""))
    if profile.get("years_experience") not in (None, ""):
        section("Experience", f"{profile['years_experience']} years of experience"
                + (f", currently {profile['current_title']}" if profile.get("current_title") else "")
                + (f" at {profile['current_company']}" if profile.get("current_company") else "") + ".")
    section("Skills", ", ".join(profile.get("skills", [])))
    education = " · ".join(str(profile[k]) for k in ("highest_degree", "school", "graduation_year") if profile.get(k))
    section("Education", education)
    section("Languages", ", ".join(profile.get("languages", [])))
    raw = str(profile.get("raw_text") or "").strip()
    if raw and raw != str(profile.get("summary", "")).strip():
        section("About me", [p for p in raw.splitlines() if p.strip()][:25])
    return out


def make_pdf(profile: dict) -> bytes:
    rows = _lines(profile)
    pages: list[list[str]] = [[]]
    y = PAGE_H - MARGIN
    for text, size, font in rows:
        step = size + 5
        if y - step < MARGIN:
            pages.append([])
            y = PAGE_H - MARGIN
        y -= step
        if text:
            pages[-1].append(f"BT /{font} {size} Tf {MARGIN} {y} Td ({_esc(text)}) Tj ET")
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages_id = len(objects) + 1 + 2 * len(pages)  # pages object goes after every page + its content
    page_ids = []
    for content in pages:
        stream = "\n".join(content).encode("latin-1", "replace")
        cid = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>"
            % (pages_id, PAGE_W, PAGE_H, cid, font1, font2)))
    kids = " ".join(f"{i} 0 R" for i in page_ids).encode()
    assert add(b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids)) == pages_id
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref)
    return bytes(out)


def ensure_cv_file() -> str | None:
    """The CV to upload: the user's own file, or one made from their profile. None if there's no profile."""
    path = store.get("cv_file")
    if path and Path(path).exists():
        return path
    profile = store.get("profile") or {}
    if not profile:
        return None
    name = "".join(c for c in str(profile.get("name") or "My") if c.isalnum() or c == " ").strip().replace(" ", "_") or "My"
    made = store.save_file(f"{name}_CV.pdf", make_pdf(profile), folder="cv")
    store.put("cv_file", made)
    store.put("cv_generated", True)
    return made
