from pydantic import BaseModel
from typing import List, Optional


class DriverResponse(BaseModel):
    driver_id: str
    driver_number: Optional[int] = None
    driver_code: Optional[str] = None
    driver_forename: str
    driver_surname: str
    driver_full_name: str
    nationality: Optional[str] = None
    team_id: Optional[str] = None

    class Config:
        from_attributes = True


class DriversListResponse(BaseModel):
    drivers: List[DriverResponse]
    count: int
