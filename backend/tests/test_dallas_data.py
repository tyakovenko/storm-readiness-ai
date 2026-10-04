"""Dallas data layer: built tables match independently published figures.

Needs the raw data locally (`python data/sync_cloud_data.py pull --dataset dallas`);
skips with that instruction otherwise. Expected values come from sources outside
the build (Socrata API counts, news, city memos), so a wrong window, threshold or
parser shows up here.
"""

import csv
from pathlib import Path

import pytest

from dallas import build, sources, store

RAW = build.RAW
pytestmark = pytest.mark.skipif(
    not (RAW / "dallas311").exists(),
    reason="raw Dallas data missing: python data/sync_cloud_data.py pull --dataset dallas",
)


@pytest.fixture(scope="module")
def built():
    build.build()
    store.table.cache_clear()
    return {s["id"]: s for s in store.storms()}


def test_311_raw_window_matches_socrata_api_count():
    # Socrata API count for 2021-02-14..21, queried 2026-10-02: 3,527.
    f = next((RAW / "dallas311").glob("311_uri_2021_*.csv"))
    n = sum(1 for r in csv.DictReader(open(f, newline="")) if "2021-02-14" <= r["created_date"][:10] <= "2021-02-21")
    assert n == 3527


def test_weather_matches_published_counts(built):
    fern = built["fern_2026"]["weather"]
    assert fern["hours_below_freezing"] == 58      # DMN 2026-02-09: 58 h below freezing
    assert fern["snowfall_in"] == 2.4              # DMN: 2.4 in snow + sleet at DFW
    assert built["uri_2021"]["weather"]["hours_below_freezing"] in range(135, 145)  # ~139 h widely reported
    assert built["uri_2021"]["weather"]["min_temp_f"] < 0


def test_outages_uri_peak_is_large_and_later_storms_small(built):
    uri = built["uri_2021"]["outages"]
    assert uri["peak_customers_out"] > 300_000 and uri["peak_time"].startswith("2021-02-16")
    assert built["winter_2025"]["outages"]["peak_customers_out"] < 10_000
    assert built["fern_2026"]["outages"] is None   # EAGLE-I has no 2026 file yet


def test_311_surges_are_storm_types(built):
    for sid in ("uri_2021", "ice_2023", "fern_2026"):
        types = [s["request_type"] for s in built[sid]["impacts_311"]["surges"]]
        assert any("Sanding" in t for t in types), sid
        assert all(s["sector"] != "other" for s in built[sid]["impacts_311"]["surges"])
    # Evacuee sheltering is not a local weather surge.
    assert built["harvey_2017"]["impacts_311"]["surges"] == []


def test_fema_uri_projects(built):
    f = built["uri_2021"]["fema"]
    assert f["pa_projects"] == 33 and 4_100_000 < f["pa_amount_usd"] < 4_300_000


def test_assets_shelters_and_nss():
    build.build()
    store.table.cache_clear()
    a = store.assets()
    caps = {s["id"]: s["capacity"] for s in a["inclement_weather_shelters"]}
    assert caps == {"fair_park": 1200, "fair_park_tower": None, "austin_street": 360, "oak_lawn_umc": 80}
    assert all(s["source"] for s in a["inclement_weather_shelters"])
    assert a["evacuee_shelters_nss"]["total_evacuation_capacity"] == 49439


def test_districts_cover_city_and_shares_sum_to_one(built):
    feats = store.districts()["features"]
    assert sorted(int(f["properties"]["district"]) for f in feats) == list(range(1, 15))
    assert abs(sum(f["properties"]["winter_transport_share"] for f in feats) - 1) < 0.01


def test_every_response_fact_is_sourced():
    for facts in sources.RESPONSE_FACTS.values():
        for f in facts:
            assert f["source"] and isinstance(f["value"], (int, float))


def test_store_fails_loudly_without_data(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "LOCAL", tmp_path)
    monkeypatch.setattr(store, "BUCKET", "no-such-bucket-storm-readiness-test")
    store.table.cache_clear()
    with pytest.raises(store.DataUnavailable):
        store.storms()
    store.table.cache_clear()
