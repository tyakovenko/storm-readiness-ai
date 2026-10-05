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


# Controlled vocabulary for Fact.metric, from the hurricane packs' `gaps` list. A metric outside it is
# kept (non-key, ages) so new findings aren't dropped, and the reviewer sees it isn't in the vocabulary.
METRICS = {
    "shelter_capacity": Metric("people", key=True, ages=True),
    "shelter_count": Metric("shelters", key=False, ages=True),
    "staff_count": Metric("people", key=True, ages=True),
    "crew_count": Metric("crews", key=True, ages=True),
    "vehicle_count": Metric("vehicles", key=True, ages=True),
    "staging_sites": Metric("sites", key=False, ages=True),
    "peak_customers_out": Metric("customers", key=True, ages=False),
    "evacuee_count": Metric("people", key=True, ages=False),
    "fema_pa_total": Metric("usd", key=True, ages=False),
    "service_requests": Metric("requests", key=False, ages=False),
}
UNKNOWN_METRIC = Metric("", key=False, ages=True)

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
    return METRICS.get(name, UNKNOWN_METRIC)


def is_official(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host.endswith((".gov", ".mil", ".us")) or any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)
