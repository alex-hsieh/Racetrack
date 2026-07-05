import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from app.external.jolpica import JolpicaF1Client
from app.services.db_writer import (
    upsert_driver_standings,
    upsert_constructor_standings,
    upsert_race_results
)

logger = logging.getLogger(__name__)


class F1AutoUpdater:

    def __init__(self):
        self.client = JolpicaF1Client()
        self.scheduler = AsyncIOScheduler()
        logger.info("[AUTO-UPDATER] F1AutoUpdater initialized")

    def start_scheduler(self):
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("[AUTO-UPDATER] ✓ Scheduler started")
        else:
            logger.info("[AUTO-UPDATER] Scheduler already running")

    def stop_scheduler(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("[AUTO-UPDATER] Scheduler stopped")

    def schedule_upcoming_races(self, year: int = 2026):
        from database.database import SessionLocal
        from app.models.models import Race, Prediction
        from datetime import timezone

        logger.info(f"[AUTO-UPDATER] Scheduling upcoming races for {year}...")
        session = SessionLocal()
        now = datetime.now(timezone.utc)
        upcoming_races = session.query(Race).filter(
            Race.year == year,
            Race.end_datetime.isnot(None),
            Race.end_datetime > now
        ).order_by(Race.round).all()

        logger.info(f"[AUTO-UPDATER] Found {len(upcoming_races)} upcoming races")
        scheduled_count = 0
        for race in upcoming_races:
            if race.end_datetime:
                self.schedule_race_update(race.end_datetime, year, race.round)
                scheduled_count += 1
            if race.qualifying_datetime:
                # Covers both: qualifying still upcoming, AND qualifying
                # already happened but this race never got a prediction (e.g.
                # this code was deployed/restarted after qualifying already
                # passed) — schedule_qualifying_prediction below runs
                # near-immediately for the latter case rather than skipping it.
                has_prediction = session.query(Prediction).filter(
                    Prediction.race_id == race.race_id
                ).first() is not None
                if not has_prediction:
                    self.schedule_qualifying_prediction(race.qualifying_datetime, year, race.round)

        session.close()
        logger.info(f"[AUTO-UPDATER] ✓ Scheduled {scheduled_count} upcoming races for {year}")
        return scheduled_count

    def schedule_race_update(self, race_end_time: datetime, year: int, round_number: int):
        trigger_time = race_end_time + timedelta(hours=2)
        self.scheduler.add_job(
            self.run_post_race_update,
            trigger=DateTrigger(run_date=trigger_time),
            args=[year, round_number],
            id=f"race_update_{year}_round_{round_number}",
            replace_existing=True
        )
        logger.info(f"[AUTO-UPDATER] Scheduled update for {year} round {round_number} at {trigger_time}")

    def schedule_qualifying_prediction(
        self, quali_time: datetime, year: int, round_number: int,
        attempt: int = 1, max_attempts: int = 6
    ):
        """One-shot job that runs the post-qualifying grid+prediction pipeline.
        Self-reschedules (up to max_attempts) if qualifying results aren't
        posted yet, rather than using a repeating trigger that would need
        separate stop-on-success teardown logic."""
        from datetime import timezone

        if attempt == 1:
            target = quali_time + timedelta(hours=2)
            now = datetime.now(timezone.utc)
            # If qualifying already happened well before this fired (e.g. a
            # fresh deploy mid-race-weekend), don't schedule a job for a time
            # that's already passed — run it almost immediately instead.
            trigger_time = target if target > now else now + timedelta(seconds=10)
        else:
            trigger_time = datetime.now(timezone.utc) + timedelta(minutes=20)

        self.scheduler.add_job(
            self._run_qualifying_prediction_attempt,
            trigger=DateTrigger(run_date=trigger_time),
            args=[year, round_number, attempt, max_attempts],
            id=f"quali_predict_{year}_round_{round_number}",
            replace_existing=True
        )
        logger.info(
            f"[AUTO-UPDATER] Scheduled qualifying prediction for {year} round "
            f"{round_number} at {trigger_time} (attempt {attempt}/{max_attempts})"
        )

    def _run_qualifying_prediction_attempt(
        self, year: int, round_number: int, attempt: int, max_attempts: int
    ):
        try:
            ok = self.run_post_qualifying_update(year, round_number)
        except Exception:
            logger.error(
                f"[AUTO-UPDATER] Qualifying prediction attempt {attempt} for "
                f"{year} round {round_number} raised",
                exc_info=True
            )
            ok = False

        if not ok and attempt < max_attempts:
            self.schedule_qualifying_prediction(
                None, year, round_number, attempt=attempt + 1, max_attempts=max_attempts
            )
        elif not ok:
            logger.warning(
                f"[AUTO-UPDATER] Giving up on qualifying prediction for {year} "
                f"round {round_number} after {max_attempts} attempts"
            )

    def run_post_race_update(self, year: int, round_number: int):
        logger.info(f"[AUTO-UPDATER] ===== POST-RACE UPDATE STARTED =====")
        logger.info(f"[AUTO-UPDATER] Year: {year}, Round: {round_number}")
        try:
            race_results = self.fetch_race_results(year, round_number)
            logger.info(f"[AUTO-UPDATER] ✓ Race results: {len(race_results)} rows fetched")
            rows_saved = upsert_race_results(race_results)
            logger.info(f"[AUTO-UPDATER] ✓ Race results: {rows_saved} rows saved")

            driver_standings = self.fetch_driver_standings(year)
            rows_saved = upsert_driver_standings(driver_standings)
            logger.info(f"[AUTO-UPDATER] ✓ Driver standings: {rows_saved} rows saved")

            constructor_standings = self.fetch_constructor_standings(year)
            rows_saved = upsert_constructor_standings(constructor_standings)
            logger.info(f"[AUTO-UPDATER] ✓ Constructor standings: {rows_saved} rows saved")

            logger.info(f"[AUTO-UPDATER] ===== POST-RACE UPDATE COMPLETE =====")
        except Exception as e:
            logger.error(f"[AUTO-UPDATER] ===== POST-RACE UPDATE FAILED =====")
            logger.error(f"[AUTO-UPDATER] Error: {e}", exc_info=True)
            raise

    def fetch_driver_standings(self, year: int = 2026) -> List[Dict[str, Any]]:
        logger.info(f"[AUTO-UPDATER] Fetching driver standings for {year}...")
        try:
            standings_data = self.client.get_driver_standings(year)
            if not standings_data:
                logger.warning(f"[AUTO-UPDATER] No driver standings data for {year}")
                return []
            normalized = []
            for entry in standings_data:
                normalized.append({
                    'year': year,
                    'driver_id': entry['Driver']['driverId'],
                    'position': int(entry['position']),
                    'points': float(entry['points']),
                    'wins': int(entry['wins']),
                    'team_id': entry['Constructors'][0]['constructorId'] if entry.get('Constructors') else None
                })
            logger.info(f"[AUTO-UPDATER] ✓ Fetched {len(normalized)} driver standings")
            return normalized
        except Exception as e:
            logger.error(f"[AUTO-UPDATER] ✗ Error fetching driver standings: {e}")
            raise

    def fetch_constructor_standings(self, year: int = 2026) -> List[Dict[str, Any]]:
        logger.info(f"[AUTO-UPDATER] Fetching constructor standings for {year}...")
        try:
            standings_data = self.client.get_constructor_standings(year)
            if not standings_data:
                logger.warning(f"[AUTO-UPDATER] No constructor standings data for {year}")
                return []
            normalized = []
            for entry in standings_data:
                normalized.append({
                    'year': year,
                    'team_id': entry['Constructor']['constructorId'],
                    'position': int(entry['position']),
                    'points': float(entry['points']),
                    'wins': int(entry['wins'])
                })
            logger.info(f"[AUTO-UPDATER] ✓ Fetched {len(normalized)} constructor standings")
            return normalized
        except Exception as e:
            logger.error(f"[AUTO-UPDATER] ✗ Error fetching constructor standings: {e}")
            raise

    def fetch_race_results(self, year: int, round_number: int) -> List[Dict[str, Any]]:
        logger.info(f"[AUTO-UPDATER] Fetching race results for {year} round {round_number}...")
        try:
            results_data = self.client.get_race_results(year, round_number)
            if not results_data:
                logger.warning(f"[AUTO-UPDATER] No race results for {year} round {round_number}")
                return []

            from database.database import SessionLocal
            from app.models.models import Race, WeatherData

            session = SessionLocal()
            race = session.query(Race).filter(
                Race.year == year,
                Race.round == round_number
            ).first()

            if not race:
                logger.error(f"[AUTO-UPDATER] Race not found for {year} round {round_number}")
                session.close()
                return []

            race_id = race.race_id
            circuit_id = race.circuit_id
            race_date = race.date

            weather_data = session.query(WeatherData).filter(
                WeatherData.race_id == race_id
            ).first()

            weather_condition = 'dry'
            if weather_data and weather_data.conditions:
                conditions_lower = weather_data.conditions.lower()
                if 'rain' in conditions_lower:
                    weather_condition = 'wet'
                logger.info(f"[AUTO-UPDATER] Weather: {weather_data.conditions} → {weather_condition}")
            else:
                logger.info(f"[AUTO-UPDATER] No weather data, defaulting to dry")

            session.close()

            normalized = []
            for result in results_data:
                normalized.append({
                    'race_id': race_id,
                    'circuit_id': circuit_id,
                    'race_date': race_date,
                    'driver_id': result['Driver']['driverId'],
                    'team_id': result['Constructor']['constructorId'],
                    'grid_position': float(result.get('grid', 0)),
                    'finish_position': float(result['position']),
                    'points_scored': float(result['points']),
                    'position_text': result['positionText'],
                    'laps_completed': int(result.get('laps', 0)),
                    'status': result['status'],
                    'time': result.get('Time', {}).get('time', None) if 'Time' in result else None,
                    'dnf': result['status'] != 'Finished',
                    'weather_condition': weather_condition
                })

            logger.info(f"[AUTO-UPDATER] ✓ Fetched {len(normalized)} race results")
            return normalized
        except Exception as e:
            logger.error(f"[AUTO-UPDATER] ✗ Error fetching race results: {e}")
            raise

    def fetch_qualifying_results(self, year: int, round_number: int) -> List[Dict[str, Any]]:
        """Partial race_results rows carrying only the real grid position from
        qualifying — finish_position/points/etc. are filled in later by the
        normal post-race upsert, via the same (race_id, driver_id) conflict key."""
        logger.info(f"[AUTO-UPDATER] Fetching qualifying results for {year} round {round_number}...")
        try:
            quali_data = self.client.get_qualifying_results(year, round_number)
            if not quali_data:
                logger.warning(f"[AUTO-UPDATER] No qualifying results yet for {year} round {round_number}")
                return []

            from database.database import SessionLocal
            from app.models.models import Race

            session = SessionLocal()
            race = session.query(Race).filter(
                Race.year == year,
                Race.round == round_number
            ).first()

            if not race:
                logger.error(f"[AUTO-UPDATER] Race not found for {year} round {round_number}")
                session.close()
                return []

            race_id = race.race_id
            circuit_id = race.circuit_id
            race_date = race.date
            session.close()

            normalized = []
            for result in quali_data:
                normalized.append({
                    'race_id': race_id,
                    'circuit_id': circuit_id,
                    'race_date': race_date,
                    'driver_id': result['Driver']['driverId'],
                    'team_id': result['Constructor']['constructorId'],
                    'grid_position': float(result['position']),
                    'finish_position': None,
                    'points_scored': 0.0,
                    'position_text': None,
                    'laps_completed': 0,
                    'status': None,
                    'time': None,
                    'dnf': False,
                    'weather_condition': None,
                })

            logger.info(f"[AUTO-UPDATER] ✓ Fetched {len(normalized)} qualifying results")
            return normalized
        except Exception as e:
            logger.error(f"[AUTO-UPDATER] ✗ Error fetching qualifying results: {e}")
            raise

    def run_post_qualifying_update(self, year: int, round_number: int) -> bool:
        """Pull real grid positions from qualifying, then generate and store
        a grid-aware win prediction. Returns False (not an error) when
        qualifying results simply aren't posted yet, so the caller can retry."""
        logger.info(f"[AUTO-UPDATER] ===== POST-QUALIFYING UPDATE STARTED =====")
        logger.info(f"[AUTO-UPDATER] Year: {year}, Round: {round_number}")
        try:
            quali_rows = self.fetch_qualifying_results(year, round_number)
            if not quali_rows:
                logger.info(f"[AUTO-UPDATER] Qualifying not posted yet for {year} round {round_number}")
                return False

            rows_saved = upsert_race_results(quali_rows)
            logger.info(f"[AUTO-UPDATER] ✓ Grid positions: {rows_saved} rows saved")

            from database.crud import get_race_by_year_round, save_prediction
            from app.ml.predictor import predictor
            import json

            race = get_race_by_year_round(year, round_number)
            race_id = race['race_id']

            predictions = predictor.predict_race_winner(race_id)
            winner = next(p for p in predictions if p['predicted_position'] == 1)
            top_3 = [p['driver_id'] for p in sorted(predictions, key=lambda p: p['predicted_position'])[:3]]

            save_prediction(
                race_id=race_id,
                predicted_winner_id=winner['driver_id'],
                confidence_score=winner['confidence_score'],
                predicted_top_3=json.dumps(top_3),
            )
            logger.info(f"[AUTO-UPDATER] ✓ Saved prediction: {winner['driver_id']} ({winner['confidence_score']})")
            logger.info(f"[AUTO-UPDATER] ===== POST-QUALIFYING UPDATE COMPLETE =====")
            return True
        except Exception as e:
            logger.error(f"[AUTO-UPDATER] ===== POST-QUALIFYING UPDATE FAILED =====")
            logger.error(f"[AUTO-UPDATER] Error: {e}", exc_info=True)
            raise

    def seed_race_calendar(self, year: int = 2026):
        from database.database import SessionLocal
        from app.models.models import Race, Circuit
        from datetime import timezone

        def _parse_dt(date_str, time_str):
            try:
                return datetime.strptime(f"{date_str}T{time_str}", '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            except:
                return None

        logger.info(f"[AUTO-UPDATER] Seeding race calendar for {year}...")
        races_data = self.client.get_race_schedule(year)

        if not races_data:
            logger.warning(f"[AUTO-UPDATER] No race data returned for {year}")
            return 0

        session = SessionLocal()
        count = 0
        try:
            for r in races_data:
                circuit_data = r['Circuit']

                circuit = session.get(Circuit, circuit_data['circuitId'])
                if not circuit:
                    session.add(Circuit(
                        circuit_id=circuit_data['circuitId'],
                        circuit_name=circuit_data['circuitName'],
                        location=circuit_data['Location']['locality'],
                        country=circuit_data['Location']['country'],
                        latitude=circuit_data['Location']['lat'],
                        longitude=circuit_data['Location']['long'],
                    ))

                race_dt = _parse_dt(r['date'], r.get('time', '00:00:00Z'))
                end_dt = race_dt + timedelta(hours=2) if race_dt else None

                session_keys = ['FirstPractice', 'SecondPractice', 'ThirdPractice', 'Sprint', 'Qualifying']
                session_dts = [
                    _parse_dt(r[s]['date'], r[s].get('time', '00:00:00Z'))
                    for s in session_keys if s in r
                ]
                session_dts = [d for d in session_dts if d]
                start_dt = min(session_dts) if session_dts else race_dt

                quali_dt = (
                    _parse_dt(r['Qualifying']['date'], r['Qualifying'].get('time', '00:00:00Z'))
                    if 'Qualifying' in r else None
                )

                existing = session.query(Race).filter(
                    Race.year == year,
                    Race.round == int(r['round'])
                ).first()

                if not existing:
                    session.add(Race(
                        year=year,
                        round=int(r['round']),
                        race_name=r['raceName'],
                        circuit_id=circuit_data['circuitId'],
                        circuit_name=circuit_data['circuitName'],
                        country=circuit_data['Location']['country'],
                        date=datetime.strptime(r['date'], '%Y-%m-%d').date(),
                        start_datetime=start_dt,
                        end_datetime=end_dt,
                        qualifying_datetime=quali_dt,
                    ))
                    count += 1
                elif existing.qualifying_datetime is None and quali_dt is not None:
                    # Backfill onto races seeded before this column existed,
                    # without touching any other already-seeded fields.
                    existing.qualifying_datetime = quali_dt

            session.commit()
            logger.info(f"[AUTO-UPDATER] ✓ Seeded {count} races for {year}")
        except Exception as e:
            session.rollback()
            logger.error(f"[AUTO-UPDATER] ✗ Seed failed: {e}")
            raise
        finally:
            session.close()

        return count

    def seed_drivers_and_teams(self, year: int = 2026):
        from database.database import SessionLocal
        from app.models.models import Driver, Team

        logger.info(f"[AUTO-UPDATER] Seeding drivers and teams for {year}...")
        session = SessionLocal()
        try:
            constructors = self.client.get_all_constructors(year)
            team_count = 0
            for c in constructors:
                if not session.get(Team, c['constructorId']):
                    session.add(Team(
                        team_id=c['constructorId'],
                        team_name=c['name'],
                    ))
                    team_count += 1

            session.flush()

            drivers = self.client.get_all_drivers(year)
            driver_count = 0
            for d in drivers:
                if not session.get(Driver, d['driverId']):
                    session.add(Driver(
                        driver_id=d['driverId'],
                        driver_code=d.get('code'),
                        driver_number=int(d['permanentNumber']) if d.get('permanentNumber') else None,
                        driver_forename=d['givenName'],
                        driver_surname=d['familyName'],
                        driver_full_name=f"{d['givenName']} {d['familyName']}",
                        nationality=d.get('nationality'),
                    ))
                    driver_count += 1

            session.commit()
            logger.info(f"[AUTO-UPDATER] ✓ Seeded {team_count} teams, {driver_count} drivers")
        except Exception as e:
            session.rollback()
            logger.error(f"[AUTO-UPDATER] ✗ seed_drivers_and_teams failed: {e}")
            raise
        finally:
            session.close()

    def seed_past_results(self, year: int = 2026):
        from database.database import SessionLocal
        from app.models.models import Race
        from datetime import timezone

        logger.info(f"[AUTO-UPDATER] Seeding past results for {year}...")
        session = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            completed = session.query(Race).filter(
                Race.year == year,
                Race.end_datetime.isnot(None),
                Race.end_datetime < now
            ).order_by(Race.round).all()
            logger.info(f"[AUTO-UPDATER] Found {len(completed)} completed races")
            session.close()

            for race in completed:
                results = self.fetch_race_results(year, race.round)
                if results:
                    saved = upsert_race_results(results)
                    logger.info(f"[AUTO-UPDATER] ✓ Round {race.round}: {saved} results saved")
        except Exception as e:
            logger.error(f"[AUTO-UPDATER] ✗ seed_past_results failed: {e}")
            raise


# Singleton instance
_updater = None

def get_updater() -> F1AutoUpdater:
    global _updater
    if _updater is None:
        _updater = F1AutoUpdater()
    return _updater