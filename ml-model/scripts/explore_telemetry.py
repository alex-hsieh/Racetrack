"""
Exploratory check: does OpenF1 race-pace telemetry from this season add
predictive signal beyond the existing point-in-time features?

Not a production integration — this pulls the 8 completed 2026 races,
computes one simple per-driver-per-race metric (median green-flag race lap
time, expressed as a percentile within the field), and checks whether it
correlates with who actually won. Eight races is too little data to
responsibly retrain and ship a new production feature on; this just tells us
whether the idea is worth revisiting once more of the season exists.

Uses the OpenF1 REST API (https://openf1.org) rather than FastF1 — FastF1's
lap-timing parser currently fails to load 2026 session data in this
environment ("Failed to load timing data!" across every session tried,
race and qualifying alike), while OpenF1's plain /laps and /car_data
endpoints return real per-lap and per-sample telemetry with no such gap.

Usage (run from ml-model/):
    python scripts/explore_telemetry.py
"""
import os
from pathlib import Path

import pandas as pd
import psycopg2
import requests
from dotenv import load_dotenv
from scipy.stats import pointbiserialr

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT.parent / "Backend" / ".env.local")

OPENF1_BASE = "https://api.openf1.org/v1"
COMPLETED_2026_ROUNDS = list(range(1, 9))  # rounds 1-8 confirmed complete


def get_completed_rounds() -> pd.DataFrame:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    df = pd.read_sql(
        """
        SELECT round, race_name, date
        FROM races
        WHERE year = 2026 AND round <= %s
        ORDER BY round
        """,
        conn,
        params=(max(COMPLETED_2026_ROUNDS),),
    )
    conn.close()
    return df


def get_driver_number_map() -> dict:
    """driver_number -> driver_id, e.g. 1 -> 'max_verstappen'.

    Scoped to drivers who actually raced in 2026: car numbers get reused by
    different drivers across eras (e.g. #12 belongs to both a historical
    driver and Antonelli in 2026), so a global drivers-table lookup silently
    mismaps anyone whose number collides with an older entry. Restricting to
    2026 race_results avoids that entirely, since a number is unique within
    a single season.
    """
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    df = pd.read_sql(
        """
        SELECT DISTINCT d.driver_id, d.driver_number
        FROM drivers d
        JOIN race_results rr ON rr.driver_id = d.driver_id
        JOIN races r ON rr.race_id = r.race_id
        WHERE r.year = 2026
        """,
        conn,
    )
    conn.close()
    df = df.dropna(subset=["driver_number"])
    df["driver_number"] = df["driver_number"].astype(int)
    return dict(zip(df["driver_number"], df["driver_id"]))


def find_race_session_key(race_date: str) -> int | None:
    resp = requests.get(
        f"{OPENF1_BASE}/sessions",
        params={"year": 2026, "session_type": "Race"},
        timeout=20,
    )
    resp.raise_for_status()
    sessions = resp.json()
    for s in sessions:
        if s["date_start"][:10] == str(race_date):
            return s["session_key"]
    return None


def race_pace_percentiles(session_key: int) -> pd.DataFrame:
    resp = requests.get(f"{OPENF1_BASE}/laps", params={"session_key": session_key}, timeout=30)
    resp.raise_for_status()
    laps = pd.DataFrame(resp.json())
    if laps.empty:
        return pd.DataFrame(columns=["driver_number", "telemetry_pace_percentile"])

    laps = laps[laps["is_pit_out_lap"] == False]  # noqa: E712
    laps = laps.dropna(subset=["lap_duration"])

    # Drop safety-car / VSC-affected outlier laps: anything well above the
    # field's typical lap time that race for that lap number.
    median_by_lap = laps.groupby("lap_number")["lap_duration"].transform("median")
    laps = laps[laps["lap_duration"] <= median_by_lap * 1.15]

    pace = laps.groupby("driver_number")["lap_duration"].median()
    percentile = pace.rank(pct=True)
    return pd.DataFrame({
        "driver_number": percentile.index,
        "telemetry_pace_percentile": percentile.values,
    })


def main():
    rounds = get_completed_rounds()
    driver_number_to_id = get_driver_number_map()

    frames = []
    for _, race in rounds.iterrows():
        print(f"Round {race['round']} ({race['race_name']}, {race['date']})...", end=" ")
        session_key = find_race_session_key(race["date"])
        if session_key is None:
            print("no OpenF1 session found, skipping")
            continue
        pace = race_pace_percentiles(session_key)
        if pace.empty:
            print("no lap data returned, skipping")
            continue
        pace["round"] = race["round"]
        frames.append(pace)
        print(f"ok ({len(pace)} drivers)")

    if not frames:
        print("No telemetry data could be retrieved for any completed round.")
        return

    telemetry = pd.concat(frames, ignore_index=True)
    telemetry["driver_id"] = telemetry["driver_number"].map(driver_number_to_id)
    telemetry = telemetry.dropna(subset=["driver_id"])

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    results = pd.read_sql(
        """
        SELECT r.round, rr.driver_id, rr.finish_position,
               (rr.finish_position = 1) AS won_race
        FROM race_results rr
        JOIN races r ON rr.race_id = r.race_id
        WHERE r.year = 2026 AND r.round <= %s
        """,
        conn,
        params=(max(COMPLETED_2026_ROUNDS),),
    )
    conn.close()

    merged = results.merge(telemetry, on=["round", "driver_id"], how="inner")
    print(f"\nMatched {len(merged)} driver-race rows across {merged['round'].nunique()} races")

    corr, p_value = pointbiserialr(merged["won_race"], -merged["telemetry_pace_percentile"])
    print(f"\nCorrelation(won_race, telemetry pace rank): r={corr:.3f}  p={p_value:.3f}")

    winner_percentiles = merged.loc[merged["won_race"], "telemetry_pace_percentile"]
    print(f"Winner's median pace percentile across these {len(winner_percentiles)} races: "
          f"{winner_percentiles.median():.2f} (0.0 = fastest in the field, 1.0 = slowest)")
    print(f"Winner was fastest-on-pace (top 15%) in "
          f"{(winner_percentiles < 0.15).sum()}/{len(winner_percentiles)} of these races")

    print(
        "\nInterpretation: a correlation this size on an 8-race sample is not "
        "enough to justify retraining/shipping a telemetry feature yet, but it "
        "indicates whether race pace tracks race wins closely enough to be "
        "worth revisiting once more of the 2026 season has completed."
    )


if __name__ == "__main__":
    main()
