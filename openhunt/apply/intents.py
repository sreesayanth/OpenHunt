"""Common application-form questions, recognised in the many ways sites word them.

"How many years of experience do you have with Tableau?", "Tableau experience (years)" and
"How long have you used Tableau?" all become the intent `years_with` with the slot `tableau`, so
the user is asked once and every later wording reuses that answer.
"""

import re
from dataclasses import dataclass, field

from openhunt.apply.fields import CHOICE_KINDS

ANY = None
TEXTY = frozenset({"text", "textarea", "email", "tel", "url", "number"})
SHORT = frozenset({"text", "email", "tel", "url", "number", *CHOICE_KINDS})  # not essays
CHOICE = frozenset(CHOICE_KINDS)
NOT_FILE = frozenset({"text", "textarea", "email", "tel", "url", "number", "date", *CHOICE_KINDS})


@dataclass(frozen=True)
class Intent:
    name: str
    kind: str  # value kind: num | bool | money | days | text | degree | decline | file | choices | essay
    title: str  # shown to the user; "{}" is replaced by the slot
    patterns: tuple[str, ...]
    fields: frozenset | None = ANY  # form field kinds this intent applies to
    slot: str = ""  # how to clean the captured slot: skill | country | lang | degree | topic | shift
    sensitive: bool = False  # never matched by AI; only the user's own answer or a CV fact is used
    per_company: bool = False  # the answer depends on the company


@dataclass
class Recognized:
    intent: Intent
    slot: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.intent.name}:{self.slot}" if self.slot else self.intent.name

    @property
    def title(self) -> str:
        if self.slot.startswith("role:"):
            role = self.extra.get("display") or self.slot[5:]
            return {"years_with": f"Years of experience as {role}", "has_skill": f"Experience as {role}"}.get(self.intent.name, role)
        if self.intent.slot == "country":
            where = {"us": "in the US", "uk": "in the UK", "eu": "in the EU", "uae": "in the UAE"}.get(self.slot, f"in {self.slot.title()}" if self.slot else "")
            return self.intent.title.replace("{}", where).strip()
        slot = self.extra.get("display") or (self.slot.title() if self.intent.slot in ("lang", "degree") else self.slot)
        return self.intent.title.replace("{}", slot or "this").strip()


Y = r"(?:years?|yrs?)"
E = r"(?:experience|exp\b)"
SKILL = r"(?P<slot>[^?()]+?)"
END = r"\s*(?:\?|\(|,|$|\.(?:\s|$)|\*)"
LANG = (
    r"(?P<slot>english|hindi|tamil|telugu|kannada|malayalam|marathi|bengali|gujarati|punjabi|urdu|german|french|spanish|"
    r"arabic|japanese|mandarin|chinese|cantonese|korean|dutch|italian|portuguese|russian|polish|swedish|turkish)"
)

INTENTS: list[Intent] = [
    # ---- files and essays ----
    Intent("resume", "file", "Your CV", (r"\b(?:resume|résumé|cv|curriculum vitae)\b",), fields=frozenset({"file"})),
    Intent("cover_letter", "essay", "Cover letter", (r"cover letter",), fields=frozenset({"file", "textarea", "text"})),
    Intent(
        "essay", "essay", "A short written answer",
        (
            r"why (?:do you want to|would you like to|are you (?:interested in|applying)|do you wish to) (?:work|join|apply)",
            r"why (?:are you interested|this (?:company|role|position|job)|our company|us\b|do you want this)",
            r"what (?:interests|excites|attracts|motivates) you",
            r"tell us (?:about yourself|a bit about|why)", r"about yourself", r"what makes you (?:a good|the right|a great)",
            r"why should we hire",
        ),
        fields=frozenset({"textarea", "text"}),
        per_company=True,
    ),
    # ---- contact and identity ----
    Intent("first_name", "text", "First name", (r"\bfirst name\b", r"\bgiven name\b", r"\bpreferred (?:first )?name\b"), fields=TEXTY),
    Intent("last_name", "text", "Last name", (r"\blast name\b", r"\bsurname\b", r"\bfamily name\b"), fields=TEXTY),
    Intent("full_name", "text", "Full name", (r"^(?:your |full |legal |candidate )?name\b", r"\bfull name\b", r"\blegal name\b"), fields=TEXTY),
    Intent("email", "text", "Email", (r"\be-?mail\b",), fields=TEXTY),
    Intent("phone_code", "text", "Phone country code", (r"(?:phone|mobile).*country code", r"^country code$", r"dial(?:ling)? code"), fields=CHOICE | TEXTY),
    Intent("phone", "text", "Phone number", (r"\b(?:phone|mobile|cell|telephone|contact number|whatsapp)\b",), fields=TEXTY),
    Intent("linkedin", "text", "LinkedIn profile link", (r"linkedin",), fields=TEXTY),
    Intent("github", "text", "GitHub profile link", (r"github",), fields=TEXTY),
    Intent("portfolio", "text", "Portfolio or website", (r"portfolio", r"personal (?:website|site|page)", r"^website\b", r"\bblog\b"), fields=TEXTY),
    Intent("country", "text", "Country you live in", (r"^country\b", r"country of residence", r"which country (?:do you|are you)"), fields=SHORT),
    Intent(
        "city", "text", "City you live in",
        (r"\b(?:current |present )?(?:city|location)\b", r"where are you (?:currently )?(?:based|located|living)", r"city of residence"),
        fields=SHORT,
    ),
    Intent("current_title", "text", "Current job title", (r"current (?:job )?(?:title|role|position|designation)",), fields=SHORT),
    Intent("current_company", "text", "Current company", (r"current (?:company|employer|organi[sz]ation)", r"(?:company|employer) name$"), fields=SHORT),
    # ---- education ----
    Intent(
        "has_degree", "bool", "Have a {} degree",
        (
            r"(?:completed|earned|hold|have|obtained|possess|finished)\b.*?\b(?P<slot>bachelor|master|ph\.?d|doctorate|post ?graduat\w*|graduat\w*|b\.?\s?tech|b\.?e\.?\b|b\.?sc|m\.?\s?tech|m\.?sc|mba|diploma|high school)",
        ),
        fields=CHOICE | TEXTY,
        slot="degree",
    ),
    Intent(
        "highest_education", "degree", "Highest education",
        (r"highest (?:level of )?(?:education|qualification|degree)", r"education(?:al)? (?:level|qualification)", r"^(?:degree|qualification)$"),
        fields=SHORT,
    ),
    Intent("degree_field", "text", "Field of study", (r"field of study", r"\bmajor\b", r"\bdiscipline\b", r"speciali[sz]ation", r"\bstream\b"), fields=SHORT),
    Intent("school", "text", "College or university", (r"\b(?:school|college|university|institut\w*)(?: name)?\b",), fields=SHORT),
    Intent("graduation_year", "num", "Graduation year", (r"graduat\w* (?:year|date)", r"year of (?:graduation|passing|completion)", r"passing year"), fields=SHORT),
    # ---- experience ----
    Intent(
        "years_with", "num", "Years of experience with {}",
        (
            rf"how many {Y}\b.*?{E}.*?\b(?:with|in|using|on|of working with|working with|working on|working in)\s+{SKILL}{END}",
            rf"{Y} of (?P<slot>[\w .+#/&-]{{1,40}}?) {E}",
            rf"^(?P<slot>[\w .+#/&-]{{1,40}}?) {E}\s*\(?(?:in )?{Y}\)?",
            r"how long have you (?:been )?(?:used|using|worked with|working with|worked on|working on|worked in|working in|known|programmed in|coded in)\s+(?P<slot>[^?()]+)",
            rf"how many {Y} have you (?:been )?(?:used|using|worked with|working with|worked on|working on|worked in|working in|programmed in|coded in)\s+{SKILL}{END}",
            rf"(?:experience|exp) (?:with|in|using) (?P<slot>[\w .+#/&-]{{1,40}}?) \(?(?:in )?{Y}\)?",
        ),
        fields=SHORT,
        slot="skill",
    ),
    Intent(
        "years_total", "num", "Total years of work experience",
        (
            rf"(?:total|overall)\s+(?:{Y} of\s+)?(?:work |professional |relevant )?{E}",
            rf"how many {Y}\b.*?{E}",
            rf"{Y} of (?:work |professional |full[- ]time )?{E}",
            rf"^(?:work |professional )?{E}\s*\(?(?:in )?{Y}\)?$",
        ),
        fields=SHORT,
    ),
    Intent(
        "has_skill", "bool", "Experience with {}",
        (
            r"do you have (?:any )?(?:prior |previous |hands-on |professional |working |practical |strong )?(?:experience|knowledge|exposure|familiarity|expertise) (?:with|in|of|using|on|working with)\s+(?P<slot>[^?()]+)",
            r"(?:are you|have you been) (?:familiar|experienced|proficient|comfortable) (?:with|in|using)\s+(?P<slot>[^?()]+)",
            r"have you (?:ever )?(?:used|worked with|worked on|worked in)\s+(?P<slot>[^?()]+)",
        ),
        fields=CHOICE | TEXTY,
        slot="skill",
    ),
    # ---- availability and pay ----
    Intent(
        "notice_period", "days", "Notice period",
        (
            r"notice period", r"how soon can you (?:join|start)", r"when (?:can|could|would) you (?:join|start)",
            r"earliest (?:possible )?(?:start|joining|available)", r"available to (?:start|join)", r"availability to (?:join|start)",
            r"joining (?:time|date)", r"\bstart date\b", r"date (?:of )?availability",
        ),
        fields=NOT_FILE,
    ),
    Intent(
        "current_salary", "money", "Current salary",
        (r"current (?:annual |monthly |fixed )?(?:ctc|salary|compensation|pay|package)", r"present (?:ctc|salary)", r"last drawn", r"\bcctc\b"),
        fields=SHORT, sensitive=True,
    ),
    Intent(
        "expected_salary", "money", "Expected salary",
        (
            r"expected (?:annual |monthly |fixed )?(?:ctc|salary|compensation|pay|package)", r"salary expectation", r"desired (?:salary|compensation|pay)",
            r"what (?:salary|compensation) are you (?:looking|expecting|seeking)", r"\bectc\b", r"salary requirement", r"compensation expectation",
        ),
        fields=SHORT, sensitive=True,
    ),
    # ---- work rights ----
    Intent(
        "needs_sponsorship", "bool", "Need visa sponsorship {}",
        (r"sponsor", r"(?:require|need)\w* (?:a |an |any )?(?:work )?(?:visa|work permit)"),
        fields=CHOICE | TEXTY, slot="country", sensitive=True,
    ),
    Intent(
        "work_authorized", "bool", "Allowed to work {}",
        (r"(?:legally )?(?:authori[sz]ed|eligible|permitted|allowed|entitled|right) to work", r"work authori[sz]ation", r"right to work"),
        fields=CHOICE | TEXTY, slot="country", sensitive=True,
    ),
    Intent("relocate", "bool", "Willing to relocate", (r"relocat",), fields=CHOICE | TEXTY),
    Intent(
        "onsite", "bool", "OK to work from the office",
        (
            r"(?:comfortable|willing|able|open|ok|okay|happy)\b.*\b(?:office|on-?site|hybrid|in[- ]person)",
            r"work from (?:the |our )?office", r"(?:on-?site|hybrid) (?:work|setup|arrangement|model|role)", r"commut",
        ),
        fields=CHOICE | TEXTY,
    ),
    Intent("shifts", "bool", "OK with {} shifts", (r"(?P<slot>night|rotational|rotating|weekend|evening|us|uk) shifts?",), fields=CHOICE | TEXTY, slot="shift"),
    Intent("travel", "bool", "Willing to travel", (r"willing to travel", r"travel (?:is )?(?:required|up to|frequently)", r"able to travel"), fields=CHOICE | TEXTY),
    Intent("adult", "bool", "18 or older", (r"(?:at least|over|above|older than) 18", r"18 (?:years|yrs)(?: of age| old)? or (?:older|above)", r"legal (?:working )?age"), fields=CHOICE | TEXTY),
    Intent(
        "language", "bool", "Speak {}",
        (
            rf"(?:speak|read and write|communicate in|fluent in|fluency in|proficiency in|proficient in|knowledge of|level of)\s+(?:the\s+)?{LANG}\b",
            rf"\b{LANG} (?:language )?(?:proficiency|level|fluency|skills|speaker)",
        ),
        fields=CHOICE | TEXTY, slot="lang",
    ),
    # ---- background and legal ----
    Intent("criminal", "bool", "Criminal record", (r"criminal", r"convict", r"felony", r"background (?:check|verification|screening)"), fields=CHOICE | TEXTY, sensitive=True),
    Intent(
        "consent", "bool", "Agree to privacy and terms",
        (r"(?:agree|consent|acknowledge|accept)\b.*\b(?:privacy|terms|processing|personal data|data protection|policy|notice)", r"i (?:hereby )?(?:confirm|certify|declare|attest)"),
        fields=CHOICE | TEXTY, sensitive=True,
    ),
    Intent(
        "worked_here", "bool", "Worked at this company before",
        (r"(?:previously|ever|before) (?:worked|been employed)", r"(?:worked|been employed) (?:for|at|with) (?:us|this company|[a-z0-9 &.]+) (?:before|previously)", r"former employee"),
        fields=CHOICE | TEXTY, per_company=True,
    ),
    Intent("referred", "bool", "Referred by an employee", (r"\breferr(?:ed|al)\b",), fields=CHOICE),
    Intent(
        "hear_about", "choices", "Where you found the job",
        (r"how did you (?:hear|find|learn|come across)", r"where did you (?:hear|find|see)", r"\bsource\b.*\b(?:application|job|hear)", r"^source$"),
        fields=SHORT,
    ),
    # ---- self-identification (default: prefer not to say) ----
    Intent(
        "eeo", "decline", "Self-identification: {}",
        (
            r"\b(?P<slot>gender|sex|pronouns?)\b", r"\b(?P<slot>race|ethnicity|ethnic|hispanic|latino)\b", r"\b(?P<slot>veteran)\b",
            r"\b(?P<slot>disabilit\w*)\b", r"\b(?P<slot>sexual orientation|lgbt\w*|transgender)\b", r"\b(?P<slot>caste|religion|marital status)\b",
        ),
        fields=NOT_FILE, slot="topic", sensitive=True,
    ),
]

BY_NAME = {i.name: i for i in INTENTS}

# ---- slot cleaning ----

SKILL_ALIASES = {
    "ms excel": "excel", "microsoft excel": "excel", "advanced excel": "excel", "power-bi": "power bi", "powerbi": "power bi",
    "ms power bi": "power bi", "microsoft power bi": "power bi", "js": "javascript", "node.js": "node", "nodejs": "node",
    "react.js": "react", "reactjs": "react", "vue.js": "vue", "vuejs": "vue", "postgres": "postgresql", "golang": "go",
    "amazon web services": "aws", "google cloud": "gcp", "google cloud platform": "gcp", "microsoft azure": "azure",
    "k8s": "kubernetes", "ml": "machine learning", "ai/ml": "machine learning", "c sharp": "c#", "dot net": ".net",
    "dotnet": ".net", "ts": "typescript", "py": "python", "python programming": "python", "sql server": "sql",
    "ms sql": "sql", "mysql database": "mysql",
}
TOTAL_WORDS = {"total", "overall", "work", "professional", "full time", "full-time", "paid", "industry experience", "it", "corporate", "experience"}
ROLE_RELATIVE = re.compile(
    r"\b(?:similar|this|the same|same|related|relevant|such a|such|this type of|comparable)\b.*\b(?:role|position|job|field|capacity|domain|function|work)\b"
    r"|^(?:the |this |a )?(?:role|position|field|domain|job)$|^relevant$|^this$"
)
_CUT = re.compile(
    r"\s+(?:in|for|at|within|as|on)\s+(?:a|an|the|your|production|professional|commercial|enterprise|industry|real|live)\b.*$"
    r"|\s+(?:professionally|commercially|overall|so far|till date|to date|until now)\b.*$"
)

COUNTRIES = {
    "us": "us", "usa": "us", "u.s": "us", "u.s.": "us", "u.s.a": "us", "united states": "us", "united states of america": "us", "america": "us",
    "uk": "uk", "u.k": "uk", "united kingdom": "uk", "britain": "uk", "great britain": "uk", "england": "uk",
    "india": "india", "canada": "canada", "germany": "germany", "australia": "australia", "singapore": "singapore",
    "uae": "uae", "united arab emirates": "uae", "dubai": "uae", "ireland": "ireland", "netherlands": "netherlands",
    "the netherlands": "netherlands", "france": "france", "spain": "spain", "japan": "japan", "eu": "eu", "european union": "eu",
    "new zealand": "new zealand", "saudi arabia": "saudi arabia", "qatar": "qatar", "poland": "poland", "sweden": "sweden",
    "switzerland": "switzerland", "israel": "israel", "philippines": "philippines", "malaysia": "malaysia",
}
_COUNTRY_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, COUNTRIES), key=len, reverse=True)) + r")\b")

DEGREE_LEVELS = {"high school": 1, "diploma": 2, "bachelor": 3, "master": 4, "phd": 5}
_DEGREE_RE = [
    ("phd", r"ph\.?\s?d|doctor"),
    ("master", r"master|post ?grad|\bpg\b|m\.?\s?tech|m\.?\s?sc|\bmba\b|\bm\.?\s?e\b|\bmca\b|\bm\.?s\b|\bm\.?a\b|\bm\.?com"),
    ("bachelor", r"bachelor|under ?grad|\bug\b|graduat|b\.?\s?tech|b\.?\s?sc|\bb\.?\s?e\b|\bbca\b|\bbba\b|\bb\.?\s?com|\bb\.?a\b|\bb\.?s\b|degree"),
    ("diploma", r"diploma|associate|polytechnic"),
    ("high school", r"high school|secondary|12th|10th|hsc|ssc|puc|intermediate|ged"),
]

TOPICS = {
    "gender": "gender", "sex": "gender", "pronoun": "pronouns", "pronouns": "pronouns", "race": "race and ethnicity",
    "ethnicity": "race and ethnicity", "ethnic": "race and ethnicity", "hispanic": "race and ethnicity", "latino": "race and ethnicity",
    "veteran": "veteran status", "sexual orientation": "sexual orientation", "transgender": "gender",
    "caste": "caste", "religion": "religion", "marital status": "marital status",
}


def norm(text: str) -> str:
    text = (text or "").lower().replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" *:").strip()


def clean_skill(raw: str) -> str:
    s = norm(raw)
    s = _CUT.sub("", s)
    s = re.sub(r"^(?:the|a|an|using|working with|work with)\s+", "", s)
    s = re.sub(r"\s+(?:skills?|technology|technologies|tools?|software|platform|language|framework|programming|development)$", "", s)
    s = s.strip(" .,:;!?-")
    return SKILL_ALIASES.get(s, s)


def degree_level(text: str) -> str:
    low = norm(text)
    for level, pattern in _DEGREE_RE:
        if re.search(pattern, low):
            return level
    return ""


def find_country(text: str) -> str:
    found = _COUNTRY_RE.search(norm(text))
    return COUNTRIES[found.group(1)] if found else ""


def _slot(intent: Intent, raw: str, question: str, job_title: str) -> str | None:
    """Clean the captured slot. None means this intent doesn't really fit the question."""
    if intent.slot == "skill":
        skill = clean_skill(raw)
        if not skill or len(skill) > 40:
            return None
        if ROLE_RELATIVE.search(skill):
            # "a similar role" depends on the job, so the answer is kept per job title.
            return "role:" + (norm(job_title) or "this job")
        return skill
    if intent.slot == "country":
        return find_country(question)
    if intent.slot == "lang":
        return raw.strip().lower()
    if intent.slot == "degree":
        return degree_level(raw) or None
    if intent.slot == "topic":
        low = raw.lower()
        if low.startswith("disabilit"):
            return "disability"
        if low.startswith("lgbt"):
            return "sexual orientation"
        return TOPICS.get(low, low)
    if intent.slot == "shift":
        return {"rotating": "rotational"}.get(raw.lower(), raw.lower())
    return ""


def _display(slot: str, question: str, job_title: str) -> str:
    """The slot as the user would write it: 'Power BI', not 'power bi'."""
    if slot.startswith("role:"):
        return job_title.strip()
    if not slot:
        return ""
    found = re.search(re.escape(slot), question, re.I)
    return found.group(0) if found and not found.group(0).islower() else ""


def recognize(question: str, kind: str = "text", job_title: str = "") -> Recognized | None:
    """Which common question is this? None if it's not one we know."""
    q = norm(question)
    if not q:
        return None
    for intent in INTENTS:
        if intent.fields is not None and kind not in intent.fields:
            continue
        for pattern in intent.patterns:
            found = re.search(pattern, q)
            if not found:
                continue
            raw = found.groupdict().get("slot") or ""
            slot = _slot(intent, raw, q, job_title)
            if slot is None:
                continue
            if intent.name in ("years_with", "has_skill") and slot in TOTAL_WORDS:
                if intent.name == "has_skill":
                    continue
                return Recognized(BY_NAME["years_total"])
            return Recognized(intent, slot, {"display": _display(slot, question, job_title)})
    return None


STOPWORDS = set(
    """a an the and or of to in on for with at by from as is are was were be been being do does did you your yours
    we our us i me my have has had please kindly any this that these those it its if can could would will shall should
    may might currently current indicate specify select enter provide state mention list share let know tell below above
    following here there what which who how much many when where whether yes no""".split()
)


def question_key(question: str) -> str:
    """Wording-insensitive key for questions that aren't common intents."""
    text = re.sub(r"'s\b", "", norm(question)).replace("'", "")
    words = re.findall(r"[a-z0-9+#]+", text)
    content = sorted({w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w not in STOPWORDS})
    return "q:" + " ".join(content)
