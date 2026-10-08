"""Phase 1: storm-wide, multi-county Risk Map (agent/storm_view.py, GET /api/storms/{slug}/overview).

Needs real packs + the real trained model bundle (GCS/local artifacts), like test_hurricane_agent.py
and test_model_bundle.py -- skipped if that data isn't reachable in this environment.
"""

import os

import pytest

from agent import registry
from agent.hurricane_contracts import StormWideRiskView
from hurricane.storm_regions import NEIGHBOR_FIPS

SLUGS = ["harris-hurricane", "miami-dade-hurricane", "lee-hurricane"]


@pytest.fixture(scope="module")
def client():
    os.environ["LLM_MODEL"] = "mock"
    from fastapi.testclient import TestClient

    from backend.app import app
    with TestClient(app) as test_client:
        yield test_client


def _skip_if_unavailable():
    try:
        registry.storm_overview(SLUGS[0], 48)
    except Exception as e:  # pack/model data not reachable in this environment
        pytest.skip(f"storm-wide data unavailable: {e}")


@pytest.mark.parametrize("slug", SLUGS)
@pytest.mark.parametrize("horizon_h", [24, 48, 72])
def test_storm_overview_matches_contract_for_every_slug_and_horizon(slug, horizon_h):
    _skip_if_unavailable()
    out = registry.storm_overview(slug, horizon_h)
    StormWideRiskView.model_validate(out)  # raises on any contract mismatch

    assert out["horizon_h"] == horizon_h
    assert out["kind"] == "replay"
    assert set(out["available_horizons_h"]) <= {24, 48, 72}

    fips_seen = {c["fips"] for c in out["counties"]}
    expected = {out["home_county_fips"]} | set(NEIGHBOR_FIPS.get(slug, []))
    assert fips_seen == expected

    home = next(c for c in out["counties"] if c["fips"] == out["home_county_fips"])
    assert home["has_local_pack"] is True
    for fips in NEIGHBOR_FIPS.get(slug, []):
        neighbor = next(c for c in out["counties"] if c["fips"] == fips)
        # Phase 1 neighbors have no published hurricane pack: a real prediction, no shelter data.
        assert neighbor["has_local_pack"] is False

    # Every shelter in the merged list belongs to a county that actually has a pack.
    shelter_fips = {s["county_fips"] for s in out["shelters"]}
    assert shelter_fips <= {c["fips"] for c in out["counties"] if c["has_local_pack"]}


def test_storm_overview_default_horizon_is_48h_when_available():
    _skip_if_unavailable()
    out = registry.storm_overview(SLUGS[0], None)
    assert out["horizon_h"] == 48


def test_storm_overview_rejects_an_unavailable_horizon_instead_of_substituting_one():
    _skip_if_unavailable()
    with pytest.raises(ValueError):
        registry.storm_overview(SLUGS[0], 36)  # not in SUPPORTED_HORIZONS_H


def test_storm_overview_unknown_slug_raises_key_error():
    _skip_if_unavailable()
    with pytest.raises(KeyError):
        registry.storm_overview("not-a-real-storm", 48)


def test_storm_overview_endpoint_round_trip(client):
    _skip_if_unavailable()
    r = client.get(f"/api/storms/{SLUGS[2]}/overview", params={"horizon_h": 48})
    assert r.status_code == 200
    StormWideRiskView.model_validate(r.json())

    assert client.get("/api/storms/not-a-real-storm/overview").status_code == 404
    assert client.get(f"/api/storms/{SLUGS[2]}/overview", params={"horizon_h": 36}).status_code == 422
