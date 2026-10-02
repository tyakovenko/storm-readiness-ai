"""Bootstrap training data generator for Quantile XGBoost model.

Generates realistic hurricane outage samples based on meteorological wind decay
and physical vulnerability relationships, enabling full training and testing
prior to final upstream EAGLE-I joined tables.
"""

import numpy as np
import pandas as pd
from .schema import FEATURE_COLUMNS


def generate_bootstrap_dataset(n_samples: int = 1500, random_seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    """Generate physically-realistic training dataset for outage model."""
    rng = np.random.default_rng(random_seed)

    # 1. Hazard features
    max_wind_kt = rng.uniform(20.0, 130.0, size=n_samples)
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
    oni = rng.choice([-1.5, -0.8, 0.0, 0.8, 1.5, 2.0], size=n_samples)
    lead_time_h = rng.uniform(12.0, 96.0, size=n_samples)

    # 3. Target: Peak % of customers out (0 - 100)
    # Wind force scales with velocity squared (dynamic pressure)
    wind_factor = (np.maximum(0, max_wind_kt - 25.0) / 75.0) ** 2.2
    dist_attenuation = np.exp(-dist_to_track_nm / 65.0)
    tree_factor = 1.0 + (tree_canopy / 100.0) * 0.4
    quadrant_factor = 1.0 + quadrant_right * 0.25
    svi_factor = 1.0 + (svi - 0.5) * 0.2

    base_outage = 100.0 * (wind_factor * dist_attenuation * tree_factor * quadrant_factor * svi_factor)
    noise = rng.normal(0.0, 4.0, size=n_samples)
    peak_pct_out = np.clip(base_outage + noise, 0.0, 100.0)

    # Build DataFrame
    df = pd.DataFrame({
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
        "oni_anomaly": oni,
        "lead_time_h": lead_time_h,
    }, columns=FEATURE_COLUMNS)

    y = pd.Series(peak_pct_out, name="pct_customers_out")
    return df, y
