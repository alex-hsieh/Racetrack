from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import logging

from app.services.auto_updater import get_updater

router = APIRouter()
logger = logging.getLogger(__name__)


class SyncResponse(BaseModel):
    success: bool
    message: str
    drivers_fetched: int
    drivers_saved: int
    constructors_fetched: int
    constructors_saved: int
    race_results_fetched: int
    race_results_saved: int


@router.post("/sync", response_model=SyncResponse)
def manual_sync(
    year: int = Query(2026, description="Season year"),
    round_number: Optional[int] = Query(None, description="Race round number (optional)")
):
    """
    Manually trigger data synchronization from Jolpica API.
    
    **WARNING: This endpoint has no authentication and is for testing only.**
    
    - Fetches driver standings for specified year
    - Fetches constructor standings for specified year
    - Optionally fetches race results if round_number provided
    - Saves all data to database via upsert functions
    
    Example:
    - POST /api/admin/sync?year=2026 - Update standings only
    - POST /api/admin/sync?year=2026&round_number=5 - Update standings + race 5 results
    """
    logger.info(f"[ADMIN] ===== MANUAL SYNC TRIGGERED =====")
    logger.info(f"[ADMIN] Year: {year}, Round: {round_number}")
    
    try:
        updater = get_updater()
        
        # Initialize counters
        drivers_fetched = 0
        drivers_saved = 0
        constructors_fetched = 0
        constructors_saved = 0
        race_results_fetched = 0
        race_results_saved = 0
        
        # Fetch and save driver standings
        logger.info(f"[ADMIN] Fetching driver standings...")
        drivers = updater.fetch_driver_standings(year)
        drivers_fetched = len(drivers)
        logger.info(f"[ADMIN] ✓ Fetched {drivers_fetched} driver standings")
        
        if drivers:
            from app.services.db_writer import upsert_driver_standings
            drivers_saved = upsert_driver_standings(drivers)
            logger.info(f"[ADMIN] ✓ Saved {drivers_saved} driver standings to database")
        
        # Fetch and save constructor standings
        logger.info(f"[ADMIN] Fetching constructor standings...")
        constructors = updater.fetch_constructor_standings(year)
        constructors_fetched = len(constructors)
        logger.info(f"[ADMIN] ✓ Fetched {constructors_fetched} constructor standings")
        
        if constructors:
            from app.services.db_writer import upsert_constructor_standings
            constructors_saved = upsert_constructor_standings(constructors)
            logger.info(f"[ADMIN] ✓ Saved {constructors_saved} constructor standings to database")
        
        # Fetch and save race results if round specified
        if round_number:
            logger.info(f"[ADMIN] Fetching race results for round {round_number}...")
            race_results = updater.fetch_race_results(year, round_number)
            race_results_fetched = len(race_results)
            logger.info(f"[ADMIN] ✓ Fetched {race_results_fetched} race results")
            
            if race_results:
                from app.services.db_writer import upsert_race_results
                race_results_saved = upsert_race_results(race_results)
                logger.info(f"[ADMIN] ✓ Saved {race_results_saved} race results to database")
        
        logger.info(f"[ADMIN] ===== MANUAL SYNC COMPLETE =====")
        
        return SyncResponse(
            success=True,
            message=f"Sync complete - data fetched and saved to database",
            drivers_fetched=drivers_fetched,
            drivers_saved=drivers_saved,
            constructors_fetched=constructors_fetched,
            constructors_saved=constructors_saved,
            race_results_fetched=race_results_fetched,
            race_results_saved=race_results_saved
        )
        
    except Exception as e:
        logger.error(f"[ADMIN] ===== MANUAL SYNC FAILED =====")
        logger.error(f"[ADMIN] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Sync failed: {str(e)}"
        )


class QualifyingSyncResponse(BaseModel):
    success: bool
    message: str
    qualifying_found: bool


@router.post("/sync-qualifying", response_model=QualifyingSyncResponse)
def manual_qualifying_sync(
    year: int = Query(2026, description="Season year"),
    round_number: int = Query(..., description="Race round number"),
):
    """
    Manually run the post-qualifying pipeline for a specific race: pulls real
    grid positions from qualifying, then generates and stores a grid-aware
    win prediction.

    Exists as a backfill tool for races whose qualifying already passed before
    the scheduled job for it existed/fired (e.g. right after a fresh deploy
    mid-race-weekend) — the normal path is the scheduler in auto_updater.py.

    **WARNING: This endpoint has no authentication and is for testing/ops use only.**
    """
    logger.info(f"[ADMIN] ===== MANUAL QUALIFYING SYNC TRIGGERED =====")
    logger.info(f"[ADMIN] Year: {year}, Round: {round_number}")
    try:
        updater = get_updater()
        found = updater.run_post_qualifying_update(year, round_number)
        logger.info(f"[ADMIN] ===== MANUAL QUALIFYING SYNC COMPLETE =====")
        return QualifyingSyncResponse(
            success=True,
            message="Qualifying results processed and prediction saved" if found
                     else "No qualifying results available yet for this round",
            qualifying_found=found,
        )
    except Exception as e:
        logger.error(f"[ADMIN] ===== MANUAL QUALIFYING SYNC FAILED =====")
        logger.error(f"[ADMIN] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Qualifying sync failed: {str(e)}")


@router.get("/sync/status")
def sync_status():
    """
    Check auto-updater status.
    
    Returns information about the scheduler and configuration.
    """
    updater = get_updater()
    
    return {
        "scheduler_running": updater.scheduler.running if updater.scheduler else False,
        "scheduled_jobs": len(updater.scheduler.get_jobs()) if updater.scheduler else 0,
        "message": f"Scheduler running. {len(updater.scheduler.get_jobs())} races scheduled for auto-update.",
        "manual_sync_available": True,
        "endpoints": {
            "manual_sync": "POST /api/admin/sync?year=2026&round_number=5",
            "status": "GET /api/admin/sync/status"
        }
    }


@router.get("/sentry-test")
def sentry_test():
    """TEMPORARY - remove after confirming Sentry captures this. Deliberately
    raises to verify the Sentry SDK is actually forwarding unhandled
    exceptions, not just initialized without crashing at startup."""
    raise RuntimeError("Sentry test error - safe to ignore, this endpoint is temporary")