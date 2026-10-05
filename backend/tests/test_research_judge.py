"""Research judge verdict logic with a scripted model (no network). Live quality is the planted-error eval."""

from datetime import date

from research import numbers
from research.fetch import Fetcher
from research.judge import Judge, _overlap
from research.schema import DraftPack, Fact, FactDraft, Page, Storm, Target, Verdict

TARGET = Target(fips="48201", county="Harris County", state="TX", hazard="hurricane", cities=["Houston"],
                storms=[Storm(id="AL022024", name="Beryl", year=2024)])
AAR = "https://www.readyharris.org/beryl"
PAGES = {
    AAR: "Harris County, Beryl 2024. County shelters had capacity for 2,000 people during the storm.\n"
         "Harris County opened 12 shelters.",
    "https://news.example.com/a": "Harris County said shelters could hold 2,000 people during Beryl in 2024.",
    "https://wire.example.org/b": "Harris County, Beryl 2024. County shelters had capacity for 2,000 people during the storm.",
    "https://other.example.net/c": "Harris County said shelters could hold 2,500 people during Beryl in 2024.",
    "https://www.readyharris.org/other": "Harris County, Beryl 2024. Shelters could hold 2,000 people.",
}


class FakeLLM:
    def __init__(self, entail="supports", pick="first", search=()):
        self.entail, self.pick_mode, self.results, self.count, self.prompts = entail, pick, list(search), 0, []

    def json(self, prompt):
        self.count += 1
        self.prompts.append(prompt)
        if prompt.startswith("You check one claim"):
            if self.entail == "garbage":
                return {"label": "maybe"}
            return {"label": self.entail, "reason": "scripted"}
        lines = prompt.split("Lines:", 1)[1]  # the instructions above carry an example tag
        ref = next((t for t in lines.split("⟦")[1:]), None)  # first tagged number in the lines
        return {"value_ref": ref.split("⟧")[0] if ref and self.pick_mode == "first" else None}

    def search(self, prompt):
        self.count += 1
        return self.results


def judge(**kw):
    fetcher = Fetcher(get=lambda u: Page(url=u, final_url=u, text=PAGES[u]) if u in PAGES else Page(url=u, error="HTTP 404"))
    llm = FakeLLM(**kw)
    return Judge("fake", llm=llm, fetcher=fetcher, resolve=lambda u: u, today=date(2026, 10, 5)), llm


def fact(metric="shelter_capacity", unit="people", raw="2,000", **kw) -> Fact:
    spans = numbers.extract(PAGES[AAR])
    sid = next(s.id for s in spans if s.raw == raw)
    d = FactDraft(id="f1", metric=metric, unit=unit, value_ref=sid, source="AAR", source_url=AAR, subject="Harris County",
                  retrieved="2026-10-05", as_of="2024", **kw)
    return numbers.fact_from_ref(d, spans, PAGES[AAR])


def test_layer1_failure_skips_the_model():
    j, llm = judge()
    bad = fact().model_copy(update={"value": 2001.0, "value_raw": "2,001"})
    assert j.review_fact(bad, TARGET).verdict is Verdict.UNSUPPORTED and llm.count == 0


def test_entailment_rejects():
    j, _ = judge(entail="wrong_metric")
    r = j.review_fact(fact(), TARGET)
    assert r.verdict is Verdict.UNSUPPORTED and r.checks[-1].detail.startswith("wrong_metric")


def test_unparseable_entailment_is_unchecked():
    j, _ = judge(entail="garbage")
    assert j.review_fact(fact(), TARGET).verdict is Verdict.UNCHECKED


def test_entailment_prompt_has_claim_not_researcher_reasoning():
    j, llm = judge()
    j.review_fact(fact(), TARGET)
    p = llm.prompts[0]
    assert "metric: shelter_capacity (people)" in p and "value: exact 2,000" in p and "Harris County, TX" in p


def test_non_key_metric_is_single_source_marked_official():
    j, llm = judge(search=("https://news.example.com/a",))
    r = j.review_fact(fact(metric="shelter_count", unit="shelters", raw="12"), TARGET)
    assert r.verdict is Verdict.SINGLE_SOURCE and r.notes == "official source"
    assert llm.count == 1  # no corroboration for non-key metrics


def test_independent_source_verifies():
    j, _ = judge(search=("https://news.example.com/a",))
    r = j.review_fact(fact(), TARGET)
    assert r.verdict is Verdict.VERIFIED and r.corroborating_urls == ["https://news.example.com/a"]


def test_syndicated_copy_not_counted():
    j, _ = judge(search=("https://wire.example.org/b",))
    r = j.review_fact(fact(), TARGET)
    assert r.verdict is Verdict.SINGLE_SOURCE and any("syndicated" in c.detail for c in r.checks)


def test_same_domain_not_independent():
    j, _ = judge(search=("https://www.readyharris.org/other",))
    assert j.review_fact(fact(), TARGET).verdict is Verdict.SINGLE_SOURCE


def test_different_value_is_conflicting_even_with_support():
    j, _ = judge(search=("https://news.example.com/a", "https://other.example.net/c"))
    r = j.review_fact(fact(), TARGET)
    assert r.verdict is Verdict.CONFLICTING and "2,500" in next(c.detail for c in r.checks if c.name == "conflict")


def test_candidate_number_with_another_meaning_not_counted():
    class SecondPassageDisagrees(FakeLLM):
        def json(self, prompt):
            out = super().json(prompt)
            if prompt.startswith("You check one claim") and "news.example.com" in prompt:
                return {"label": "wrong_metric", "reason": "a different 2,000"}
            return out
    j, _ = judge(search=("https://news.example.com/a",))
    j.llm = SecondPassageDisagrees(search=("https://news.example.com/a",))
    r = j.review_fact(fact(), TARGET)
    assert r.verdict is Verdict.SINGLE_SOURCE and any("not the same claim" in c.detail for c in r.checks)


def test_unreadable_candidate_is_reported_not_counted():
    j, _ = judge(search=("https://gone.example.com/x",))
    r = j.review_fact(fact(), TARGET)
    assert r.verdict is Verdict.SINGLE_SOURCE and any("HTTP 404" in c.detail for c in r.checks)


def test_review_survives_a_broken_fact():
    j, _ = judge()
    j.review_fact = lambda f, t: (_ for _ in ()).throw(RuntimeError("boom"))
    draft = DraftPack(target=TARGET, run_id="r", researcher_model="m", facts=[fact()])
    out = j.review(draft)
    assert out.reviews[0].verdict is Verdict.UNCHECKED and "boom" in out.reviews[0].notes and out.judge_model == "fake"


def test_overlap_catches_rewritten_lead_in():
    a = "County shelters had capacity for 2,000 people; occupancy peaked at 1,314 evacuees on July 9."
    b = "At Hurricane Beryl's peak, county shelters had capacity for 2,000 people; occupancy peaked at 1,314 evacuees on July 9."
    assert _overlap(a, b) >= 0.9
    assert _overlap(a, "Harris County said shelters could hold 2,000 people during Beryl in 2024.") < 0.9


def test_rate_limit_retried_then_surfaced(monkeypatch):
    from research import judge as J
    calls = []

    class Models:
        def generate_content(self, **kw):
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return type("R", (), {"text": '{"label": "supports"}'})()

    g = J.GeminiCalls.__new__(J.GeminiCalls)
    g.model, g.cap, g.count, g._sleep = "m", 10, 0, lambda s: None
    g.client = type("C", (), {"models": Models()})()
    assert g.json("x") == {"label": "supports"} and len(calls) == 3

    calls.clear()
    Models.generate_content = lambda self, **kw: (_ for _ in ()).throw(RuntimeError("400 INVALID_ARGUMENT"))
    import pytest
    with pytest.raises(RuntimeError, match="400"):
        g.json("x")
