"""Research judge layer 1 (fixed checks), no network: pages are inline text.

One correct fact passes; each test then breaks one thing and checks the matching check catches it.
"""

from datetime import date

import pytest

from research.schema import DraftPack, Fact, Page, Storm, Target, Verdict
from research.verify import check_fact, fixed_verdict

TODAY = date(2026, 10, 5)
TARGET = Target(fips="48201", county="Harris County", state="TX", hazard="hurricane",
                cities=["Houston", "Pasadena"], storms=[Storm(id="beryl_2024", name="Beryl", year=2024),
                                                         Storm(id="harvey_2017", name="Harvey", year=2017)])
PAGE_TEXT = (
    "Harris County Office of Homeland Security — Hurricane Beryl after-action summary, July 2024.\n"
    "The county opened 12 shelters. At the peak, shelters housed 1,314 evacuees on July 9, "
    "with a combined capacity of “more than 2,000 beds” across sites in Houston and Pasadena.\n"
    "CenterPoint reported 2.26 million customers without power.\n"
    "Source: FOX 26 Houston.")
PAGE = Page(url="https://www.readyharris.org/beryl-aar", text=PAGE_TEXT)


def fact(**kw) -> Fact:
    base = dict(id="f1", metric="evacuee_count", value=1314, value_raw="1,314", unit="people", storm_id="beryl_2024",
                quote="At the peak, shelters housed 1,314 evacuees on July 9", source="Beryl AAR",
                source_url=PAGE.url, retrieved="2026-10-05")
    return Fact(**{**base, **kw})


def by_name(checks):
    return {c.name: c for c in checks}


def test_correct_fact_passes_layer1():
    checks = check_fact(fact(), PAGE, TARGET, TODAY)
    assert fixed_verdict(checks) is None, [c for c in checks if c.ok is False]
    c = by_name(checks)
    assert c["quote_in_source"].ok and c["value_at_source"].ok and c["unit"].ok
    assert c["jurisdiction"].ok and c["storm"].ok


def test_quote_with_curly_quotes_and_dashes_matches():
    f = fact(metric="shelter_capacity", value=2000, value_raw="2,000", qualifier="over", storm_id=None,
             as_of="2024-07", quote='combined capacity of "more than 2,000 beds" across sites')
    c = by_name(check_fact(f, PAGE, TARGET, TODAY))
    assert c["quote_in_source"].ok and c["value_at_source"].ok and c["unit"].ok


def test_qualifier_dropped_is_unsupported():
    f = fact(metric="shelter_capacity", value=2000, value_raw="2,000", storm_id=None, as_of="2024-07",
             quote='combined capacity of "more than 2,000 beds" across sites')
    c = by_name(check_fact(f, PAGE, TARGET, TODAY))["value_at_source"]
    assert c.ok is False and "over" in c.detail


def test_pdf_line_break_hyphenation_matches_compact():
    page = PAGE.model_copy(update={"text": PAGE_TEXT.replace("evacuees", "evacu-\nees")})
    c = by_name(check_fact(fact(), page, TARGET, TODAY))
    assert c["quote_in_source"].ok and "ignoring punctuation" in c["quote_in_source"].detail


def test_invented_quote_is_unsupported():
    checks = check_fact(fact(quote="At the peak, shelters housed 1,314 people on July 8"), PAGE, TARGET, TODAY)
    assert by_name(checks)["quote_in_source"].ok is False
    assert fixed_verdict(checks) is Verdict.UNSUPPORTED


def test_short_quote_is_unsupported():
    checks = check_fact(fact(quote="1,314 evacuees"), PAGE, TARGET, TODAY)
    assert by_name(checks)["quote_in_source"].ok is False


def test_wrong_value_is_unsupported():
    checks = check_fact(fact(value=1341), PAGE, TARGET, TODAY)
    c = by_name(checks)["value_at_source"]
    assert c.ok is False and "1,314" in c.detail
    assert fixed_verdict(checks) is Verdict.UNSUPPORTED


@pytest.mark.parametrize("value,raw,quote", [
    (2260000, "2.26 million", "CenterPoint reported 2.26 million customers without power"),
    (12, "12", "The county opened 12 shelters. At the peak"),
])
def test_value_forms(value, raw, quote):
    metric = "peak_customers_out" if value > 100 else "shelter_count"
    unit = "customers" if value > 100 else "shelters"
    f = fact(metric=metric, value=value, value_raw=raw, unit=unit, quote=quote)
    assert by_name(check_fact(f, PAGE, TARGET, TODAY))["value_at_source"].ok


def test_number_only_in_citation_not_evidence():
    # "FOX 26" carries 26, but the quote that holds it doesn't state any metric
    f = fact(metric="staff_count", value=26, value_raw="26", storm_id=None, quote="Source: FOX 26 Houston.",
             as_of="2024")
    checks = check_fact(f, PAGE, TARGET, TODAY)
    c = by_name(checks)["value_at_source"]
    assert c.ok is False and "label" in c.detail
    assert fixed_verdict(checks) is Verdict.UNSUPPORTED


def test_unit_not_matching_metric_refused_by_schema():
    with pytest.raises(ValueError, match="counted in people, not customers"):
        fact(unit="customers")


@pytest.mark.parametrize("kw,msg", [
    ({"metric": "shelter_count", "unit": "shelters", "value": 2.5, "value_raw": "2.5"}, "whole-number count"),
    ({"value": -3, "value_raw": "-3"}, "outside"),
    ({"as_of": "2024-02-30"}, "day is out of range"),
    ({"published": "last July"}, "YYYY"),
    ({"source_url": "readyharris.org/x"}, "http"),
    ({"retrieved": "yesterday"}, "ISO"),
])
def test_typed_contract(kw, msg):
    with pytest.raises(ValueError, match=msg):
        fact(**kw)


def test_counts_stored_as_int_money_as_float():
    assert type(fact(value=1314.0).value) is int
    f = fact(metric="fema_pa_total", unit="usd", value=4200000, value_raw="$4.2 million", storm_id=None)
    assert type(f.value) is float


def test_draft_rejects_storm_or_place_outside_target():
    with pytest.raises(ValueError, match="not one of Harris County's storms"):
        DraftPack(target=TARGET, run_id="r", researcher_model="m", facts=[fact(storm_id="AL092008")])
    with pytest.raises(ValueError, match="not Harris County or a listed city"):
        DraftPack(target=TARGET, run_id="r", researcher_model="m", facts=[fact(place="Galveston")])


def test_unit_word_start_only():
    page = Page(url=PAGE.url, text="Harris County Beryl 2024. As described in the plan, 1,314 was the total figure here.")
    f = fact(metric="shelter_capacity", storm_id=None, as_of="2024",
             quote="As described in the plan, 1,314 was the total figure here.")
    assert by_name(check_fact(f, page, TARGET, TODAY))["unit"].ok is False


def test_wrong_county_is_unsupported():
    page = Page(url="https://www.galvestoncountytx.gov/x",
                text=PAGE_TEXT.replace("Harris County", "Galveston County").replace("Houston", "Galveston")
                .replace("Pasadena", "League City"))
    checks = check_fact(fact(), page, TARGET, TODAY)
    assert by_name(checks)["jurisdiction"].ok is False
    assert fixed_verdict(checks) is Verdict.UNSUPPORTED


def test_city_figure_with_place():
    f = fact(metric="staff_count", value=2000, value_raw="2,000", qualifier="over", storm_id=None, as_of="2024",
             place="Houston", quote='combined capacity of "more than 2,000 beds" across sites')
    assert by_name(check_fact(f, PAGE, TARGET, TODAY))["jurisdiction"].ok
    c = by_name(check_fact(f.model_copy(update={"place": "Galveston"}), PAGE, TARGET, TODAY))["jurisdiction"]
    assert c.ok is False and "not Harris County" in c.detail


@pytest.mark.parametrize("subject,ok", [("Harris County Office of Homeland Security", True),
                                        ("Harris County Sheriff's Office", False), ("", None)])
def test_subject_named_on_page(subject, ok):
    assert by_name(check_fact(fact(subject=subject), PAGE, TARGET, TODAY))["subject"].ok is ok


def test_hyphenated_alias_matches():
    t = Target(fips="12086", county="Miami-Dade County", state="FL", hazard="hurricane")
    page = Page(url="u", text="Miami Dade shelters opened ahead of Irma 2017.")
    assert by_name(check_fact(fact(storm_id=None, quote="Miami Dade shelters opened ahead of Irma"), page, t,
                              TODAY))["jurisdiction"].ok


def test_wrong_storm_year():
    page = PAGE.model_copy(update={"text": PAGE_TEXT.replace("2024", "2018")})
    c = by_name(check_fact(fact(), page, TARGET, TODAY))["storm"]
    assert c.ok is False and "2024" in c.detail


def test_storm_not_in_target():
    c = by_name(check_fact(fact(storm_id="ike_2008"), PAGE, TARGET, TODAY))["storm"]
    assert c.ok is False


def test_stale_is_flag_not_block():
    f = fact(metric="shelter_capacity", value=2000, value_raw="2,000", qualifier="over", storm_id=None, as_of="2012",
             quote='combined capacity of "more than 2,000 beds" across sites')
    checks = check_fact(f, PAGE, TARGET, TODAY)
    stale = by_name(checks)["stale"]
    assert stale.ok is False and stale.severity == "flag"
    assert fixed_verdict(checks) is None


def test_past_storm_fact_never_stale():
    assert by_name(check_fact(fact(), PAGE, TARGET, TODAY))["stale"].ok is None


@pytest.mark.parametrize("page", [
    Page(url="u", error="HTTP 403"),
    Page(url="u", content_type="application/pdf", text=""),
])
def test_unfetched_source_is_unchecked_not_passed(page):
    checks = check_fact(fact(), page, TARGET, TODAY)
    assert fixed_verdict(checks) is Verdict.UNCHECKED


def test_value_without_raw_rejected():
    with pytest.raises(ValueError):
        fact(value_raw=None)


def test_draft_pack_rejects_duplicate_ids_and_orphan_reviews():
    with pytest.raises(ValueError):
        DraftPack(target=TARGET, run_id="r", researcher_model="m", facts=[fact(), fact()])
    from research.schema import FactReview
    with pytest.raises(ValueError):
        DraftPack(target=TARGET, run_id="r", researcher_model="m", facts=[fact()],
                  reviews=[FactReview(fact_id="nope", verdict=Verdict.VERIFIED)])
