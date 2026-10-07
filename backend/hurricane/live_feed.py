"""Live NOAA/NHC and NWS active storm & alert feed ingestion poller.

Provides Layer 1 active tropical cyclone ingestion as specified in proposal §Architecture:
- NHC Active Storms: https://www.nhc.noaa.gov/CurrentStorms.json
- NWS Active Weather Alerts: https://api.weather.gov/alerts/active

Features thread-safe caching, TTL rate limiting, offline fallback, and county-level threat assessment.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

NHC_CURRENT_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
NWS_ACTIVE_ALERTS_URL = "https://api.weather.gov/alerts/active?status=actual&message_type=alert"
USER_AGENT = "storm-readiness-ai/1.0 (contact@stormreadiness.ai)"
DEFAULT_CACHE_TTL_SEC = 300.0  # 5 minutes
HTTP_TIMEOUT_SEC = 8.0

# Relevant tropical cyclone alert events from NWS
TROPICAL_ALERT_EVENTS = {
    "Hurricane Warning",
    "Hurricane Watch",
    "Tropical Storm Warning",
    "Tropical Storm Watch",
    "Storm Surge Warning",
    "Storm Surge Watch",
    "Extreme Wind Warning",
    "Tropical Cyclone Local Statement",
    "Flash Flood Warning",
}


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points in nautical miles."""
    r_nm = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return round(2.0 * r_nm * math.atan2(math.sqrt(a), math.sqrt(1.0 - a)), 1)


def _fetch_url(url: str, timeout: float = HTTP_TIMEOUT_SEC) -> dict | None:
    """Safely fetch and parse JSON from a remote URL with custom User-Agent."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/geo+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        log.warning("Failed to fetch %s: %s", url, e)
    return None


class LiveFeedPoller:
    """Thread-safe background poller and cache for active NOAA/NWS storm intelligence."""

    def __init__(self, ttl_seconds: float = DEFAULT_CACHE_TTL_SEC):
        self.ttl = ttl_seconds
        self._lock = threading.RLock()
        self._last_polled_utc: str | None = None
        self._last_poll_timestamp: float = 0.0
        self._cached_storms: list[dict] = []
        self._cached_alerts: list[dict] = []
        self._is_connected: bool = False

    def poll(self, force: bool = False) -> dict[str, Any]:
        """Fetch latest active storms and alerts if cache expired or force=True."""
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()

        with self._lock:
            if not force and (now_ts - self._last_poll_timestamp) < self.ttl and self._last_polled_utc:
                return self._status_dict()

            # Poll NHC Active Storms
            nhc_data = _fetch_url(NHC_CURRENT_STORMS_URL)
            if nhc_data and "activeStorms" in nhc_data:
                parsed_storms = []
                for s in nhc_data.get("activeStorms", []):
                    try:
                        intensity_kt = float(s.get("intensity") or 0.0)
                        pressure_mb = float(s.get("pressure") or 0.0)
                        lat = float(s.get("latitudeNumeric") or 0.0)
                        lon = float(s.get("longitudeNumeric") or 0.0)
                        pa = s.get("publicAdvisory") or {}
                        parsed_storms.append({
                            "storm_id": s.get("id", "").upper(),
                            "name": s.get("name", "").strip().title(),
                            "classification": s.get("classification", "").strip(),
                            "intensity_kt": intensity_kt,
                            "pressure_mb": pressure_mb,
                            "lat": lat,
                            "lon": lon,
                            "movement_dir_deg": s.get("movementDir"),
                            "movement_speed_kt": s.get("movementSpeed"),
                            "last_update_utc": s.get("lastUpdate"),
                            "advisory_num": pa.get("advNum"),
                            "public_advisory_url": pa.get("url"),
                            "forecast_advisory_url": (s.get("forecastAdvisory") or {}).get("url"),
                        })
                    except (ValueError, TypeError) as e:
                        log.debug("Skipping unparseable storm entry %s: %s", s, e)
                self._cached_storms = parsed_storms
                self._is_connected = True

            # Poll NWS Active Tropical Alerts
            nws_data = _fetch_url(NWS_ACTIVE_ALERTS_URL)
            if nws_data and "features" in nws_data:
                parsed_alerts = []
                for f in nws_data.get("features", []):
                    props = f.get("properties", {})
                    event = props.get("event", "")
                    if any(t in event for t in ("Hurricane", "Tropical", "Surge", "Extreme Wind")):
                        geocode = props.get("geocode", {})
                        same_fips = geocode.get("SAME", [])
                        ugc = geocode.get("UGC", [])
                        parsed_alerts.append({
                            "id": props.get("id"),
                            "event": event,
                            "severity": props.get("severity"),
                            "urgency": props.get("urgency"),
                            "headline": props.get("headline"),
                            "area_desc": props.get("areaDesc"),
                            "fips_codes": [str(c)[1:] if len(str(c)) == 6 else str(c) for c in same_fips],
                            "ugc_codes": ugc,
                            "effective_utc": props.get("effective"),
                            "expires_utc": props.get("expires"),
                        })
                self._cached_alerts = parsed_alerts
                self._is_connected = True

            self._last_poll_timestamp = now_ts
            self._last_polled_utc = now.isoformat(timespec="seconds")
            return self._status_dict()

    def _status_dict(self) -> dict[str, Any]:
        return {
            "status": "online" if self._is_connected else "offline_or_fallback",
            "last_polled_utc": self._last_polled_utc,
            "ttl_seconds": self.ttl,
            "active_storms_count": len(self._cached_storms),
            "active_tropical_alerts_count": len(self._cached_alerts),
            "source": "NOAA NHC CurrentStorms.json & NWS Active Alerts API",
        }

    def get_active_storms(self) -> list[dict]:
        """Return currently active tropical cyclones from NHC."""
        self.poll()
        with self._lock:
            return list(self._cached_storms)

    def get_active_alerts(self, fips: str | None = None) -> list[dict]:
        """Return active tropical alerts, optionally filtered for a specific county FIPS."""
        self.poll()
        with self._lock:
            if not fips:
                return list(self._cached_alerts)
            fips_norm = str(fips).zfill(5)
            return [
                a for a in self._cached_alerts
                if fips_norm in a["fips_codes"] or (fips_norm[2:] in "".join(a["ugc_codes"]))
            ]

    def assess_county_threat(self, fips: str, lat: float, lon: float) -> dict[str, Any]:
        """Assess if any active NOAA storm or NWS alert directly threatens this county."""
        self.poll()
        with self._lock:
            storms = list(self._cached_storms)
            alerts = self.get_active_alerts(fips=fips)

        closest_storm = None
        min_dist_nm = float("inf")
        for s in storms:
            d = haversine_nm(lat, lon, s["lat"], s["lon"])
            if d < min_dist_nm:
                min_dist_nm = d
                closest_storm = dict(s) | {"distance_nm": d}

        threat_level = "none"
        if alerts:
            threat_level = "imminent" if any("Warning" in a["event"] for a in alerts) else "elevated"
        elif closest_storm and min_dist_nm <= 250.0:
            threat_level = "elevated"

        return {
            "county_fips": fips,
            "live_connected": self._is_connected,
            "active_storms_total": len(storms),
            "threat_level": threat_level,
            "closest_active_storm": closest_storm if closest_storm and min_dist_nm < 1500.0 else None,
            "county_active_alerts": alerts,
            "source": "NOAA NHC + NWS Live Poller",
            "evaluated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


# Module singleton
_FEED = LiveFeedPoller()


def get_poller() -> LiveFeedPoller:
    return _FEED
