"""A form field as every site adapter reports it, independent of the site's HTML."""

from dataclasses import asdict, dataclass, field

# Kinds where the user picks from the site's own options.
CHOICE_KINDS = {"select", "radio", "checkbox"}
TEXT_KINDS = {"text", "textarea", "email", "tel", "url", "number", "date"}

_PLACEHOLDER = ("select", "choose", "please select", "--", "—", "pick one", "none selected")


@dataclass
class FormField:
    label: str
    kind: str = "text"  # text | textarea | number | email | tel | url | date | select | radio | checkbox | file
    options: list[str] = field(default_factory=list)
    required: bool = False
    context: str = ""  # section heading or help text near the field
    locator: str = ""  # how the adapter finds the field again; never shown to the user

    def __post_init__(self) -> None:
        self.label = " ".join((self.label or "").split())
        self.options = [o.strip() for o in self.options if o and o.strip() and not is_placeholder(o)]

    @property
    def is_choice(self) -> bool:
        return self.kind in CHOICE_KINDS and bool(self.options)

    @property
    def is_single_checkbox(self) -> bool:
        return self.kind == "checkbox" and len(self.options) <= 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FormField":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def is_placeholder(option: str) -> bool:
    low = option.strip().lower().rstrip(".…")
    return not low or low in _PLACEHOLDER or low.startswith(("select an", "select one", "please choose"))
