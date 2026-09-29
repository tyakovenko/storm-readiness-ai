# Data contract: what each agent tool returns

The agent, trust layer and UI only depend on these shapes. How you compute them is up to you. The code version is [`backend/agent/contracts.py`](../backend/agent/contracts.py); every tool output is validated against it at runtime, so a mismatch fails loudly instead of quietly confusing the model.

**How to plug in real data:** replace the function body in `backend/agent/tools.py` (or the constants in `stub_data.py`) and keep the keys. Run `cd backend && .venv/bin/pytest -q`; `test_stub_outputs_meet_contract` tells you which field is off.

**Rules that apply everywhere**

| Rule | Why |
|---|---|
| County FIPS is a **5-character zero-padded string** (`"01001"`, not `1001`) | EAGLE-I `fips_code` can load as an int and lose the leading zero; joins to NRI/SVI then fail silently |
| Outage predictions are `{low, median, high}` in **percent (0–100)**, `low ≤ median ≤ high` | Quantile XGBoost can cross; the contract rejects crossed quantiles |
| Every output has a `source` string | Feeds the Sources panel (MVP requirement) |
| Every storm-dependent output has `advisory_number` | Trust layer blocks answers that mix advisories (stale data) |
| New field? Add it to `contracts.py` + this table first | Contracts use `extra="forbid"` so they can't go stale |

## Tools → data sources (from the Data Strategy doc)

| Tool | Key fields | Source |
|---|---|---|
| `get_advisory` | `storm_id` (ATCF, e.g. `AL102023`), `storm_name`, `basin` (`AL`/`EP`), `advisory_number`, `issued_utc`, `category`, `max_wind_kt`, `lead_time_to_landfall_h`, `forecast_landfall` | Historical NHC forecast/advisory (Source 2) for replay. **Not HURDAT2**, which is post-storm best track and would leak the future |
| `generate_scenarios` | `n_scenarios`, `lead_time_h`, `landfall_spread_nm`, `pct_scenarios_landfall_west_of_forecast` | NHC advisory + historical forecast errors (Workstream B, upgrade) |
| `get_enso_context` | `season` (e.g. `JAS`), `year`, `oni_c`, `phase`, `strength` | NOAA CPC ONI (Source 5) |
| `predict_impact` | per county: `fips`, `name`, `state`, `risk_tier` (green/yellow/orange/red), `pct_customers_out{low,median,high}`, `customers_served`, `why[]`; plus `model_version` | Target = **peak % customers out** per county over the storm window = max EAGLE-I `sum` ÷ MCC customers (Source 3). Features: HURDAT2 wind/track, NRI, SVI, ONI. `why` = top feature importances in plain words |
| `solve_staging` | `allocations[]` (`truckloads_needed/assigned/unmet` per county), `shelter_beds_available`, `shelter_demand_estimate`, `shelter_bed_shortfall`, `shelter_demand_assumption`, `method` | Workstream B optimizer (or highest-need-first). Shelter beds = sum of ESF #6 `evacuation_capacity` of open shelters |
| `diff_plans` | `county_changes[]`, before/after for unmet truckloads, beds, shortfall | Computed from two `solve_staging` runs; no new data |
| `find_analogs` | `storm`, `year`, `enso_phase`, `similarity` (0–1), `peak_pct_customers_out_median` | HURDAT2 + ONI; outages from EAGLE-I (so only 2014–2022 analogs have outage numbers) |
| `query_assets` | shelters: `id`, `name`, `county_fips`, `lat`, `lon`, `evacuation_capacity`, `post_impact_capacity`, `status`, `generator`, `wheelchair_accessible`, `pets_allowed`, `in_surge_zone` (booleans may be `null` = unknown) | FEMA ESF #6 National Shelter System (Source 7) |
| `retrieve_guidance` | `snippets[]` | FEMA / Ready.gov (retrieval index pending) |

## Still open on the data side (affects the contract)

- **Target definition** (Data Strategy action item 3): the contract assumes *peak % customers out per county over the storm window*. If the team picks something else (e.g. customer-hours), `pct_customers_out` changes name and the UI copy changes.
- **Geography** (action item 1): `basin` allows `AL` and `EP`. If we go Atlantic/Gulf only, narrow it to `AL`.
- **EAGLE-I coverage:** `coverage_history.csv` says how much of each state EAGLE-I saw per year. Low-coverage county-years should be dropped or flagged before training, or the model learns "no outage" where there was just no data.
- **Truckloads needed per county** are made up in the stub. The real demand model (outage × population × rate) is Workstream B's call.
