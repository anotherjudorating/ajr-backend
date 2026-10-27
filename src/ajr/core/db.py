from sqlalchemy import create_engine

from ajr.core.settings import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    # Supabase's transaction pooler does not support prepared statements.
    connect_args={"prepare_threshold": None},
)
