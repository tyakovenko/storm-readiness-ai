"""Deterministic number pass over a source page (ADR 20261005-numbers-by-reference).

extract() turns every number into a NumberSpan with offsets, parsed value, kind and qualifier.
tag() marks the usable ones for the researcher (⟦N17⟧1,314). fact_from_ref() builds a Fact from the
researcher's reference, so the value, qualifier and quote all come from code, never from the LLM.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from agent.trust import _SMALL, _TENS, WORD_NUM_RE  # same word-number vocabulary as the chat trust layer
from research import policy
from research.schema import Fact, FactDraft

USABLE_KINDS = frozenset({"quantity", "money", "percent"})

_MONTHS = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
           r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
# Order matters: earlier patterns claim their characters first, so "July 9, 2024" is one date,
# not a date plus a year plus a count of 9.
_NON_VALUE = [
    ("phone", re.compile(r"(?<!\d)(?:\(\d{3}\)\s?|\d{3}[-.])\d{3}[-.]\d{4}(?!\d)")),
    ("date", re.compile(r"(?<!\d)\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})(?!\d)|\b\d{4}-\d{2}-\d{2}\b")),
    ("date", re.compile(rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+\d{{4}}\b)?", re.IGNORECASE)),
    ("time", re.compile(r"\b\d{1,2}:\d{2}(?:\s?[ap]\.?m\.?)?|\b\d{1,2}\s?(?:[ap]\.m\.|[AP]M\b)")),
    ("ordinal", re.compile(r"\b\d+(?:st|nd|rd|th)\b")),
]
_SCALES = {"k": 1e3, "thousand": 1e3, "million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9}
_NUM = re.compile(
    r"(?<![\w.,])(?P<dollar>\$\s?)?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?(?P<plus>\+)?"
    r"(?:\s?(?P<pct>%|percent\b|per cent\b)|\s?(?P<scale>thousand|million|billion|bn|k|K|M)\b)?")
_WORD_SCALE = re.compile(r"\s+(thousand|million|billion)\b", re.IGNORECASE)
# A number right after these is a name, not a measurement ("District 14", "FOX 26", "Category 4").
# Not "us": "told us 300 people" is a count; "US 59" falls to layer 2.
_LABEL_BEFORE = re.compile(
    r"(?:\b(?:district|category|cat\.?|precinct|ward|route|highway|hwy|interstate|loop|fm|sr|fox|abc|nbc|cbs|"
    r"channel|station|zone|region|area|phase|level|tier|section|chapter|appendix|page|pages|p\.|pp\.|figure|fig\.|"
    r"table|item|no\.|number|unit|building|room|suite|step|version|v\.|exhibit|line|pod|site)\s*|#\s*|[a-z]-)$",
    re.IGNORECASE)
_STREET_AFTER = re.compile(r"^\s+(?:[NSEW]\.?\s+)?[A-Z][\w.]*(?:\s+[A-Z][\w.]*)?\s+"
                           r"(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Way|Ln|Lane|Pkwy|Parkway|Fwy|"
                           r"Freeway|Hwy|Ct|Court|Pl|Place)\b")
_QUALIFIERS = [  # matched against the words right before the number
    ("over", r"(?:more than|over|in excess of|upwards of|exceeding)"),
    ("at_least", r"(?:at least|a minimum of|no fewer than|no less than)"),
    ("about", r"(?:about|approximately|approx\.?|nearly|almost|around|roughly|some|an estimated|estimated|~)"),
    ("up_to", r"(?:up to|as many as|a maximum of|no more than)"),
]
_QUALIFIER_RES = [(q, re.compile(rf"\b{p}\s*$" if p[0] != "~" else rf"{p}\s*$", re.IGNORECASE))
                  for q, p in _QUALIFIERS]
_RANGE_JOIN = re.compile(r"^\s*(?:-|–|—|to|and)\s*$", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)|\n")


class NumberSpan(BaseModel):
    id: str
    start: int
    end: int
    raw: str
    value: float
    kind: str
    qualifier: str = "exact"
    range_of: str | None = None

    @property
    def usable(self) -> bool:
        return self.kind in USABLE_KINDS


def _is_unit_word(name: str) -> bool:
    """A word or field name ("TOTAL_CAPACITY") whose parts start with a unit word. Parts, not substrings:
    "bus" must not match "business"."""
    parts = [p for p in re.split(r"[\W_]+", name.lower()) if p]
    return any(p.startswith(w) for p in parts for words in policy.UNIT_SYNONYMS.values() for w in words if w.isalpha())


def _unit_word_follows(text: str, end: int) -> bool:
    m = re.match(r"\s+([a-z]+)", text[end:end + 30], re.IGNORECASE)
    return bool(m) and _is_unit_word(m.group(1))


def _qualifier(text: str, start: int) -> str:
    before = text[max(0, start - 30):start]
    return next((q for q, rx in _QUALIFIER_RES if rx.search(before)), "exact")


# Structured rows ("CAPACITY: 1200; LAT: 25.7"): the field name says what the number is.
_FIELD_BEFORE = re.compile(r"([A-Za-z][\w .]*?)\s*:\s*$")
_FIELD_YEAR = re.compile(r"year|yr|date", re.IGNORECASE)
_FIELD_LABEL = re.compile(r"(^|_|\b)(id|objectid|fid|gid|zip|zipcode|phone|fax|code|no|num|number|lat|lon|"
                          r"latitude|longitude|x|y|shape\w*|district|precinct|zone)$", re.IGNORECASE)


def _digit_kind(m: re.Match, text: str) -> str:
    line_start = text.rfind("\n", 0, m.start()) + 1
    field = _FIELD_BEFORE.search(re.split(r"[;|]", text[line_start:m.start()])[-1])
    name = field.group(1).strip() if field else ""
    if name and not m.group("dollar") and not m.group("pct"):
        if _FIELD_YEAR.search(name):
            return "year"
        if _FIELD_LABEL.search(name):
            return "label"
    if m.group("dollar") or re.match(r"\s?dollars?\b", text[m.end():], re.IGNORECASE):
        return "money"
    if m.group("pct"):
        return "percent"
    if _LABEL_BEFORE.search(text[max(0, m.start() - 20):m.start()]) or _STREET_AFTER.match(text[m.end():m.end() + 40]):
        return "label"
    plain = not (m.group("dec") or m.group("scale") or m.group("plus") or "," in m.group("int"))
    # A bare 19xx/20xx is a year unless a unit follows ("2000 beds") or its field names one ("CAPACITY: 1200").
    if plain and len(m.group("int")) == 4 and 1900 <= int(m.group("int")) <= 2099 \
            and not _unit_word_follows(text, m.end()) and not _is_unit_word(name):
        return "year"
    return "quantity"


def extract(text: str) -> list[NumberSpan]:
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, int, str, float, str]] = []  # start, end, kind, value, qualifier

    def free(s: int, e: int) -> bool:
        return all(e <= a or s >= b for a, b in taken)

    for kind, rx in _NON_VALUE:
        for m in rx.finditer(text):
            if free(m.start(), m.end()):
                taken.append((m.start(), m.end()))
                found.append((m.start(), m.end(), kind, float(re.search(r"\d+", m.group()).group()), "exact"))
    for m in _NUM.finditer(text):
        if not free(m.start(), m.end()):
            continue
        value = float(m.group("int").replace(",", "") + (m.group("dec") or ""))
        if m.group("scale"):
            value *= _SCALES[m.group("scale").lower()]
        kind = _digit_kind(m, text)
        qual = "at_least" if m.group("plus") else _qualifier(text, m.start())
        taken.append((m.start(), m.end()))
        found.append((m.start(), m.end(), kind, value, qual))
    for m in WORD_NUM_RE.finditer(text):
        if not free(m.start(), m.end()):
            continue
        if m.group(1):
            value = _TENS[m.group(1).lower()] + (_SMALL[m.group(2).lower()] if m.group(2) else 0)
        else:
            value = 12 if "dozen" in m.group(3).lower() else _SMALL[m.group(3).lower()]
        end = m.end()
        sm = _WORD_SCALE.match(text, end)
        if sm:
            value, end = value * _SCALES[sm.group(1).lower()], sm.end()
        taken.append((m.start(), end))
        found.append((m.start(), end, "quantity", float(value), _qualifier(text, m.start())))

    found.sort()
    spans = [NumberSpan(id=f"N{i + 1}", start=s, end=e, raw=text[s:e], value=v, kind=k, qualifier=q)
             for i, (s, e, k, v, q) in enumerate(found)]
    _link_ranges(text, spans)
    return spans


def _link_ranges(text: str, spans: list[NumberSpan]) -> None:
    """"1,200-1,500", "1,200 to 1,500", "between 1,200 and 1,500" -> linked low/high spans.
    "$1.2-1.5 million" / "20-30%": the low end takes the high end's scale and kind."""
    for lo, hi in zip(spans, spans[1:]):
        if not (lo.usable or lo.kind == "year") or not hi.usable or lo.range_of:
            continue
        between = text[lo.end:hi.start]
        if not _RANGE_JOIN.match(between):
            continue
        if between.strip().lower() == "and" and not re.search(r"\bbetween\s*\$?$", text[max(0, lo.start - 12):lo.start],
                                                               re.IGNORECASE):
            continue
        if lo.value < hi.value / 100 and not re.search(r"[kmb%]|thousand|million|billion|percent", lo.raw, re.I):
            lo.value *= hi.value / _bare(hi.raw)  # scale carried over from the high end
        # "$" sits on the low end, "%" on the high end: either marks the whole range.
        kind = next((k for k in ("money", "percent") if k in (lo.kind, hi.kind)), "quantity")
        lo.kind = hi.kind = kind
        lo.qualifier, hi.qualifier = "range_low", "range_high"
        lo.range_of, hi.range_of = hi.id, lo.id


def _bare(raw: str) -> float:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", raw)
    return float(m.group().replace(",", "")) if m else 1.0


def tag(text: str, spans: list[NumberSpan]) -> str:
    """Page text for the researcher: usable numbers prefixed with their id. Non-usable ones stay
    plain so the researcher can't cite a year, phone number or label as a value."""
    out, pos = [], 0
    for s in spans:
        if s.usable:
            out += [text[pos:s.start], f"⟦{s.id}⟧", text[s.start:s.end]]
            pos = s.end
    return "".join(out) + text[pos:]


def sentence_around(text: str, start: int, end: int) -> tuple[int, int]:
    bounds = [m.end() for m in _SENTENCE_END.finditer(text)]
    s = max((b for b in bounds if b <= start), default=0)
    e = min((b for b in bounds if b >= end), default=len(text))
    while s < e and text[s].isspace():
        s += 1
    return s, e


class BadReference(ValueError):
    pass


def fact_from_ref(draft: FactDraft, spans: list[NumberSpan], text: str) -> Fact:
    """The researcher picks a span; code fills value, raw text, qualifier and quote from the page."""
    base = draft.model_dump(exclude={"value_ref", "quote"})
    if draft.value_ref is None:
        if not draft.quote:
            raise BadReference(f"{draft.id}: no value_ref and no quote")
        return Fact(**base, value=None, quote=draft.quote)
    span = next((s for s in spans if s.id == draft.value_ref), None)
    if span is None:
        raise BadReference(f"{draft.id}: {draft.value_ref} is not a number on this page")
    if not span.usable:
        raise BadReference(f"{draft.id}: {draft.value_ref} ({span.raw!r}) is a {span.kind}, not a value")
    s, e = sentence_around(text, span.start, span.end)
    return Fact(**base, value=span.value, value_raw=span.raw, qualifier=span.qualifier, quote=text[s:e].strip())
