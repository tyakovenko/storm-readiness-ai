"""Quantile XGBoost Outage Impact Model.

Predicts county-level peak % customers out (low, median, high quantiles)
from storm wind fields, track distance, Census exposure, FEMA NRI, CDC SVI,
and NOAA ONI El Niño context.
"""

from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Literal
import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

from .schema import CountyFeatures, FEATURE_COLUMNS, features_to_dataframe

log = logging.getLogger(__name__)

RiskTier = Literal["green", "yellow", "orange", "red"]


class QuantileOutageModel:
    """Three-headed Quantile XGBoost regressor predicting low, median, and high peak outage %."""

    def __init__(
        self,
        alpha_low: float = 0.10,
        alpha_median: float = 0.50,
        alpha_high: float = 0.90,
        n_estimators: int = 120,
        max_depth: int = 4,
        learning_rate: float = 0.08,
        version: str = "xgboost-quantile-v1.0",
    ):
        self.alpha_low = alpha_low
        self.alpha_median = alpha_median
        self.alpha_high = alpha_high
        self.version = version
        self.is_fitted = False

        self.model_low = xgb.XGBRegressor(
            objective="reg:quantileerror",
            quantile_alpha=self.alpha_low,
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=42,
        )
        self.model_median = xgb.XGBRegressor(
            objective="reg:quantileerror",
            quantile_alpha=self.alpha_median,
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=42,
        )
        self.model_high = xgb.XGBRegressor(
            objective="reg:quantileerror",
            quantile_alpha=self.alpha_high,
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=42,
        )

    def fit(self, X: pd.DataFrame | np.ndarray, y: pd.Series | np.ndarray) -> "QuantileOutageModel":
        """Fit all 3 quantile regressors on training features and outage labels (0-100%)."""
        if isinstance(X, pd.DataFrame):
            X_mat = X[FEATURE_COLUMNS].to_numpy()
        else:
            X_mat = np.asarray(X)
        y_arr = np.asarray(y, dtype=float)

        self.model_low.fit(X_mat, y_arr)
        self.model_median.fit(X_mat, y_arr)
        self.model_high.fit(X_mat, y_arr)
        self.is_fitted = True
        return self

    def predict_quantiles(self, df_features: pd.DataFrame) -> np.ndarray:
        """Predict low, median, high quantiles with guaranteed monotonicity.

        Returns array of shape (N, 3) where columns are [low, median, high] in % [0, 100].
        """
        if not self.is_fitted:
            raise RuntimeError("QuantileOutageModel must be fitted or loaded before predicting.")

        X_mat = df_features[FEATURE_COLUMNS].to_numpy()
        pred_low = self.model_low.predict(X_mat)
        pred_med = self.model_median.predict(X_mat)
        pred_high = self.model_high.predict(X_mat)

        # Enforce valid range [0, 100] %
        pred_low = np.clip(pred_low, 0.0, 100.0)
        pred_med = np.clip(pred_med, 0.0, 100.0)
        pred_high = np.clip(pred_high, 0.0, 100.0)

        # Enforce quantile monotonicity: low <= median <= high
        stacked = np.column_stack([pred_low, pred_med, pred_high])
        ordered = np.sort(stacked, axis=1)
        return ordered

    @staticmethod
    def assign_risk_tier(pct_median: float, svi_overall: float, max_wind_kt: float) -> RiskTier:
        """Rule-based risk score cut into 4 tiers (green, yellow, orange, red)."""
        if pct_median >= 40.0 or (pct_median >= 25.0 and svi_overall >= 0.65) or max_wind_kt >= 85.0:
            return "red"
        elif pct_median >= 20.0 or (pct_median >= 12.0 and svi_overall >= 0.50):
            return "orange"
        elif pct_median >= 5.0 or max_wind_kt >= 34.0:
            return "yellow"
        else:
            return "green"

    @staticmethod
    def explain(county: CountyFeatures, pct_median: float) -> list[str]:
        """Explain why an area was identified as high risk in plain language."""
        drivers = []
        if county.max_wind_kt >= 64:
            drivers.append(f"Hurricane-force winds forecast ({int(county.max_wind_kt)} kt)")
        elif county.max_wind_kt >= 34:
            drivers.append(f"Tropical storm-force winds forecast ({int(county.max_wind_kt)} kt)")

        if county.dist_to_track_nm <= 35:
            drivers.append(f"Direct proximity to storm track ({int(county.dist_to_track_nm)} nm from eye)")
        elif county.dist_to_track_nm <= 70 and county.quadrant_right:
            drivers.append("Located in higher-hazard right-front quadrant")

        if county.tree_canopy_pct >= 45:
            drivers.append(f"Elevated tree canopy ({int(county.tree_canopy_pct)}%) increasing power line strike risk")

        if county.svi_overall >= 0.70:
            drivers.append(f"High social vulnerability index (CDC SVI {county.svi_overall:.2f})")

        if county.nri_risk_score >= 30:
            drivers.append("Elevated FEMA National Risk Index baseline")

        if county.oni_anomaly >= 0.5:
            drivers.append("Active El Niño climate pattern with heightened storm shear/instability")

        if not drivers:
            drivers.append("Peripheral wind field and local utility exposure")

        return drivers[:3]

    def predict(
        self,
        county_features: list[CountyFeatures],
        advisory_number: int = 1,
        source_note: str | None = None,
    ) -> dict:
        """Generate full impact prediction dict conforming to agent contract."""
        if not county_features:
            return {
                "advisory_number": advisory_number,
                "model_version": self.version,
                "counties": [],
                "source": f"Quantile XGBoost Impact Model ({self.version})",
            }

        df = features_to_dataframe(county_features)
        quantiles = self.predict_quantiles(df)

        counties_output = []
        for cf, q in zip(county_features, quantiles):
            low, med, high = round(float(q[0]), 1), round(float(q[1]), 1), round(float(q[2]), 1)
            # Extra safety check for pydantic strict order
            if not low <= med <= high:
                low = min(low, med)
                high = max(high, med)

            risk_tier = self.assign_risk_tier(med, cf.svi_overall, cf.max_wind_kt)
            drivers = self.explain(cf, med)

            counties_output.append({
                "fips": cf.fips,
                "name": cf.name,
                "state": cf.state,
                "risk_tier": risk_tier,
                "pct_customers_out": {
                    "low": low,
                    "median": med,
                    "high": high,
                },
                "customers_served": cf.customers_served,
                "why": drivers,
            })

        source = source_note or (
            f"Quantile XGBoost Impact Model ({self.version}) trained on EAGLE-I, HURDAT2, FEMA NRI, CDC SVI"
        )
        return {
            "advisory_number": advisory_number,
            "model_version": self.version,
            "counties": counties_output,
            "source": source,
        }

    def save(self, filepath: str | Path) -> None:
        """Save model bundle to disk."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        bundle = {
            "version": self.version,
            "alpha_low": self.alpha_low,
            "alpha_median": self.alpha_median,
            "alpha_high": self.alpha_high,
            "is_fitted": self.is_fitted,
            "feature_columns": FEATURE_COLUMNS,
            "model_low": self.model_low,
            "model_median": self.model_median,
            "model_high": self.model_high,
        }
        joblib.dump(bundle, path)
        log.info(f"Saved QuantileOutageModel to {path}")

    @classmethod
    def load(cls, filepath: str | Path) -> "QuantileOutageModel":
        """Load model bundle from disk."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        bundle = joblib.load(path)
        instance = cls(
            alpha_low=bundle["alpha_low"],
            alpha_median=bundle["alpha_median"],
            alpha_high=bundle["alpha_high"],
            version=bundle.get("version", "xgboost-quantile-v1.0"),
        )
        instance.model_low = bundle["model_low"]
        instance.model_median = bundle["model_median"]
        instance.model_high = bundle["model_high"]
        instance.is_fitted = bundle.get("is_fitted", True)
        return instance
