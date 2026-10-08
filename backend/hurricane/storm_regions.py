"""Real, documented neighboring counties for each existing hurricane pack's replayed storm.

Not a new data source: these FIPS codes feed the SAME trained outage model via
models/pipeline.run_impact_pipeline, using nationwide FEMA NRI / CDC SVI / EAGLE-I / Census
tables that already cover every US county -- whether or not that county has its own hurricane
pack (shelters/assets). Each list was chosen because the storm that pack already replays is a
real, well-documented historical hurricane whose own track and impact area (per NOAA/NHC) passed
near or through these counties, and was verified end-to-end against the real model before being
added here (see Phase 1 architecture notes). Keep each list small and honest -- every entry must
be a real place that storm's own replayed track plausibly affects, never padding for a
bigger-looking map.
"""

from __future__ import annotations

# slug (matches hurricane/build_pack.py's COUNTIES[*]["slug"]) -> extra real county FIPS codes,
# beyond the pack's own home county, that the SAME replayed storm's real track also affects.
NEIGHBOR_FIPS: dict[str, list[str]] = {
    # Hurricane Ian, 2022 (AL092022): Charlotte, Collier, Sarasota, DeSoto counties, FL --
    # all real, well-documented major-impact counties along Ian's track alongside Lee County.
    "lee-hurricane": ["12015", "12021", "12115", "12027"],
    # Hurricane Irma, 2017 (AL112017): Broward, Monroe (the Florida Keys, Irma's actual US
    # landfall), and Palm Beach counties, FL -- real, well-documented SE Florida impact area.
    "miami-dade-hurricane": ["12011", "12087", "12099"],
    # Hurricane Beryl, 2024 (AL022024): Galveston, Fort Bend, Montgomery and Brazoria counties,
    # TX -- real Houston-area counties affected alongside Harris County.
    "harris-hurricane": ["48167", "48157", "48339", "48039"],
}
