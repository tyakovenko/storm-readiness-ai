"""Output contracts for the Dallas tools (dallas_tools.py).

Same rule as contracts.py: run_tool validates every output, and a mismatch is
an engine bug that raises instead of reaching the model. Every output names its
source(s). Ranges are low <= median <= high and always say how many past storms
they rest on (n), because n is small (2-4) and the reader needs to know.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import EnsoContext, Guidance  # noqa: F401  (shared with hurricane tools)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Range(_Strict):
    low: float
    median: float
    high: float
    n: int = Field(ge=1, description="number of past storms the range rests on")
    unit: str

    @model_validator(mode="after")
    def _ordered(self):
        if not self.low <= self.median <= self.high:
            raise ValueError(f"range out of order: {self.low}, {self.median}, {self.high}")
        return self


class Hazards(_Strict):
    ice_accretion_in: float = Field(ge=0)
    min_temp_f: float
    hours_below_freezing: float = Field(ge=0)
    snowfall_in: float = Field(ge=0)


class StormAlert(_Strict):
    scenario_id: str
    kind: Literal["scenario", "live"]
    headline: str
    area: str
    onset_local: str
    lead_time_h: float = Field(ge=0)
    hazards: Hazards | None = Field(description="None for a live alert whose text has no structured amounts")
    live_check: str = Field(description="result of the live NWS lookup, so a failed check is visible")
    note: str
    source: str


class SimilarStorm(_Strict):
    storm_id: str
    name: str
    event_dates: list[str]
    similarity: float = Field(ge=0, le=1)
    weather: dict
    peak_customers_out: int | None
    peak_pct_customers: float | None
    excess_311_by_sector: dict[str, int]
    enso_phase: str | None


class SimilarStorms(_Strict):
    scenario_id: str
    compared_on: list[str]
    storms: list[SimilarStorm]
    caveat: str
    source: str


class StormImpacts(_Strict):
    storm_id: str
    name: str
    event_dates: list[str]
    weather: dict | None
    outages: dict | None
    surges_311: list[dict]
    excess_311_by_sector: dict[str, int]
    top_districts: list[dict]
    noaa_events: list[dict]
    noaa_narrative: str | None
    fema: dict
    city_response: list[dict]
    sources: list[str]


class DistrictDemand(_Strict):
    district: str
    transport_requests: Range


class DemandEstimate(_Strict):
    scenario_id: str
    basis_storms: list[str]
    shelter_guests_per_day: Range | None
    transport_requests_storm_days: Range
    peak_customers_out: Range | None
    by_district: list[DistrictDemand]
    method: str
    caveat: str
    source: str


class ShelterSite(_Strict):
    id: str
    name: str
    capacity: int | None
    capacity_note: str
    source: str


class Assets(_Strict):
    shelters: list[ShelterSite]
    resources: list[dict]
    departments: dict[str, str]
    department_staff: dict
    shelter_history: list[dict]
    evacuee_shelters_nss: dict
    source: str


class DistrictAllocation(_Strict):
    district: str
    trucks: int = Field(ge=0)
    weight: float = Field(ge=0, le=1)


class ResponsePlan(_Strict):
    scenario_id: str
    trucks_available: int = Field(ge=0)
    truck_allocation: list[DistrictAllocation]
    shelters_open: list[str]
    shelters_closed: list[str]
    shelter_beds_known: int = Field(ge=0)
    shelters_unknown_capacity: list[str]
    shelter_demand: Range | None
    shelter_shortfall_at_median: int | None
    shelter_shortfall_at_high: int | None
    staff_note: str
    method: str
    source: str


class DistrictChange(_Strict):
    district: str
    trucks_before: int
    trucks_after: int
    change: int


class PlanDiff(_Strict):
    scenario_id: str
    baseline: dict
    what_if: dict
    district_changes: list[DistrictChange]
    shelter_beds_before: int
    shelter_beds_after: int
    shelter_shortfall_at_median_before: int | None
    shelter_shortfall_at_median_after: int | None
    source: str


CONTRACTS = {
    "get_storm_alert": StormAlert,
    "find_similar_storms": SimilarStorms,
    "get_storm_impacts": StormImpacts,
    "estimate_demand": DemandEstimate,
    "query_assets": Assets,
    "plan_response": ResponsePlan,
    "diff_plans": PlanDiff,
    "get_enso_context": EnsoContext,
    "retrieve_guidance": Guidance,
}
