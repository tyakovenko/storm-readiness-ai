# Data Sources

This file records the sources, download scripts, and retrieval dates for datasets used in the storm readiness outage model and planning pipeline.

All raw datasets are centralized in Google Cloud Storage for team-wide access:
- **GCS Bucket:** `gs://uc3-storm-impact-intelligence-data/raw/`
- **Sync Tool:** `python data/sync_cloud_data.py pull` (or `--dataset <name>`)

---

## 1. FEMA National Risk Index (NRI) Counties

- **Dataset:** FEMA National Risk Index – Counties (`NRI_Counties_Prod`, Layer 0)
- **Service Endpoint:** `https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Counties/FeatureServer/0`
- **Query Endpoint:** `https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Counties/FeatureServer/0/query`
- **Download Script:** `data/download_nri.py`
- **Output Destination:** `data/raw/nri/nri_counties.csv`
- **Last Downloaded / Verified:** 2026-10-01
- **Key Details:**
  - 3,232 county records and 467 attributes fetched using pagination (2,000 records per page).
  - Join key: `STCOFIPS` (5-character FIPS code).
  - Includes hurricane risk and loss metrics such as `HRCN_EALB` (Expected Annual Loss - Building), `HRCN_RISKS` (Risk Score), `HRCN_EVNTS`, `HRCN_AFREQ`, `HRCN_EXPB`, and overall composite scores.

---

## 2. Other Core Outage Model Inputs

- **EAGLE-I Outages (ORNL / DOE):** `data/raw/census/EAGLE I/`
  - County-level power outage history for target labels (`pct_customers_out`).
- **NOAA HURDAT2 Best Tracks:** `data/raw/hurdat2/`
  - Historical storm tracks and intensities for training labels and analog matching.
- **NOAA CPC ONI (Oceanic Niño Index):** `data/raw/oni/oni.ascii.txt`
  - ENSO climate cycle context (`get_enso_context`).
- **US Census Cartographic Boundaries & Demographics:** `data/raw/census/`
  - County boundary geometries, population, and housing exposure data.
- **Automated Tropical Cyclone Forecasting (ATCF):** `data/raw/atcf/`
  - Historical advisory and track forecast records.
