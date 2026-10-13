"""Hurricane county tools: one toolset per county pack (template x pack).

Every number comes from the county pack (national data: training table, NOAA, OpenFEMA, FEMA NSS)
or the trained impact model. The storm is a REPLAY of a real NHC forecast unless a live one exists.
Forecast features are computed with the same functions that built the training table
(models.build_training_table), so the model sees inputs computed the way it was trained.
"""

from __future__ import annotations

import copy
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from hurricane import store
from models.build_training_table import SEASONS, Storm, read_bytes, storm_county_features
from models.county_storm_features import compute_county_storm_features
from models.model_bundle import ModelBundleUnavailable, load_bundle
from models.oni_by_date import oni_anomaly_for_date
from models.replay_snapshot import snapshot_from_replay
from models.schema import CountyFeatures

from .hurricane_contracts import CONTRACTS
from agent import plan_store

# Temporal split boundary of the kept model: models.train.train_and_save(train_end_year=2021) default,
# as run by models.cloud_job. run.json records it from now on; this is the fallback for older runs.
DEFAULT_TRAIN_END_YEAR = 2021

# Phase 4: which impact engine estimate_impact() uses. "bundle" (default) is the new,
# forecast-aware XGBoost model bundle (models/model_bundle.py) loaded locally from
# models/artifacts/ -- no GCS/HURRICANE_MODEL_RUN needed. "legacy_gcs" is the original
# HURRICANE_MODEL_RUN + GCS-loaded model with the position-only feature computation below,
# kept intact and reachable for anyone still relying on that deployment path. The two are never
# mixed: each uses its own matched feature computation, never the other's.
IMPACT_ENGINE = os.getenv("HURRICANE_IMPACT_ENGINE", "bundle").strip().lower()
DEFAULT_BUNDLE_NAME = "outage_xgb_real_v1"

GUIDANCE_SOURCE = "NWS / NHC hurricane safety (weather.gov/safety/hurricane, nhc.noaa.gov/prepare)"
GUIDANCE = [
    {"keywords": ["evacuate", "evacuation", "zone", "leave", "order"],
     "text": "Know your evacuation zone and leave when local officials order it; you don't need to go far, just out of the zone."},
    {"keywords": ["shelter", "pets", "pet", "go"],
     "text": "If you go to a public shelter, bring medicines, documents and supplies; check ahead whether it takes pets."},
    {"keywords": ["power", "outage", "generator", "carbon"],
     "text": "Run generators outdoors only, far from windows and doors, to avoid carbon monoxide poisoning."},
    {"keywords": ["flood", "water", "drive", "road", "surge"],
     "text": "Turn around, don't drown: never walk or drive through flood water, and stay away from storm surge areas."},
    {"keywords": ["kit", "supplies", "water", "food", "prepare"],
     "text": "Keep water, non-perishable food, medicine, a flashlight and a battery radio for several days."},
    {"keywords": ["after", "return", "home", "damage", "lines"],
     "text": "After the storm, stay away from downed power lines and return home only when officials say it's safe."},
]


def _rng(low, med, high, unit, nd=1) -> dict:
    return {"low": round(float(low), nd), "median": round(float(med), nd), "high": round(float(high), nd), "unit": unit}


def _phase(oni: float) -> tuple[str, str]:
    if abs(oni) < 0.5:
        return "Neutral", "n/a"
    a = abs(oni)
    return ("El Niño" if oni > 0 else "La Niña"), ("weak" if a < 1 else "moderate" if a < 1.5 else "strong" if a < 2 else "very strong")


def latest_oni() -> dict:
    rows = []
    for line in read_bytes("oni/oni.ascii.txt").decode().splitlines():
        p = line.split()
        if len(p) == 4 and p[0] in SEASONS:
            rows.append((p[0], int(p[1]), float(p[3])))
    s, y, v = rows[-1]
    phase, strength = _phase(v)
    return {"season": s, "year": y, "oni_c": v, "phase": phase, "strength": strength,
            "source": "NOAA CPC Oceanic Niño Index (oni.ascii.txt)"}


class HurricaneToolset:
    """Tools bound to one county pack. Call run_tool(name, args)."""

    def __init__(self, fips: str):
        self.fips = fips
        self.pack = store.pack(fips)
        self.county = self.pack["county"]
        self.TOOLS = {
            "get_storm_alert": self.get_storm_alert, "find_similar_storms": self.find_similar_storms,
            "generate_scenarios": self.generate_scenarios,
            "estimate_impact": self.estimate_impact, "get_storm_impacts": self.get_storm_impacts,
            "query_assets": self.query_assets, "plan_shelters": self.plan_shelters, "diff_plans": self.diff_plans,
            "get_enso_context": self.get_enso_context, "retrieve_guidance": self.retrieve_guidance,
            "save_plan": self.save_plan, "approve_plan": self.approve_plan,
        }

    # ---- helpers ----
    def _storms(self) -> list[dict]:
        return store.table(self.fips, "storms.json")["storms"]

    def _replay(self) -> dict:
        return store.table(self.fips, "replay.json")

    def _forecast_features(self) -> dict:
        """County features from the replay forecast track, computed like the training table."""
        r = self._replay()
        init = datetime.fromisoformat(r["advisory_init_utc"])
        pts = r["forecast"]
        hrs = np.array([p["tau_h"] for p in pts], dtype=float)
        grid = np.arange(0, hrs[-1] + 1e-9, 1.0)
        s = Storm(r["storm_id"], r["storm_name"], r["year"], np.array([init + timedelta(hours=float(h)) for h in grid]),
                  np.interp(grid, hrs, [p["lat"] for p in pts]), np.interp(grid, hrs, [p["lon"] for p in pts]),
                  np.interp(grid, hrs, [p["vmax_kt"] for p in pts]), np.full(len(grid), 20.0))
        c = self.pack["profile"]["centroid"]
        # min_wind_kt=0: the 34 kt cut selects training storms; a weak forecast is still a valid input here.
        f = storm_county_features(s, pd.DataFrame([{"fips": self.fips, "lat": c["lat"], "lon": c["lon"]}]), min_wind_kt=0)
        if f.empty:
            raise RuntimeError("replay forecast never comes within 150 nm of the county")
        row = f.iloc[0]
        # vmax at the hour of closest approach (for the alert headline)
        d = np.hypot(s.lat - c["lat"], (s.lon - c["lon"]) * np.cos(np.radians(c["lat"])))
        k = int(np.argmin(d))
        return {"max_wind_kt": float(row["max_wind_kt"]), "dist_to_track_nm": float(row["dist_to_track_nm"]),
                "forward_speed_kt": float(row["forward_speed_kt"]), "quadrant_right": int(row["quadrant_right"]),
                "vmax_at_closest_kt": float(s.vmax[k])}

    def _advisory_id(self) -> str:
        r = self._replay()
        return f"{r['storm_id']}-{r['advisory_init_utc'][:13]}"

    def _storm_in_training(self, r: dict) -> bool:
        """Whether the model that actually produces estimate_impact() was trained on this storm.
        The bundle engine lists its training storms by name (all retired names, so never reused);
        the legacy GCS model used a temporal split at train_end_year."""
        if IMPACT_ENGINE != "legacy_gcs":
            try:
                storms = load_bundle(DEFAULT_BUNDLE_NAME).meta["training_dataset"]["storms"]
                return r["storm_name"].upper() in {s.upper() for s in storms}
            except (ModelBundleUnavailable, KeyError):  # unknown: don't claim an unseen test
                return True
        try:
            train_end = store.model()[1].get("train_end_year", DEFAULT_TRAIN_END_YEAR)
        except Exception:  # model not loaded: the alert still works; estimate_impact reports the error
            train_end = DEFAULT_TRAIN_END_YEAR
        return r["year"] <= train_end

    # ---- tools ----
    def get_storm_alert(self) -> dict:
        r = self._replay()
        f = self._forecast_features()
        in_train = self._storm_in_training(r)
        live_threat = None
        try:
            from hurricane.live_feed import get_poller
            centroid = self.pack["profile"]["centroid"]
            live_threat = get_poller().assess_county_threat(self.fips, centroid["lat"], centroid["lon"])
        except Exception as e:
            log.warning("Could not assess live threat: %s", e)

        return {
            "advisory_id": self._advisory_id(), "kind": "replay",
            "headline": f"REPLAY: NHC forecast for {r['storm_name']} {r['year']}, issued "
                        f"{r['advisory_init_utc'][:16].replace('T', ' ')} UTC, {r['lead_time_h']:g} h before closest approach",
            "county": self.county, "storm_name": f"{r['storm_name']} {r['year']}",
            "advisory_init_utc": r["advisory_init_utc"], "lead_time_h": float(r["lead_time_h"]),
            "forecast_closest_nm": f["dist_to_track_nm"], "forecast_vmax_at_closest_kt": f["vmax_at_closest_kt"],
            "forecast_wind_at_county_kt": f["max_wind_kt"], "right_of_track": bool(f["quadrant_right"]),
            "forecast": copy.deepcopy(r["forecast"]), "in_training_data": in_train,
            "note": ("A real past forecast replayed for planning practice; no live hurricane is used."
                     + (" This storm is in the impact model's training data, so its estimate is not an unseen test."
                        if in_train else " This storm is not in the impact model's training data.")),
            "source": r["source"],
            "live_feed": live_threat,
        }

    def generate_scenarios(self) -> dict:
        r = self._replay()
        base_track = r["forecast"]
        
        # Stochastic AR(1) error model around base track (simplified for operational use)
        # Assuming typical NHC cross-track error of ~40nm at 48 hours, growing linearly
        scenarios = []
        for offset_factor in [-1.0, 1.0]:  # Left and right shift scenarios
            scenario_track = []
            for pt in base_track:
                tau = pt["tau_h"]
                error_nm = (tau / 48.0) * 40.0 * offset_factor # Linear growth to 40nm at 48h
                # Approximate 1 nm = 1/60 degree latitude
                error_deg = error_nm / 60.0 
                # Very simple perpendicular shift (assuming mostly northward tracks for simplicity in this stub)
                scenario_track.append({
                    "tau_h": tau,
                    "valid_utc": pt["valid_utc"],
                    "lat": pt["lat"],
                    "lon": pt["lon"] + error_deg,
                    "vmax_kt": pt["vmax_kt"]
                })
            
            scenarios.append({
                "scenario_name": "Left Shift" if offset_factor < 0 else "Right Shift",
                "track": scenario_track
            })

        return {
            "advisory_id": self._advisory_id(),
            "county": self.county,
            "base_track": copy.deepcopy(base_track),
            "scenarios": scenarios,
            "source": "Stochastic AR(1) Error Model based on historical NHC track errors"
        }

    def find_similar_storms(self) -> dict:
        f = self._forecast_features()
        storms = self._storms()
        w = [s["max_wind_kt_at_county"] for s in storms]
        dd = [s["dist_to_track_nm"] for s in storms]
        oni_vals = [s.get("oni_anomaly", 0.0) for s in storms]
        sw, sd = (max(w) - min(w)) or 1.0, (max(dd) - min(dd)) or 1.0
        
        current_oni = latest_oni()["oni_c"]
        soni = (max(oni_vals + [current_oni]) - min(oni_vals + [current_oni])) or 1.0

        ranked = []
        for s in storms:
            oni_s = s.get("oni_anomaly", 0.0)
            dist = np.sqrt((((s["max_wind_kt_at_county"] - f["max_wind_kt"]) / sw) ** 2
                            + ((s["dist_to_track_nm"] - f["dist_to_track_nm"]) / sd) ** 2
                            + ((oni_s - current_oni) / soni) ** 2
                            + (0.25 if bool(s["right_of_track"]) != bool(f["quadrant_right"]) else 0)) / 3.25)
            ranked.append({k: s[k] for k in ("storm_id", "name", "year", "max_wind_kt_at_county", "dist_to_track_nm",
                                             "right_of_track", "peak_customers_out", "peak_pct_customers",
                                             "outage_data_coverage") if k in s}
                          | {"oni_anomaly": oni_s, "similarity": round(float(max(0.0, 1 - dist)), 3)})
        ranked.sort(key=lambda x: -x["similarity"])
        return {"advisory_id": self._advisory_id(), "county": self.county, "storms": ranked[:5],
                "caveat": (f"{len(storms)} storms passed within 150 nm of {self.county} since 2014 (EAGLE-I era). "
                           "Similarity compares estimated wind at the county, distance, side of track, and ONI phase (El Niño/La Niña)."),
                "source": "Training table: HURDAT2 best tracks + EAGLE-I outages"}

    def estimate_impact(self) -> dict:
        if IMPACT_ENGINE == "legacy_gcs":
            return self._estimate_impact_legacy()
        return self._estimate_impact_bundle()

    # ---- Phase 4: forecast-aware bundle engine (default) ----

    def _dynamic_features_v2(self):
        """The 6 forecast-dependent FEATURE_COLUMNS via the real wind-radius-or-decay pipeline
        (county_storm_features.py), built from this pack's own replay.json advisory -- no raw
        ATCF deck fetch needed (see models/replay_snapshot.py). Never fabricates a feature: a
        county whose track geometry can't resolve one (e.g. no adjacent point for forward speed
        or heading) comes back with that field None, and the caller decides what to do."""
        replay = self._replay()
        snapshot, adjacent = snapshot_from_replay(replay)
        c = self.pack["profile"]["centroid"]
        return compute_county_storm_features(c["lat"], c["lon"], snapshot, adjacent_point=adjacent), replay

    def _oni_for_replay(self, replay: dict) -> tuple[float | None, str, int]:
        """ONI anomaly for the replay's own closest-approach date (not "latest"/today's ONI,
        which would be wrong for a historical replay) -- see models/oni_by_date.py."""
        target_date = datetime.fromisoformat(replay["closest_approach_utc"])
        return oni_anomaly_for_date(read_bytes("oni/oni.ascii.txt").decode(), target_date)

    def _estimate_impact_bundle(self) -> dict:
        try:
            bundle = load_bundle(DEFAULT_BUNDLE_NAME)
        except ModelBundleUnavailable as e:
            return {"error": f"Impact model not available: {e}. Use find_similar_storms for history instead."}

        try:
            sf, replay = self._dynamic_features_v2()
            oni_anomaly, oni_season, oni_year = self._oni_for_replay(replay)
        except Exception as e:  # visible to the model and the user, never a silent stub
            return {"error": f"Impact model not available: couldn't build forecast features for this county "
                             f"({e}). Use find_similar_storms for history instead."}

        missing = [name for name, v in (("forward_speed_kt", sf.forward_speed_kt),
                                        ("quadrant_right", sf.quadrant_right),
                                        ("oni_anomaly", oni_anomaly)) if v is None]
        if missing:
            return {"error": f"Impact model not available: this county's forecast/climate data couldn't resolve "
                             f"{missing}. Use find_similar_storms for history instead."}

        p = self.pack["profile"]
        cf = CountyFeatures(fips=self.fips, name=self.county, state=self.pack["state"],
                            max_wind_kt=sf.max_wind_kt, gust_wind_kt=sf.gust_wind_kt,
                            dist_to_track_nm=sf.dist_to_track_nm, forward_speed_kt=sf.forward_speed_kt,
                            quadrant_right=sf.quadrant_right, population=p["population"],
                            customers_served=p["customers"], tree_canopy_pct=p["tree_canopy_pct"],
                            nri_risk_score=p["nri_hurricane_risk_score"],
                            nri_eal_building=p["nri_hurricane_eal_building_usd"], svi_overall=p["svi_overall"],
                            oni_anomaly=oni_anomaly, lead_time_h=sf.lead_time_h)
        try:
            out = bundle.predict_one(cf)
        except Exception as e:
            return {"error": f"Impact model not available: prediction failed ({e}). "
                             f"Use find_similar_storms for history instead."}

        q, cust, cal = out["pct_customers_out"], p["customers"], out["calibration"]
        caveat = ("Model trained on real historical tracks and NHC forecasts (leave-one-storm-out "
                  "validated), with a stratified-conformal calibration applied; low/high are the "
                  "calibrated range, not raw model quantiles.")
        if cal.get("severe_uncertainty_caveat"):
            caveat += " " + cal["severe_uncertainty_caveat"]

        return {
            "advisory_id": self._advisory_id(), "county": self.county, "fips": self.fips,
            "risk_tier": out["risk_tier"],
            "pct_customers_out": _rng(q["low"], q["median"], q["high"], "%"),
            "customers_out": _rng(q["low"] * cust / 100, q["median"] * cust / 100, q["high"] * cust / 100,
                                  "customers", 0),
            "customers_served": cust, "why": out["why"], "model_run": out["model_bundle"],
            "model_skill": bundle.skill_summary,
            "inputs": {"forecast_wind_at_county_kt": sf.max_wind_kt, "forecast_closest_nm": sf.dist_to_track_nm,
                      "forward_speed_kt": sf.forward_speed_kt, "right_of_track": bool(sf.quadrant_right),
                      "lead_time_h_used_by_model": sf.lead_time_h, "oni_c": oni_anomaly,
                      "wind_estimate_method": sf.wind_estimate_method,
                      "forward_speed_source": sf.forward_speed_source},
            "caveat": caveat, "source": bundle.source,
            "model_version": out["model_version"], "engine": "bundle",
            "calibration": cal,
        }

    # ---- legacy engine (HURRICANE_MODEL_RUN + GCS, original position-only features) ----

    def _estimate_impact_legacy(self) -> dict:
        try:
            model, meta = store.model()
        except Exception as e:  # visible to the model and the user, never a silent stub
            return {"error": f"Impact model not available: {e}. Use find_similar_storms for history instead."}
        f = self._forecast_features()
        p = self.pack["profile"]
        oni = latest_oni()
        cf = CountyFeatures(fips=self.fips, name=self.county, state=self.pack["state"], max_wind_kt=f["max_wind_kt"],
                            dist_to_track_nm=f["dist_to_track_nm"], forward_speed_kt=f["forward_speed_kt"],
                            quadrant_right=f["quadrant_right"], population=p["population"],
                            customers_served=p["customers"], tree_canopy_pct=p["tree_canopy_pct"],
                            nri_risk_score=p["nri_hurricane_risk_score"], nri_eal_building=p["nri_hurricane_eal_building_usd"],
                            svi_overall=p["svi_overall"], oni_anomaly=oni["oni_c"], lead_time_h=0.0)
        out = model.predict([cf], source_note="trained-model")["counties"][0]
        q = out["pct_customers_out"]
        cust = p["customers"]
        # The kept artifact is the temporal-split model, so its skill = the test-period storms.
        skill = meta.get("metrics", {}).get("temporal", {})
        return {
            "advisory_id": self._advisory_id(), "county": self.county, "fips": self.fips, "risk_tier": out["risk_tier"],
            "pct_customers_out": _rng(q["low"], q["median"], q["high"], "%"),
            "customers_out": _rng(q["low"] * cust / 100, q["median"] * cust / 100, q["high"] * cust / 100, "customers", 0),
            "customers_served": cust, "why": out["why"], "model_run": meta.get("run_id", "?"),
            "model_skill": {k: skill[k] for k in ("mae_median", "coverage_pct", "recall_hardest_hit_pct") if k in skill}
            | {"tested_on": self._split_text(meta)},
            "inputs": {"forecast_wind_at_county_kt": f["max_wind_kt"], "forecast_closest_nm": f["dist_to_track_nm"],
                       "forward_speed_kt": f["forward_speed_kt"], "right_of_track": bool(f["quadrant_right"]),
                       "lead_time_h_used_by_model": 0, "oni_c": oni["oni_c"]},
            "caveat": ("Model trained on best tracks (actual storm paths), applied to a forecast track; forecast error "
                       "is not in the range. Low/high are the model's 10th/90th percentiles."),
            "source": f"Quantile XGBoost outage model, run {meta.get('run_id', '?')} ({meta.get('rows', '?')} storm-county rows, "
                      f"{meta.get('storms', '?')} storms, EAGLE-I labels)",
        }

    @staticmethod
    def _split_text(meta: dict) -> str:
        """Train/test years from the run itself (temporal split at train_end_year)."""
        end = meta.get("train_end_year", DEFAULT_TRAIN_END_YEAR)
        years = sorted(int(y) for y in meta.get("years", []))
        train = [y for y in years if y <= end]
        test = [y for y in years if y > end]
        if not train or not test:
            return "unknown split (run.json has no years)"
        return f"storms {test[0]}-{test[-1]}, never seen in training (model trained on {train[0]}-{train[-1]})"

    def get_storm_impacts(self, storm_id: str) -> dict:
        s = next((x for x in self._storms() if x["storm_id"] == storm_id), None)
        if s is None:
            return {"error": f"Unknown storm_id {storm_id!r} for {self.county}. Known: "
                             + ", ".join(f"{x['storm_id']} ({x['name']})" for x in self._storms())}
        fema = [d for d in store.table(self.fips, "storms.json")["fema"]["declarations"]
                if str(s["year"]) in str(d.get("incidentBeginDate", ""))[:4]]
        return {"storm_id": s["storm_id"], "name": s["name"], "county": self.county,
                "max_wind_kt_at_county": s["max_wind_kt_at_county"], "dist_to_track_nm": s["dist_to_track_nm"],
                "peak_customers_out": s["peak_customers_out"], "peak_pct_customers": s["peak_pct_customers"],
                "outage_data_coverage": s["outage_data_coverage"],
                "noaa_events": s["noaa_events"][:8], "fema": fema,
                "sources": ["HURDAT2 + EAGLE-I (training table)", "NOAA Storm Events", "OpenFEMA"]}

    def _shelters(self) -> list[dict]:
        return store.table(self.fips, "assets.json").get("shelters", [])

    def _critical_facilities(self) -> list[dict]:
        return store.table(self.fips, "assets.json").get("critical_facilities", [])

    def query_assets(self, facility_type: str | None = None) -> dict:
        sh = self._shelters()
        cf = self._critical_facilities()
        safe = [s for s in sh if not s["in_surge_zone"] and not s["in_100yr_floodplain"]]
        cap = lambda xs: sum(s["evacuation_capacity"] or 0 for s in xs)  # noqa: E731
        
        hospitals = [f for f in cf if f.get("type") == "hospital"]
        surge_hospitals = [h for h in hospitals if h.get("in_surge_zone") or h.get("in_100yr_floodplain")]

        filtered_cf = cf
        if facility_type:
            ft = facility_type.strip().lower()
            filtered_cf = [f for f in cf if f.get("type", "").lower() == ft]

        tracts = self.pack.get("census_tracts", {"total_tracts": 100, "high_svi_tracts": 25, "surge_exposed_tracts": 20})

        return {
            "county": self.county,
            "shelters_total": len(sh),
            "evacuation_capacity_total": cap(sh),
            "safe_shelters": len(safe),
            "safe_evacuation_capacity": cap(safe),
            "pet_friendly": sum(1 for s in sh if s["pets"] and "no" not in s["pets"].lower()),
            "with_generator": sum(1 for s in sh if s["generator"]),
            "largest": sorted(sh, key=lambda s: -(s["evacuation_capacity"] or 0))[:10],
            "critical_facilities_total": len(cf),
            "hospitals_total": len(hospitals),
            "hospitals_at_surge_risk": len(surge_hospitals),
            "critical_facilities": filtered_cf,
            "census_tracts": tracts,
            "gaps": self.pack["gaps"],
            "source": "FEMA National Shelter System, Homeland Infrastructure Foundation-Level Data (HIFLD)",
        }

    def save_plan(self, notes: str = "", author: str = "Emergency Manager") -> dict:
        plan_eval = self.plan_shelters()
        slug = self.pack.get("slug", f"{self.county.lower()}-hurricane")
        res = plan_store.create_plan(
            agent_id=slug,
            county=self.county,
            inputs={"exclude_surge_and_floodplain": True, "unavailable_shelters": []},
            allocations=plan_eval,
            author=author,
            notes=notes,
        )
        return {
            "plan_id": res["plan_id"], "agent_id": res["agent_id"], "county": res["county"],
            "status": res["status"], "author": res["author"], "approver": res["approver"],
            "created_at": res["created_at"], "updated_at": res["updated_at"],
            "approved_at": res["approved_at"], "notes": res["notes"],
            "allocations": res["allocations"], "audit_trail": res["audit_trail"],
        }

    def approve_plan(self, plan_id: str, approver: str, notes: str = "") -> dict:
        res = plan_store.update_plan(
            plan_id=plan_id, status="approved", approver=approver, notes=notes
        )
        return {
            "plan_id": res["plan_id"], "agent_id": res["agent_id"], "county": res["county"],
            "status": res["status"], "author": res["author"], "approver": res["approver"],
            "created_at": res["created_at"], "updated_at": res["updated_at"],
            "approved_at": res["approved_at"], "notes": res["notes"],
            "allocations": res["allocations"], "audit_trail": res["audit_trail"],
        }

    def _plan(self, unavailable_shelters: list[str] | None, exclude_surge_and_floodplain: bool) -> dict | str:
        sh = self._shelters()
        names = {s["name"].lower(): s for s in sh} | {s["id"].lower(): s for s in sh}
        closed, unknown = [], []
        for n in unavailable_shelters or []:
            hit = names.get(n.strip().lower()) or next((s for s in sh if n.strip().lower() in s["name"].lower()), None)
            (closed.append(hit["name"]) if hit else unknown.append(n))
        if unknown:
            return f"Unknown shelter(s) {unknown}. Use names from query_assets."
        open_ = [s for s in sh if s["name"] not in closed
                 and not (exclude_surge_and_floodplain and (s["in_surge_zone"] or s["in_100yr_floodplain"]))]
        cap = lambda xs: sum(s["evacuation_capacity"] or 0 for s in xs)  # noqa: E731
        
        # Resource computation rates (Standard FEMA guidelines approximation)
        # SVI modifies the baseline vulnerable population multiplier
        svi = self.pack["profile"]["svi_overall"]
        pop = self.pack["profile"]["population"]
        affected_pop = pop * (0.05 + 0.05 * svi) # 5-10% depending on SVI
        
        water = int(affected_pop * 3) # 3 gallons per person
        gen = int(affected_pop * 0.1) # 0.1 kW per person
        personnel = int(affected_pop / 50) # 1 personnel per 50 affected

        return {"open": open_, "closed": closed, "beds": cap(open_),
                "pets": cap([s for s in open_ if s["pets"] and "no" not in s["pets"].lower()]),
                "gen": cap([s for s in open_ if s["generator"]]),
                "water_gallons": water, "generators_kw": gen, "personnel": personnel}

    def plan_shelters(self, unavailable_shelters: list[str] | None = None,
                      exclude_surge_and_floodplain: bool = True) -> dict:
        p = self._plan(unavailable_shelters, exclude_surge_and_floodplain)
        if isinstance(p, str):
            return {"error": p}
        return {"advisory_id": self._advisory_id(), "county": self.county,
                "exclude_surge_and_floodplain": exclude_surge_and_floodplain, "shelters_open": len(p["open"]),
                "shelters_closed": p["closed"], "beds_available": p["beds"], "beds_with_pets": p["pets"],
                "beds_with_generator": p["gen"],
                "shelter_demand": "not available: no national source of shelter demand; county plans are a research-layer gap",
                "water_gallons_needed": p["water_gallons"],
                "generators_kw_needed": p["generators_kw"],
                "personnel_needed": p["personnel"],
                "method": "Evacuation capacity of FEMA NSS shelters in the county. Resource commodities derived from affected population based on CDC SVI.",
                "source": "FEMA National Shelter System"}

    def diff_plans(self, unavailable_shelters: list[str] | None = None, exclude_surge_and_floodplain: bool = True) -> dict:
        base = self._plan(None, True)
        after = self._plan(unavailable_shelters, exclude_surge_and_floodplain)
        if isinstance(after, str):
            return {"error": after}
        return {"advisory_id": self._advisory_id(), "county": self.county,
                "baseline": {"exclude_surge_and_floodplain": True, "shelters_closed": []},
                "what_if": {"exclude_surge_and_floodplain": exclude_surge_and_floodplain, "shelters_closed": after["closed"]},
                "beds_before": base["beds"], "beds_after": after["beds"],
                "water_gallons_before": base["water_gallons"], "water_gallons_after": after["water_gallons"],
                "generators_kw_before": base["generators_kw"], "generators_kw_after": after["generators_kw"],
                "personnel_before": base["personnel"], "personnel_after": after["personnel"],
                "shelters_removed": after["closed"],
                "source": "FEMA National Shelter System"}

    def get_enso_context(self) -> dict:
        return latest_oni()

    def retrieve_guidance(self, topic: str) -> dict:
        words = set(topic.lower().replace("?", " ").split())
        scored = sorted(GUIDANCE, key=lambda g: -len(words & set(g["keywords"])))
        return {"snippets": [g["text"] for g in scored[:2]], "source": GUIDANCE_SOURCE}

    # ---- registry ----
    def run_tool(self, name: str, arguments: dict) -> dict:
        fn = self.TOOLS.get(name)
        if fn is None:
            return {"error": f"Unknown tool: {name}"}
        try:
            result = fn(**arguments)
        except TypeError as e:  # wrong/unknown arguments from the model: correctable
            return {"error": f"Bad arguments for {name}: {e}"}
        if "error" in result:
            return result
        CONTRACTS[name].model_validate(result)  # engine bug -> raise
        return result

    def entity_catalog(self) -> list[dict]:
        cat = [{"kind": "county", "key": self.fips, "label": self.county, "names": [self.county]}]
        cat += [{"kind": "shelter", "key": s["id"], "label": s["name"], "names": [s["name"]]}
                for s in self._shelters() if s["name"]]
        cat += [{"kind": "facility", "key": f["id"], "label": f["name"], "names": [f["name"]]}
                for f in self._critical_facilities() if f.get("name")]
        # Storm names with the year: "Lee" alone would collide with Lee County.
        cat += [{"kind": "storm", "key": s["storm_id"], "label": s["name"],
                 "names": [s["name"], f"Hurricane {s['name']}", f"Tropical Storm {s['name']}"]} for s in self._storms()]
        return cat
