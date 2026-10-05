"""Planted-error eval for the research judge (plan R3).

Synthetic source pages (served by a fake fetcher) hold correct facts and traps. Each case is a fact the
judge reviews; planted errors must not come out VERIFIED and must be stopped by the expected layer.
Controls must get their expected verdict (else: false alarm). Layers 2-3 call the real judge model;
only web search is stubbed, so the candidate "second sources" are controlled.

    python -m evals.research_planted_errors                          # judge model from research.config
    python -m evals.research_planted_errors --models gemini-3.1-pro-preview gemini-2.5-pro gemini-3.8-flash
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date

from research import config, numbers
from research.fetch import Fetcher
from research.judge import GeminiCalls, Judge
from research.schema import Fact, FactDraft, Page, Storm, Target, Verdict

TODAY = date(2026, 10, 5)
TARGET = Target(fips="48201", county="Harris County", state="TX", hazard="hurricane", cities=["Houston", "Pasadena"],
                storms=[Storm(id="AL022024", name="Beryl", year=2024), Storm(id="AL092017", name="Harvey", year=2017),
                        Storm(id="AL092008", name="Ike", year=2008)])

AAR = "https://www.readyharris.org/beryl-2024-aar"
AAR_TEXT = """Harris County Office of Homeland Security and Emergency Management
Hurricane Beryl (July 2024) After-Action Summary
Harris County opened 12 shelters ahead of landfall on July 8, 2024.
County shelters had capacity for 2,000 people; occupancy peaked at 1,314 evacuees on July 9.
Citywide, the City of Houston deployed 3,000 employees to storm response, according to the Mayor's office.
For comparison, during Hurricane Ike in 2008, county shelters housed 4,100 evacuees.
CenterPoint Energy brought in 12,000 restoration workers, including mutual aid crews from other states.
The City of Houston set up a cooling shelter at a sports complex to hold as many as 250 people.
Hurricane Harvey in 2017 remains the county's largest sheltering operation.
Reported by FOX 26 Houston and county staff."""

FEMA = "https://www.fema.gov/pa-projects/ike-memorial-hermann"
FEMA_TEXT = """FEMA Public Assistance - Hurricane Ike (DR-1791), Texas, 2008.
Applicant: Memorial Hermann Health System, headquartered in Houston, Harris County, Texas.
FEMA obligated $4.2 million to the applicant for emergency protective measures at its hospital in Galveston County.
Project category B, emergency protective measures, approved in 2009 for the Galveston facility."""

NEWS = "https://www.houstonchronicle.com/news/beryl-shelters"
NEWS_TEXT = """Houston Chronicle, July 2024. Beryl shelters in Harris County.
Harris County said its shelters could hold 2,000 people during Hurricane Beryl in 2024, with Red Cross support.
Officials said Houston-area shelters stayed open through July 12 as power returned slowly."""

COPY = "https://www.ksat.com/news/ap-beryl-shelters"
COPY_TEXT = """Associated Press, July 2024. Harris County, Texas.
At Hurricane Beryl's peak, county shelters had capacity for 2,000 people; occupancy peaked at 1,314 evacuees on July 9.
The county said shelters would stay open while power was restored across Houston in 2024."""

GALV = "https://www.galvestoncountytx.gov/beryl"
GALV_TEXT = """Galveston County Office of Emergency Management, Hurricane Beryl, July 2024.
Galveston County opened 4 shelters; occupancy peaked at 1,314 evacuees on July 9, 2024, in League City and Texas City.
The county thanks volunteers from Texas City and League City for their support."""

DECL = "https://gov.texas.gov/news/beryl-declaration"
DECL_TEXT = """Office of the Texas Governor, July 2024. Hurricane Beryl disaster declaration.
The state deployed more than 250 personnel from the Texas Division of Emergency Management to Harris County.
Houston and surrounding counties were approved for federal assistance after Hurricane Beryl in 2024."""

PAGES = {DECL: DECL_TEXT, AAR: AAR_TEXT, FEMA: FEMA_TEXT, NEWS: NEWS_TEXT, COPY: COPY_TEXT, GALV: GALV_TEXT}


def by_ref(url: str, raw: str, **kw) -> Fact:
    """Facts are built the production way: by reference to a span on the page."""
    text = PAGES[url]
    spans = numbers.extract(text)
    sid = next(s.id for s in spans if s.raw == raw and s.usable)
    d = FactDraft(id=kw.pop("id"), value_ref=sid, source=kw.pop("source", "src"), source_url=url,
                  retrieved="2026-10-05", subject=kw.pop("subject", "Harris County"), **kw)
    return numbers.fact_from_ref(d, spans, text)


class SchemaRejected:
    """The typed contract refused the fact before any check ran: counts as caught, at layer "schema"."""

    def __init__(self, error: Exception):
        self.error = str(error).splitlines()[1].strip() if "\n" in str(error) else str(error)


def raw_fact(**kw) -> Fact | SchemaRejected:
    """A fact as a careless researcher would write it (bypassing by-reference), to test layer 1."""
    base = dict(source="src", retrieved="2026-10-05")
    try:
        return Fact(**{**base, **kw})
    except ValueError as e:
        return SchemaRejected(e)


@dataclass
class Case:
    name: str
    fact: Fact | SchemaRejected
    planted: bool
    expect: Verdict | tuple | str   # verdict(s) that count as correct; "schema_rejected" = refused by the contract
    layer: str                # layer expected to decide: fixed | entailment | corroboration
    search: tuple = ()        # stubbed web-search results for corroboration


def cases() -> list[Case]:
    return [
        # ---- controls ----
        Case("control: evacuees by reference", by_ref(AAR, "1,314", id="c1", metric="evacuee_count", unit="people",
             storm_id="AL022024"), False, (Verdict.SINGLE_SOURCE, Verdict.VERIFIED), "entailment"),
        Case("control: capacity, independent 2nd source", by_ref(AAR, "2,000", id="c2", metric="shelter_capacity",
             unit="people", as_of="2024"), False, Verdict.VERIFIED, "corroboration", search=(NEWS,)),
        Case("control: city figure with place=Houston", by_ref(AAR, "3,000", id="c4", metric="staff_count",
             unit="people", as_of="2024", place="Houston", subject="City of Houston"), False, Verdict.SINGLE_SOURCE, "entailment"),
        Case("control: shelter count (non-key)", by_ref(AAR, "12", id="c3", metric="shelter_count", unit="shelters",
             storm_id="AL022024"), False, Verdict.SINGLE_SOURCE, "entailment"),
        # ---- planted: layer 1 ----
        Case("wrong value", raw_fact(id="p1", metric="evacuee_count", value=1341, value_raw="1,341", unit="people",
             storm_id="AL022024", quote="occupancy peaked at 1,314 evacuees on July 9", source_url=AAR),
             True, Verdict.UNSUPPORTED, "fixed"),
        Case("wrong unit", raw_fact(id="p2", metric="evacuee_count", value=1314, value_raw="1,314", unit="customers",
             storm_id="AL022024", quote="occupancy peaked at 1,314 evacuees on July 9", source_url=AAR),
             True, "schema_rejected", "schema"),
        Case("wrong county", by_ref(GALV, "1,314", id="p3", metric="evacuee_count", unit="people",
             storm_id="AL022024", subject="Galveston County"), True, Verdict.UNSUPPORTED, "fixed"),
        Case("quote not in page", raw_fact(id="p4", metric="evacuee_count", value=1314, value_raw="1,314",
             unit="people", storm_id="AL022024", quote="shelters housed 1,314 people at the peak of Beryl",
             source_url=AAR), True, Verdict.UNSUPPORTED, "fixed"),
        Case("number only in citation", raw_fact(id="p5", metric="staff_count", value=26, value_raw="26",
             unit="people", as_of="2024", quote="Reported by FOX 26 Houston and county staff.", source_url=AAR),
             True, Verdict.UNSUPPORTED, "fixed"),
        # ---- planted: layer 2 ----
        Case("applicant county (FEMA PA)", by_ref(FEMA, "$4.2 million", id="p6", metric="fema_pa_total", unit="usd", subject="Memorial Hermann",
             storm_id="AL092008"), True, Verdict.UNSUPPORTED, "entailment"),
        Case("city figure as county", by_ref(AAR, "3,000", id="p7", metric="staff_count", unit="people",
             as_of="2024", subject="Harris County"), True, Verdict.UNSUPPORTED, "entailment"),
        Case("wrong storm (Ike figure as Harvey)", by_ref(AAR, "4,100", id="p8", metric="evacuee_count", unit="people",
             storm_id="AL092017"), True, Verdict.UNSUPPORTED, "entailment"),
        Case("occupancy as capacity", by_ref(AAR, "1,314", id="p9", metric="shelter_capacity", unit="people",
             as_of="2024"), True, Verdict.UNSUPPORTED, "entailment"),
        Case("utility workers as county staff", by_ref(AAR, "12,000", id="p11", metric="staff_count", unit="people",
             as_of="2024", subject="CenterPoint Energy"), True, Verdict.UNSUPPORTED, "entailment"),
        # ---- planted: layer 3 ----
        Case("same number, other meaning, as 2nd source", by_ref(AAR, "250", id="p12", metric="shelter_capacity",
             unit="people", as_of="2024", place="Houston", subject="City of Houston"), True, Verdict.SINGLE_SOURCE,
             "corroboration", search=(DECL,)),
        Case("syndicated copy as 2nd source", by_ref(AAR, "1,314", id="p10", metric="evacuee_count", unit="people",
             storm_id="AL022024"), True, Verdict.SINGLE_SOURCE, "corroboration", search=(COPY,)),
    ]


class StubSearch(GeminiCalls):
    """Real model for entailment and number picking; web search answers from the case's stub list."""

    def __init__(self, model: str):
        super().__init__(model)
        self.results: tuple = ()

    def search(self, prompt: str) -> list[str]:
        self.count += 1
        return list(self.results)


def layer_of(review) -> str:
    """The layer that decided: the last layer with a failing blocking check, else the last layer that ran."""
    failing = [c.layer for c in review.checks if c.ok is False and c.severity == "block"]
    return failing[0] if failing else (review.checks[-1].layer if review.checks else "none")


def run(model: str) -> dict:
    llm = StubSearch(model)
    fetcher = Fetcher(get=lambda url: Page(url=url, final_url=url, text=PAGES[url], retrieved="2026-10-05")
                      if url in PAGES else Page(url=url, error="HTTP 404"))
    judge = Judge(model, llm=llm, fetcher=fetcher, resolve=lambda u: u, today=TODAY)
    rows = []
    for c in cases():
        llm.results = c.search
        if isinstance(c.fact, SchemaRejected):
            rows.append({"case": c.name, "planted": c.planted, "verdict": "schema_rejected",
                         "ok": c.expect == "schema_rejected", "false_verified": False, "layer": "schema",
                         "expected_layer": c.layer, "detail": c.fact.error[:110]})
            continue
        r = judge.review_fact(c.fact, TARGET)
        expect = c.expect if isinstance(c.expect, tuple) else (c.expect,)
        ok = r.verdict in expect
        false_verified = c.planted and r.verdict is Verdict.VERIFIED
        detail = next((ch.detail for ch in r.checks if ch.ok is False), r.checks[-1].detail if r.checks else r.notes)
        rows.append({"case": c.name, "planted": c.planted, "verdict": r.verdict.value, "ok": ok,
                     "false_verified": false_verified, "layer": layer_of(r), "expected_layer": c.layer,
                     "detail": detail[:110]})
    planted = [r for r in rows if r["planted"]]
    controls = [r for r in rows if not r["planted"]]
    return {"model": model, "rows": rows, "caught": sum(r["ok"] for r in planted), "planted": len(planted),
            "false_verified": sum(r["false_verified"] for r in rows), "false_alarms": sum(not r["ok"] for r in controls),
            "controls": len(controls), "model_calls": llm.count}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=[config.JUDGE_MODEL])
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    config.vertex_env()
    for m in a.models:
        res = run(m)
        print(f"\n## {m}: caught {res['caught']}/{res['planted']}, false verifications {res['false_verified']}, "
              f"false alarms {res['false_alarms']}/{res['controls']}, {res['model_calls']} calls")
        print("| case | verdict | ok | layer (expected) | detail |\n|---|---|---|---|---|")
        for r in res["rows"]:
            print(f"| {r['case']} | {r['verdict']} | {'✓' if r['ok'] else '✗'} | {r['layer']} ({r['expected_layer']}) "
                  f"| {r['detail']} |")


if __name__ == "__main__":
    main()
