"""Input feature schema and transformation for the Outage Predictive Model."""

from dataclasses import dataclass, field
import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "max_wind_kt",
    "gust_wind_kt",
    "dist_to_track_nm",
    "forward_speed_kt",
    "quadrant_right",
    "population_log",
    "customers_served_log",
    "tree_canopy_pct",
    "nri_risk_score",
    "nri_eal_building_log",
    "svi_overall",
    "oni_anomaly",
    "lead_time_h",
]


@dataclass
class CountyFeatures:
    """Per-county raw input data for storm outage prediction."""
    fips: str
    name: str
    state: str
    max_wind_kt: float
    dist_to_track_nm: float
    gust_wind_kt: float | None = None
    forward_speed_kt: float = 12.0
    quadrant_right: int = 1
    population: int = 50000
    customers_served: int = 25000
    tree_canopy_pct: float = 40.0
    nri_risk_score: float = 25.0
    nri_eal_building: float = 500000.0
    svi_overall: float = 0.50
    oni_anomaly: float = 0.0
    lead_time_h: float = 48.0

    def __post_init__(self):
        # Guarantee 5-digit zero-padded FIPS code
        if not isinstance(self.fips, str) or len(self.fips) != 5:
            self.fips = str(self.fips).zfill(5)
        if self.gust_wind_kt is None:
            # Standard hurricane gust factor is ~1.25x sustained wind
            self.gust_wind_kt = round(self.max_wind_kt * 1.25, 1)


def features_to_dataframe(county_features: list[CountyFeatures]) -> pd.DataFrame:
    """Transform list of CountyFeatures dataclasses into model-ready DataFrame."""
    rows = []
    for c in county_features:
        rows.append({
            "max_wind_kt": float(c.max_wind_kt),
            "gust_wind_kt": float(c.gust_wind_kt if c.gust_wind_kt is not None else c.max_wind_kt * 1.25),
            "dist_to_track_nm": float(c.dist_to_track_nm),
            "forward_speed_kt": float(c.forward_speed_kt),
            "quadrant_right": int(c.quadrant_right),
            "population_log": float(np.log1p(max(0, c.population))),
            "customers_served_log": float(np.log1p(max(0, c.customers_served))),
            "tree_canopy_pct": float(c.tree_canopy_pct),
            "nri_risk_score": float(c.nri_risk_score),
            "nri_eal_building_log": float(np.log1p(max(0, c.nri_eal_building))),
            "svi_overall": float(c.svi_overall),
            "oni_anomaly": float(c.oni_anomaly),
            "lead_time_h": float(c.lead_time_h),
        })
    return pd.DataFrame(rows, columns=FEATURE_COLUMNS)
