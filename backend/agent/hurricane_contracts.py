"""Output contracts for the hurricane county template (hurricane_tools.py).

Same rules as the Dallas contracts: run_tool validates every output; a mismatch is an engine
bug that raises. Every estimate is a low/median/high range with its unit, so the trust layer can
require the range whenever the median is quoted.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import EnsoContext, Guidance, RiskTier  # noqa: F401


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelRange(_Strict):
    low: float
    median: float
    high: float
    unit: str

    @model_validator(mode="after")
    def _ordered(self):
        if not self.low <= self.median <= self.high:
            raise ValueError(f"range out of order: {self.low}, {self.median}, {self.high}")
        return self


class ForecastPoint(_Strict):
    tau_h: int
    valid_utc: str
    lat: float
    lon: float
    vmax_kt: float


class StormAlert(_Strict):
    advisory_id: str
    kind: Literal["replay", "live", "scenario"]
    headline: str
    county: str
    storm_name: str
    advisory_init_utc: str
    lead_time_h: float = Field(ge=0)
    forecast_closest_nm: float = Field(ge=0)
    forecast_vmax_at_closest_kt: float = Field(ge=0)
    forecast_wind_at_county_kt: float = Field(ge=0)
    right_of_track: bool
    forecast: list[ForecastPoint]
    in_training_data: bool
    note: str
    source: str


class PastStorm(_Strict):
    storm_id: str
    name: str
    year: int
    similarity: float = Field(ge=0, le=1)
    max_wind_kt_at_county: float
    dist_to_track_nm: float
    right_of_track: bool
    peak_customers_out: int
    peak_pct_customers: float
    outage_data_coverage: str


class SimilarStorms(_Strict):
    advisory_id: str
    county: str
    storms: list[PastStorm]
    caveat: str
    source: str


class ImpactEstimate(_Strict):
    advisory_id: str
    county: str
    fips: str
    risk_tier: RiskTier
    pct_customers_out: ModelRange
    customers_out: ModelRange
    customers_served: int
    why: list[str]
    model_run: str
    model_skill: dict = Field(description="held-out metrics from the training run (storms never seen)")
    inputs: dict
    caveat: str
    source: str


class StormImpacts(_Strict):
    storm_id: str
    name: str
    county: str
    max_wind_kt_at_county: float
    dist_to_track_nm: float
    peak_customers_out: int
    peak_pct_customers: float
    outage_data_coverage: str
    noaa_events: list[dict]
    fema: list[dict]
    sources: list[str]


class Shelter(_Strict):
    id: str
    name: str
    city: str | None
    evacuation_capacity: int | None
    post_impact_capacity: int | None
    pets: str | None
    ada: bool
    generator: bool
    in_surge_zone: bool
    in_100yr_floodplain: bool
    lat: float | None
    lon: float | None


class Assets(_Strict):
    county: str
    shelters_total: int
    evacuation_capacity_total: int
    safe_shelters: int = Field(description="outside surge zone and 100-yr floodplain")
    safe_evacuation_capacity: int
    pet_friendly: int
    with_generator: int
    largest: list[Shelter]
    gaps: list[dict]
    source: str


class ShelterPlan(_Strict):
    advisory_id: str
    county: str
    exclude_surge_and_floodplain: bool
    shelters_open: int
    shelters_closed: list[str]
    beds_available: int
    beds_with_pets: int
    beds_with_generator: int
    shelter_demand: str
    method: str
    source: str


class PlanDiff(_Strict):
    advisory_id: str
    county: str
    baseline: dict
    what_if: dict
    beds_before: int
    beds_after: int
    shelters_removed: list[str]
    source: str


CONTRACTS = {
    "get_storm_alert": StormAlert,
    "find_similar_storms": SimilarStorms,
    "estimate_impact": ImpactEstimate,
    "get_storm_impacts": StormImpacts,
    "query_assets": Assets,
    "plan_shelters": ShelterPlan,
    "diff_plans": PlanDiff,
    "get_enso_context": EnsoContext,
    "retrieve_guidance": Guidance,
}
