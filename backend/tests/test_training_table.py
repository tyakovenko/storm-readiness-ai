"""Hurricane training-table builder: track features on a storm with known geography (Idalia 2023).

Needs HURDAT2 + the county gazetteer (local data/raw or GCS); skips otherwise. The EAGLE-I
label pass streams GBs and runs in the cloud job, so it's checked there via the manifest.
"""

import pytest

from models import build_training_table as B


@pytest.fixture(scope="module")
def idalia():
    try:
        counties = B.load_counties()
        storms = B.parse_hurdat(B.read_bytes("hurdat2/hurdat2_atlantic.txt").decode(), {2023})
    except Exception as e:  # no local data and no GCS access
        pytest.skip(f"HURDAT2 / gazetteer unavailable: {e}")
    s = next(x for x in storms if x.name == "Idalia")
    f = B.storm_county_features(s, counties).set_index("fips")
    return s, f, storms, counties


def test_idalia_landfall_county_gets_peak_wind(idalia):
    s, f, _, _ = idalia
    assert f["max_wind_kt"].idxmax() == "12123"            # Taylor County, Keaton Beach landfall
    assert f.loc["12123", "dist_to_track_nm"] < 15


def test_idalia_right_and_left_of_a_northeastward_track(idalia):
    _, f, _, _ = idalia
    for right in ("12067", "12121", "12029", "12075"):     # Lafayette, Suwannee, Dixie, Levy (east/south)
        assert f.loc[right, "quadrant_right"] == 1, right
    for left in ("12079", "12065", "12073"):               # Madison, Jefferson, Leon (west/north)
        assert f.loc[left, "quadrant_right"] == 0, left


def test_2023_storms_with_us_impact(idalia):
    _, _, storms, counties = idalia
    hit = {s.name for s in storms if not B.storm_county_features(s, counties).empty}
    assert {"Idalia", "Harold", "Lee", "Ophelia"} <= hit


def test_label_window_brackets_the_storm(idalia):
    s, f, _, _ = idalia
    w = f.loc["12123"]
    assert w["window_start"] < s.t[0] + (s.t[-1] - s.t[0]) and w["window_end"] > w["window_start"]
