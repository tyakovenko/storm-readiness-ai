"""Live-storms Ask AI agent: questions about the storms NHC is tracking right now.

The county agents answer about one county's replayed past storm. This agent answers about the
current ones, from the same live data the Live Operations page shows:
  - NOAA NHC CurrentStorms.json + the official ATCF forecast (hurricane/live_feed.py),
  - at-risk counties, their resources and history, and each storm's staging site (hurricane/live_risk.py),
  - NWS active tropical alerts.
Same ADK + trust runner as every other agent (adk_runner.run_with_trust): every number and place in
an answer must come from these tools' outputs.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import AsyncGenerator

from google.adk.agents.llm_agent import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from . import trust
from .adk_runner import TRUST_PREFIX, model_from_name, run_with_trust

log = logging.getLogger(__name__)

AGENT_ID = "live-storms"
META = {"id": AGENT_ID, "name": "Live storms", "hazard": "live", "status": "live"}

INSTRUCTION = """You are the StormReady live-storms assistant. You answer questions about the tropical \
cyclones NOAA's National Hurricane Center is tracking right now: where they are, where the official forecast \
takes them, which US counties are at risk, what resources (shelters, hospitals, fire departments) those counties \
have, how past storms hit them, and where each storm's staging site is.

Rules:
- Answer first: your first sentence directly answers the question - the storm, the counties, the yes/no, or \
the estimate with its range. Details, the live-data note and context come after it, never before.
- In every turn, call get_live_storms first. It is live NHC data: say, right after your first sentence, that it \
is the current advisory, not a replay.
- Never calculate, estimate or invent numbers: no sums, differences, counts, conversions or rounding. Every \
number, place, facility and storm you mention must come from a tool result in this conversation, written exactly \
as given (e.g. "75,953", not "about 76,000").
- For where a storm is headed or how strong it will get, call get_forecast_track.
- For which counties are at risk, power outages, staging or trucks, call get_counties_at_risk. Quote every outage or \
truck estimate as "<low> to <high> (median <median>)" filled in with the tool's numbers and unit - never a median alone. The outage figures come from a trained model run on \
the NHC forecast; never present a median as certain and never use certainty words (will, definitely) about impacts. \
If the tool returns caveats (e.g. a Pacific storm), say them plainly. Truck counts rest on a stated planning \
assumption: mention it.
- For a county's shelters, hospitals, fire departments or past storms, call get_county_resources.
- For hurricane or tropical-storm watches and warnings, call get_nws_alerts.
- If a storm has no US counties at risk, say so; don't stretch the data.
- Questions naming a past-storm replay scenario (e.g. Hurricane Ian in Lee County) are answered by that \
county's replay assistant. If one reaches you anyway, say you cover the storms happening now and suggest naming \
the replay scenario (Harris County / Beryl, Miami-Dade / Irma, Lee County / Ian, Dallas winter storm).
- Be brief: a few sentences or a short list. End with one line on what it means for preparedness, using only tool \
numbers."""

_CAT_LABEL = {-1: "Tropical Depression", 0: "Tropical Storm", 1: "Category 1 hurricane", 2: "Category 2 hurricane",
              3: "Category 3 hurricane", 4: "Category 4 hurricane", 5: "Category 5 hurricane"}
_CAT_MIN_KT = [(137, 5), (113, 4), (96, 3), (83, 2), (64, 1), (34, 0)]
_CLASS = {"HU": "Hurricane", "TS": "Tropical Storm", "TD": "Tropical Depression", "STS": "Subtropical Storm",
          "SS": "Subtropical Storm", "SD": "Subtropical Depression", "PTC": "Potential Tropical Cyclone",
          "PC": "Post-Tropical Cyclone"}
_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
_TIER = {"green": "Low Risk", "yellow": "Moderate Risk", "orange": "High Risk", "red": "Severe Risk"}

# Words that mean "now", for routing a question here instead of to a county's replay scenario.
# STRICT is used where a county scenario is already open ("the current shelter plan" there is about
# that scenario); BROAD on the home page, where nothing is selected yet.
LIVE_STRICT_RE = re.compile(r"\b(live|right now|happening now|active (?:storms?|hurricanes?|systems?|tropical|cyclones?))\b",
                            re.IGNORECASE)
LIVE_BROAD_RE = re.compile(r"\b(current|currently|today|tonight|this week|upcoming|ongoing|underway)\b", re.IGNORECASE)


def _category(kt) -> int:
    v = float(kt or 0)
    return next((c for m, c in _CAT_MIN_KT if v >= m), -1)


def _when(iso: str | None) -> str | None:
    """'Sat Oct 10, 06:00 UTC' -- numbers in this form survive the trust layer's number check."""
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    dt = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    return f"{dt:%a %b} {dt.day}, {dt:%H:%M} UTC"


def _mph(kt) -> int:
    return round(float(kt) * 1.15078)


class LiveToolset:
    """Tool implementations over the live feed + live risk view. No county is fixed: the model names
    the storm (and county); unknown names come back as errors listing what exists."""

    def __init__(self):
        from hurricane.live_feed import get_poller
        self.poller = get_poller()

    # ---- lookups ----

    def storms(self) -> list[dict]:
        return self.poller.get_active_storms()

    def _storm(self, storm: str | None) -> dict:
        storms = self.storms()
        q = (storm or "").strip().lower()
        for s in storms:
            if q and (q == s["storm_id"].lower() or q == s["name"].lower() or s["name"].lower() in q.split()):
                return s
        if not q and len(storms) == 1:
            return storms[0]
        raise LookupError(f"No active storm matches {storm!r}. Active storms: "
                          + (", ".join(f"{s['name']} ({s['storm_id']})" for s in storms) or "none"))

    def _risk(self, storm_id: str) -> dict:
        from hurricane.live_risk import storm_risk
        return storm_risk(storm_id)

    # ---- tools ----

    def get_live_storms(self) -> dict:
        storms = self.storms()
        horizons = []
        out = []
        for s in storms:
            try:
                horizons.append(max(p.tau_h for p in self.poller.get_forecast_points(s["storm_id"])))
            except Exception:  # a storm without an official track still gets listed
                pass
            cat = _category(s["intensity_kt"])
            speed = s.get("movement_speed_mph")
            out.append({
                "storm_id": s["storm_id"], "name": s["name"],
                "classification": _CLASS.get(s["classification"], s["classification"]),
                "intensity": _CAT_LABEL[cat], "max_wind_kt": s["intensity_kt"], "max_wind_mph": _mph(s["intensity_kt"]),
                "pressure_mb": s["pressure_mb"] or None, "lat": s["lat"], "lon": s["lon"],
                "moving": None if speed is None or s.get("movement_dir_deg") is None else
                f"{_COMPASS[round(float(s['movement_dir_deg']) / 22.5) % 16]} at {speed} mph",
                "advisory": s.get("advisory_num"), "updated": _when(s.get("last_update_utc")),
                "nhc_public_advisory": s.get("public_advisory_url"),
            })
        status = self.poller.poll()
        return {
            "headline": f"LIVE: NOAA NHC is tracking {len(out)} active tropical cyclone(s)",
            "kind": "live", "feed_version": status.get("last_polled_utc"),
            "lead_time_h": max(horizons) if horizons else 0,  # longest official forecast horizon
            "storms_active": len(out), "storms": out,
            "active_nws_tropical_alerts": status.get("active_tropical_alerts_count"),
            "source": "NOAA NHC CurrentStorms.json (live) + NWS Active Alerts API",
        }

    def get_forecast_track(self, storm: str) -> dict:
        s = self._storm(storm)
        pts = self.poller.get_forecast_points(s["storm_id"])
        cycle = pts[0].cycle_init_time_utc
        return {
            "storm_id": s["storm_id"], "storm_name": s["name"],
            "forecast_issued": _when(cycle.isoformat()),
            "points": [{"hours_after_issue": p.tau_h, "valid": _when(p.valid_time_utc.isoformat()),
                        "lat": p.lat, "lon": p.lon, "max_wind_kt": p.vmax_kt, "max_wind_mph": _mph(p.vmax_kt),
                        "intensity": _CAT_LABEL[_category(p.vmax_kt)]} for p in pts],
            "source": "NOAA NHC ATCF a-deck, official (OFCL) forecast",
        }

    def get_counties_at_risk(self, storm: str) -> dict:
        s = self._storm(storm)
        r = self._risk(s["storm_id"])
        rng = lambda d, unit: {**{k: d[k] for k in ("low", "median", "high")}, "unit": unit}
        st = r.get("staging")
        return {
            "storm_id": s["storm_id"], "storm_name": s["name"], "forecast_issued": _when(r["forecast_cycle_utc"]),
            "risk_radius_nm": r["risk_radius_nm"], "counties_evaluated": r.get("counties_evaluated", 0),
            "counties_shown": len(r["counties"]), "note": r.get("note"),
            "counties": [{
                "name": c["name"], "state": c["state"], "fips": c["fips"],
                "risk_level": _TIER.get(c["risk_tier"], c["risk_tier"]),
                "pct_customers_out": rng(c["pct_customers_out"], "%"),
                "customers_out": rng(c["customers_out"], "customers"),
                "customers_served": c["customers_served"],
                "distance_to_forecast_track_nm": c["distance_to_track_nm"],
                "closest_approach": _when(c["closest_forecast_utc"]),
                "forecast_wind_kt_at_closest_approach": c["forecast_wind_kt_at_closest"],
                "trucks_needed": rng(c["trucks_needed"], "trucks"),
                "model_inputs": c["why"],
            } for c in r["counties"]],
            "staging": None if not st else {
                "name": st["name"], "county": st["county"], "state": st["state"],
                "clearance_from_forecast_track_nm": st["clearance_from_track_nm"],
                "average_distance_to_at_risk_counties_nm": st["avg_distance_to_counties_nm"], "method": st["method"],
                # on the staging record, so the total binds to the site it is staged at
                "trucks_needed_total": rng(r["trucks_needed_total"], "trucks")},
            "assumptions": r["assumptions"], "caveats": r["caveats"],
            "skipped_counties": [x["name"] for x in r["skipped"]],
            "source": r.get("model_source", "trained outage model on the NHC forecast"),
        }

    def get_county_resources(self, storm: str, county: str) -> dict:
        from hurricane.live_risk import county_key
        s = self._storm(storm)
        r = self._risk(s["storm_id"])
        q = county_key(county.split(",")[0])
        c = next((c for c in r["counties"] if county_key(c["name"]) == q), None)
        if c is None:
            raise LookupError(f"{county!r} is not among {s['name']}'s at-risk counties: "
                              + ", ".join(f"{x['name']}, {x['state']}" for x in r["counties"]))
        return {"storm_name": s["name"], "name": c["name"], "state": c["state"], "fips": c["fips"],
                "shelters": c["shelters"], "hospitals": c["hospitals"], "fire_departments": c["fire"],
                "storm_history": c["history"]}

    def get_nws_alerts(self, state: str | None = None) -> dict:
        alerts = self.poller.get_active_alerts()
        st = (state or "").strip().upper()[:2]
        if st:
            alerts = [a for a in alerts if any(str(u).upper().startswith(st) for u in a.get("ugc_codes") or [])]
        by_event: dict[str, int] = {}
        for a in alerts:
            by_event[a["event"]] = by_event.get(a["event"], 0) + 1
        return {"state": st or None, "alerts_total": len(alerts), "alerts_by_type": by_event,
                "alerts": [{"event": a["event"], "severity": a.get("severity"), "area": (a.get("area_desc") or "")[:240],
                            "expires": _when(a.get("expires_utc"))} for a in alerts[:12]],
                "source": "NWS Active Alerts API (api.weather.gov)"}

    def run_tool(self, name: str, args: dict) -> dict:
        try:
            return getattr(self, name)(**args)
        except LookupError as e:
            return {"error": str(e)}
        except Exception as e:  # live sources can fail; report it, never substitute
            log.warning("live tool %s failed: %s", name, e)
            return {"error": f"{name} unavailable: {e}"}

    def entity_catalog(self) -> list[dict]:
        """Every storm and county a live answer may name. Computing the risk views here (cached, shared with
        the Live Operations page) means the trust layer knows each at-risk county before the model speaks."""
        cat = []
        for s in self.storms():
            cat.append({"key": s["storm_id"], "label": s["name"], "kind": "live_storm",
                        "names": [s["name"], f"Hurricane {s['name']}", f"Tropical Storm {s['name']}", s["storm_id"]]})
            try:
                r = self._risk(s["storm_id"])
            except Exception as e:
                log.warning("live catalog: no risk view for %s: %s", s["storm_id"], e)
                continue
            places = [(c["fips"], c["name"], c["state"]) for c in r["counties"]]
            if r.get("staging"):
                st = r["staging"]
                places.append((st["fips"], st["county"], st["state"]))
            for fips, name, state in places:
                if not any(e["key"] == fips for e in cat):
                    cat.append({"key": fips, "label": f"{name}, {state}", "kind": "county",
                                "names": [name, f"{name}, {state}"]})
        return cat


def _tools_for(ts: LiveToolset) -> list:
    def get_live_storms() -> dict:
        """Every tropical cyclone NOAA NHC is tracking right now: name, intensity, wind, pressure, position,
        motion, advisory and update time, plus the count of active NWS tropical alerts. Call first."""
        return ts.run_tool("get_live_storms", {})

    def get_forecast_track(storm: str) -> dict:
        """The storm's official NHC forecast track: position, wind and intensity at each forecast time.

        Args:
            storm: Storm name or id, e.g. Isaias or AL092026 (from get_live_storms).
        """
        return ts.run_tool("get_forecast_track", {"storm": storm})

    def get_counties_at_risk(storm: str) -> dict:
        """US counties near the storm's forecast track, scored by the trained outage model: risk level,
        customers out and % out (low/median/high), distance and time of closest approach, estimated utility
        trucks, plus this storm's staging site. Slow on first call.

        Args:
            storm: Storm name or id (from get_live_storms).
        """
        return ts.run_tool("get_counties_at_risk", {"storm": storm})

    def get_county_resources(storm: str, county: str) -> dict:
        """One at-risk county's resources and history: FEMA shelters (beds, generators), CMS hospitals (with
        emergency departments), USFA fire departments (stations, career and volunteer firefighters), its worst
        past storm outages and FEMA hurricane declarations.

        Args:
            storm: Storm name or id.
            county: County name, e.g. Baldwin County (from get_counties_at_risk).
        """
        return ts.run_tool("get_county_resources", {"storm": storm, "county": county})

    def get_nws_alerts(state: str = "") -> dict:
        """Active NWS hurricane / tropical-storm / storm-surge watches and warnings, optionally for one state.

        Args:
            state: Two-letter state code, e.g. FL; empty for all.
        """
        return ts.run_tool("get_nws_alerts", {"state": state} if state else {})

    return [get_live_storms, get_forecast_track, get_counties_at_risk, get_county_resources, get_nws_alerts]


LIVE = trust.Profile("get_live_storms", frozenset({"get_counties_at_risk", "get_forecast_track"}),
                     "get_counties_at_risk", "feed_version", "headline", (trust.COUNTY_MENTION_RE,),
                     uncertain_lead_h=0)  # any live forecast is uncertain: ranges always, no certainty words


# ---- scripted mock (LLM_MODEL=mock): answers only from tool outputs ----

def _n(v) -> str:
    if v is None:
        return "unknown"
    v = float(v)
    return f"{int(v):,}" if v.is_integer() else f"{v:g}"


def _rng(r: dict) -> str:
    return f"{_n(r['low'])} to {_n(r['high'])} (median {_n(r['median'])})"


def _named_storm(q: str, ts: LiveToolset) -> dict | None:
    ql = q.lower()
    storms = ts.storms()
    return next((s for s in storms if s["name"].lower() in ql or s["storm_id"].lower() in ql), None)


def _named_county(q: str, ts: LiveToolset, storm: dict | None):
    from hurricane.live_risk import _cache  # only views already computed; the mock never starts a slow run
    ql = q.lower()
    for sid, (_, view) in _cache.items():
        if storm and sid != storm["storm_id"]:
            continue
        for c in view["counties"]:
            base = c["name"].lower().replace(" county", "").replace(" parish", "")
            if re.search(rf"\b{re.escape(base)}\b", ql):
                return sid, c["name"]
    return None


def _plan_calls(q: str, ts: LiveToolset) -> list[tuple[str, dict]]:
    ql = q.lower()
    calls = [("get_live_storms", {})]
    storm = _named_storm(q, ts)
    county = _named_county(q, ts, storm)
    if county:
        sid, name = county
        return calls + [("get_county_resources", {"storm": sid, "county": name})]
    if any(w in ql for w in ("warning", "watch", "alert")):
        m = re.search(r"\b(?:in|for)\s+([A-Z]{2})\b", q)
        return calls + [("get_nws_alerts", {"state": m.group(1)} if m else {})]
    target = storm or next(iter(ts.storms()), None)
    if target is None:
        return calls
    if any(w in ql for w in ("county", "counties", "risk", "outage", "power", "staging", "stage", "truck", "resource", "impact")):
        return calls + [("get_counties_at_risk", {"storm": target["storm_id"]})]
    if any(w in ql for w in ("head", "track", "where", "landfall", "path", "going", "strength", "forecast")):
        return calls + [("get_forecast_track", {"storm": target["storm_id"]})]
    return calls


def _compose(o: dict) -> str:
    L = []
    a = o.get("get_live_storms")
    if a and len(o) > 1:  # a specific question: one line of context, then the answer
        L.append(a["headline"] + " (current advisories, not a replay).")
    elif a:
        L.append(a["headline"] + " (current advisories, not a replay):")
        for s in a["storms"]:
            L.append(f"- {s['classification']} {s['name']}: {_n(s['max_wind_kt'])} kt ({_n(s['max_wind_mph'])} mph), "
                     f"{s['moving'] or 'motion unknown'}, advisory {s['advisory']}, updated {s['updated']}.")
    t = o.get("get_forecast_track")
    if t and not t.get("error"):
        last = t["points"][-1]
        peak = max(t["points"], key=lambda p: p["max_wind_kt"])
        L.append(f"NHC forecast for {t['storm_name']} (issued {t['forecast_issued']}): strongest at {_n(peak['max_wind_kt'])} kt "
                 f"({peak['intensity']}) at {peak['valid']}; by {last['valid']} it is near {_n(last['lat'])}N, "
                 f"{_n(abs(last['lon']))}W at {_n(last['max_wind_kt'])} kt.")
    r = o.get("get_counties_at_risk")
    if r and not r.get("error"):
        if not r["counties"]:
            L.append(f"{r['storm_name']}: {r['note']}")
        else:
            L.append(f"Counties at risk from {r['storm_name']} (trained outage model on the NHC forecast; ranges, not certainties):")
            for c in r["counties"][:5]:
                L.append(f"- {c['name']}, {c['state']} ({c['risk_level']}): {_rng(c['customers_out'])} customers out.")
            if r["staging"]:
                L.append(f"Staging site: {r['staging']['name']}, {_n(r['staging']['clearance_from_forecast_track_nm'])} nm "
                         f"clear of the track; {_rng(r['staging']['trucks_needed_total'])} trucks. {' '.join(r['assumptions'])}")
            L += r["caveats"]
    c = o.get("get_county_resources")
    if c and not c.get("error"):
        sh, ho, fi, hi = c["shelters"], c["hospitals"], c["fire_departments"], c["storm_history"]
        L.append(f"{c['name']}, {c['state']}: {_n(sh['count'])} FEMA shelters with {_n(sh['evacuation_capacity'])} beds; "
                 f"{_n(ho['count'])} hospitals ({_n(ho.get('with_emergency_dept'))} with an emergency department); "
                 f"{_n(fi['departments'])} fire departments with {_n(fi['stations'])} stations, "
                 f"{_n(fi['career_firefighters'])} career and {_n(fi['volunteer_firefighters'])} volunteer firefighters.")
        if hi["worst"]:
            w = hi["worst"][0]
            L.append(f"Worst past outage on record: {w['storm']} {w['year']}, {_n(w['peak_customers_out'])} customers out "
                     f"({_n(w['pct_customers_out'])}%).")
    al = o.get("get_nws_alerts")
    if al and not al.get("error"):
        kinds = "; ".join(f"{k}: {_n(v)}" for k, v in al["alerts_by_type"].items()) or "none"
        L.append(f"Active NWS tropical alerts{' in ' + al['state'] if al['state'] else ''}: {_n(al['alerts_total'])} ({kinds}).")
    for k, v in o.items():
        if isinstance(v, dict) and v.get("error"):
            L.append(v["error"])
    return "\n".join(L) or "I couldn't get live storm data right now."


class MockLiveLlm(BaseLlm):
    model: str = "mock"
    toolset: object = None

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        contents = llm_request.contents or []
        user_idx = [i for i, c in enumerate(contents) if c.role == "user" and any(p.text for p in c.parts or [])]
        last_user = user_idx[-1] if user_idx else -1
        question = next((p.text for c in (contents[i] for i in reversed(user_idx))
                         for p in c.parts if p.text and not p.text.startswith(TRUST_PREFIX)), "")
        feedback = bool(user_idx) and any((p.text or "").startswith(TRUST_PREFIX) for p in contents[last_user].parts)
        outputs = {p.function_response.name: p.function_response.response
                   for c in contents for p in c.parts or [] if p.function_response}
        since = any(p.function_response for c in contents[last_user + 1:] for p in c.parts or [])
        if not since and not feedback:
            parts = [types.Part(function_call=types.FunctionCall(name=n, args=a)) for n, a in _plan_calls(question, self.toolset)]
        else:
            parts = [types.Part(text=_compose(outputs))]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


# ---- routing, build, run ----

def is_live_question(question: str, strict: bool = False) -> bool:
    """Names a storm NHC is tracking now, or asks about live/active storms (or, unless strict,
    "current"/"upcoming" ones)."""
    if LIVE_STRICT_RE.search(question) or (not strict and LIVE_BROAD_RE.search(question)):
        return True
    return names_active_storm(question)


def names_active_storm(question: str) -> bool:
    try:
        from hurricane.live_feed import get_poller
        storms = get_poller().get_active_storms()  # cached by the poller
    except Exception:
        return False
    ql = question.lower()
    return any(re.search(rf"\b{re.escape(s['name'].lower())}\b", ql) or s["storm_id"].lower() in ql
               for s in storms if s.get("name"))


def build_live_agent(model_name: str | None = None):
    ts = LiveToolset()
    model = model_from_name(model_name, lambda: MockLiveLlm(toolset=ts))
    agent = Agent(model=model, name="live_storms", instruction=INSTRUCTION, tools=_tools_for(ts),
                  description="Active NHC storms: forecast tracks, at-risk counties, their resources, staging.")
    return agent, ts


def run_live_agent(question: str, history: list[dict], agent, toolset: LiveToolset, judge=None) -> dict:
    return run_with_trust(question, history, agent, judge, LIVE, toolset.entity_catalog())
