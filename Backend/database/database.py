from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
POOL_SIZE = int(os.getenv('DATABASE_POOL_SIZE', 10))
MAX_OVERFLOW = int(os.getenv('DATABASE_MAX_OVERFLOW', 20))

# SQLAlchemy setup
Base = declarative_base()

# Single connection pool for the whole app — the ORM session (SessionLocal)
# and any raw psycopg2 access (via engine.raw_connection()) both draw from
# this one pool, so there's one place that owns connection limits.
engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependency for FastAPI
def get_db():
    """Get database session for FastAPI dependency injection"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()