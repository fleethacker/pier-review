"""Reusable guardrails for optional LLM narration over code-owned facts.

Models may arrange words and select allowlisted placeholders.  Numeric values,
units, UTC presentation, risk labels, and verdicts remain application-owned.
"""

import re
import unicodedata
from datetime import UTC, datetime

REFERENCE = re.compile(r"\{\{([^{}]+)\}\}")
NUMBER_WORDS = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundred|thousand|million|billion|half|quarter|twice|"
    r"double|triple|dozen|couple|first|second|third|fourth|fifth)\b", re.IGNORECASE,
)
RISK_LANGUAGE = re.compile(
    r"\b(?:RED|AMBER|GREEN|safe(?:r|st|ly)?|calm(?:er|est)?|benign|harmless|favou?rable|reassuring)\b"
    r"|\blow[\W_]+risk\b"
    r"|\b(?:no|minimal|negligible|little|zero|limited)[\W_]+(?:risk|concern|threat|danger|hazard)s?\b"
    r"|\bnothing[\W_]+to[\W_]+worry\b"
    r"|\b(?:MST|Mooring[\W_]+Service[\W_]+Type|Type)[\s:=-]+[IVXLCDM]+A?\b", re.IGNORECASE,
)
UNIT_TOKENS = re.compile(r"(?<!\w)(?:kts?|knots?|m\s*/\s*s|mph|deg(?:ree)?s?|ft)(?!\w)|°", re.IGNORECASE)


class GuardrailError(ValueError):
    """A fixed, non-sensitive reason suitable for narration provenance."""


def format_fact(field: str, value, unit: str | None = None) -> str:
    """Format typed facts with code-owned UTC and unit presentation."""
    if field.endswith("_utc"):
        if not isinstance(value, datetime):
            raise ValueError("Time facts must be typed datetimes")
        return value.astimezone(UTC).strftime("%H:%MZ %d %b")
    if isinstance(value, bool):
        return "yes" if value else "no"
    if unit is None:
        unit = next((suffix for suffix in ("kt", "deg", "ft") if field.endswith("_" + suffix)), None)
    suffix = "°" if unit == "deg" else f" {unit}" if unit else ""
    return f"{value}{suffix}"


def render(template: str, facts: dict[str, str], *, sentence: bool = False) -> str:
    """Render allowlisted placeholders and reject model-authored facts or risk claims."""
    if any(ch.isnumeric() for ch in REFERENCE.sub("FACT", template)):
        raise GuardrailError("numeric literal")
    template = unicodedata.normalize("NFKC", template).strip()
    literal = REFERENCE.sub("FACT", template)
    if (not literal or len(template) > 1000 or any(ch.isnumeric() for ch in literal)
            or NUMBER_WORDS.search(literal) or "{" in literal or "}" in literal):
        raise GuardrailError("numeric literal or malformed reference")
    if RISK_LANGUAGE.search(literal):
        raise GuardrailError("risk language")
    if UNIT_TOKENS.search(literal):
        raise GuardrailError("unit token")
    if sentence and (not literal.endswith(".") or re.search(r"[.!?]", literal[:-1])):
        raise GuardrailError("sentence structure")

    def replace(match: re.Match) -> str:
        if match[1] not in facts:
            raise GuardrailError("fact reference")
        return facts[match[1]]

    return REFERENCE.sub(replace, template)

