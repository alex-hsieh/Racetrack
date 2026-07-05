"""
OpenF1 API Client
Fetches qualifying-session lap telemetry to derive a driver's pace
percentile for the current race weekend. Public API, no key required.
https://openf1.org

Qualifying (not the race itself) is used deliberately: qualifying happens
before the race, so it's safe to use as a prediction feature. Using the
target race's own lap times would leak the outcome we're trying to predict.

Coverage starts around the 2023 season — earlier years return no data.
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

import requests


class RateLimiter:
    def __init__(self, calls_per_minute: int = 30):
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute
        self.last_call = 0

    def wait(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()


class CacheManager:
    def __init__(self, cache_dir: str = ".cache/openf1", ttl_hours: int = 6):
        self.cache_dir = cache_dir
        self.ttl = timedelta(hours=ttl_hours)
        os.makedirs(cache_dir, exist_ok=True)

    def _get_cache_path(self, key: str) -> str:
        safe_key = "".join(c if c.isalnum() else "_" for c in key)
        return os.path.join(self.cache_dir, f"{safe_key}.json")

    def get(self, key: str) -> Optional[list]:
        cache_path = self._get_cache_path(key)
        if not os.path.exists(cache_path):
            return None
        try:
            with open(cache_path, "r") as f:
                cached = json.load(f)
            cached_time = datetime.fromisoformat(cached["timestamp"])
            if datetime.now() - cached_time > self.ttl:
                return None
            return cached["data"]
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def set(self, key: str, data: list):
        cache_path = self._get_cache_path(key)
        with open(cache_path, "w") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "data": data}, f)


class OpenF1Client:
    """Client for the OpenF1 API — used to derive a driver's qualifying
    pace percentile for the current race weekend (0.0 = fastest lap in the
    field, 1.0 = slowest)."""

    BASE_URL = "https://api.openf1.org/v1"
    EARLIEST_COVERAGE_YEAR = 2023  # OpenF1 has negligible data before this

    def __init__(self, cache_hours: int = 6):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "F1-Predictor-App/1.0"})
        self.rate_limiter = RateLimiter(calls_per_minute=30)
        self.cache = CacheManager(cache_dir=".cache/openf1", ttl_hours=cache_hours)

    def _make_request(self, endpoint: str, params: Dict) -> Optional[list]:
        cache_key = f"{endpoint}_{json.dumps(params, sort_keys=True, default=str)}"
        cached_data = self.cache.get(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            self.rate_limiter.wait()
            response = self.session.get(f"{self.BASE_URL}/{endpoint}", params=params, timeout=15)
            if response.status_code != 200:
                print(f"OpenF1: {endpoint} returned status {response.status_code}")
                return None
            data = response.json()
            self.cache.set(cache_key, data)
            return data
        except requests.exceptions.RequestException as e:
            print(f"OpenF1: request failed: {e}")
            return None

    def _find_qualifying_session_key(self, year: int, race_date) -> Optional[int]:
        """Find the qualifying session belonging to the same race weekend
        as race_date, by matching that weekend's Race session date."""
        race_sessions = self._make_request("sessions", {"year": year, "session_type": "Race"})
        if not race_sessions:
            return None

        race_date_str = race_date.isoformat()[:10] if hasattr(race_date, "isoformat") else str(race_date)[:10]
        meeting_key = None
        for s in race_sessions:
            if s["date_start"][:10] == race_date_str:
                meeting_key = s["meeting_key"]
                break
        if meeting_key is None:
            return None

        quali_sessions = self._make_request(
            "sessions", {"meeting_key": meeting_key, "session_type": "Qualifying"}
        )
        if not quali_sessions:
            return None
        return quali_sessions[0]["session_key"]

    def get_qualifying_pace_percentiles(self, year: int, race_date) -> Dict[int, float]:
        """driver_number -> pace percentile for that weekend's qualifying
        session. Returns an empty dict if no session/lap data is available
        (pre-2023, session hasn't happened yet, or the API call failed)."""
        if year < self.EARLIEST_COVERAGE_YEAR:
            return {}

        session_key = self._find_qualifying_session_key(year, race_date)
        if session_key is None:
            return {}

        laps = self._make_request("laps", {"session_key": session_key})
        if not laps:
            return {}

        best_lap_by_driver: Dict[int, float] = {}
        for lap in laps:
            duration = lap.get("lap_duration")
            if duration is None:
                continue
            driver_number = lap["driver_number"]
            if driver_number not in best_lap_by_driver or duration < best_lap_by_driver[driver_number]:
                best_lap_by_driver[driver_number] = duration

        if not best_lap_by_driver:
            return {}

        ranked = sorted(best_lap_by_driver.items(), key=lambda kv: kv[1])
        n = len(ranked)
        return {
            driver_number: (rank / (n - 1) if n > 1 else 0.0)
            for rank, (driver_number, _) in enumerate(ranked)
        }
