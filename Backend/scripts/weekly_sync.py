"""Standalone weekly sync run by the Render Cron Job.

Re-syncs any race that finished in the last 8 days, independent of whether
the web service is awake (the in-process APScheduler in app/main.py only
fires if that process happens to be running at the trigger time).
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from database.database import SessionLocal
from app.models.models import Race
from app.services.auto_updater import F1AutoUpdater

YEAR = datetime.now(timezone.utc).year


def main():
    session = SessionLocal()
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(days=8)
    races = (
        session.query(Race)
        .filter(
            Race.year == YEAR,
            Race.end_datetime.isnot(None),
            Race.end_datetime <= now,
            Race.end_datetime >= lookback,
        )
        .order_by(Race.round)
        .all()
    )
    session.close()

    if not races:
        print(f"No races completed in the last 8 days for {YEAR}. Nothing to sync.")
        return

    updater = F1AutoUpdater()
    for race in races:
        print(f"Syncing round {race.round} ({race.race_name})...")
        updater.run_post_race_update(YEAR, race.round)
    print("Weekly sync complete.")


if __name__ == "__main__":
    main()
