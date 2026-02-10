"""SQLite connection management for conversation persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.database.config import DatabaseSettings


def get_database_connection(
    settings: DatabaseSettings | None = None,
) -> sqlite3.Connection:
    """Get or create a SQLite database connection.

    Creates the database file and parent directories if they don't exist.
    Initializes the schema on first connection.

    Args:
        settings: DatabaseSettings instance. If None, uses default settings.

    Returns:
        SQLite connection object configured for the conversations database.
    """
    if settings is None:
        settings = DatabaseSettings()

    # Ensure parent directory exists
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Connect to database
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row

    # Initialize schema
    _initialize_schema(conn)

    return conn


def _initialize_schema(conn: sqlite3.Connection) -> None:
    """Initialize the database schema by running migration files.

    Migrations are run in sorted order (001_initial.sql, 002_add_..., etc).
    ALTER TABLE statements are wrapped in try/except to handle idempotency.

    Args:
        conn: Active SQLite connection.
    """
    migrations_dir = Path(__file__).parent / "migrations"

    # Get all SQL migration files in sorted order
    migration_files = sorted(migrations_dir.glob("*.sql"))

    for migration_file in migration_files:
        with open(migration_file) as f:
            sql_content = f.read()

        # For ALTER TABLE statements, catch errors if column already exists
        if "ALTER TABLE" in sql_content:
            try:
                conn.executescript(sql_content)
            except sqlite3.OperationalError:
                # Column likely already exists, which is fine
                pass
        else:
            conn.executescript(sql_content)

        conn.commit()
