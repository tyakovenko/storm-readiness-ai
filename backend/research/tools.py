"""Researcher tools, as closures over one ResearchSession (one county, one run).

Numbers by reference: read_source returns the page with usable numbers tagged ⟦N17⟧; submit_fact takes the
tag, never a value. submit_fact also runs the judge's fixed checks on the researcher's copy of the page and
returns the failures, so the model can correct itself. That doesn't replace the judge, which refetches.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from collections import Counter

from research import numbers, policy, verify
from research.fetch import USER_AGENT, Fetcher
from research.schema import Fact, FactDraft, Gap, Page, Target

log = logging.getLogger(__name__)
PAGE_CHUNK_CHARS = 30_000   # per read_source call; long pages are read in chunks via `start`
MAX_FIND_LINES = 30


def http_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class ResearchSession:
    def __init__(self, target: Target, portals: dict | None = None, fetcher: Fetcher | None = None,
                 get_json=http_json):
        self.target = target
        self.portals = portals or {}
        self.fetch = fetcher or Fetcher()
        self.get_json = get_json
        self.pages: dict[str, tuple[Page, list[numbers.NumberSpan]]] = {}
        self.facts: list[Fact] = []
        self.gaps: list[Gap] = []
        self.rejected: list[dict] = []   # every refused submit_fact, with the reason: in the run log
        self.calls: Counter = Counter()

    # ---- helpers -------------------------------------------------------------------------------
    def _page(self, url: str) -> tuple[Page, list[numbers.NumberSpan]] | None:
        return self.pages.get(url)

    def _reject(self, args: dict, reason: str) -> dict:
        self.rejected.append({**args, "reason": reason})
        return {"accepted": False, "reason": reason}

    # ---- tools ---------------------------------------------------------------------------------
    def read_source(self, url: str, start: int = 0) -> dict:
        """Read a web page or data endpoint. Usable numbers are tagged like ⟦N17⟧1,314 - cite a number by
        its tag (N17) in submit_fact. Long pages come in chunks: call again with start=next_start.

        Args:
            url: page URL (search result links are fine; redirects are followed).
            start: character offset for the next chunk.
        """
        self.calls["read_source"] += 1
        page = self.fetch(url)
        if page.error:
            return {"url": url, "error": page.error}
        if url not in self.pages:
            spans = numbers.extract(page.text)
            for u in {url, page.final_url or url}:
                self.pages[u] = (page, spans)
        page, spans = self.pages[url]
        tagged = numbers.tag(page.text, spans)
        chunk = tagged[start:start + PAGE_CHUNK_CHARS]
        nxt = start + PAGE_CHUNK_CHARS
        return {"url": page.final_url or url, "text": chunk, "total_chars": len(tagged),
                "next_start": nxt if nxt < len(tagged) else None}

    def find_in_source(self, url: str, keywords: list[str]) -> dict:
        """Lines of an already-read source that contain any keyword (case-insensitive), with number tags.

        Args:
            url: a URL already passed to read_source.
            keywords: words to look for, e.g. ["shelter", "capacity"].
        """
        self.calls["find_in_source"] += 1
        got = self._page(url)
        if got is None:
            return {"error": "call read_source on this url first"}
        page, spans = got
        rx = re.compile("|".join(re.escape(k) for k in keywords if k), re.IGNORECASE)
        lines = [ln for ln in numbers.tag(page.text, spans).split("\n") if rx.search(ln)]
        return {"url": url, "lines": lines[:MAX_FIND_LINES], "more": max(0, len(lines) - MAX_FIND_LINES)}

    def submit_fact(self, metric: str, unit: str, source_url: str, source_title: str, subject: str, value_ref: str = "",
                    quote: str = "", storm_id: str = "", place: str = "", as_of: str = "",
                    publisher: str = "", published: str = "") -> dict:
        """Record one fact from a source you have read. For a number, give its tag as value_ref (e.g. "N17");
        never type the number. For a fact without a number, leave value_ref empty and give the exact quote.

        Args:
            metric: one of the metric names in your instructions.
            unit: the metric's unit from your instructions.
            source_url: the url you passed to read_source.
            source_title: the document's title.
            subject: whose figure it is, as the source names it (e.g. "Harris County Office of Homeland
                Security", "City of Houston", "CenterPoint Energy", "American Red Cross").
            value_ref: the number's tag on that page, e.g. "N17".
            quote: only for facts without a number: exact text from the page.
            storm_id: the storm id from your instructions if the fact is about one storm, else empty.
            place: a city name from your instructions if the figure is that city's, not the county's; else empty.
            as_of: date the figure refers to, YYYY, YYYY-MM or YYYY-MM-DD, if the source says.
            publisher: organization that published the source.
            published: publication date, YYYY, YYYY-MM or YYYY-MM-DD, if shown.
        """
        self.calls["submit_fact"] += 1
        args = {"metric": metric, "unit": unit, "source_url": source_url, "value_ref": value_ref, "subject": subject}
        got = self._page(source_url)
        if got is None:
            return self._reject(args, "call read_source on this url first, then cite its number tags")
        page, spans = got
        # Typed contract (schema): metric in the vocabulary, its unit, dates as YYYY[-MM[-DD]], http(s) URL.
        # A bad field is refused with the validation message, so the model can resubmit it correctly.
        try:
            draft = FactDraft(id=f"f{len(self.facts) + 1}", metric=metric, unit=unit, value_ref=value_ref or None,
                              quote=quote or None, storm_id=storm_id or None, place=place or None,
                              subject=subject, as_of=as_of or None, source=source_title,
                              source_url=page.final_url or source_url, publisher=publisher or None,
                              published=published or None, retrieved=page.retrieved or "")
            fact = numbers.fact_from_ref(draft, spans, page.text)
        except (numbers.BadReference, ValueError) as e:
            return self._reject(args, str(e))
        if any(f.metric == fact.metric and f.value == fact.value and f.source_url == fact.source_url
               and f.storm_id == fact.storm_id for f in self.facts):
            return self._reject(args, "duplicate of a fact already submitted")
        checks = verify.check_fact(fact, page, self.target)
        failed = [f"{c.name}: {c.detail}" for c in checks if c.severity == "block" and c.ok is False]
        if failed:
            return self._reject(args, "; ".join(failed))
        self.facts.append(fact)
        return {"accepted": True, "id": fact.id, "value": fact.value, "qualifier": fact.qualifier, "quote": fact.quote}

    def report_gap(self, metric: str, reason: str) -> dict:
        """Record a metric you looked for and could not source. Say where you looked.

        Args:
            metric: metric name from your instructions.
            reason: what you searched and why it isn't sourced (e.g. "county plan lists sites without capacity").
        """
        self.calls["report_gap"] += 1
        self.gaps.append(Gap(metric=metric, reason=reason))
        return {"recorded": True}

    def arcgis_search(self, query: str) -> dict:
        """Search ArcGIS Online / Hub items (county GIS layers: shelters, evacuation zones, facilities).
        Feature layers come with a query_url you can pass to read_source to get their records.

        Args:
            query: e.g. "Miami-Dade hurricane shelters".
        """
        self.calls["arcgis_search"] += 1
        url = "https://www.arcgis.com/sharing/rest/search?" + urllib.parse.urlencode({"q": query, "num": 10, "f": "json"})
        try:
            d = self.get_json(url)
        except Exception as e:
            return {"error": f"ArcGIS search failed: {e}"}
        items = []
        for r in d.get("results", []):
            item = {"title": r.get("title"), "type": r.get("type"), "owner": r.get("owner"),
                    "snippet": r.get("snippet"), "url": r.get("url"), "modified_ms": r.get("modified")}
            if r.get("type") in ("Feature Service", "Map Service") and r.get("url"):
                item["query_url"] = (f"{r['url'].rstrip('/')}/0/query?" +
                                     urllib.parse.urlencode({"where": "1=1", "outFields": "*", "f": "json",
                                                             "resultRecordCount": 200}))
            items.append(item)
        return {"results": items}

    def legistar_search(self, client: str, query: str) -> dict:
        """Search a Legistar legislative system (council/commission items: after-action reports, briefings).

        Args:
            client: one of the Legistar clients in your instructions.
            query: a word or short phrase in the item title, e.g. "hurricane".
        """
        self.calls["legistar_search"] += 1
        if client not in self.portals.get("legistar", []):
            return {"error": f"unknown Legistar client {client!r}; use one of {self.portals.get('legistar', [])}"}
        q = query.replace("'", "''")
        url = (f"https://webapi.legistar.com/v1/{client}/matters?" +
               urllib.parse.urlencode({"$filter": f"substringof('{q}',MatterTitle)", "$top": 20,
                                       "$orderby": "MatterIntroDate desc"}))
        try:
            rows = self.get_json(url)
        except Exception as e:
            return {"error": f"Legistar search failed: {e}"}
        return {"results": [{"title": r.get("MatterTitle"), "file": r.get("MatterFile"),
                             "date": r.get("MatterIntroDate"), "status": r.get("MatterStatusName"),
                             "url": f"https://{client}.legistar.com/LegislationDetail.aspx?ID={r.get('MatterId')}"
                                    f"&GUID={r.get('MatterGuid')}"} for r in rows]}

    def tools(self) -> list:
        """Bound methods for the ADK agent; portal tools only where the county has that portal."""
        out = [self.read_source, self.find_in_source, self.submit_fact, self.report_gap, self.arcgis_search]
        if self.portals.get("legistar"):
            out.append(self.legistar_search)
        return out
