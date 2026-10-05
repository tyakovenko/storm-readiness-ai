"""Deterministic number pass (research.numbers): kinds, qualifiers, scale, ranges, by-reference facts."""

import pytest

from research.numbers import BadReference, extract, fact_from_ref, tag
from research.schema import FactDraft


def one(text, raw=None):
    spans = extract(text)
    return next(s for s in spans if raw is None or s.raw == raw)


@pytest.mark.parametrize("text,raw,value,kind", [
    ("shelters housed 1,314 evacuees", "1,314", 1314, "quantity"),
    ("2.26 million customers", "2.26 million", 2_260_000, "quantity"),
    ("cost $2.9M in overtime", "$2.9M", 2_900_000, "money"),
    ("cost $4.2 million", "$4.2 million", 4_200_000, "money"),
    ("30.4% of customers", "30.4%", 30.4, "percent"),
    ("opened twelve shelters", "twelve", 12, "quantity"),
    ("2000 beds were ready", "2000", 2000, "quantity"),
    ("in 2017 the county", "2017", 2017, "year"),
    ("Council District 14 had", "14", 14, "label"),
    ("reported by FOX 26 Houston", "26", 26, "label"),
    ("a Category 4 storm", "4", 4, "label"),
    ("closed I-45 north", "45", 45, "label"),
    ("at 1001 Preston St downtown", "1001", 1001, "label"),
    ("call 713-555-0100 now", "713-555-0100", 713, "phone"),
    ("on July 9, 2024 the peak", "July 9, 2024", 9, "date"),
    ("by 7/9/2024", "7/9/2024", 7, "date"),
    ("at 3:00 p.m. on", "3:00 p.m.", 3, "time"),
    ("the 4th shelter", "4th", 4, "ordinal"),
    ("officials told us 300 people came", "300", 300, "quantity"),
])
def test_kinds_and_values(text, raw, value, kind):
    s = one(text, raw)
    assert (s.value, s.kind) == (value, kind)


@pytest.mark.parametrize("text,raw,qual", [
    ("more than 2,000 beds", "2,000", "over"),
    ("at least 1,200 people", "1,200", "at_least"),
    ("180+ virtual staff", "180+", "at_least"),
    ("approximately 950 guests", "950", "about"),
    ("up to 300 cots", "300", "up_to"),
    ("more than $2 million", "$2 million", "over"),
    ("housed 1,314 evacuees", "1,314", "exact"),
])
def test_qualifiers(text, raw, qual):
    assert one(text, raw).qualifier == qual


@pytest.mark.parametrize("text,lo,hi,kind", [
    ("1,200-1,500 beds", 1200, 1500, "quantity"),
    ("between 1,200 and 1,500 beds", 1200, 1500, "quantity"),
    ("$1.2-1.5 million", 1_200_000, 1_500_000, "money"),
    ("20–30% of customers", 20, 30, "percent"),
])
def test_ranges(text, lo, hi, kind):
    a, b = [s for s in extract(text) if s.usable]
    assert (a.value, b.value, a.kind, b.kind) == (lo, hi, kind, kind)
    assert (a.qualifier, b.qualifier, a.range_of, b.range_of) == ("range_low", "range_high", b.id, a.id)


def test_two_counts_joined_by_and_are_not_a_range():
    a, b = [s for s in extract("12 shelters and 300 staff") if s.usable]
    assert a.range_of is None and b.range_of is None


def test_tag_marks_only_usable_numbers():
    text = "On July 9, 2024, FOX 26 said 1,314 evacuees were housed."
    spans = extract(text)
    out = tag(text, spans)
    usable = [s for s in spans if s.usable]
    assert len(usable) == 1 and f"⟦{usable[0].id}⟧1,314" in out
    assert "FOX 26" in out and "⟦" not in out.split("said")[0]


TEXT = "Harris County opened 12 shelters. At the peak, shelters housed more than 1,314 evacuees. Source: FOX 26."


def draft(**kw):
    base = dict(id="f1", metric="evacuee_count", unit="people", source="AAR", source_url="https://x.gov/u", retrieved="2026-10-05",
                subject="Harris County")
    return FactDraft(**{**base, **kw})


def test_fact_from_ref_takes_value_qualifier_and_sentence_from_page():
    spans = extract(TEXT)
    ref = next(s.id for s in spans if s.raw == "1,314")
    f = fact_from_ref(draft(value_ref=ref), spans, TEXT)
    assert (f.value, f.value_raw, f.qualifier) == (1314, "1,314", "over")
    assert f.quote == "At the peak, shelters housed more than 1,314 evacuees."


def test_fact_from_ref_rejects_label_and_unknown_ids():
    spans = extract(TEXT)
    label = next(s.id for s in spans if s.raw == "26")
    with pytest.raises(BadReference, match="label"):
        fact_from_ref(draft(value_ref=label), spans, TEXT)
    with pytest.raises(BadReference):
        fact_from_ref(draft(value_ref="N999"), spans, TEXT)


def test_existence_fact_keeps_its_quote():
    f = fact_from_ref(draft(metric="staging_sites", unit="sites", quote="Harris County opened 12 shelters."),
                      extract(TEXT), TEXT)
    assert f.value is None


def test_extracted_fact_passes_layer1_on_the_same_page():
    """Round trip: a fact built by reference passes the judge's own parse of the page."""
    from research.schema import Page, Target
    from research.verify import check_fact, fixed_verdict
    spans = extract(TEXT)
    f = fact_from_ref(draft(value_ref=next(s.id for s in spans if s.raw == "1,314")), spans, TEXT)
    t = Target(fips="48201", county="Harris County", state="TX", hazard="hurricane")
    assert fixed_verdict(check_fact(f, Page(url="u", text=TEXT), t)) is None


def test_extract_is_linear_on_long_colonless_lines():
    """Regression: a field-name regex backtracked catastrophically and hung a judge run at 100 % CPU."""
    import time
    line = " ".join(f"word {i} more text here" for i in range(5000))
    t = time.time()
    assert len(extract(line)) == 5000
    assert time.time() - t < 3
