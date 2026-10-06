"""Research R2 without network: fetch parsing, the researcher's tools, targets, agent construction."""

import io

import pytest

from research import fetch
from research.fetch import Fetcher, html_to_text, json_to_text
from research.numbers import extract
from research.schema import Page, Storm, Target
from research.tools import ResearchSession

TARGET = Target(fips="48201", county="Harris County", state="TX", hazard="hurricane", cities=["Houston"],
                storms=[Storm(id="AL022024", name="Beryl", year=2024)])
AAR = ("<html><head><script>var x = 999;</script></head><body><h1>Harris County Beryl 2024 after-action</h1>"
       "<p>At the peak, shelters housed more than 1,314 evacuees.</p><p>Source: FOX 26 Houston.</p>"
       "<table><tr><td>Shelters</td><td>12</td></tr><tr><td>Staff</td><td>300</td></tr></table>"
       "<p>The Office of Homeland Security and Emergency Management coordinated shelter operations with the "
       "American Red Cross and city partners throughout the response period.</p></body></html>")


def test_html_to_text_skips_scripts_and_separates_cells():
    text = html_to_text(AAR)
    assert "999" not in text
    assert "more than 1,314 evacuees." in text
    assert "12300" not in text.replace(" ", "")  # cells "12" and "300" stay apart
    assert "| Shelters | 12" in text


def test_leaked_escaped_markup_cleaned():
    text = html_to_text("<div>&lt;p&gt;Red Cross had &amp;ldquo;6 shelters&amp;rdquo; open.&lt;/p&gt;</div>")
    assert text == "Red Cross had \u201c6 shelters\u201d open."


def test_json_to_text_arcgis_rows_and_field_kinds():
    raw = ('{"features": [{"attributes": {"OBJECTID": 5, "NAME": "Fair Park", "CAPACITY": 1200, '
           '"YEAR_BUILT": 1998, "LAT": 25.7}}]}')
    text = json_to_text(raw)
    assert text == "OBJECTID: 5; NAME: Fair Park; CAPACITY: 1200; YEAR_BUILT: 1998; LAT: 25.7"
    kinds = {s.raw: s.kind for s in extract(text)}
    assert kinds == {"5": "label", "1200": "quantity", "1998": "year", "25.7": "label"}


def test_prose_field_prefix_keeps_year_rule():
    assert next(s for s in extract("Note: 2017 was the worst year") if s.raw == "2017").kind == "year"


class _Resp:
    def __init__(self, body: bytes, ctype: str, url="https://x.gov/a"):
        self._b, self._url = body, url
        from email.message import Message
        self.headers = Message()
        self.headers["Content-Type"] = ctype

    def read(self, n=-1):
        out, self._b = self._b, b""  # like a real response: the body once, then EOF
        return out

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("body,ctype,error", [
    (b"%PDF-1.7 ...", "application/octet-stream", fetch.PDF_ERROR),
    (b"<html><body>Loading...</body></html>", "text/html", "JS-rendered"),
    (b"\x89PNG", "image/png", "unsupported content type"),
])
def test_fetch_reports_unreadable_sources(monkeypatch, body, ctype, error):
    monkeypatch.setattr(fetch.urllib.request, "urlopen", lambda req, timeout: _Resp(body, ctype))
    page = fetch._get("https://x.gov/a")
    assert page.error and error in page.error


def test_fetch_html_ok(monkeypatch):
    monkeypatch.setattr(fetch.urllib.request, "urlopen", lambda req, timeout: _Resp(AAR.encode(), "text/html"))
    page = fetch._get("https://x.gov/a")
    assert page.error is None and "1,314" in page.text


def test_fetcher_caches_and_caps():
    calls = []

    def get(url):
        calls.append(url)
        return Page(url=url, text="x" * 300)
    f = Fetcher(max_fetches=2, get=get)
    f("a"), f("a"), f("b")
    capped = f("c")
    assert calls == ["a", "b"] and "fetch cap" in capped.error


def session(pages: dict[str, str] | None = None, get_json=None) -> ResearchSession:
    pages = pages or {"https://readyharris.org/beryl": html_to_text(AAR)}
    fetcher = Fetcher(get=lambda url: Page(url=url, text=pages[url], retrieved="2026-10-05") if url in pages
                      else Page(url=url, error="HTTP 404"))
    return ResearchSession(TARGET, {"legistar": ["miamidade"]}, fetcher, get_json=get_json)


def ref(s: ResearchSession, url: str, raw: str) -> str:
    return next(sp.id for sp in s.pages[url][1] if sp.raw == raw)


URL = "https://readyharris.org/beryl"


def test_read_source_tags_usable_numbers_only():
    s = session()
    out = s.read_source(URL)
    assert "⟦" in out["text"] and "FOX 26" in out["text"]
    assert out["next_start"] is None


def test_read_source_error_passed_to_model():
    assert session().read_source("https://nope")["error"] == "HTTP 404"


def test_submit_fact_by_reference():
    s = session()
    s.read_source(URL)
    out = s.submit_fact("evacuee_count", "people", URL, "Beryl AAR", "Harris County", value_ref=ref(s, URL, "1,314"),
                        storm_id="AL022024")
    assert out["accepted"] and out["value"] == 1314 and out["qualifier"] == "over"
    assert s.facts[0].quote == "At the peak, shelters housed more than 1,314 evacuees."


@pytest.mark.parametrize("kw,reason", [
    ({"value_ref": "1314"}, "not a number on this page"),               # typed the number instead of a tag
    ({"value_ref": "LABEL"}, "label"),                                    # FOX 26
    ({"unit": "customers", "value_ref": "EVAC"}, "counted in people"),   # unit doesn't match metric (schema)
    ({"metric": "cots", "value_ref": "EVAC"}, "not in the vocabulary"),  # metric outside the vocabulary
    ({"as_of": "July 2024", "value_ref": "EVAC"}, "YYYY"),               # free-text date
    ({"storm_id": "AL092022", "value_ref": "EVAC"}, "storm"),           # storm not in target
])
def test_submit_fact_rejections_are_logged(kw, reason):
    s = session()
    s.read_source(URL)
    swap = {"LABEL": ref(s, URL, "26"), "EVAC": ref(s, URL, "1,314")}
    kw = {k: swap.get(v, v) for k, v in kw.items()}
    out = s.submit_fact(**{"metric": "evacuee_count", "unit": "people", "source_url": URL, "source_title": "AAR",
                           "subject": "Harris County",
                           "storm_id": "AL022024", **kw})
    assert out["accepted"] is False and reason in out["reason"]
    assert s.rejected[-1]["reason"] == out["reason"] and not s.facts


def test_submit_fact_rejects_subject_not_on_page():
    s = session()
    s.read_source(URL)
    out = s.submit_fact("staff_count", "people", URL, "AAR", "CenterPoint Energy", value_ref=ref(s, URL, "300"),
                        as_of="2024")
    assert out["accepted"] is False and "never names CenterPoint Energy" in out["reason"]


def test_submit_fact_needs_read_and_rejects_duplicates():
    s = session()
    assert "read_source" in s.submit_fact("evacuee_count", "people", URL, "AAR", "Harris County", value_ref="N1")["reason"]
    s.read_source(URL)
    r = ref(s, URL, "1,314")
    assert s.submit_fact("evacuee_count", "people", URL, "AAR", "Harris County", value_ref=r, storm_id="AL022024")["accepted"]
    assert "duplicate" in s.submit_fact("evacuee_count", "people", URL, "AAR", "Harris County", value_ref=r,
                                        storm_id="AL022024")["reason"]


def test_arcgis_search_gives_query_url_for_layers():
    d = {"results": [{"title": "Shelters", "type": "Feature Service", "url": "https://services.arcgis.com/x/FeatureServer"},
                     {"title": "Map", "type": "Web Map", "url": None}]}
    out = session(get_json=lambda url: d).arcgis_search("Harris shelters")["results"]
    assert out[0]["query_url"].startswith("https://services.arcgis.com/x/FeatureServer/0/query?where=1%3D1")
    assert "query_url" not in out[1]


def test_legistar_only_configured_clients():
    seen = []
    s = session(get_json=lambda url: seen.append(url) or [{"MatterTitle": "Hurricane Ian AAR", "MatterId": 7,
                                                            "MatterGuid": "g"}])
    assert "unknown" in s.legistar_search("houston", "hurricane")["error"]
    out = s.legistar_search("miamidade", "hurricane's")["results"]
    assert out[0]["url"] == "https://miamidade.legistar.com/LegislationDetail.aspx?ID=7&GUID=g"
    assert "hurricane%27%27s" in seen[0]  # OData quote escaped


def test_portal_tools_only_where_configured():
    names = {t.__name__ for t in ResearchSession(TARGET, {"legistar": []}).tools()}
    assert "legistar_search" not in names and "arcgis_search" in names


def test_target_from_pack():
    from research.targets import target_from_pack
    try:
        target, gaps, portals = target_from_pack("12086")
    except Exception as e:  # pack not available locally or in GCS
        pytest.skip(f"hurricane pack unavailable: {e}")
    assert target.county == "Miami-Dade County" and "Dade County" in target.aliases
    assert any(s.name == "Irma" and s.year == 2017 for s in target.storms)
    assert gaps and portals["legistar"] == ["miamidade"]


def test_agent_builds_with_instruction_and_tools():
    from research.researcher import CallCap, build_agent
    s = session()
    agent = build_agent(s, [], "gemini-3.8-flash", CallCap(5))
    assert "AL022024: Beryl 2024" in agent.instruction and "shelter_capacity: people (key)" in agent.instruction
    assert "legistar_search (clients: miamidade)" in agent.instruction
    assert len(agent.tools) == 1 + len(s.tools())


def test_call_cap_answers_in_place_of_model():
    from research.researcher import CallCap
    cap = CallCap(1)
    assert cap(None, None) is None
    assert "cap" in cap(None, None).content.parts[0].text and cap.hit


def test_run_failure_saves_partial_draft(monkeypatch):
    import asyncio
    from research import researcher

    class Boom:
        def __init__(self, agent, app_name):
            self.session_service = type("SS", (), {"create_session": staticmethod(
                lambda **kw: asyncio.sleep(0, result=type("S", (), {"id": "s"})()))})()

        def run_async(self, **kw):
            async def gen():
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
                yield  # noqa
            return gen()
    monkeypatch.setattr(researcher, "InMemoryRunner", Boom)
    s = session()
    s.read_source(URL)
    s.submit_fact("evacuee_count", "people", URL, "AAR", "Harris County", value_ref=ref(s, URL, "1,314"), storm_id="AL022024")
    d = asyncio.run(researcher.run_research(TARGET, [], {}, "gemini-3.8-flash", session=s))
    assert len(d.facts) == 1 and d.run_log["partial"] and "429" in d.run_log["run_error"]


def test_hung_run_hard_stops_with_partial_draft(monkeypatch):
    import asyncio
    from research import researcher
    monkeypatch.setattr(researcher, "HARD_STOP_GRACE_S", 0)

    class Hang:
        def __init__(self, agent, app_name):
            self.session_service = type("SS", (), {"create_session": staticmethod(
                lambda **kw: asyncio.sleep(0, result=type("S", (), {"id": "s"})()))})()

        def run_async(self, **kw):
            async def gen():
                await asyncio.sleep(3600)  # a model call that never returns
                yield None
            return gen()
    monkeypatch.setattr(researcher, "InMemoryRunner", Hang)
    d = asyncio.run(researcher.run_research(TARGET, [], {}, "gemini-3.8-flash", session=session(), max_seconds=1))
    assert d.run_log["partial"] and "hard stop" in d.run_log["run_error"]


def test_trickling_download_stopped(monkeypatch):
    class Trickle(_Resp):
        def read(self, n=-1):
            return b"x"  # never EOF
    monkeypatch.setattr(fetch, "TOTAL_TIMEOUT_S", 0.2)
    monkeypatch.setattr(fetch.urllib.request, "urlopen", lambda req, timeout: Trickle(b"", "text/html"))
    assert "exceeded" in fetch._get("https://x.gov/a").error
