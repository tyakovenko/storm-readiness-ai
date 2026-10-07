"""Tests for HURDAT2 best-track parsing and landfall extraction (Phase 3G).

Small synthetic HURDAT2-format text only (field layout verified against the
real hurdat2_atlantic.txt file's Hurricane Michael 2018 entry) -- no real
archive data.
"""

import io
from datetime import datetime

import pytest

from backend.models.hurdat2 import find_storm, landfall_record, parse_hurdat2_storms, select_us_landfall

# Mirrors the real AL142018 (Michael) block's format exactly, trimmed to a
# few track lines plus the real landfall line verified against hurdat2_atlantic.txt.
MICHAEL_SAMPLE = """AL142018,            MICHAEL,      4,
20181007, 1200,  , TS, 18.8N,  86.4W,  35, 1003,  120,  180,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
20181010, 1200,  , HU, 29.0N,  86.3W, 125,  934,  150,  140,   80,  120,   80,   80,   40,   50,   40,   35,   25,   30, -999
20181010, 1730, L, HU, 30.0N,  85.5W, 140,  919,   90,  140,  100,   80,   60,   80,   50,   50,   35,   35,   25,   25,   10
20181011, 0000,  , HU, 31.5N,  84.5W,  80,  957,   60,  140,   60,   40,   40,   40,   30,   20,   25,   25,    0,    0, -999
"""

NO_LANDFALL_SAMPLE = """AL992099,             OFFSHORE,      2,
20991007, 1200,  , TS, 18.8N,  86.4W,  35, 1003,  120,  180,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
20991008, 0000,  , TS, 19.0N,  87.0W,  40, 1000,  120,  180,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
"""

MULTI_LANDFALL_SAMPLE = """AL992098,             DOUBLEHIT,      3,
20981007, 1200, L, HU, 18.8N,  86.4W,  70,  990,  120,  180,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
20981007, 1800,  , HU, 19.0N,  87.0W,  65,  992,  120,  180,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
20981008, 0000, L, TS, 19.5N,  87.5W,  50, 1000,  120,  180,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
"""

# Mimics Ian 2022's real pattern: an earlier Cuba landfall (outside CONUS_BBOX,
# stronger wind) followed by the real, lower-wind-at-that-instant Florida
# landfall (inside CONUS_BBOX) -- tests that CONUS filtering, not raw wind
# magnitude, drives the choice between a foreign and a US landfall.
FOREIGN_THEN_US_SAMPLE = """AL992097,             CARIBHIT,      2,
20971007, 0830, L, HU, 22.2N,  83.7W, 110,  947,  120,  180,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
20971008, 1905, L, HU, 26.7N,  82.2W,  95,  950,  120,  180,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
"""

# Mimics a storm with two real CONUS landfalls of different strength (e.g.
# Ian's FL-then-SC pattern) -- tests the max-wind tiebreaker among CONUS
# candidates specifically.
TWO_US_LANDFALLS_SAMPLE = """AL992096,             TWOUSHIT,      2,
20961007, 1200, L, HU, 26.0N,  82.0W,  90,  955,  120,  180,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
20961009, 1200, L, HU, 33.3N,  79.2W,  70,  980,  120,  180,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
"""


def test_parses_header_and_all_track_lines():
    storms = parse_hurdat2_storms(io.StringIO(MICHAEL_SAMPLE))
    assert len(storms) == 1
    storm = storms[0]
    assert storm.storm_id == "AL142018"
    assert storm.name == "MICHAEL"
    assert len(storm.track) == 4


def test_track_point_fields_parsed_correctly():
    storms = parse_hurdat2_storms(io.StringIO(MICHAEL_SAMPLE))
    first = storms[0].track[0]
    assert first.time == datetime(2018, 10, 7, 12, 0)
    assert first.record_identifier is None
    assert first.status == "TS"
    assert first.lat == pytest.approx(18.8)
    assert first.lon == pytest.approx(-86.4)
    assert first.max_wind_kt == 35.0
    assert first.min_pressure_mb == 1003.0


def test_missing_pressure_sentinel_is_none_not_minus_999():
    # not exercised by the trimmed Michael sample (all rows have real pressure),
    # so use a row with the -999 sentinel explicitly
    sample = """AL002099,             TESTSTORM,      1,
20990101, 0000,  , TD, 10.0N,  50.0W,  25, -999,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
"""
    storms = parse_hurdat2_storms(io.StringIO(sample))
    assert storms[0].track[0].min_pressure_mb is None


def test_parses_multiple_storms_in_one_file():
    combined = MICHAEL_SAMPLE + NO_LANDFALL_SAMPLE
    storms = parse_hurdat2_storms(io.StringIO(combined))
    assert len(storms) == 2
    assert {s.storm_id for s in storms} == {"AL142018", "AL992099"}


# --- find_storm ---------------------------------------------------------------


def test_find_storm_returns_exact_match():
    storms = parse_hurdat2_storms(io.StringIO(MICHAEL_SAMPLE))
    found = find_storm(storms, "AL142018")
    assert found.name == "MICHAEL"


def test_find_storm_raises_on_unknown_id():
    storms = parse_hurdat2_storms(io.StringIO(MICHAEL_SAMPLE))
    with pytest.raises(ValueError, match="AL999999"):
        find_storm(storms, "AL999999")


# --- landfall_record -----------------------------------------------------------


def test_landfall_record_finds_the_l_flagged_row():
    storms = parse_hurdat2_storms(io.StringIO(MICHAEL_SAMPLE))
    landfall = landfall_record(storms[0])
    assert landfall is not None
    # real values from hurdat2_atlantic.txt's AL142018 landfall line
    assert landfall.time == datetime(2018, 10, 10, 17, 30)
    assert landfall.lat == pytest.approx(30.0)
    assert landfall.lon == pytest.approx(-85.5)
    assert landfall.max_wind_kt == 140.0
    assert landfall.min_pressure_mb == 919.0


def test_landfall_record_none_when_storm_never_made_landfall():
    storms = parse_hurdat2_storms(io.StringIO(NO_LANDFALL_SAMPLE))
    assert landfall_record(storms[0]) is None


def test_landfall_record_returns_first_of_multiple_landfalls():
    storms = parse_hurdat2_storms(io.StringIO(MULTI_LANDFALL_SAMPLE))
    landfall = landfall_record(storms[0])
    assert landfall.time == datetime(2098, 10, 7, 12, 0)  # the first L, not the second


# --- select_us_landfall (Phase 3L) ----------------------------------------------


def test_select_us_landfall_single_landfall_matches_landfall_record():
    # for an unambiguous single-landfall storm, both functions agree (Michael)
    storms = parse_hurdat2_storms(io.StringIO(MICHAEL_SAMPLE))
    assert select_us_landfall(storms[0]) == landfall_record(storms[0])


def test_select_us_landfall_skips_foreign_landfall():
    # mimics Ian: an earlier, higher-wind Cuba landfall must be skipped in
    # favor of the lower-wind-at-that-instant Florida landfall
    storms = parse_hurdat2_storms(io.StringIO(FOREIGN_THEN_US_SAMPLE))
    us_landfall = select_us_landfall(storms[0])
    assert us_landfall.lat == pytest.approx(26.7)
    assert us_landfall.lon == pytest.approx(-82.2)
    assert us_landfall.max_wind_kt == 95.0


def test_select_us_landfall_picks_max_wind_among_us_candidates():
    storms = parse_hurdat2_storms(io.StringIO(TWO_US_LANDFALLS_SAMPLE))
    us_landfall = select_us_landfall(storms[0])
    assert us_landfall.max_wind_kt == 90.0  # the FL landfall, not the weaker SC one
    assert us_landfall.lon == pytest.approx(-82.0)


def test_select_us_landfall_none_when_no_conus_landfall():
    # both of MULTI_LANDFALL_SAMPLE's landfalls are in the Yucatan/Caribbean,
    # well outside CONUS_BBOX
    storms = parse_hurdat2_storms(io.StringIO(MULTI_LANDFALL_SAMPLE))
    assert select_us_landfall(storms[0]) is None


def test_select_us_landfall_none_when_storm_never_made_landfall():
    storms = parse_hurdat2_storms(io.StringIO(NO_LANDFALL_SAMPLE))
    assert select_us_landfall(storms[0]) is None
