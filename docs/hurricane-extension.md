# Hurricane extension: plan and open issues

Branch `hurricane-extension`, from `c/dallas` (2026-10-04). Goal: a second agent for hurricanes,
deployed as its own Cloud Run service (no UI toggle for now), built on **national** data so it
works for any coastal county, with an optional **county deep dive** like the Dallas build.

## 1. What exists today

| Piece | State |
|---|---|
| Hurricane agent | Plain loop (`agent/loop.py`) + ADK scaffold (`storm_agent/`). Runs with `AGENT_DOMAIN=hurricane` |
| Hurricane tools | **Stub data** (`agent/stub_data.py`): fictional storm, 4 Florida counties, made-up shelters |
| Trust layer | Works for hurricanes (`trust.HURRICANE` profile); planted-error eval 37/37, 0 false alarms |
| Raw data in GCS | ATCF advisories (Florence 2018, Ian 2022, Idalia 2023, Helene 2024, Milton 2024, Otis 2023), HURDAT2 (Atlantic + Pacific), FEMA NRI, CDC SVI, NOAA ONI, Census shapes, EAGLE-I full archive (2014–2025, ~12 GB unfiltered) |
| Processed hurricane tables | **None** |
| Impact model (XGBoost) | Trained on **synthetic** data; see §2 |

## 2. Issue: the XGBoost model is trained on synthetic data

Checked 2026-10-04 in four ways:

1. **No real training table exists**, neither in `gs://uc3-storm-impact-intelligence-data` (raw files only) nor in the repo.
2. **No code builds one.** Nothing joins HURDAT2 tracks and EAGLE-I outages into the 13 features plus a label.
3. **`train.py` falls back to synthetic data.** With no `--data`, it logs "Upstream ETL in progress: generating calibrated bootstrap dataset" and trains on `synthetic_bootstrap.py` output.
4. **The saved model fits the synthetic data closely:** median-model MAE 3.5 points on a 0–100% scale.

Re-training with the defaults did **not** reproduce the artifact exactly (predictions differ by up to 11–19 points), probably because the generator or settings changed in the "re-calibrate" commit (ed605c9). To confirm with Kanupriya.

**Misleading label:** `outage_model.py` reports its source as "trained on EAGLE-I, HURDAT2, FEMA NRI, CDC SVI". Until a real retrain exists, it should say synthetic. The current pipeline also falls back to stub data silently, with only a WARNING log (issue #3).

### What a real retrain needs

The model code, the 13 inputs and the low/median/high outputs stay the same. The work is building the training table (one row per storm × county) and then running `python -m models.train --data <table>`.

| Feature / label | Source | In GCS? | Work |
|---|---|---|---|
| **label:** peak % customers out | EAGLE-I max(customers_out) over storm window ÷ county customers (MCC / `eaglei_county_customers`) | yes | Stream the 12 GB archive per year, filter to storm windows and counties near the track (same streaming filter used for Dallas) |
| max_wind_kt, gust_wind_kt | HURDAT2 track + a wind-decay / radius model to each county centroid | yes (tracks) | Implement wind at county: distance-decay inland (Kaplan-DeMaria) or a simple parametric profile |
| dist_to_track_nm, forward_speed_kt, quadrant_right | HURDAT2 track geometry vs Census county centroids | yes | Geometry only |
| population_log, customers_served_log | Census / EAGLE-I MCC | yes | Join on FIPS |
| nri_risk_score, nri_eal_building_log | FEMA NRI | yes | Join on FIPS |
| svi_overall | CDC SVI 2020 | yes | Join on FIPS |
| oni_anomaly | NOAA ONI by storm season | yes | Lookup |
| **tree_canopy_pct** | USFS / NLCD Tree Canopy Cover | **no** | Download the county zonal stats, or drop the feature |
| **lead_time_h** | n/a for historical best tracks | n/a | Decide: set it to 0 in training (the model learns impact, lead time drives uncertainty elsewhere), or simulate it from ATCF advisories for the 6 storms we have |

Scale: EAGLE-I covers 2014–2025, which is about 30–40 US landfalling storms × the counties within ~150 nm of the track, so a few thousand rows. That's enough for quantile XGBoost if validated with the existing held-out-storm split.

### Data staged for the retrain (2026-10-05)

`gs://uc3-storm-impact-intelligence-data/raw/national/` (pull: `python data/sync_cloud_data.py pull --dataset national`; details in its `MANIFEST.md`):

| Path | What | Status |
|---|---|---|
| `noaa_storm_events/` | NOAA Storm Events details 2000–2026, all states | done (27 files) |
| `atcf_archive_2014_2025/` | NHC ATCF a-decks (forecasts) + b-decks (best tracks), Atlantic | done (430 files) |
| `fema_nss/` | FEMA National Shelter System, all 71,857 shelters | done; 2,205 rows have lat/lon swapped, fips_code blank |
| `openfema/` | Disaster declarations + Public Assistance funded projects (national bulk CSV) | done |
| `tree_canopy/` | Mean tree canopy % per CONUS county (USFS NLCD TCC ImageServer) | in progress |

EAGLE-I stays as the 11.6 GB archive (`raw/census/EAGLE I/24237376.zip`). Direct-to-bucket transfer of the per-year files isn't possible: figshare redirects to a 10-second S3 link, and Storage Transfer Service would need its API enabled + an IAM grant. The training-table builder should stream per-year CSVs and keep only storm windows near each track (as done for Dallas). Running that on GCP needs a service account with bucket write access (IAM grant by Taya).

## 3. Other open issues to carry over

- `storm_agent/agent.py` default `GEMINI_MODEL=gemini-flash-latest` 404s on Vertex. Use `gemini-3.8-flash` with `GOOGLE_CLOUD_LOCATION=global`.
- The hurricane agent isn't on ADK + the trust wrapper yet. Port it the way `agent/dallas_adk.py` was done.
- The hurricane loop calls Gemini through LiteLLM. Check `vertex_ai/...` works with ADC on Cloud Run, or move it to ADK.
- Real shelters: FEMA NSS (`gis.fema.gov/arcgis/rest/services/NSS/FEMA_NSS/MapServer/5`). Query by `county_parish` + `state`; `fips_code` is blank in the layer.
- Scenarios from real advisories: ATCF files give the official forecast per advisory, which supports a replay mode ("Idalia, advisory 14") before live NHC.
- Staging assets (trucks, staging areas) have no national dataset. They're county or state specific, so they belong in the county deep dive (§4).

## 4. Scaling: national baseline + county deep dive

### Is it technically possible?

**Yes, as two separate parts:**

1. **National baseline (every coastal county, same tools).** Only uniform national datasets: HURDAT2/ATCF, EAGLE-I, NRI, SVI, ONI, FEMA NSS shelters, FEMA PA/declarations, NOAA Storm Events (with narratives), Census. Retrained XGBoost for impact ranges. This is the current hurricane agent with real data instead of stub, and it scales because nothing is city-specific.

2. **County deep dive = an offline research pipeline, not a live chat feature.** For one county it automates what was done by hand for Dallas, and outputs a **county pack** in the same shape as `backend/dallas/sources.py` + processed tables:
   - **Discover:** open-data portals through the Socrata catalog API (`api.us.socrata.com/api/catalog/v1?domains=...`) and ArcGIS Hub search; Legistar for council briefings and after-action reports; budget book PDFs; local 311.
   - **Extract:** pull figures with an exact quote and source per fact (staff by department, trucks, shelters and capacities, past-storm response numbers). Map local 311 request types to sectors (LLM-assisted, then reviewed).
   - **Validate:** cross-check against independent sources, the way the Dallas build was pinned to Socrata API counts, NWS hours below freezing and DMN snowfall. Unknowns stay `None`.
   - **Review:** a person approves the pack. Only approved packs reach the live agent (`processed/<fips>/`).

### Why the research must not run live in chat

Research outputs are candidate facts, not data. In the Dallas build alone:

- The "payroll registry" turned out to be city-wide totals, not per-employee.
- Hourly ASOS precipitation over-read sleet (11 in vs 0.91 in).
- The FEMA NSS `fips_code` field was blank.
- Ready.gov blocked automated fetches.
- 32°F vs <32°F changed the hours-below-freezing count from 78 to 58.

A live agent that trusted its own research would pass these through, and the trust layer only checks that answers match tool outputs, not that tool outputs are true. Hence the offline pipeline plus human approval.

### Realism and effort

| Part | Automatable? | Notes |
|---|---|---|
| National baseline tables | Fully | Same code for every county |
| Portal discovery (Socrata / ArcGIS / Legistar) | Mostly | APIs exist; coverage varies a lot by city, and many counties have no portal (pack records the gaps) |
| 311 type → sector mapping | Partly | Every city names types differently; LLM proposal + review |
| PDF extraction (memos, budgets, AARs) | Partly | Works with citations; error-prone on tables, so needs review |
| Cross-validation | Partly | Needs a second independent source per key number, which often doesn't exist |

Rough cost per county: about 30–60 min of agent time plus 1–2 h of human review, versus most of a day by hand for Dallas. It's a complex agent (multi-step research, extraction, validation, review queue) but uses standard pieces: ADK with search/fetch tools, structured extraction to a pydantic schema, and the existing contract + trust machinery for the output.

### Suggested order

1. **Real training table + retrain** (§2), with Kanupriya. This is the critical path, since without it the impact numbers are fiction.
2. National hurricane tools on real data (NSS shelters, ATCF replay, FEMA/NOAA history), ported to ADK + trust wrapper; deploy as a second Cloud Run service (`AGENT_DOMAIN=hurricane`).
3. County deep-dive pipeline, prototyped on one coastal county and checked against the Dallas pack format.
