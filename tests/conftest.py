import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from clinical_data_platform.database import connect_database

DATABASE_URL = os.getenv("DATABASE_URL")


@pytest.fixture
def clean_database_connection() -> Iterator[psycopg.Connection[Any]]:
    """Provide a PostgreSQL connection with no platform schemas or migration history."""
    if DATABASE_URL is None:
        pytest.skip("DATABASE_URL is not configured")

    with connect_database(DATABASE_URL) as connection:
        connection.execute(
            """
            DROP SCHEMA IF EXISTS analytics CASCADE;
            DROP SCHEMA IF EXISTS clinical CASCADE;
            DROP SCHEMA IF EXISTS audit CASCADE;
            DROP TABLE IF EXISTS public.schema_migrations;
            """,
            prepare=False,
        )
        connection.commit()
        yield connection
        connection.rollback()
        connection.execute(
            """
            DROP SCHEMA IF EXISTS analytics CASCADE;
            DROP SCHEMA IF EXISTS clinical CASCADE;
            DROP SCHEMA IF EXISTS audit CASCADE;
            DROP TABLE IF EXISTS public.schema_migrations;
            """,
            prepare=False,
        )
        connection.commit()
