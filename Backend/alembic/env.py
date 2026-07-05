from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add Backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Import your models Base
from app.models.models import Base

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate
target_metadata = Base.metadata

# Migrations need a session-level connection (DDL, explicit transactions,
# search_path) — DATABASE_URL points at Supabase's transaction-pooling
# connection (PgBouncer), which doesn't reliably preserve that across pooled
# backend connections and can fail with e.g. "no schema has been selected to
# create in" on CREATE TABLE. MIGRATIONS_DATABASE_URL should be Supabase's
# direct (session-mode) connection string instead. Falls back to
# DATABASE_URL so environments that only define one (e.g. a plain local
# Postgres with no pooler) keep working unchanged.
def _migrations_url() -> str:
    return os.getenv('MIGRATIONS_DATABASE_URL') or os.getenv('DATABASE_URL')


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = _migrations_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Get config section and add database URL
    configuration = config.get_section(config.config_ini_section, {})
    configuration['sqlalchemy.url'] = _migrations_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()