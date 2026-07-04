from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging
from contextlib import asynccontextmanager

from app.core.config import settings
from app.services.auto_updater import get_updater

from app.api.v1.endpoints.races import router as races_router
from routes.health import router as health_router
from app.api.v1.endpoints.predictions import router as predictions_router
from app.api.v1.endpoints.standings import router as standings_router
from app.api.v1.endpoints.races_data import router as races_data_router
from app.api.v1.endpoints.circuits import router as circuits_router
from app.api.v1.endpoints.simulator import router as simulator_router
from app.api.v1.endpoints.weather import router as weather_router
from app.api.v1.endpoints.news import router as news_router
from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.drivers import router as drivers_router

from database.database import Base, engine
import app.models.models

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def _seed_and_schedule(updater):
    """Runs the Jolpica-API-backed seeding off the event loop so a slow or
    unresponsive external API can't hang app startup (and take the whole
    deploy health check down with it, as happened in production)."""
    try:
        await asyncio.to_thread(updater.seed_race_calendar, 2026)
        await asyncio.to_thread(updater.seed_drivers_and_teams, 2026)
        await asyncio.to_thread(updater.seed_past_results, 2026)
        scheduled = await asyncio.to_thread(updater.schedule_upcoming_races, 2026)
        logger.info(f"Scheduled {scheduled} upcoming race updates")
    except Exception:
        logger.error("Background startup seeding failed", exc_info=True)


# Lifespan context manager for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events"""
    Base.metadata.create_all(bind=engine)

    # Startup
    logger.info("Starting F1 Predictor API...")
    updater = get_updater()
    updater.start_scheduler()
    logger.info("Auto-updater scheduler started")

    seed_task = asyncio.create_task(_seed_and_schedule(updater))

    yield

    # Shutdown
    logger.info("Shutting down F1 Predictor API...")
    seed_task.cancel()
    updater.stop_scheduler()
    logger.info("Auto-updater scheduler stopped")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="F1 Predictor API",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(races_router, prefix="/api/races", tags=["races"])
app.include_router(health_router)
app.include_router(predictions_router, prefix="/api/predictions", tags=["predictions"])
app.include_router(standings_router,   prefix="/api/standings",   tags=["standings"])
app.include_router(races_data_router,  prefix="/api/races",        tags=["data-center-races"])
app.include_router(circuits_router,    prefix="/api/circuits",     tags=["circuits"])
app.include_router(simulator_router,   prefix="/api/simulator",    tags=["simulator"])
app.include_router(weather_router,     prefix="/api/weather",      tags=["weather"])
app.include_router(news_router,        prefix="/api/news",         tags=["news"])
app.include_router(drivers_router,     prefix="/api/drivers",      tags=["drivers"])
app.include_router(admin_router,       prefix="/api/admin",        tags=["admin"])


@app.get("/health")
def health_check():
    return {"status": "ok", "version": settings.VERSION}

@app.get("/")
def root():
    return {"message": "F1 Predictor API", "docs": "/docs"}