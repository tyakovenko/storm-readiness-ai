# Storm Readiness AI – Data Architecture & Cloud Sync

All raw training, validation, and geographic datasets for the Storm Readiness platform are hosted centrally in **Google Cloud Storage (GCS)** under the project:

- **GCP Project:** `uc3-storm-impact-intelligence`
- **GCS Bucket:** `gs://uc3-storm-impact-intelligence-data`
- **Prefix:** `gs://uc3-storm-impact-intelligence-data/raw/`

This keeps the Git repository lightweight while allowing all team members and cloud environments (Cloud Run, Vertex AI, Compute VMs) to access the exact same dataset directly.

---

## Directory Structure

```text
gs://uc3-storm-impact-intelligence-data/raw/
├── atcf/                          # NHC ATCF storm advisory and track forecast records
│   ├── aal*.dat / aal*.dat.gz     # Florence 2018, Ian 2022, Idalia 2023, Helene 2024, Milton 2024
│   └── aep092023.dat / .gz        # Otis 2023
├── census/                        # US Census Cartographic Boundary files
│   ├── counties/                  # 2025 US County 500k shapefile suite (.shp, .dbf, .shx, etc.)
│   ├── all/                       # All US geographic level shapefile packages
│   └── cb_2025_us_all_500k.zip    # Full census cartographic archive
├── census/EAGLE I/                # ORNL / DOE EAGLE-I power outage records
│   ├── eaglei_outages_2024.zip    # 2024 county-level power outage data
│   ├── eaglei_outages_2025.csv    # 2025 county-level power outage data
│   ├── eaglei_county_customers_fall_2025.csv # County customer counts
│   ├── 24237376.zip               # Complete 2014-2025 historical archive
│   └── README*.txt                # Documentation and data dictionary
├── hurdat2/                       # NOAA Best Track database
│   ├── hurdat2_atlantic.txt       # Atlantic basin historical tracks
│   └── hurdat2_pacific.txt        # Northeast/Central Pacific historical tracks
├── nri/                           # FEMA National Risk Index
│   └── nri_counties.csv           # 3,232 counties, 467 risk/loss attributes (HRCN_EALB, HRCN_RISKS, etc.)
├── oni/                           # NOAA Climate Prediction Center
│   └── oni.ascii.txt              # Oceanic Niño Index (ENSO phases)
└── svi/                           # CDC / ATSDR Social Vulnerability Index
    └── SVI_2020_US_COUNTY.csv     # County vulnerability metrics
```

---

## Quick Start: Using the Cloud Sync Utility

We provide `data/sync_cloud_data.py` to synchronize data between your local machine and GCS. It automatically detects and uses `gcloud storage` or `gsutil`.

### 1. Check sync status
Compare which files you have locally versus what is stored in Google Cloud:
```bash
python data/sync_cloud_data.py status
```

### 2. Pull data to your local machine
Download all datasets:
```bash
python data/sync_cloud_data.py pull
```

Or pull only a specific dataset you need:
```bash
python data/sync_cloud_data.py pull --dataset nri
python data/sync_cloud_data.py pull --dataset svi
python data/sync_cloud_data.py pull --dataset hurdat2
python data/sync_cloud_data.py pull --dataset eaglei
python data/sync_cloud_data.py pull --dataset atcf
python data/sync_cloud_data.py pull --dataset census
```

### 3. List all files in the bucket
```bash
python data/sync_cloud_data.py list
```

---

## Using Cloud Data in Python & Notebooks

You can use the helper function `ensure_data` in your scripts, notebooks, or backend modules. If the file is not yet cached locally, it will download it on demand from GCS:

```python
from data.sync_cloud_data import ensure_data
import pandas as pd

# Automatically downloads from gs://uc3-storm-impact-intelligence-data/ if not cached locally:
nri_path = ensure_data("raw/nri/nri_counties.csv")
df_nri = pd.read_csv(nri_path)

print(f"Loaded {len(df_nri)} counties from {nri_path}")
```

---

## Direct `gcloud` Command Alternatives

If you prefer using the `gcloud` CLI directly:

```bash
# Pull all raw data locally:
gcloud storage cp -r "gs://uc3-storm-impact-intelligence-data/raw/*" data/raw/

# Pull only NRI county data:
gcloud storage cp "gs://uc3-storm-impact-intelligence-data/raw/nri/nri_counties.csv" data/raw/nri/
```
