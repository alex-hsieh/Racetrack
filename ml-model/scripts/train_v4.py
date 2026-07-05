"""
Train F1 win-prediction model v4.0 with point-in-time-correct features.

v1-v3 (see ml-model/notebooks/train_v3_with_weather.ipynb) computed every
driver/team/circuit stat as a single whole-dataset aggregate (past AND future
races) mapped back onto every row by name, and computed
qualifying_position_delta directly from the current row's own
finish_position. That leakage is why v3 reported 98.99% training accuracy,
and it also meant training-time features didn't resemble what
Backend/app/ml/predictor.py::_calculate_driver_stats actually serves at
inference time (which correctly restricts to races before the target race,
but as a result has no visibility into the current season at all).

This script recomputes every feature as an expanding/rolling statistic over
strictly earlier races only, evaluates with a chronological holdout instead
of a random split, and saves the result as v4.0.

Usage (run from ml-model/):
    python scripts/train_v4.py
"""
import json
import os
import pickle
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT.parent / "Backend" / ".env.local")

FEATURE_COLS = [
    "driver_win_rate", "team_avg_finish", "driver_recent_form", "grid_position",
    "driver_avg_finish", "driver_podium_rate", "circuit_driver_performance",
    "qualifying_position_delta", "temperature_normalized", "humidity_normalized",
    "wind_speed_normalized", "rainfall_intensity",
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

TRAIN_TEST_CUTOFF_YEAR = 2025  # train < this year, test >= this year


def load_race_results() -> pd.DataFrame:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    df = pd.read_sql(
        """
        SELECT
            r.year, r.round, r.race_name, r.circuit_id, r.circuit_name, r.date,
            d.driver_id, d.driver_full_name,
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

    # The app never thresholds at 0.5 — predict_race_winner ranks every
    # driver in a race by predict_proba and picks the highest. That's the
    # metric that actually matters for "is the model's top pick right".
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

    out_dir = ROOT / "models" / "v4.0"
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "f1_winner_model_v4.pkl", "wb") as f:
        pickle.dump(final_model, f)
    with open(out_dir / "model_features.pkl", "wb") as f:
        pickle.dump(FEATURE_COLS, f)

    model_info = {
        "version": "4.0",
        "model_file": "f1_winner_model_v4.pkl",
        "features_file": "model_features.pkl",
        "created_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": f"Full database with weather ({df['year'].min()}-{df['year'].max()}), point-in-time features",
        "num_samples": int(len(X)),
        "features": FEATURE_COLS,
        "accuracy": f"{accuracy * 100:.2f}%",
        "win_detection_rate_0.5_threshold": f"{win_detection:.1f}%",
        "top1_per_race_accuracy": f"{top1_accuracy:.1f}% ({top1_hits}/{total_races} races)",
        "accuracy_methodology": (
            "Chronological holdout (train < {}, test >= {}) using point-in-time "
            "(expanding/shifted) features computed only from strictly earlier races. "
            "v1-v3 accuracy numbers used a random stratified split over features that "
            "were whole-dataset aggregates (including future results) and are not "
            "comparable to this number."
        ).format(TRAIN_TEST_CUTOFF_YEAR, TRAIN_TEST_CUTOFF_YEAR),
        "model_type": "RandomForestClassifier",
        "hyperparameters": {"n_estimators": 100, "max_depth": 10, "random_state": 42},
        "fixes_over_v3": {
            "leakage_removed": (
                "driver_win_rate/team_avg_finish/driver_avg_finish/driver_podium_rate/"
                "circuit_driver_performance/qualifying_position_delta were previously "
                "whole-dataset aggregates (including future results) mapped back onto "
                "every row; qualifying_position_delta additionally computed the current "
                "race's own grid-minus-finish delta directly, leaking part of the answer. "
                "All are now expanding/rolling stats computed only from strictly earlier "
                "races, shifted so the current race never contributes to its own features."
            ),
            "current_season_included": (
                "Training pulls directly from the live database, so an in-progress "
                "season's completed races become valid history for later rounds in "
                "that same season."
            ),
            "evaluation_split": (
                "Switched from a random stratified 80/20 split to a chronological "
                "holdout, the only honest way to estimate forecasting accuracy for a "
                "time-ordered problem."
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

    print(f"\nSaved v4.0 model to {out_dir}")


if __name__ == "__main__":
    main()
