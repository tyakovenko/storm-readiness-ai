"""Research judge: layer 1 fixed checks -> layer 2 entailment -> layer 3 independent corroboration
(ADR layered-judge). The judge refetches every source with its own Fetcher and never sees the researcher's
reasoning or page copy.

Numbers by reference here too: in corroboration the model picks a number tag on the other page; code
reads the value and compares (ADR numbers-by-reference).
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.request
from datetime import date
from urllib.parse import urlparse

from research import config, numbers, policy, verify
from research.fetch import USER_AGENT, Fetcher
from research.schema import Check, DraftPack, Fact, FactReview, Page, Target, Verdict

log = logging.getLogger(__name__)
CONTEXT_CHARS = 600          # passage around the quote given to the entailment model
MAX_CANDIDATES = 3           # corroborating pages fetched per key fact
MAX_PICK_LINES = 60          # lines of a candidate page shown when asking which number states the metric
SYNDICATED_RATIO = 0.9       # share of the shorter sentence found in the other: at or above = a copy
CALL_TIMEOUT_MS = 180_000    # per Gemini call; without it one call hung a re-judge for 7 h
RETRIES = 4                  # on 429 / 503 only
BACKOFF_S = 5                # 5, 10, 20, 40 s
ENTAIL_LABELS = ("supports", "wrong_metric", "wrong_scope", "wrong_time", "not_enough")

ENTAIL_PROMPT = """You check one claim against one passage from its cited source. Decide only whether the \
passage states this claim: the same metric as defined (capacity is not occupancy; staff is not volunteers or \
utility workers), the same organization, the same \
place (a city figure is not the county's; a FEMA applicant's home county is not where the damage was), and \
the same time or storm. The number itself was already matched by code: do not re-check its digits.

Claim:
{claim}

Passage (from {url}):
\"\"\"{passage}\"\"\"

Answer JSON: {{"label": one of {labels}, "reason": one sentence}}"""

PICK_PROMPT = """Below are lines from a web page; numbers are tagged like ⟦N17⟧1,314. Which tag, if any, \
states this metric for this place and time?

Metric: {claim}

Lines:
{lines}

Answer JSON: {{"value_ref": "N.." or null, "reason": one sentence}}. Pick only a number that states exactly \
this metric; if none does, null."""

SEARCH_PROMPT = """Find published sources (official reports, government pages, news) that report: {claim}. \
List the sources you found."""


def _claim(fact: Fact, target: Target) -> str:
    storm = next((f"{s.name} {s.year}" for s in target.storms if s.id == fact.storm_id), None)
    value = "no number" if fact.value is None else f"{fact.qualifier.replace('_', ' ')} {fact.value_raw}"
    m = policy.metric(fact.metric)
    parts = [f"metric: {fact.metric} ({fact.unit})" + (f" = {m.definition}" if m.definition else ""),
             f"value: {value}", f"place: {fact.place or target.county}, {target.state}"]
    if fact.subject:
        parts.append(f"whose figure: {fact.subject}")
    if storm:
        parts.append(f"storm: {storm}")
    if fact.as_of:
        parts.append(f"as of: {fact.as_of}")
    return "; ".join(parts)


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return ".".join(host.split(".")[-2:])


def _overlap(a: str, b: str) -> float:
    """Share of the shorter text that appears, in order, in the other. Wire copies get a new lead-in
    ("At Hurricane Beryl's peak, ...") that drops plain similarity below any useful threshold."""
    a, b = verify._norm(a), verify._norm(b)
    if not a or not b:
        return 0.0
    matched = sum(m.size for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    return matched / min(len(a), len(b))


def _resolve(url: str) -> str:
    """Grounding links are vertexaisearch redirects; store and compare the real URL (R0)."""
    if "grounding-api-redirect" not in url:
        return url
    err = None
    for method in ("HEAD", "GET"):  # some redirects answer HEAD with 403 (Harris run); GET follows them
        req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.geturl()
        except urllib.error.HTTPError as e:
            if e.url and "grounding-api-redirect" not in e.url:
                return e.url  # redirected fine; the target itself refused us - the fetch will report it
            err = e
        except Exception as e:
            err = e
    log.warning("could not resolve grounding redirect: %s", err)
    return url


class GeminiCalls:
    """Thin JSON-call wrapper with a per-run cap. Keeps the Client referenced for its lifetime
    (a temporary Client can be collected mid-call: 'client has been closed')."""

    def __init__(self, model: str, cap: int = policy.MAX_GEMINI_CALLS):
        from google import genai
        self.model, self.cap, self.count = model, cap, 0
        self._lock = threading.Lock()  # shared across judge threads
        from google.genai import types
        self.client = genai.Client(http_options=types.HttpOptions(timeout=CALL_TIMEOUT_MS))
        self._sleep = time.sleep

    def _go(self, prompt: str, **cfg):
        from google.genai import types
        for attempt in range(RETRIES + 1):
            with self._lock:
                if self.count >= self.cap:
                    raise RuntimeError(f"judge model-call cap reached ({self.cap})")
                self.count += 1
            try:
                return self.client.models.generate_content(model=self.model, contents=prompt,
                                                           config=types.GenerateContentConfig(**cfg))
            except Exception as e:
                # Quota (429) and overload (503) pass; anything else, or the last try, surfaces as UNCHECKED.
                if attempt == RETRIES or not re.search(r"\b(429|503)\b|RESOURCE_EXHAUSTED|UNAVAILABLE|timed out|Timeout",
                                                       f"{type(e).__name__} {e}"):
                    raise
                wait = BACKOFF_S * 2 ** attempt
                log.warning("judge call rate-limited (%s); retry %d in %d s", str(e)[:60], attempt + 1, wait)
                self._sleep(wait)

    def json(self, prompt: str) -> dict:
        r = self._go(prompt, response_mime_type="application/json")
        out = json.loads(r.text or "{}")
        if isinstance(out, list):  # the model sometimes wraps the object in a list (Harris run)
            out = next((x for x in out if isinstance(x, dict)), {})
        return out if isinstance(out, dict) else {}

    def search(self, prompt: str) -> list[str]:
        from google.genai import types
        r = self._go(prompt, tools=[types.Tool(google_search=types.GoogleSearch())])
        gm = r.candidates[0].grounding_metadata if r.candidates else None
        return [c.web.uri for c in (gm.grounding_chunks or [])] if gm and gm.grounding_chunks else []


class Judge:
    def __init__(self, model: str = config.JUDGE_MODEL, llm=None, fetcher: Fetcher | None = None,
                 resolve=_resolve, today: date | None = None, picker=None):
        self.model = model
        self.llm = llm or GeminiCalls(model)
        # Tests pass one scripted llm: it serves both roles unless a picker is given.
        self.picker = picker or (GeminiCalls(config.PICK_MODEL) if llm is None else llm)
        self.fetch = fetcher or Fetcher()
        self.resolve = resolve
        self.today = today

    # ---- layer 2 -------------------------------------------------------------------------------
    def entailment(self, fact: Fact, page: Page, target: Target) -> Check:
        """Key metrics: "supports" must be unanimous over ENTAILMENT_VOTES_KEY calls; the first other
        label decides. Non-key metrics: one call."""
        _, where = verify._locate_quote(fact.quote, page.text)
        s, e = where or (0, 0)
        passage = page.text[max(0, s - CONTEXT_CHARS): e + CONTEXT_CHARS]
        prompt = ENTAIL_PROMPT.format(claim=_claim(fact, target), url=page.final_url or page.url,
                                      passage=passage, labels=" | ".join(ENTAIL_LABELS))
        votes = policy.ENTAILMENT_VOTES_KEY if fact.value is not None and policy.metric(fact.metric).key else 1
        reason = ""
        for i in range(votes):
            try:
                out = self.llm.json(prompt)
                label, reason = out.get("label"), out.get("reason", "")
            except Exception as e:
                log.error("entailment call failed for %s: %s", fact.id, e)
                return Check(layer="entailment", name="entailment", ok=None, detail=f"not graded: {e}")
            if label not in ENTAIL_LABELS:
                return Check(layer="entailment", name="entailment", ok=None, detail=f"unparseable label {label!r}")
            if label != "supports":
                split = f" (after {i} supporting vote{'s' if i != 1 else ''})" if i else ""
                return Check(layer="entailment", name="entailment", ok=False, detail=f"{label}{split}: {reason}")
        return Check(layer="entailment", name="entailment", ok=True,
                     detail=f"supports{f' ({votes}/{votes})' if votes > 1 else ''}: {reason}")

    # ---- layer 3 -------------------------------------------------------------------------------
    def _pick(self, fact: Fact, target: Target, page: Page) -> numbers.NumberSpan | None:
        spans = numbers.extract(page.text)
        words = policy.UNIT_SYNONYMS.get(fact.unit, ())
        tagged = numbers.tag(page.text, spans).split("\n")
        lines = [ln for ln in tagged if "⟦" in ln and any(w in ln.lower() for w in words)][:MAX_PICK_LINES]
        if not lines:
            return None
        out = self.picker.json(PICK_PROMPT.format(claim=_claim(fact, target), lines="\n".join(lines)))
        ref = out.get("value_ref")
        span = next((sp for sp in spans if sp.id == ref), None)
        return span if span and span.usable else None

    def corroborate(self, fact: Fact, target: Target, original: Page) -> tuple[list[Check], list[str]]:
        try:
            found = [self.resolve(u) for u in self.llm.search(SEARCH_PROMPT.format(claim=_claim(fact, target)))]
        except Exception as e:
            log.error("corroboration search failed for %s: %s", fact.id, e)
            return [Check(layer="corroboration", name="search", ok=None, detail=f"search failed: {e}")], []
        own = _domain(original.final_url or original.url)
        candidates = [u for u in dict.fromkeys(found) if _domain(u) != own][:MAX_CANDIDATES]
        checks, supporting = [], []
        for url in candidates:
            page = self.fetch(url)
            if page.error:
                checks.append(Check(layer="corroboration", name="source", ok=None, detail=f"{url}: {page.error}"))
                continue
            try:
                span = self._pick(fact, target, page)
            except Exception as e:
                checks.append(Check(layer="corroboration", name="source", ok=None, detail=f"{url}: pick failed {e}"))
                continue
            if span is None:
                checks.append(Check(layer="corroboration", name="source", ok=None, detail=f"{url}: metric not stated"))
                continue
            s, e = numbers.sentence_around(page.text, span.start, span.end)
            sentence = page.text[s:e]
            # Subject left open: a second source may name the organization differently.
            other = Fact(**{**fact.model_dump(), "value": span.value, "value_raw": span.raw,
                            "qualifier": span.qualifier, "quote": sentence, "source_url": url, "subject": ""})
            fixed = verify.check_fact(other, page, target, self.today)
            if verify.fixed_verdict(fixed) is not None:
                bad = "; ".join(c.detail for c in fixed if c.ok is False) or "fixed checks did not run"
                checks.append(Check(layer="corroboration", name="source", ok=None, detail=f"{url}: {bad}"))
                continue
            # The picked number counts only if its own passage states the same claim (same metric, place,
            # time, organization). Harris run: a "250" on a disaster-declaration page verified a 250-person
            # shelter area because only the values were compared.
            same = self.entailment(other, page, target)
            if not same.ok:
                checks.append(Check(layer="corroboration", name="source", ok=None,
                                    detail=f"{url}: {span.raw} is not the same claim ({same.detail[:120]})"))
                continue
            close = abs(span.value - fact.value) <= policy.CORROBORATION_TOLERANCE * abs(fact.value)
            copy = _overlap(sentence, fact.quote) >= SYNDICATED_RATIO
            if close and copy:
                checks.append(Check(layer="corroboration", name="independent", ok=None,
                                    detail=f"{url}: same sentence as the cited source (syndicated copy), not counted"))
            elif close:
                supporting.append(url)
                checks.append(Check(layer="corroboration", name="independent", ok=True, detail=f"{url}: {span.raw}"))
            else:
                checks.append(Check(layer="corroboration", name="conflict", ok=False, severity="flag",
                                    detail=f"{url}: states {span.raw} ({span.qualifier})"))
        return checks, supporting

    # ---- verdict ---------------------------------------------------------------------------------
    def review_fact(self, fact: Fact, target: Target) -> FactReview:
        page = self.fetch(fact.source_url)
        checks = verify.check_fact(fact, page, target, self.today)
        verdict = verify.fixed_verdict(checks)
        if verdict is not None:
            return FactReview(fact_id=fact.id, verdict=verdict, checks=checks)
        l2 = self.entailment(fact, page, target)
        checks.append(l2)
        if l2.ok is None:
            return FactReview(fact_id=fact.id, verdict=Verdict.UNCHECKED, checks=checks)
        if not l2.ok:
            return FactReview(fact_id=fact.id, verdict=Verdict.UNSUPPORTED, checks=checks)
        official = policy.is_official(page.final_url or fact.source_url)
        note = "official source" if official else ""
        if fact.value is None or not policy.metric(fact.metric).key:
            return FactReview(fact_id=fact.id, verdict=Verdict.SINGLE_SOURCE, checks=checks, notes=note)
        l3, supporting = self.corroborate(fact, target, page)
        checks += l3
        # A conflict always goes to the reviewer, even with support (policy.CONFLICTS_AUTO_RESOLVE False).
        if any(c.name == "conflict" for c in l3):
            verdict = Verdict.CONFLICTING
        elif supporting:
            verdict = Verdict.VERIFIED
        else:
            verdict = Verdict.SINGLE_SOURCE
        return FactReview(fact_id=fact.id, verdict=verdict, checks=checks, corroborating_urls=supporting, notes=note)

    def _safe_review(self, f: Fact, target: Target) -> FactReview:
        try:
            return self.review_fact(f, target)
        except Exception as e:  # one broken fact must not sink the run, and must not pass
            log.error("review of %s failed: %s", f.id, e)
            return FactReview(fact_id=f.id, verdict=Verdict.UNCHECKED, notes=f"review failed: {e}")

    def review(self, draft: DraftPack, workers: int = policy.JUDGE_CONCURRENCY) -> DraftPack:
        # Facts are independent; one call at a time made a 20-fact county take ~25 min.
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            reviews = list(pool.map(lambda f: self._safe_review(f, draft.target), draft.facts))
        log_ = {**draft.run_log, "judge_model_calls": self.llm.count,
                "judge_pick_calls": self.picker.count if self.picker is not self.llm else None,
                "judge_pick_model": getattr(self.picker, "model", None), "judge_fetches": self.fetch.count,
                "judge_seconds": round(time.time() - t0, 1), "judge_workers": workers}
        return draft.model_copy(update={"reviews": reviews, "judge_model": self.model, "run_log": log_})
