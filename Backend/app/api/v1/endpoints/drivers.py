from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List

from app.schemas.drivers import DriverResponse, DriversListResponse
from database.database import get_db
from app.models.models import Driver, Race, RaceResult
from app.core.config import settings

router = APIRouter()

# 2026 F1 Driver Grid - Hardcoded fallback (used only if the DB has no
# race_results yet for the current season)
DRIVERS_2026 = [
    {"driver_id": "max_verstappen", "driver_number": 1, "driver_code": "VER", "driver_forename": "Max", "driver_surname": "Verstappen", "driver_full_name": "Max Verstappen", "nationality": "Dutch", "team_id": "red_bull"},
    {"driver_id": "liam_lawson", "driver_number": 11, "driver_code": "LAW", "driver_forename": "Liam", "driver_surname": "Lawson", "driver_full_name": "Liam Lawson", "nationality": "New Zealand", "team_id": "red_bull"},
    {"driver_id": "lando_norris", "driver_number": 4, "driver_code": "NOR", "driver_forename": "Lando", "driver_surname": "Norris", "driver_full_name": "Lando Norris", "nationality": "British", "team_id": "mclaren"},
    {"driver_id": "oscar_piastri", "driver_number": 81, "driver_code": "PIA", "driver_forename": "Oscar", "driver_surname": "Piastri", "driver_full_name": "Oscar Piastri", "nationality": "Australian", "team_id": "mclaren"},
    {"driver_id": "charles_leclerc", "driver_number": 16, "driver_code": "LEC", "driver_forename": "Charles", "driver_surname": "Leclerc", "driver_full_name": "Charles Leclerc", "nationality": "Monegasque", "team_id": "ferrari"},
    {"driver_id": "lewis_hamilton", "driver_number": 44, "driver_code": "HAM", "driver_forename": "Lewis", "driver_surname": "Hamilton", "driver_full_name": "Lewis Hamilton", "nationality": "British", "team_id": "ferrari"},
    {"driver_id": "george_russell", "driver_number": 63, "driver_code": "RUS", "driver_forename": "George", "driver_surname": "Russell", "driver_full_name": "George Russell", "nationality": "British", "team_id": "mercedes"},
    {"driver_id": "andrea_antonelli", "driver_number": 12, "driver_code": "ANT", "driver_forename": "Andrea", "driver_surname": "Antonelli", "driver_full_name": "Andrea Kimi Antonelli", "nationality": "Italian", "team_id": "mercedes"},
    {"driver_id": "fernando_alonso", "driver_number": 14, "driver_code": "ALO", "driver_forename": "Fernando", "driver_surname": "Alonso", "driver_full_name": "Fernando Alonso", "nationality": "Spanish", "team_id": "aston_martin"},
    {"driver_id": "lance_stroll", "driver_number": 18, "driver_code": "STR", "driver_forename": "Lance", "driver_surname": "Stroll", "driver_full_name": "Lance Stroll", "nationality": "Canadian", "team_id": "aston_martin"},
    {"driver_id": "pierre_gasly", "driver_number": 10, "driver_code": "GAS", "driver_forename": "Pierre", "driver_surname": "Gasly", "driver_full_name": "Pierre Gasly", "nationality": "French", "team_id": "alpine"},
    {"driver_id": "jack_doohan", "driver_number": 7, "driver_code": "DOO", "driver_forename": "Jack", "driver_surname": "Doohan", "driver_full_name": "Jack Doohan", "nationality": "Australian", "team_id": "alpine"},
    {"driver_id": "carlos_sainz", "driver_number": 55, "driver_code": "SAI", "driver_forename": "Carlos", "driver_surname": "Sainz", "driver_full_name": "Carlos Sainz", "nationality": "Spanish", "team_id": "williams"},
    {"driver_id": "alexander_albon", "driver_number": 23, "driver_code": "ALB", "driver_forename": "Alexander", "driver_surname": "Albon", "driver_full_name": "Alexander Albon", "nationality": "Thai", "team_id": "williams"},
    {"driver_id": "yuki_tsunoda", "driver_number": 22, "driver_code": "TSU", "driver_forename": "Yuki", "driver_surname": "Tsunoda", "driver_full_name": "Yuki Tsunoda", "nationality": "Japanese", "team_id": "rb"},
    {"driver_id": "isack_hadjar", "driver_number": 21, "driver_code": "HAD", "driver_forename": "Isack", "driver_surname": "Hadjar", "driver_full_name": "Isack Hadjar", "nationality": "French", "team_id": "rb"},
    {"driver_id": "nico_hulkenberg", "driver_number": 27, "driver_code": "HUL", "driver_forename": "Nico", "driver_surname": "Hulkenberg", "driver_full_name": "Nico Hulkenberg", "nationality": "German", "team_id": "sauber"},
    {"driver_id": "gabriel_bortoleto", "driver_number": 5, "driver_code": "BOR", "driver_forename": "Gabriel", "driver_surname": "Bortoleto", "driver_full_name": "Gabriel Bortoleto", "nationality": "Brazilian", "team_id": "sauber"},
    {"driver_id": "oliver_bearman", "driver_number": 87, "driver_code": "BEA", "driver_forename": "Oliver", "driver_surname": "Bearman", "driver_full_name": "Oliver Bearman", "nationality": "British", "team_id": "haas"},
    {"driver_id": "esteban_ocon", "driver_number": 31, "driver_code": "OCO", "driver_forename": "Esteban", "driver_surname": "Ocon", "driver_full_name": "Esteban Ocon", "nationality": "French", "team_id": "haas"},
]


def _get_current_grid(db: Session, year: int) -> List[DriverResponse]:
    """
    Determine the current grid from race_results: since drivers.team_id is
    never populated by the sync pipeline, a driver's current team is derived
    from their most recent race_result within the given season.
    """
    row_number = (
        func.row_number()
        .over(
            partition_by=RaceResult.driver_id,
            order_by=(Race.date.desc(), RaceResult.race_id.desc()),
        )
        .label("rn")
    )

    latest_results = (
        db.query(
            RaceResult.driver_id.label("driver_id"),
            RaceResult.team_id.label("current_team_id"),
            row_number,
        )
        .join(Race, Race.race_id == RaceResult.race_id)
        .filter(Race.year == year)
        .subquery()
    )

    rows = (
        db.query(Driver, latest_results.c.current_team_id)
        .join(latest_results, latest_results.c.driver_id == Driver.driver_id)
        .filter(latest_results.c.rn == 1)
        .all()
    )

    drivers_list = []
    for driver, team_id in rows:
        drivers_list.append(
            DriverResponse(
                driver_id=driver.driver_id,
                driver_number=driver.driver_number,
                driver_code=driver.driver_code,
                driver_forename=driver.driver_forename,
                driver_surname=driver.driver_surname,
                driver_full_name=driver.driver_full_name,
                nationality=driver.nationality,
                team_id=team_id,
            )
        )
    return drivers_list


@router.get("/", response_model=DriversListResponse)
async def get_drivers(db: Session = Depends(get_db)):
    """
    Get the current F1 grid, derived from the current season's race_results
    (each driver's most recent race in the season determines their team).

    Falls back to a hardcoded grid if the season has no results yet
    (e.g. before the first race of the year has been synced).
    """
    drivers_list = _get_current_grid(db, settings.CURRENT_SEASON)

    if not drivers_list:
        drivers_list = [DriverResponse(**driver) for driver in DRIVERS_2026]

    return DriversListResponse(drivers=drivers_list, count=len(drivers_list))
