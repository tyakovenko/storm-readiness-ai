"""Gold-set scorer (evals.research_gold), offline: recall, same_as merging, decoys, contradictions."""

from evals.research_gold import score
from research.schema import DraftPack, Fact, FactReview, Storm, Target, Verdict

TARGET = Target(fips="48201", county="Harris County", state="TX", hazard="hurricane",
                storms=[Storm(id="AL092017", name="Harvey", year=2017), Storm(id="AL022024", name="Beryl", year=2024)])
GOLD = {"facts": [
    {"id": "g1", "metric": "shelter_capacity", "unit": "people", "value_raw": "10,000", "storm_id": "AL092017",
     "subject": "Harris County"},
    {"id": "g3", "metric": "shelter_capacity", "unit": "people", "value_raw": "10,000", "storm_id": "AL092017", "same_as": "g1",
     "subject": "Harris County"},
    {"id": "g2", "metric": "evacuee_count", "unit": "people", "value_raw": "3,365", "storm_id": "AL092017",
     "subject": "NRG Center"}],
    "decoys": [{"metric": "evacuee_count", "value": 9000, "storm_id": "AL092017", "unless_subject": "George R. Brown",
                "why": "one shelter"}]}


def fact(i, metric, value, storm="AL092017", subject="Harris County", place=None):
    return Fact(id=i, metric=metric, value=value, value_raw=f"{value:,}", unit="people", storm_id=storm, place=place,
                subject=subject, quote="q" * 30, source="s", source_url="https://x.gov/a", retrieved="2026-10-05")


def draft(facts, verdicts):
    return DraftPack(target=TARGET, run_id="r", researcher_model="m", facts=facts,
                     reviews=[FactReview(fact_id=f.id, verdict=v) for f, v in zip(facts, verdicts)])


def test_recall_merges_same_as_and_counts_verdicts():
    s = score(draft([fact("f1", "shelter_capacity", 10000)], [Verdict.VERIFIED]), GOLD)
    assert s["recall"] == "1/2" and s["found"] == {"g1": ["f1"]} and s["missed"] == ["g2"]
    assert s["matched_verdicts"] == {"verified": 1} and s["false_verified"] == []


def test_decoy_verified_is_false_verification_unless_subject_names_it():
    bad = score(draft([fact("f1", "evacuee_count", 9000)], [Verdict.VERIFIED]), GOLD)
    assert bad["false_verified"][0]["why"].startswith("decoy")
    ok = score(draft([fact("f1", "evacuee_count", 9000, subject="George R. Brown Convention Center")],
                     [Verdict.VERIFIED]), GOLD)
    assert not any(x["why"].startswith("decoy") for x in ok["false_verified"])


def test_verified_contradiction_of_gold_counts_only_for_same_subject():
    s = score(draft([fact("f1", "evacuee_count", 4100, subject="NRG Center mega-shelter")], [Verdict.VERIFIED]), GOLD)
    assert s["false_verified"] == [{"fact": "f1", "why": "contradicts a gold fact (same metric/storm/place/subject, other value)"}]
    other = score(draft([fact("f1", "evacuee_count", 14154, subject="Red Cross")], [Verdict.VERIFIED]), GOLD)
    assert other["false_verified"] == []


def test_single_source_decoy_is_not_a_false_verification():
    assert score(draft([fact("f1", "evacuee_count", 9000)], [Verdict.SINGLE_SOURCE]), GOLD)["false_verified"] == []
