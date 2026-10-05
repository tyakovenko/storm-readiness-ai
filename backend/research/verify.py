"""Judge layer 1: fixed checks of a fact against the page the judge fetched itself (no LLM).

Pure functions: the page is passed in, so tests run without network. A check that can't run returns
ok=None; fixed_verdict() turns a missing required check into UNCHECKED, never into a pass.
Numbers are compared as parsed spans of the judge's own fetch (research.numbers), never as text.
"""

from __future__ import annotations

import re
from datetime import date

from research import numbers, policy
from research.schema import Check, Fact, Page, Target, Verdict

# Checks without which nothing is known about the fact: if one couldn't run, the verdict is UNCHECKED.
REQUIRED = ("fetch", "quote_in_source")

_PUNCT = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
                        "—": "-", "−": "-", " ": " ", "­": ""})
_COMPACT_KEEP = re.compile(r"[0-9a-z$%]")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _norm_map(text: str, compact: bool = False) -> tuple[str, list[int]]:
    """Normalized text + the original index of every normalized char, so a match maps back to the page.
    Normal: unified quotes/dashes, whitespace collapsed, casefolded. Compact: letters, digits, $ and % only
    (PDF text breaks words at line ends, "evacu- ees"; compact still needs every char, in order)."""
    out, idx = [], []
    for i, ch in enumerate(text):
        for c in ch.translate(_PUNCT).casefold():
            if compact:
                if not _COMPACT_KEEP.match(c):
                    continue
            elif c.isspace():
                if not out or out[-1] == " ":
                    continue
                c = " "
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def _norm(text: str) -> str:
    return _norm_map(text)[0].strip()


def _check(name: str, ok: bool | None, detail: str, severity: str = "block") -> Check:
    return Check(layer="fixed", name=name, ok=ok, detail=detail, severity=severity)


def _locate_quote(quote: str, page_text: str) -> tuple[Check, tuple[int, int] | None]:
    """(check, quote's (start, end) in the original page text)."""
    if len(quote.strip()) < policy.MIN_QUOTE_CHARS:
        return _check("quote_in_source", False,
                      f"quote shorter than {policy.MIN_QUOTE_CHARS} chars can't tie the value to the claim"), None
    for compact, how in ((False, "quote found"), (True, "quote found ignoring punctuation and spacing")):
        page, idx = _norm_map(page_text, compact)
        q = _norm_map(quote, compact)[0].strip()
        i = page.find(q) if q else -1
        if i >= 0:
            return _check("quote_in_source", True, how), (idx[i], idx[i + len(q) - 1] + 1)
    return _check("quote_in_source", False, "quote not in the fetched page"), None


def _value_at_source(fact: Fact, spans: list[numbers.NumberSpan], where: tuple[int, int] | None) -> Check:
    if fact.value is None:
        return _check("value_at_source", None, "fact has no number")
    if where is None:
        return _check("value_at_source", False, "quote not located; value can't be tied to the page")
    inside = [s for s in spans if s.start >= where[0] and s.end <= where[1]]
    same = [s for s in inside if s.value == fact.value]
    usable = [s for s in same if s.usable]
    if not usable:
        found = ", ".join(f"{s.raw} ({s.kind})" for s in inside) or "none"
        why = " - present but not a value" if same else ""
        return _check("value_at_source", False, f"{fact.value:g} not a value in the quote{why} (numbers there: {found})")
    if not any(s.qualifier == fact.qualifier for s in usable):
        return _check("value_at_source", False,
                      f"source says {usable[0].qualifier} {usable[0].raw}, fact says {fact.qualifier}")
    return _check("value_at_source", True, f"{usable[0].raw} = {fact.value:g} ({usable[0].kind}, {fact.qualifier})")


def _unit(fact: Fact, sentence: str) -> Check:
    expected = policy.metric(fact.metric).unit
    if expected and fact.unit != expected:
        return _check("unit", False, f"metric {fact.metric} is counted in {expected}, fact says {fact.unit}")
    words = policy.UNIT_SYNONYMS.get(fact.unit)
    if words is None:
        return _check("unit", None, f"unit '{fact.unit}' not in policy; not checked")
    text = _norm(sentence)
    # Word start only ("bed" must not match "described"); prefix is fine so plurals match.
    hit = next((w for w in words if re.search(r"(?<![a-z])" + re.escape(w), text)), None)
    return (_check("unit", True, f"'{hit}' in the quote's sentence") if hit
            else _check("unit", False, f"no {fact.unit} word in the quote's sentence"))


def _names_re(names: list[str]) -> re.Pattern:
    alts = sorted({_norm(n) for n in names if n}, key=len, reverse=True)
    return re.compile(r"(?<![\w-])(" + "|".join(re.escape(a).replace(r"\-", r"[- ]?") for a in alts) + r")(?![\w])")


def _jurisdiction(fact: Fact, target: Target, page: str) -> Check:
    if fact.place:
        # A city figure: the city must belong to the target and be named on the page.
        if _norm(fact.place) not in {_norm(n) for n in target.jurisdiction_names()}:
            return _check("jurisdiction", False, f"{fact.place} is not {target.county} or one of its listed cities")
        names = [fact.place]
    else:
        names = target.jurisdiction_names()
    m = _names_re(names).search(page)
    return (_check("jurisdiction", True, f"page mentions {m.group(1)}") if m
            else _check("jurisdiction", False, f"page never mentions {fact.place or target.county + ' or its cities'}"))


def _storm(fact: Fact, target: Target, page: str) -> Check:
    if fact.storm_id is None:
        return _check("storm", None, "fact is not about a storm")
    storm = next((s for s in target.storms if s.id == fact.storm_id), None)
    if storm is None:
        return _check("storm", False, f"storm_id {fact.storm_id} not in target storms")
    # Names repeat across years (Beryl 2018 and 2024): need the year on the page too.
    name_ok = _names_re([storm.name]).search(page) is not None
    year_ok = str(storm.year) in page
    if name_ok and year_ok:
        return _check("storm", True, f"page mentions {storm.name} and {storm.year}")
    missing = " and ".join(x for x, ok in ((storm.name, name_ok), (str(storm.year), year_ok)) if not ok)
    return _check("storm", False, f"page never mentions {missing}")


def _stale(fact: Fact, today: date) -> Check:
    if not policy.metric(fact.metric).ages or fact.storm_id:
        return _check("stale", None, "past-storm fact; doesn't go stale", "flag")
    m = _YEAR.search(fact.as_of or fact.published or "")
    if not m:
        return _check("stale", None, "no as_of or published date; age unknown", "flag")
    age = today.year - int(m.group(0))
    return _check("stale", age <= policy.STALE_YEARS, f"{age} years old (limit {policy.STALE_YEARS})", "flag")


def check_fact(fact: Fact, page: Page, target: Target, today: date | None = None) -> list[Check]:
    if page.error:
        return [_check("fetch", None, f"source not fetched: {page.error}")]
    if not page.text.strip():
        return [_check("fetch", None, f"no text extracted ({page.content_type or 'unknown type'})")]
    quote_check, where = _locate_quote(fact.quote, page.text)
    sentence = page.text[slice(*numbers.sentence_around(page.text, *where))] if where else fact.quote
    norm_page = _norm(page.text)
    return [_check("fetch", True, page.final_url or page.url), quote_check,
            _value_at_source(fact, numbers.extract(page.text), where), _unit(fact, sentence),
            _jurisdiction(fact, target, norm_page), _storm(fact, target, norm_page), _stale(fact, today or date.today())]


def fixed_verdict(checks: list[Check]) -> Verdict | None:
    """UNSUPPORTED / UNCHECKED, or None = passed layer 1, go on to entailment."""
    if any(c.severity == "block" and c.ok is False for c in checks):
        return Verdict.UNSUPPORTED
    ran = {c.name for c in checks if c.ok is not None}
    if any(name not in ran for name in REQUIRED):
        return Verdict.UNCHECKED
    return None
