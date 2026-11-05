"""Typed answer values, and fitting one value to whatever field a site shows.

Answers are stored as small dicts like {"t": "num", "v": 3}, not as text, so that "3 years" can
become `3` in a number box on one site and `2-4 years` in a dropdown on another.

Value types:
  num     {"t": "num", "v": 3}
  bool    {"t": "bool", "v": true}
  money   {"t": "money", "v": 1200000, "cur": "INR"}       (yearly amount)
  days    {"t": "days", "v": 30}
  text    {"t": "text", "v": "Bangalore"}
  degree  {"t": "degree", "v": "bachelor"}
  decline {"t": "decline"}                                  (prefer not to say)
  choices {"t": "choices", "v": ["LinkedIn", "Job board"]}  (first option that exists wins)
  file    {"t": "file", "v": "/path/to/file.pdf"}
"""

import math
import re
from datetime import date, timedelta
from difflib import SequenceMatcher

from openhunt.apply.fields import FormField
from openhunt.apply.intents import DEGREE_LEVELS, degree_level, norm

Fill = str | bool | list[str]

YES = re.compile(r"^(?:yes|y|yeah|yep|true|sure|ok|okay|i am|i do|i have|i will|i can|i agree|agree|i accept|accept|absolutely|definitely)\b")
NO = re.compile(r"^(?:no|n|nope|false|not|never|i am not|i'm not|i do not|i don't|i have not|i haven't|i will not|i won't|i can't|i cannot)\b")
DECLINE = re.compile(
    r"prefer not|decline|don'?t wish|do not wish|not (?:to )?(?:say|answer|disclose|specify|identify)|rather not|choose not|"
    r"not specified|don'?t want to|do not want to|wish not to|i don'?t know|not declared"
)


# ---------- reading what the user typed ----------

def parse_number(text: str) -> float | None:
    found = re.search(r"-?\d+(?:[.,]\d+)?", text.replace(",", "") if re.search(r"\d,\d{3}", text) else text)
    if not found:
        words = {"zero": 0, "none": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "half": 0.5}
        for word, n in words.items():
            if re.search(rf"\b{word}\b", text.lower()):
                return float(n)
        return None
    return float(found.group(0).replace(",", "."))


def parse_bool(text: str) -> bool | None:
    low = norm(text)
    if NO.search(low):
        return False
    if YES.search(low):
        return True
    return None


def parse_days(text: str) -> int | None:
    low = norm(text)
    n = parse_number(low)
    if n is None:
        immediate = r"immediate|right away|right now|asap|^now$|no notice|serving notice.*over|already free|any ?time"
        return 0 if re.search(immediate, low) else None
    if re.search(r"month", low):
        return round(n * 30)
    if re.search(r"week", low):
        return round(n * 7)
    return round(n)


def guess_currency(text: str, default: str = "") -> str:
    low = norm(text)
    if re.search(r"₹|\binr\b|\brs\.?|rupee|lpa|lakh|lac\b|\bcr\b|crore|\bctc\b", low):
        return "INR"
    if "$" in low or re.search(r"\busd\b|dollar", low):
        return "USD"
    if "€" in low or re.search(r"\beur\b|euro", low):
        return "EUR"
    if "£" in low or re.search(r"\bgbp\b|pound", low):
        return "GBP"
    if re.search(r"\baed\b|dirham", low):
        return "AED"
    return default


def parse_money(text: str, default_currency: str = "INR") -> dict | None:
    """'12 LPA', '₹12,00,000', '$60k', '1.2 cr', '80000 per month' → yearly amount with currency."""
    low = norm(text)
    n = parse_number(low)
    if n is None:
        return None
    cur = guess_currency(low, default_currency)
    if re.search(r"lpa|lakh|\blac\b|\bl\b|\d\s*l\b", low):
        n *= 100_000
    elif re.search(r"\bcr\b|crore", low):
        n *= 10_000_000
    elif re.search(r"\d\s*k\b|\bk\b|thousand", low):
        n *= 1000
    elif re.search(r"\d\s*m\b|million", low):
        n *= 1_000_000
    if re.search(r"per month|a month|/ ?month|monthly|\bpm\b|/ ?mo\b", low):
        n *= 12
    return {"t": "money", "v": round(n), "cur": cur}


def parse_reply(kind: str, text: str, default_currency: str = "INR") -> dict | None:
    """Turn the user's typed reply into a value of the given kind. None if it doesn't fit."""
    text = (text or "").strip()
    if not text:
        return None
    if kind == "num":
        n = parse_number(text)
        return None if n is None else {"t": "num", "v": n}
    if kind == "bool":
        b = parse_bool(text)
        return None if b is None else {"t": "bool", "v": b}
    if kind == "days":
        d = parse_days(text)
        return None if d is None else {"t": "days", "v": d}
    if kind == "money":
        return parse_money(text, default_currency)
    if kind == "degree":
        level = degree_level(text)
        return {"t": "degree", "v": level} if level else {"t": "text", "v": text}
    if kind == "decline":
        return {"t": "decline"} if DECLINE.search(norm(text)) else {"t": "text", "v": text}
    return {"t": "text", "v": text[:2000]}


# ---------- showing a value to the user ----------

def _num(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else f"{n:g}"


def describe(value: dict | None) -> str:
    if not value:
        return "—"
    t, v = value.get("t"), value.get("v")
    if t == "num":
        return _num(v)
    if t == "bool":
        return "Yes" if v else "No"
    if t == "days":
        if v == 0:
            return "Immediately"
        return f"{_num(v / 30)} month{'s' if v != 30 else ''}" if v % 30 == 0 else f"{v} days"
    if t == "money":
        if value.get("cur") == "INR":
            return f"{_num(round(v / 100_000, 2))} LPA"
        symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(value.get("cur"), value.get("cur", "") + " ")
        return f"{symbol}{v:,} a year"
    if t == "degree":
        return {"high school": "High school", "diploma": "Diploma", "bachelor": "Bachelor's", "master": "Master's", "phd": "PhD"}.get(v, v)
    if t == "decline":
        return "Prefer not to say"
    if t == "choices":
        return v[0] if v else "—"
    if t == "file":
        return "📎 " + str(v).rsplit("/", 1)[-1]
    return str(v)


# ---------- fitting a value to a field ----------

_UNIT_DAYS = (("month", 30), ("week", 7), ("day", 1), ("year", 365))


def _range(option: str, kind: str, label: str = "") -> tuple[float, float] | None:
    """'2-4 years' → (2, 4); '5+' → (5, inf); 'Less than 1 month' → (0, 29); 'Immediately' → (0, 0)."""
    low = norm(option)
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", low.replace(",", ""))]
    scale = 1.0
    if kind == "days":
        scale = next((d for unit, d in _UNIT_DAYS if unit in low), 1)
    elif kind == "money":
        both = low + " " + norm(label)
        if re.search(r"lpa|lakh|\blac\b", both):
            scale = 100_000
        elif re.search(r"\bcr\b|crore", both):
            scale = 10_000_000
        elif re.search(r"\d\s*k\b|\bk\b|thousand", low):
            scale = 1000
    if kind == "days" and re.search(r"immediate|^now$|no notice|serving notice|right away", low):
        return (0, nums[-1] * scale if nums else 0)
    if not nums:
        if kind == "num" and re.search(r"^(?:none|no experience|fresher|less than (?:a|one) year)", low):
            return (0, 0.99)
        return None
    a = nums[0] * scale
    b = (nums[1] if len(nums) > 1 else nums[0]) * scale
    eps = 1 if kind == "days" else 0.01
    if re.search(r"less than|under|below|fewer than|<", low):
        return (0, a - eps)
    if re.search(r"up ?to|within|or less|and below|or below|max", low):
        return (0, a)
    if re.search(r"more than|over|>", low):
        return (a + eps, math.inf)
    if re.search(r"\+|or more|and above|& above|or above|at least|plus|minimum", low):
        return (a, math.inf)
    return (min(a, b), max(a, b))


def _pick_range(n: float, options: list[str], kind: str, label: str, tolerance: float) -> str | None:
    ranges = [(o, _range(o, kind, label)) for o in options]
    ranges = [(o, r) for o, r in ranges if r]
    if not ranges:
        return None
    for o, (lo, hi) in ranges:
        if lo <= n <= hi:
            return o
    # e.g. 1.5 years against "0-1" / "2-3": take the nearest bucket if it's close enough.
    dist = lambda r: 0 if r[0] <= n <= r[1] else min(abs(n - r[0]), abs(n - r[1]))  # noqa: E731
    o, r = min(ranges, key=lambda x: dist(x[1]))
    return o if dist(r) <= tolerance else None


def _pick_bool(b: bool, options: list[str]) -> str | None:
    pattern = YES if b else NO
    for o in options:
        if pattern.search(norm(o)):
            return o
    return None


CITY_ALIASES = {"bangalore": "bengaluru", "bombay": "mumbai", "madras": "chennai", "calcutta": "kolkata",
                "gurgaon": "gurugram", "new delhi": "delhi", "poona": "pune", "trivandrum": "thiruvananthapuram",
                "cochin": "kochi", "mysore": "mysuru", "baroda": "vadodara", "nyc": "new york", "sf": "san francisco"}
_CITY_RE = re.compile(r"\b(" + "|".join(map(re.escape, CITY_ALIASES)) + r")\b")


def _alias(text: str) -> str:
    return _CITY_RE.sub(lambda m: CITY_ALIASES[m.group(1)], norm(text))


def pick_text(value: str, options: list[str]) -> str | None:
    want = _alias(value)
    if not want:
        return None
    lows = [_alias(o) for o in options]
    for o, low in zip(options, lows):
        if low == want:
            return o
    for o, low in zip(options, lows):
        if len(want) >= 3 and len(low) >= 3 and (re.search(rf"\b{re.escape(want)}\b", low) or re.search(rf"\b{re.escape(low)}\b", want)):
            return o
    ratio = lambda o: SequenceMatcher(None, want, _alias(o)).ratio()  # noqa: E731
    best = max(options, key=ratio, default=None)
    if best and ratio(best) >= 0.85:
        return best
    return None


def _label_scale(label: str) -> float:
    """The unit a money field wants its number in: 'Expected CTC (LPA)' → lakhs."""
    low = norm(label)
    if re.search(r"lpa|lakh|\blac\b", low):
        return 100_000
    if re.search(r"\bin (?:thousands|k)\b|\(k\)|'000", low):
        return 1000
    return 1


def fit(value: dict | None, f: FormField) -> Fill | None:
    """The exact thing to put in field `f` for this stored value, or None if it doesn't fit."""
    if not value:
        return None
    t, v = value.get("t"), value.get("v")
    label = f.label + " " + f.context

    if f.kind == "file":
        return v if t == "file" and v else None

    if f.is_single_checkbox:
        return bool(v) if t == "bool" else None

    if f.is_choice:
        opts = f.options
        if t == "bool":
            return _pick_bool(bool(v), opts)
        if t == "decline":
            return next((o for o in opts if DECLINE.search(norm(o))), None)
        if t == "num":
            return _pick_range(float(v), opts, "num", label, tolerance=0.6)
        if t == "days":
            return _pick_range(float(v), opts, "days", label, tolerance=16)
        if t == "money":
            return _pick_range(float(v), opts, "money", label, tolerance=0) if value.get("cur") == _field_currency(label, value.get("cur")) else None
        if t == "degree":
            matches = [o for o in opts if degree_level(o) == v]
            return matches[0] if matches else pick_text(describe(value), opts)
        if t == "choices":
            for choice in v or []:
                hit = pick_text(choice, opts)
                if hit:
                    return hit
            return next((o for o in opts if norm(o) in ("other", "others")), None)
        if t == "text":
            if f.kind == "checkbox":  # several boxes: the saved text lists them, comma separated
                picked = [pick_text(part, opts) for part in re.split(r"\s*[,;]\s*", v)]
                picked = [p for p in picked if p]
                return picked or None
            return pick_text(v, opts)
        return None

    # Free text, number and date boxes.
    if t == "num":
        return _num(v)
    if t == "bool":
        return "Yes" if v else "No"
    if t == "days":
        if f.kind == "date":
            return (date.today() + timedelta(days=int(v))).isoformat()
        if f.kind == "number":
            if re.search(r"month", norm(label)):
                return _num(round(v / 30, 1))
            if re.search(r"week", norm(label)):
                return _num(round(v / 7, 1))
            return _num(v)
        return describe(value)
    if t == "money":
        if value.get("cur") != _field_currency(label, value.get("cur")):
            return None
        amount = float(v)
        if re.search(r"per month|monthly|/ ?month|\bpm\b", norm(label)):
            amount /= 12
        return _num(round(amount / _label_scale(label), 2))
    if t == "degree":
        return describe(value)
    if t == "decline":
        return "Prefer not to say"
    if t == "choices":
        return (v or [None])[0]
    if t == "text":
        if f.kind == "number":
            n = parse_number(v)
            return _num(n) if n is not None else None
        return v
    return None


def _field_currency(label: str, own: str) -> str:
    """The currency a field asks for; fields that don't say are assumed to use the answer's own."""
    return guess_currency(label, own)


def degree_at_least(have: str, want: str) -> bool | None:
    if have not in DEGREE_LEVELS or want not in DEGREE_LEVELS:
        return None
    return DEGREE_LEVELS[have] >= DEGREE_LEVELS[want]
