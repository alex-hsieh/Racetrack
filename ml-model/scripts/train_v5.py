"""
Train F1 win-prediction model v5.0: adds a qualifying-pace telemetry
feature on top of v4.0's point-in-time features.

Uses Backend/api_clients/openf1_client.py::OpenF1Client — the exact same
client Backend/app/ml/predictor.py calls at inference time — so training and
serving compute this feature identically. (v1-v3's leakage bug happened
precisely because training and inference used different, inconsistent
feature logic; reusing one client for both avoids repeating that.)

qualifying_pace_percentile is a driver's rank (0.0 = fastest, 1.0 = slowest)
on best qualifying lap time for that specific race weekend. Qualifying
happens before the race, so this is safe to use as a predictive feature —
unlike the race's own lap times, which would leak the outcome.

OpenF1 coverage only starts around 2023, so pre-2023 rows get the neutral
default (0.5, i.e. "no signal") — the same cold-start pattern already used
for every other feature's missing-data case.

Usage (run from ml-model/):
    python scripts/train_v5.py
"""
import json
import os
import pickle
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = ROOT.parent / "Backend"
load_dotenv(BACKEND_ROOT / ".env.local")
sys.path.insert(0, str(BACKEND_ROOT))

from api_clients.openf1_client import OpenF1Client  # noqa: E402

FEATURE_COLS = [
    "driver_win_rate", "team_avg_finish", "driver_recent_form", "grid_position",
    "driver_avg_finish", "driver_podium_rate", "circuit_driver_performance",
    "qualifying_position_delta", "temperature_normalized", "humidity_normalized",
    "wind_speed_normalized", "rainfall_intensity", "qualifying_pace_percentile",
]

# Matches the cold-start defaults in Backend/app/ml/predictor.py::_calculate_driver_stats
COLD_START = {
    "driver_win_rate": 0.05,
    "team_avg_finish": 12.0,
    "driver_recent_form": 12.0,
    "driver_avg_finish": 12.0,
    "driver_podium_rate": 0.05,
    "circuit_driver_performance": 12.0,
    "qualifying_position_delta": 0.0,
}
TELEMETRY_DEFAULT = 0.5  # matches predictor.py::_get_telemetry_features' fallback

TRAIN_TEST_CUTOFF_YEAR = 2025  # train < this year, test >= this year


def load_race_results() -> pd.DataFrame:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    df = pd.read_sql(
        """
        SELECT
            r.year, r.round, r.race_name, r.circuit_id, r.circuit_name, r.date,
            d.driver_id, d.driver_full_name, d.driver_number,
            t.team_id, t.team_name,
            rr.grid_position, rr.finish_position,
            w.temperature, w.humidity, w.wind_speed, w.rainfall
        FROM race_results rr
        JOIN races r ON rr.race_id = r.race_id
        JOIN drivers d ON rr.driver_id = d.driver_id
        JOIN teams t ON rr.team_id = t.team_id
        LEFT JOIN weather_data w ON r.race_id = w.race_id
        WHERE r.year >= 2010 AND rr.finish_position IS NOT NULL
        ORDER BY r.date, r.round
        """,
        conn,
    )
    conn.close()
    return df


def _expanding_prior_by_date(df: pd.DataFrame, group_cols, value_col: str, out_col: str) -> pd.DataFrame:
    """Compute, for each (group, date), the expanding mean of value_col using
    only rows from strictly earlier dates in that group — collapsing to one
    row per (group, date) first so teammates racing on the same date never
    leak into each other's "prior" stats via a same-date row."""
    per_date = (
        df.groupby(group_cols + ["date"])[value_col]
        .mean()
        .reset_index()
        .sort_values(group_cols + ["date"])
    )
    per_date[out_col] = per_date.groupby(group_cols)[value_col].transform(
        lambda s: s.expanding().mean().shift(1)
    )
    return df.merge(per_date[group_cols + ["date", out_col]], on=group_cols + ["date"], how="left")


def backfill_qualifying_pace(df: pd.DataFrame) -> pd.DataFrame:
    """Fetch each unique 2023+ race weekend's qualifying pace percentiles
    once (OpenF1Client caches on disk, so reruns are cheap) and map them
    onto every (year, round, driver_number) row."""
    client = OpenF1Client(cache_hours=24 * 30)  # historical backfill — cache aggressively

    weekends = df.loc[df["year"] >= OpenF1Client.EARLIEST_COVERAGE_YEAR, ["year", "round", "date"]].drop_duplicates()
    print(f"Backfilling qualifying telemetry for {len(weekends)} race weekends (2023+)...")

    rows = []
    for _, wk in weekends.iterrows():
        pace_by_number = client.get_qualifying_pace_percentiles(int(wk["year"]), wk["date"])
        for driver_number, percentile in pace_by_number.items():
            rows.append({
                "year": wk["year"], "round": wk["round"],
                "driver_number": driver_number, "qualifying_pace_percentile": percentile,
            })
        status = f"{len(pace_by_number)} drivers" if pace_by_number else "no data"
        print(f"  {int(wk['year'])} round {int(wk['round'])}: {status}")

    telemetry = pd.DataFrame(rows, columns=["year", "round", "driver_number", "qualifying_pace_percentile"])
    df = df.merge(telemetry, on=["year", "round", "driver_number"], how="left")
    df["qualifying_pace_percentile"] = df["qualifying_pace_percentile"].fillna(TELEMETRY_DEFAULT)
    return df


def build_point_in_time_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["date", "round"]).reset_index(drop=True)
    df["won_race"] = (df["finish_position"] == 1).astype(int)
    df["podium"] = (df["finish_position"] <= 3).astype(int)
    df["qual_delta_raw"] = df["grid_position"] - df["finish_position"]

    # Driver-level stats: at most one row per driver per date, so a
    # groupby-transform in chronological order is safe directly.
    df = df.sort_values(["driver_id", "date", "round"])
    df["driver_win_rate"] = df.groupby("driver_id")["won_race"].transform(
        lambda s: s.expanding().mean().shift(1)
    )
    df["driver_avg_finish"] = df.groupby("driver_id")["finish_position"].transform(
        lambda s: s.expanding().mean().shift(1)
    )
    df["driver_podium_rate"] = df.groupby("driver_id")["podium"].transform(
        lambda s: s.expanding().mean().shift(1)
    )
    df["qualifying_position_delta"] = df.groupby("driver_id")["qual_delta_raw"].transform(
        lambda s: s.expanding().mean().shift(1)
    )
    df["driver_recent_form"] = df.groupby("driver_id")["finish_position"].transform(
        lambda s: s.rolling(3, min_periods=1).mean().shift(1)
    )
    df["circuit_driver_performance"] = df.groupby(["driver_id", "circuit_id"])["finish_position"].transform(
        lambda s: s.expanding().mean().shift(1)
    )

    # Team-level stat: multiple drivers can share a race date, so this needs
    # the date-collapsing helper to avoid a teammate's same-race result
    # leaking in as "prior" data.
    df = _expanding_prior_by_date(df, ["team_id"], "finish_position", "team_avg_finish")

    for col, default in COLD_START.items():
        df[col] = df[col].fillna(default)

    df["temperature_normalized"] = ((df["temperature"] - 15) / 20).fillna(0.5)
    df["humidity_normalized"] = (df["humidity"] / 100).fillna(0.6)
    df["wind_speed_normalized"] = (df["wind_speed"] / 20).fillna(0.3)
    df["rainfall_intensity"] = (df["rainfall"] / 10).fillna(0.0)

    return df.sort_values(["date", "round"]).reset_index(drop=True)


def main():
    print("Loading race results from the database...")
    df = load_race_results()
    print(f"Loaded {len(df)} rows, {df['year'].min()}-{df['year'].max()}")

    df = backfill_qualifying_pace(df)
    df_ml = build_point_in_time_features(df)

    X = df_ml[FEATURE_COLS].copy()
    y = df_ml["won_race"].copy()

    train_mask = df_ml["year"] < TRAIN_TEST_CUTOFF_YEAR
    X_train, X_test = X[train_mask], X[~train_mask]
    y_train, y_test = y[train_mask], y[~train_mask]

    print(f"Train: {len(X_train)} rows ({df_ml.loc[train_mask, 'year'].min()}-{df_ml.loc[train_mask, 'year'].max()})")
    print(f"Test:  {len(X_test)} rows ({df_ml.loc[~train_mask, 'year'].min()}-{df_ml.loc[~train_mask, 'year'].max()})")
    print(f"Wins in test set: {int(y_test.sum())} / {len(y_test)}")

    model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred)
    wins_correct = int(((y_test == 1) & (y_pred == 1)).sum())
    win_detection = wins_correct / y_test.sum() * 100 if y_test.sum() else 0.0

    print(f"\nHonest chronological-holdout accuracy: {accuracy * 100:.2f}%")
    print(f"Win detection (0.5 threshold): {win_detection:.1f}% ({wins_correct}/{int(y_test.sum())})")
    print(classification_report(y_test, y_pred, target_names=["Did Not Win", "Won"]))
    print("Confusion matrix:")
    print(f"  TN={cm[0][0]} FP={cm[0][1]}")
    print(f"  FN={cm[1][0]} TP={cm[1][1]}")

    test_probs = model.predict_proba(X_test)[:, 1]
    test_races = df_ml.loc[~train_mask, ["year", "round", "won_race"]].copy()
    test_races["win_prob"] = test_probs
    top1_hits = 0
    total_races = 0
    for _, race_group in test_races.groupby(["year", "round"]):
        total_races += 1
        top_pick = race_group["win_prob"].idxmax()
        if race_group.loc[top_pick, "won_race"] == 1:
            top1_hits += 1
    top1_accuracy = top1_hits / total_races * 100 if total_races else 0.0
    print(f"\nTop-1 per-race accuracy (model's highest pick = actual winner): "
          f"{top1_accuracy:.1f}% ({top1_hits}/{total_races} races)")

    importance = (
        pd.DataFrame({"feature": FEATURE_COLS, "importance": model.feature_importances_})
        .sort_values("importance", ascending=False)
    )
    print("\nFeature importance:")
    for _, row in importance.iterrows():
        print(f"  {row['feature']:30s} {row['importance'] * 100:5.1f}%")

    # Refit on all available data for the deployed artifact, now that the
    # chronological holdout has given an honest accuracy estimate.
    final_model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
    final_model.fit(X, y)

    out_dir = ROOT / "models" / "v5.0"
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "f1_winner_model_v5.pkl", "wb") as f:
        pickle.dump(final_model, f)
    with open(out_dir / "model_features.pkl", "wb") as f:
        pickle.dump(FEATURE_COLS, f)

    model_info = {
        "version": "5.0",
        "model_file": "f1_winner_model_v5.pkl",
        "features_file": "model_features.pkl",
        "created_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": f"Full database with weather + qualifying telemetry ({df['year'].min()}-{df['year'].max()}), point-in-time features",
        "num_samples": int(len(X)),
        "features": FEATURE_COLS,
        "accuracy": f"{accuracy * 100:.2f}%",
        "win_detection_rate_0.5_threshold": f"{win_detection:.1f}%",
        "top1_per_race_accuracy": f"{top1_accuracy:.1f}% ({top1_hits}/{total_races} races)",
        "accuracy_methodology": (
            "Chronological holdout (train < {}, test >= {}) using point-in-time "
            "(expanding/shifted) features computed only from strictly earlier races."
        ).format(TRAIN_TEST_CUTOFF_YEAR, TRAIN_TEST_CUTOFF_YEAR),
        "model_type": "RandomForestClassifier",
        "hyperparameters": {"n_estimators": 100, "max_depth": 10, "random_state": 42},
        "new_in_v5": {
            "qualifying_pace_percentile": (
                "Driver's best-lap rank (0.0=fastest, 1.0=slowest) in that race "
                "weekend's qualifying session, from the OpenF1 API "
                "(Backend/api_clients/openf1_client.py — the same client "
                "predictor.py calls at inference time, so training and serving "
                "compute this feature identically). Qualifying happens before "
                "the race, so this is safe to use as a predictive feature; the "
                "race's own lap times would leak the outcome. OpenF1 coverage "
                "only starts around 2023, so earlier rows use the neutral "
                f"default ({TELEMETRY_DEFAULT})."
            ),
        },
        "weather_normalization": {
            "temperature": "(temp - 15) / 20",
            "humidity": "humidity / 100",
            "wind_speed": "wind_speed / 20",
            "rainfall": "rainfall / 10",
        },
    }
    with open(out_dir / "model_info.json", "w") as f:
        json.dump(model_info, f, indent=2)

    print(f"\nSaved v5.0 model to {out_dir}")


if __name__ == "__main__":
    main()
