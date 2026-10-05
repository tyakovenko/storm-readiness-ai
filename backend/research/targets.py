"""Research targets: built from the county's published national-baseline pack (storms, gaps) plus a small
per-county config of names and portals that can't be derived from data.

Portal entries were probed 2026-10-05: Legistar Web API answers for `miamidade` only (houston, harriscounty,
leecounty, capecoral, fortmyers -> 500). None of the three counties publish on Socrata (catalog search for
them returns other jurisdictions), so the Socrata tool is off for them. ArcGIS search works for all.
"""

from __future__ import annotations

import re

from research.schema import Gap, Storm, Target

COUNTY_CONFIG = {
    "48201": {"aliases": [], "cities": ["Houston", "Pasadena", "Baytown"], "legistar": [], "socrata": []},
    "12086": {"aliases": ["Dade County"], "cities": ["Miami", "Hialeah", "Miami Beach", "Homestead"],
              "legistar": ["miamidade"], "socrata": []},
    "12071": {"aliases": [], "cities": ["Fort Myers", "Cape Coral", "Bonita Springs", "Sanibel", "Fort Myers Beach"],
              "legistar": [], "socrata": []},
}


def _storm(s: dict) -> Storm:
    # Pack names carry the year ("Beryl 2024"); the storm check wants name and year apart.
    name = re.sub(r"\s+\d{4}$", "", s["name"]).strip()
    return Storm(id=s["storm_id"], name=name, year=int(s["year"]))


def target_from_pack(fips: str) -> tuple[Target, list[Gap], dict]:
    """(target, gaps to research, portals) for a county with a published hurricane pack."""
    from hurricane import store
    pack = store.pack(fips)
    if fips not in COUNTY_CONFIG:
        raise KeyError(f"{fips}: no research config (names, portals) in research/targets.py COUNTY_CONFIG")
    cfg = COUNTY_CONFIG[fips]
    target = Target(fips=fips, county=pack["county"], state=pack["state"], hazard="hurricane",
                    aliases=cfg["aliases"], cities=cfg["cities"],
                    storms=[_storm(s) for s in store.table(fips, "storms.json")["storms"]])
    gaps = [Gap(**g) for g in pack.get("gaps", [])]
    return target, gaps, {"legistar": cfg["legistar"], "socrata": cfg["socrata"]}
