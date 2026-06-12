import logging
import sqlite3
from datetime import datetime
from pathlib import Path


logger = logging.getLogger(__name__)


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "migrations"


def _migration_version(path: Path) -> int:
    prefix = path.stem.split("_", 1)[0]
    return int(prefix)


def _is_tolerated_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "duplicate column" in message or "no such column" in message


def _execute_tolerant(conn: sqlite3.Connection, sql: str, name: str) -> None:
    lines = sql.splitlines()
    body = "\n".join(lines[1:])
    for statement in body.split(";"):
        statement = statement.strip()
        if not statement:
            continue
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            if not _is_tolerated_error(exc):
                raise
            logger.info("Tolerated migration error in %s: %s", name, exc)


def apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT,
            applied_at TEXT
        )
        """
    )
    conn.commit()

    migrations_dir = _migrations_dir()
    if not migrations_dir.exists():
        logger.info("No migrations directory found: %s", migrations_dir)
        return

    applied = {
        row[0]
        for row in conn.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall()
    }
    migration_files = sorted(
        migrations_dir.glob("*.sql"),
        key=_migration_version,
    )

    for path in migration_files:
        version = _migration_version(path)
        if version in applied:
            continue

        sql = path.read_text(encoding="utf-8")
        first_line = sql.splitlines()[0] if sql.splitlines() else ""
        try:
            if first_line == "-- tolerant":
                _execute_tolerant(conn, sql, path.name)
            else:
                conn.executescript(sql)
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (version, path.name, datetime.utcnow().isoformat()),
            )
            conn.commit()
            applied.add(version)
            logger.info("Applied migration %s", path.name)
        except Exception:
            conn.rollback()
            logger.exception("Migration failed: %s", path.name)
            raise
