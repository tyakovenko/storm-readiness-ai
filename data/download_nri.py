import requests, pandas as pd
from pathlib import Path

URL = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Counties/FeatureServer/0/query"
rows, offset, page = [], 0, 2000
while True:
    r = requests.get(URL, params={"where": "1=1", "outFields": "*", "f": "json",
                                  "returnGeometry": "false", "orderByFields": "OBJECTID",
                                  "resultOffset": offset, "resultRecordCount": page}, timeout=120)
    r.raise_for_status()
    feats = r.json().get("features", [])
    rows += [f["attributes"] for f in feats]
    print(f"fetched {len(rows)} rows")
    if len(feats) < page: break
    offset += page

df = pd.DataFrame(rows)
Path("data/raw/nri").mkdir(parents=True, exist_ok=True)
df.to_csv("data/raw/nri/nri_counties.csv", index=False)
print(len(df), "counties,", len(df.columns), "columns")
print("Hurricane columns:", [c for c in df.columns if c.startswith("HRCN")][:10])
