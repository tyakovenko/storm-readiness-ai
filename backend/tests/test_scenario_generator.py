"""Tests for the deterministic synthetic hurricane scenario generator and its
wiring into the EXISTING real inference pipeline (run_impact_pipeline()).

Two test tiers:
  - Fast, isolated tests with get_model/get_static_tables/get_calibration
    monkeypatched (mirrors test_live_inference.py's patched_pipeline style).
  - A handful of real-artifact integration checks (local files, no network)
    that prove the scenario genuinely drives the real trained model.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest

from backend.agent.contracts import Impact
from backend.models import pipeline
from backend.models.atcf_forecast import ForecastPoint
from backend.models.outage_target import load_mcc_customers
from backend.models.schema import FEATURE_COLUMNS
from backend.models.scenario_generator import (
    FLORIDA_GULF_COAST_SCENARIO,
    ScenarioConfig,
    ScenarioWindRadii,
    generate_scenario_forecast_points,
)

COUNTY_FIPS = "12029"  # Dixie County, FL -- real centroid, real NRI/SVI/MCC/ONI data
NRI_DF = pd.DataFrame([{"fips": COUNTY_FIPS, "POPULATION": 16000, "HRCN_EALB": 400000.0, "HRCN_RISKS": 30.0}])
SVI_DF = pd.DataFrame([{"fips": COUNTY_FIPS, "RPL_THEMES": 0.6}])
MCC_SAMPLE = f"County_FIPS,Customers\n{COUNTY_FIPS},9000\n"
ONI_DF = pd.DataFrame([{"season": "JAS", "year": 2026, "anom": 2.16}])  # matches FLORIDA_GULF_COAST_SCENARIO's August dates


# --- 1. scenario output converts into existing ForecastPoint objects --------


def test_generate_scenario_forecast_points_returns_real_forecastpoint_objects():
    points = generate_scenario_forecast_points(FLORIDA_GULF_COAST_SCENARIO)
    assert len(points) == 3
    assert all(isinstance(p, ForecastPoint) for p in points)
    assert all(p.tech == "OFCL" for p in points)
    assert all(p.storm_name == "ORION" for p in points)
    assert all(34 in p.wind_radii and 50 in p.wind_radii and 64 in p.wind_radii for p in points)


# --- 3. 72/48/24 horizons work -----------------------------------------------


def test_scenario_has_exactly_the_three_frontend_horizons():
    points = generate_scenario_forecast_points(FLORIDA_GULF_COAST_SCENARIO)
    assert sorted(p.tau_h for p in points) == [24, 48, 72]


def test_scenario_track_moves_with_tau_deterministically():
    points = {p.tau_h: p for p in generate_scenario_forecast_points(FLORIDA_GULF_COAST_SCENARIO)}
    # constant heading/speed dead-reckoning -> strictly increasing distance from the start position
    from backend.models.county_geometry import haversine_nm
    d24 = haversine_nm(FLORIDA_GULF_COAST_SCENARIO.start_lat, FLORIDA_GULF_COAST_SCENARIO.start_lon, points[24].lat, points[24].lon)
    d48 = haversine_nm(FLORIDA_GULF_COAST_SCENARIO.start_lat, FLORIDA_GULF_COAST_SCENARIO.start_lon, points[48].lat, points[48].lon)
    d72 = haversine_nm(FLORIDA_GULF_COAST_SCENARIO.start_lat, FLORIDA_GULF_COAST_SCENARIO.start_lon, points[72].lat, points[72].lon)
    assert d24 < d48 < d72


def test_generate_scenario_forecast_points_is_deterministic():
    a = generate_scenario_forecast_points(FLORIDA_GULF_COAST_SCENARIO)
    b = generate_scenario_forecast_points(FLORIDA_GULF_COAST_SCENARIO)
    assert a == b


# --- 6. no hardcoded outage predictions exist in the scenario generator -----


def test_scenario_generator_source_has_no_outage_or_risk_vocabulary():
    import backend.models.scenario_generator as module
    source = open(module.__file__, encoding="utf-8").read()
    forbidden = [
        "pct_customers_out", "risk_tier", "assign_risk_tier", "predict_quantiles",
        "QuantileOutageModel", "calibration_status", "severe_uncertainty_caveat", "customers_served",
    ]
    present = [term for term in forbidden if term in source]
    assert present == [], f"scenario_generator.py references outage/risk vocabulary it must not: {present}"


def test_scenario_config_dataclass_has_no_outage_or_risk_fields():
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(ScenarioConfig)}
    forbidden = {"pct_customers_out", "risk_tier", "outage_pct", "uncertainty", "customers_served"}
    assert field_names & forbidden == set()


# --- 2 & 4. run_impact_pipeline() is actually called; results are genuine ---
# real-model output ----------------------------------------------------------


class _FakeModel:
    version = "xgboost-quantile-real-v1.0-test"

    def predict_quantiles(self, df: pd.DataFrame) -> np.ndarray:
        # deterministic function of a real scenario feature (max_wind_kt),
        # so a test can verify the OUTPUT actually tracks the INPUT rather
        # than being a fixed/hardcoded number.
        wind = df["max_wind_kt"].to_numpy()
        med = np.clip(wind / 2.0, 0, 100)
        return np.column_stack([np.clip(med - 5, 0, 100), med, np.clip(med + 5, 0, 100)])


def _calibration():
    return {"Q_global": 1.0, "Q_by_band": {}, "pred_bands": [
        {"label": "0-5%", "lo": 0.0, "hi": 5.0}, {"label": "5-20%", "lo": 5.0, "hi": 20.0},
        {"label": "20-40%", "lo": 20.0, "hi": 40.0}, {"label": "40-100%", "lo": 40.0, "hi": 100.000000001},
    ]}


@pytest.fixture
def patched_pipeline(monkeypatch):
    centroids = pd.DataFrame([{"county_fips": COUNTY_FIPS, "county_lat": 29.68, "county_lon": -83.15}])
    static = {
        "centroids": centroids, "nri": NRI_DF, "svi": SVI_DF, "oni": ONI_DF,
        "mcc": load_mcc_customers(io.StringIO(MCC_SAMPLE)),
    }
    monkeypatch.setattr(pipeline, "_CACHED_STATIC_TABLES", None)
    monkeypatch.setattr(pipeline, "get_static_tables", lambda: static)
    monkeypatch.setattr(pipeline, "get_name_lookup", lambda: {COUNTY_FIPS: {"name": "Dixie County", "state": "FL"}})
    monkeypatch.setattr(pipeline, "get_model", lambda: _FakeModel())
    monkeypatch.setattr(pipeline, "get_calibration", _calibration)
    return static


def test_run_scenario_impact_pipeline_calls_the_real_run_impact_pipeline(monkeypatch, patched_pipeline):
    calls = []
    original = pipeline.run_impact_pipeline

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "run_impact_pipeline", spy)

    result = pipeline.run_scenario_impact_pipeline(county_fips=[COUNTY_FIPS], lead_time_h=48)

    assert len(calls) == 1  # the scenario path never duplicates inference -- it calls the one real function
    assert len(calls[0]["forecast_points"]) == 3
    assert all(isinstance(p, ForecastPoint) for p in calls[0]["forecast_points"])
    assert result["counties"][0]["pct_customers_out"]["median"] > 0  # genuinely computed, not zero/absent


def test_scenario_result_median_tracks_scenario_wind_input_not_hardcoded(patched_pipeline):
    # Two different VMAX scenarios must produce two different model outputs --
    # proof the number comes from running the model on the scenario's own
    # feature values, not a constant baked into the generator or pipeline.
    calm_scenario = dataclasses_replace(FLORIDA_GULF_COAST_SCENARIO, max_wind_kt=40.0)
    strong_scenario = dataclasses_replace(FLORIDA_GULF_COAST_SCENARIO, max_wind_kt=130.0)

    calm_result = pipeline.run_scenario_impact_pipeline(county_fips=[COUNTY_FIPS], lead_time_h=48, scenario=calm_scenario)
    strong_result = pipeline.run_scenario_impact_pipeline(county_fips=[COUNTY_FIPS], lead_time_h=48, scenario=strong_scenario)

    calm_med = calm_result["counties"][0]["pct_customers_out"]["median"]
    strong_med = strong_result["counties"][0]["pct_customers_out"]["median"]
    assert strong_med > calm_med


def dataclasses_replace(config, **changes):
    import dataclasses
    return dataclasses.replace(config, **changes)


def test_scenario_horizons_all_succeed_through_patched_real_pipeline(patched_pipeline):
    for lt in (24, 48, 72):
        result = pipeline.run_scenario_impact_pipeline(county_fips=[COUNTY_FIPS], lead_time_h=lt)
        assert result["requested_lead_time_h"] == float(lt)
        assert len(result["counties"]) == 1


# --- 5. scenario results tagged data_source="scenario_model" ----------------


def test_scenario_result_is_tagged_scenario_model_and_matches_contract(patched_pipeline):
    result = pipeline.run_scenario_impact_pipeline(county_fips=[COUNTY_FIPS], lead_time_h=48, advisory_number=3)
    assert result["data_source"] == "scenario_model"
    assert "SIMULATED SCENARIO" in result["source"]
    assert "ORION" in result["source"]
    validated = Impact.model_validate(result)
    assert validated.data_source == "scenario_model"


# --- real artifacts (local files, no network, no monkeypatching) ------------


def test_scenario_through_the_real_model_and_calibration_end_to_end():
    result = pipeline.run_scenario_impact_pipeline(county_fips=["12029", "12075"], lead_time_h=48)
    assert result["data_source"] == "scenario_model"
    assert result["model_version"] == "xgboost-quantile-real-v1.0"
    for county in result["counties"]:
        q = county["pct_customers_out"]
        assert 0.0 <= q["low"] <= q["median"] <= q["high"] <= 100.0
        assert county["risk_tier"] in {"green", "yellow", "orange", "red"}
    Impact.model_validate(result)


def test_scenario_different_horizons_give_different_real_model_output():
    results = {lt: pipeline.run_scenario_impact_pipeline(county_fips=["12029"], lead_time_h=lt) for lt in (24, 48, 72)}
    medians = {lt: r["counties"][0]["pct_customers_out"]["median"] for lt, r in results.items()}
    # the track genuinely moves between horizons (see test_scenario_track_moves_with_tau_deterministically),
    # so at least two of the three real-model outputs must differ -- a frozen/hardcoded result would not.
    assert len(set(medians.values())) > 1, medians


# --- 7. live ATCF behavior remains unchanged ---------------------------------


def test_live_storm_query_still_takes_priority_over_scenario_when_both_set(monkeypatch):
    # agent/tools.py imports "models.pipeline"/"models.live_atcf_source" (bare,
    # not "backend.models...") -- see tools.py's own comment on why -- which
    # pytest's pythonpath loads as a SEPARATE module object from the
    # "backend.models..." one this test file otherwise uses. Must monkeypatch
    # the bare one for it to actually affect predict_impact()'s behavior.
    import models.live_atcf_source as bare_live_atcf_source
    from backend.agent.tools import predict_impact

    def boom(*args, **kwargs):
        raise bare_live_atcf_source.AtcfNetworkError("no network in this test")

    monkeypatch.setattr(bare_live_atcf_source, "fetch_current_storms_json", boom)
    monkeypatch.setenv("USE_ML_IMPACT_MODEL", "true")
    monkeypatch.setenv("LIVE_STORM_QUERY", "NONEXISTENT_STORM_XYZ")
    monkeypatch.setenv("USE_SCENARIO_MODEL", "true")

    # the live branch fails (network error) and falls back to stub -- it must
    # NOT be shadowed/preempted by the scenario branch when LIVE_STORM_QUERY is set,
    # even though USE_SCENARIO_MODEL=true and a working scenario path exists.
    res = predict_impact(["12075"])
    assert res["data_source"] == "stub_fallback"


def test_live_atcf_source_module_untouched_by_scenario_wiring():
    # scenario_generator.py must not be imported by live_atcf_source.py (no
    # shared/entangled code path between the two input sources).
    import backend.models.live_atcf_source as live_atcf_source
    assert "scenario" not in live_atcf_source.__file__.lower() or True  # file identity sanity
    import inspect
    source = inspect.getsource(live_atcf_source)
    assert "scenario_generator" not in source


# --- 8. stub fallback remains unchanged --------------------------------------


def test_stub_fallback_unchanged_when_no_mode_env_vars_set(monkeypatch):
    from backend.agent.tools import predict_impact

    monkeypatch.delenv("USE_ML_IMPACT_MODEL", raising=False)
    monkeypatch.delenv("LIVE_STORM_QUERY", raising=False)
    monkeypatch.delenv("USE_SCENARIO_MODEL", raising=False)

    res = predict_impact(["12075"])
    assert res["data_source"] == "stub_fallback"
    assert res["model_version"] == "stub-impact-v0"


# --- explicit per-request mode= selector (frontend Live/Scenario toggle) ----
# "models.pipeline"/"models.live_atcf_source" below are the bare-import module
# objects agent/tools.py actually uses -- see the module-identity note above.


def test_mode_scenario_reaches_run_scenario_impact_pipeline(monkeypatch):
    import models.pipeline as bare_pipeline
    from backend.agent.tools import predict_impact

    calls = []
    monkeypatch.setattr(bare_pipeline, "run_scenario_impact_pipeline", lambda **kw: calls.append(kw) or {
        "advisory_number": 0, "model_version": "x", "counties": [], "source": "s", "data_source": "scenario_model",
    })
    monkeypatch.setenv("USE_ML_IMPACT_MODEL", "true")
    monkeypatch.delenv("LIVE_STORM_QUERY", raising=False)

    res = predict_impact(["12075"], lead_time_h=48, mode="scenario")

    assert len(calls) == 1
    assert calls[0]["lead_time_h"] == 48
    assert res["data_source"] == "scenario_model"


def test_mode_live_reaches_run_live_impact_pipeline(monkeypatch):
    import models.pipeline as bare_pipeline
    from backend.agent.tools import predict_impact

    calls = []
    monkeypatch.setattr(bare_pipeline, "run_live_impact_pipeline", lambda storm_query, **kw: calls.append((storm_query, kw)) or {
        "advisory_number": 0, "model_version": "x", "counties": [], "source": "s", "data_source": "real_atcf_model",
    })
    monkeypatch.setenv("USE_ML_IMPACT_MODEL", "true")
    monkeypatch.setenv("LIVE_STORM_QUERY", "HELENA")

    res = predict_impact(["12075"], lead_time_h=24, mode="live")

    assert len(calls) == 1
    assert calls[0][0] == "HELENA"
    assert calls[0][1]["lead_time_h"] == 24
    assert res["data_source"] == "real_atcf_model"


def test_mode_live_without_storm_query_falls_back_to_stub_never_scenario(monkeypatch):
    # The critical "do not silently switch to Scenario Mode" requirement:
    # mode="live" with no LIVE_STORM_QUERY configured must go straight to
    # stub, even though USE_SCENARIO_MODEL=true (a working scenario path
    # exists and would otherwise be tempting to fall back to).
    import models.pipeline as bare_pipeline
    from backend.agent.tools import predict_impact

    scenario_calls = []
    monkeypatch.setattr(bare_pipeline, "run_scenario_impact_pipeline", lambda **kw: scenario_calls.append(kw))
    monkeypatch.setenv("USE_ML_IMPACT_MODEL", "true")
    monkeypatch.delenv("LIVE_STORM_QUERY", raising=False)
    monkeypatch.setenv("USE_SCENARIO_MODEL", "true")  # legacy env var present, but mode= must win

    res = predict_impact(["12075"], mode="live")

    assert scenario_calls == []  # never silently redirected to scenario
    assert res["data_source"] == "stub_fallback"


def test_explicit_mode_overrides_legacy_env_var_detection(monkeypatch):
    # LIVE_STORM_QUERY is set (legacy auto-detect would pick "live"), but an
    # explicit mode="scenario" must win -- env vars no longer decide mode
    # once a caller passes one.
    import models.pipeline as bare_pipeline
    from backend.agent.tools import predict_impact

    calls = []
    monkeypatch.setattr(bare_pipeline, "run_scenario_impact_pipeline", lambda **kw: calls.append(kw) or {
        "advisory_number": 0, "model_version": "x", "counties": [], "source": "s", "data_source": "scenario_model",
    })
    monkeypatch.setenv("USE_ML_IMPACT_MODEL", "true")
    monkeypatch.setenv("LIVE_STORM_QUERY", "HELENA")

    res = predict_impact(["12075"], mode="scenario")

    assert len(calls) == 1
    assert res["data_source"] == "scenario_model"


def test_omitted_mode_falls_back_to_legacy_env_detection(monkeypatch):
    import models.pipeline as bare_pipeline
    from backend.agent.tools import predict_impact

    calls = []
    monkeypatch.setattr(bare_pipeline, "run_live_impact_pipeline", lambda storm_query, **kw: calls.append(storm_query) or {
        "advisory_number": 0, "model_version": "x", "counties": [], "source": "s", "data_source": "real_atcf_model",
    })
    monkeypatch.setenv("USE_ML_IMPACT_MODEL", "true")
    monkeypatch.setenv("LIVE_STORM_QUERY", "HELENA")

    res = predict_impact(["12075"])  # mode omitted entirely -- old callers keep working unchanged

    assert calls == ["HELENA"]
    assert res["data_source"] == "real_atcf_model"


def test_scenario_failure_falls_back_to_stub_not_an_exception(monkeypatch):
    # Same bare-vs-"backend."-qualified module-identity note as the test above:
    # must monkeypatch "models.pipeline" (what agent/tools.py actually imports),
    # not "backend.models.pipeline", for this to affect predict_impact().
    import models.pipeline as bare_pipeline
    from backend.agent.tools import predict_impact

    monkeypatch.setenv("USE_ML_IMPACT_MODEL", "true")
    monkeypatch.delenv("LIVE_STORM_QUERY", raising=False)
    monkeypatch.setenv("USE_SCENARIO_MODEL", "true")
    monkeypatch.setattr(bare_pipeline, "get_model", lambda: (_ for _ in ()).throw(FileNotFoundError("no artifact")))

    res = predict_impact(["12075"])
    assert res["data_source"] == "stub_fallback"
