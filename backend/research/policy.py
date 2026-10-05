"""Judge policy: every threshold the research judge uses, in one place.

Defaults agreed 2026-10-05 (docs/research-agent-plan.md §Judge inputs). Change policy here, not in code.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Metric:
    unit: str
    key: bool    # key = needs 2 independent sources for VERIFIED
    ages: bool   # standing capacity/staffing facts go stale; past-storm facts don't
    definition: str = ""  # shown to researcher and judge: a metric name alone left "whose staff?" open
    # Stored type for computation downstream (sums, demand vs beds). Counts are whole numbers.
    dtype: str = "int"
    min: float = 0
    max: float | None = None


# Controlled vocabulary for Fact.metric, from the hurricane packs' `gaps` list. Closed: a fact must use one
# of these so its unit and type are known to everything that computes with it (schema enforces).
# Harris run 2026-10-05: utility workers were filed as staff_count -> utility metrics split out.
METRICS = {
    "shelter_capacity": Metric("people", True, True, "people the shelters can hold (not how many came)"),
    "shelter_count": Metric("shelters", False, True, "shelters opened or designated"),
    "staff_count": Metric("people", True, True,
                          "county or city government staff deployed for storm response or in emergency roles "
                          "(not utility workers, not volunteers)"),
    "crew_count": Metric("crews", True, True, "county or city work crews (debris, roads, public works)"),
    "vehicle_count": Metric("vehicles", True, True, "county or city trucks/vehicles used in storm response"),
    "staging_sites": Metric("sites", False, True, "county or city staging / distribution sites"),
    "utility_workers": Metric("people", False, False, "utility restoration workers incl. mutual aid, per storm"),
    "utility_staging_sites": Metric("sites", False, False, "utility restoration staging sites, per storm"),
    "peak_customers_out": Metric("customers", True, False, "peak electricity customers without power, per storm"),
    "evacuee_count": Metric("people", True, False, "people sheltered or evacuated, per storm (say which)"),
    "fema_pa_total": Metric("usd", True, False, "FEMA Public Assistance dollars for damage in this county, per storm",
                            dtype="float"),
    "service_requests": Metric("requests", False, False, "311 or equivalent storm-related service requests, per storm"),
}

# Words that count as the unit being stated near the quote. A unit not listed here -> check not run (None).
UNIT_SYNONYMS = {
    "people": ("people", "person", "persons", "resident", "guest", "evacuee", "employee", "staff", "personnel",
               "worker", "volunteer", "occupant", "capacity", "bed", "cot"),
    "shelters": ("shelter",),
    "crews": ("crew", "lineworker", "lineman", "linemen", "team"),
    "vehicles": ("truck", "vehicle", "bus", "buses"),
    "sites": ("site", "location", "staging", "point of distribution", "pod"),
    "customers": ("customer", "meter", "account", "outage"),
    "usd": ("$", "dollar", "usd"),
    "requests": ("request", "call", "ticket", "311"),
    "percent": ("%", "percent"),
    "hours": ("hour", "hrs"),
}

QUOTE_VALUE_TOLERANCE = 0.0      # the value must appear in the quote as written (after number normalization)
CORROBORATION_TOLERANCE = 0.02   # two sources agree if within 2 % (rounded press figures)
STALE_YEARS = 5
OFFICIAL_SINGLE_IS_VERIFIED = False  # one official doc -> SINGLE_SOURCE marked official, not VERIFIED
CONFLICTS_AUTO_RESOLVE = False       # conflicts always go to the reviewer
MIN_QUOTE_CHARS = 20             # shorter quotes match too easily to tie a value to its claim
MAX_GEMINI_CALLS = 150           # per county run; hitting a cap ends the run with a partial draft, cap shown
MAX_FETCHES = 40
MAX_RUN_SECONDS = 900            # wall clock; at the cap the run stops and still writes its partial draft

# County sites that aren't on .gov (checked by hand per county; add when a new county is targeted).
OFFICIAL_DOMAINS = {"leegov.com", "hctx.net", "readyharris.org"}


def metric(name: str) -> Metric:
    """Raises KeyError for a metric outside the vocabulary (Fact validation refuses those first)."""
    return METRICS[name]


def is_official(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host.endswith((".gov", ".mil", ".us")) or any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)
