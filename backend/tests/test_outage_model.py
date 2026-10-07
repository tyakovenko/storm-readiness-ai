"""Tests for Quantile XGBoost Outage Impact Model."""

import tempfile
from pathlib import Path
import numpy as np
import pytest

from backend.agent.contracts import Impact, CountyImpact
from backend.models.schema import CountyFeatures, features_to_dataframe, FEATURE_COLUMNS
from backend.models.outage_model import QuantileOutageModel
from backend.models.synthetic_bootstrap import generate_bootstrap_dataset
from backend.models.dataset import load_county_static_lookup, get_latest_oni_anomaly


@pytest.fixture(scope="module")
def trained_model():
    """Module-level trained model fixture."""
    X, y = generate_bootstrap_dataset(n_samples=500, random_seed=42)
    model = QuantileOutageModel(alpha_low=0.10, alpha_median=0.50, alpha_high=0.90, n_estimators=40)
    model.fit(X, y)
    return model


def test_county_features_fips_zero_padding():
    cf = CountyFeatures(
        fips="1001",  # 4 digits
        name="Autauga County",
        state="AL",
        max_wind_kt=60.0,
        dist_to_track_nm=25.0,
    )
    assert cf.fips == "01001"
    assert len(cf.fips) == 5
    assert cf.gust_wind_kt == 75.0  # 1.25 * 60


def test_quantile_monotonicity_and_bounds(trained_model):
    sample_counties = [
        CountyFeatures("12075", "Levy County", "FL", max_wind_kt=95.0, dist_to_track_nm=15.0),
        CountyFeatures("12029", "Dixie County", "FL", max_wind_kt=75.0, dist_to_track_nm=30.0),
        CountyFeatures("12017", "Citrus County", "FL", max_wind_kt=45.0, dist_to_track_nm=65.0),
        CountyFeatures("12123", "Taylor County", "FL", max_wind_kt=25.0, dist_to_track_nm=120.0),
    ]
    df = features_to_dataframe(sample_counties)
    quantiles = trained_model.predict_quantiles(df)

    assert quantiles.shape == (4, 3)
    for i in range(len(sample_counties)):
        low, med, high = quantiles[i]
        # Range bounds
        assert 0.0 <= low <= 100.0
        assert 0.0 <= med <= 100.0
        assert 0.0 <= high <= 100.0
        # Strict quantile ordering
        assert low <= med <= high


def test_predict_matches_impact_contract(trained_model):
    sample_counties = [
        CountyFeatures("12075", "Levy County", "FL", max_wind_kt=95.0, dist_to_track_nm=15.0),
        CountyFeatures("12029", "Dixie County", "FL", max_wind_kt=70.0, dist_to_track_nm=35.0),
    ]
    impact_dict = trained_model.predict(sample_counties, advisory_number=14)

    # Validate against strict Pydantic contract
    validated = Impact.model_validate(impact_dict)
    assert validated.advisory_number == 14
    assert validated.model_version == trained_model.version
    assert len(validated.counties) == 2
    for c in validated.counties:
        assert isinstance(c, CountyImpact)
        assert len(c.fips) == 5
        assert c.risk_tier in {"green", "yellow", "orange", "red"}
        assert c.pct_customers_out.low <= c.pct_customers_out.median <= c.pct_customers_out.high
        assert len(c.why) >= 1


def test_explain_generates_plain_language(trained_model):
    cf = CountyFeatures(
        fips="12075",
        name="Levy County",
        state="FL",
        max_wind_kt=85.0,
        dist_to_track_nm=20.0,
        quadrant_right=1,
        tree_canopy_pct=60.0,
        svi_overall=0.80,
    )
    reasons = trained_model.explain(cf, pct_median=55.0)
    assert len(reasons) >= 1
    text = " ".join(reasons)
    assert "Hurricane-force winds" in text or "proximity" in text or "tree canopy" in text


def test_risk_tier_rules():
    # Severe
    assert QuantileOutageModel.assign_risk_tier(45.0, 0.4, 60.0) == "red"
    assert QuantileOutageModel.assign_risk_tier(28.0, 0.75, 55.0) == "red"
    # High
    assert QuantileOutageModel.assign_risk_tier(22.0, 0.3, 50.0) == "orange"
    # Moderate
    assert QuantileOutageModel.assign_risk_tier(8.0, 0.3, 30.0) == "yellow"
    # Green
    assert QuantileOutageModel.assign_risk_tier(2.0, 0.2, 20.0) == "green"


def test_model_persistence(trained_model):
    with tempfile.TemporaryDirectory() as tmp_dir:
        save_path = Path(tmp_dir) / "outage_test.joblib"
        trained_model.save(save_path)
        assert save_path.exists()

        loaded = QuantileOutageModel.load(save_path)
        assert loaded.is_fitted
        assert loaded.version == trained_model.version

        sample = [CountyFeatures("12075", "Levy County", "FL", max_wind_kt=80.0, dist_to_track_nm=25.0)]
        df = features_to_dataframe(sample)
        orig_q = trained_model.predict_quantiles(df)
        loaded_q = loaded.predict_quantiles(df)
        np.testing.assert_allclose(orig_q, loaded_q, rtol=1e-5)


def test_static_county_lookup_integration():
    lookup = load_county_static_lookup()
    assert len(lookup) >= 3000
    assert "12075" in lookup  # Levy County, FL
    levy = lookup["12075"]
    assert levy["state"] == "FL"
    assert levy["nri_risk_score"] > 0
    assert levy["svi_overall"] > 0
    assert get_latest_oni_anomaly() is not None


def test_tool_predict_impact_with_ml_toggle_falls_back_without_real_forecast_data(monkeypatch):
    # Phase 3Q: pipeline.run_impact_pipeline() now requires genuine ATCF forecast
    # data (storm track/intensity/heading) to build real features, and refuses to
    # fabricate it from the demo's free-text-only stub_data.ADVISORY. So toggling
    # USE_ML_IMPACT_MODEL on with only the stub advisory available must fall back
    # to the same stub county data as the toggle-off path -- not silently use the
    # old hardcoded Florida geometry this test used to exercise.
    from backend.agent.tools import run_tool
    monkeypatch.setenv("USE_ML_IMPACT_MODEL", "true")
    res = run_tool("predict_impact", {"county_fips": ["12075", "12029"]})
    assert res["model_version"] == "stub-impact-v0"
    assert len(res["counties"]) == 2
    assert res["counties"][0]["fips"] == "12075"
    assert res["counties"][0]["risk_tier"] in {"green", "yellow", "orange", "red"}


def test_temporal_period_split_no_leakage():
    from backend.models.split import temporal_period_split
    df, y = generate_bootstrap_dataset(n_samples=600, random_seed=42)
    df["pct_customers_out"] = y

    df_train, df_test = temporal_period_split(df, train_end_year=2021, test_start_year=2022)
    assert len(df_train) > 0
    assert len(df_test) > 0
    # Strict temporal boundary check: zero overlap
    train_years = set(df_train["year"])
    test_years = set(df_test["year"])
    assert train_years.isdisjoint(test_years)
    assert max(train_years) <= 2021
    assert min(test_years) >= 2022


def test_held_out_storm_split_no_leakage():
    from backend.models.split import held_out_storm_split
    df, y = generate_bootstrap_dataset(n_samples=600, random_seed=42)
    df["pct_customers_out"] = y

    test_storms = ["Idalia", "Ian", "Hilary", "Michael"]
    df_train, df_test = held_out_storm_split(df, test_storms)
    assert len(df_train) > 0
    assert len(df_test) > 0
    # Strict storm group boundary check: zero overlap
    train_storms = set(df_train["storm_name"])
    assert train_storms.isdisjoint(set(test_storms))
    assert set(df_test["storm_name"]).issubset(set(test_storms))


