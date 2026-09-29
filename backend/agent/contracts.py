"""Output contracts: the shape every tool must return.

This is the handshake with the data (A) and optimization (B) workstreams.
Real engines can compute however they like; what they hand the agent must
validate here. run_tool() validates every output, so a shape drift fails
loudly at the tool call instead of silently confusing the LLM or the UI.

Field -> data source mapping lives in docs/data-contract.md.

extra="forbid": a new field must be added here (and to the doc) first, so the
contract never goes stale.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FIPS = Field(pattern=r"^\d{5}$", description="5-digit county FIPS as a string (zero-padded)")
RiskTier = Literal["green", "yellow", "orange", "red"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Quantiles(_Strict):
    low: float = Field(ge=0, le=100)
    median: float = Field(ge=0, le=100)
    high: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _ordered(self):
        # Quantile XGBoost can cross; enforce order instead of assuming it.
        if not self.low <= self.median <= self.high:
            raise ValueError(f"quantiles out of order: {self.low}/{self.median}/{self.high}")
        return self


class Advisory(_Strict):
    storm_id: str = Field(description="ATCF id, e.g. AL102023; joins to HURDAT2")
    storm_name: str
    basin: Literal["AL", "EP"]
    advisory_number: int
    issued_utc: str
    category: int = Field(ge=0, le=5, description="0 = tropical storm")
    max_wind_kt: int
    lead_time_to_landfall_h: float = Field(ge=0)
    forecast_landfall: str
    source: str


class Scenarios(_Strict):
    advisory_number: int
    n_scenarios: int
    lead_time_h: float
    landfall_spread_nm: float = Field(ge=0)
    pct_scenarios_landfall_west_of_forecast: float = Field(ge=0, le=100)
    method: str
    source: str


class EnsoContext(_Strict):
    season: str = Field(description="CPC 3-month season code, e.g. JAS")
    year: int
    oni_c: float = Field(description="ONI anomaly, deg C")
    phase: Literal["El Niño", "La Niña", "Neutral"]
    strength: Literal["weak", "moderate", "strong", "very strong", "n/a"]
    source: str


class CountyImpact(_Strict):
    fips: str = FIPS
    name: str
    state: str = Field(pattern=r"^[A-Z]{2}$")
    risk_tier: RiskTier
    pct_customers_out: Quantiles = Field(
        description="Peak % of customers without power over the storm window: EAGLE-I max(sum) / MCC")
    customers_served: int = Field(ge=0, description="MCC modeled county customers")
    why: list[str] = Field(min_length=1, description="Top drivers in plain words (feature importance)")


class Impact(_Strict):
    advisory_number: int
    model_version: str
    counties: list[CountyImpact]
    source: str


class Allocation(_Strict):
    county: str
    fips: str = FIPS
    truckloads_needed: int = Field(ge=0)
    truckloads_assigned: int = Field(ge=0)
    truckloads_unmet: int = Field(ge=0)


class StagingPlan(_Strict):
    advisory_number: int
    method: str
    staging_area: str
    trucks_available: int = Field(ge=0)
    allocations: list[Allocation]
    total_truckloads_unmet: int = Field(ge=0)
    shelters_open: list[str]
    shelters_closed: list[str]
    shelter_beds_available: int = Field(ge=0)
    shelter_demand_estimate: int = Field(ge=0)
    shelter_bed_shortfall: int = Field(ge=0)
    shelter_demand_assumption: str
    source: str

    @model_validator(mode="after")
    def _never_ships_more_than_it_has(self):
        assigned = sum(a.truckloads_assigned for a in self.allocations)
        if assigned > self.trucks_available:
            raise ValueError(f"assigned {assigned} truckloads but only {self.trucks_available} trucks")
        return self


class CountyChange(_Strict):
    county: str
    fips: str = FIPS
    truckloads_before: int
    truckloads_after: int
    change: int


class PlanDiff(_Strict):
    advisory_number: int
    baseline: dict
    what_if: dict
    county_changes: list[CountyChange]
    unmet_truckloads_before: int
    unmet_truckloads_after: int
    shelter_beds_before: int
    shelter_beds_after: int
    shelter_bed_shortfall_before: int
    shelter_bed_shortfall_after: int
    source: str


class Analog(_Strict):
    storm: str
    year: int
    enso_phase: Literal["El Niño", "La Niña", "Neutral"]
    similarity: float = Field(ge=0, le=1)
    peak_pct_customers_out_median: float = Field(ge=0, le=100)


class Analogs(_Strict):
    advisory_number: int
    analogs: list[Analog]
    source: str


class Shelter(_Strict):
    """FEMA ESF #6 National Shelter System fields (the subset we use)."""
    id: str
    name: str
    county_fips: str = FIPS
    lat: float
    lon: float
    evacuation_capacity: int = Field(ge=0)
    post_impact_capacity: int = Field(ge=0)
    status: str
    generator: bool | None = None
    wheelchair_accessible: bool | None = None
    pets_allowed: bool | None = None
    in_surge_zone: bool | None = None


class Assets(_Strict):
    shelters: list[Shelter]
    staging_area: str
    source: str


class Guidance(_Strict):
    snippets: list[str]
    source: str


CONTRACTS: dict[str, type[BaseModel]] = {
    "get_advisory": Advisory,
    "generate_scenarios": Scenarios,
    "get_enso_context": EnsoContext,
    "predict_impact": Impact,
    "solve_staging": StagingPlan,
    "diff_plans": PlanDiff,
    "find_analogs": Analogs,
    "query_assets": Assets,
    "retrieve_guidance": Guidance,
}
