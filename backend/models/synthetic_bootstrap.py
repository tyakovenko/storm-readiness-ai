"""Bootstrap training data generator for Quantile XGBoost model.

Generates realistic hurricane outage samples based on meteorological wind decay
and physical vulnerability relationships, grouped by storm event and year (2014-2024),
enabling temporal period and held-out storm validation.
"""

import numpy as np
import pandas as pd
from .schema import FEATURE_COLUMNS

HISTORICAL_STORMS = [
    # storm_id, storm_name, year, oni_anomaly
    ("AL142016", "Matthew", 2016, -0.7),
    ("AL092017", "Harvey", 2017, -0.1),
    ("AL112017", "Irma", 2017, -0.6),
    ("AL062018", "Florence", 2018, 0.5),   # Dev storm
    ("AL142018", "Michael", 2018, 0.8),    # Benchmark storm (Cat 5, El Niño developing)
    ("AL052019", "Dorian", 2019, 0.3),
    ("AL132020", "Laura", 2020, -1.0),
    ("AL192020", "Sally", 2020, -1.1),
    ("AL092021", "Ida", 2021, -0.8),
    ("AL092022", "Ian", 2022, -1.0),       # Benchmark storm (La Niña control)
    ("AL172022", "Nicole", 2022, -0.9),
    ("AL102023", "Idalia", 2023, 1.8),     # Benchmark storm (Strong El Niño)
    ("EP092023", "Hilary", 2023, 1.8),     # Benchmark storm (Pacific Strong El Niño)
    ("AL092024", "Helene", 2024, 0.1),
    ("AL142024", "Milton", 2024, -0.2),
]


def generate_bootstrap_dataset(
    n_samples: int = 1500,
    random_seed: int = 42,
) -> tuple[pd.DataFrame, pd.Series]:
    """Generate physically-realistic training dataset for outage model grouped by storm and period."""
    rng = np.random.default_rng(random_seed)

    # Assign samples to storms
    storm_indices = rng.integers(0, len(HISTORICAL_STORMS), size=n_samples)
    storm_ids = [HISTORICAL_STORMS[i][0] for i in storm_indices]
    storm_names = [HISTORICAL_STORMS[i][1] for i in storm_indices]
    years = [HISTORICAL_STORMS[i][2] for i in storm_indices]
    onis = np.array([HISTORICAL_STORMS[i][3] for i in storm_indices], dtype=float)

    # 1. Hazard features
    max_wind_kt = rng.uniform(25.0, 135.0, size=n_samples)
    gust_wind_kt = max_wind_kt * rng.uniform(1.15, 1.35, size=n_samples)
    dist_to_track_nm = rng.exponential(scale=45.0, size=n_samples) + rng.uniform(5.0, 20.0, size=n_samples)
    dist_to_track_nm = np.clip(dist_to_track_nm, 2.0, 250.0)
    forward_speed_kt = rng.uniform(8.0, 24.0, size=n_samples)
    quadrant_right = rng.choice([0, 1], p=[0.45, 0.55], size=n_samples)

    # 2. Exposure & Vulnerability
    pop = rng.lognormal(mean=10.5, sigma=1.2, size=n_samples)
    pop = np.clip(pop, 5000, 1200000)
    cust = pop * rng.uniform(0.40, 0.55, size=n_samples)
    tree_canopy = rng.uniform(10.0, 80.0, size=n_samples)
    nri_risk = rng.uniform(5.0, 85.0, size=n_samples)
    nri_eal = rng.lognormal(mean=13.0, sigma=1.5, size=n_samples)
    svi = rng.uniform(0.05, 0.95, size=n_samples)
    lead_time_h = rng.uniform(12.0, 96.0, size=n_samples)

    # 3. Target: Peak % of customers out (0 - 100)
    wind_factor = (np.maximum(0, max_wind_kt - 25.0) / 75.0) ** 2.2
    dist_attenuation = np.exp(-dist_to_track_nm / 65.0)
    tree_factor = 1.0 + (tree_canopy / 100.0) * 0.4
    quadrant_factor = 1.0 + quadrant_right * 0.25
    svi_factor = 1.0 + (svi - 0.5) * 0.2

    base_outage = 100.0 * (wind_factor * dist_attenuation * tree_factor * quadrant_factor * svi_factor)
    noise = rng.normal(0.0, 4.0, size=n_samples)
    peak_pct_out = np.clip(base_outage + noise, 0.0, 100.0)

    # Build DataFrame including period and storm metadata
    df = pd.DataFrame({
        "storm_id": storm_ids,
        "storm_name": storm_names,
        "year": years,
        "max_wind_kt": max_wind_kt,
        "gust_wind_kt": gust_wind_kt,
        "dist_to_track_nm": dist_to_track_nm,
        "forward_speed_kt": forward_speed_kt,
        "quadrant_right": quadrant_right,
        "population_log": np.log1p(pop),
        "customers_served_log": np.log1p(cust),
        "tree_canopy_pct": tree_canopy,
        "nri_risk_score": nri_risk,
        "nri_eal_building_log": np.log1p(nri_eal),
        "svi_overall": svi,
        "oni_anomaly": onis,
        "lead_time_h": lead_time_h,
    })

    y = pd.Series(peak_pct_out, name="pct_customers_out")
    return df, y
