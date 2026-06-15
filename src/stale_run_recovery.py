from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.storage import db

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _table_exists(name: str) -> bool:
    row = db.conn().execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (name,),
    ).fetchone()
    return row is not None


def recover_stale_running_runs() -> dict:
    """Recover scraper/bulk jobs that were RUNNING before backend restart.

    If the backend process stops, its in-memory scraper threads are gone.
    Any DB row still marked RUNNING is stale and should not remain active.
    """
    now = _utcnow()
    recovered_runs = 0
    recovered_bulk_jobs = 0

    try:
        with db.conn() as conn:
            if _table_exists("pipeline_runs"):
                cur = conn.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = 'FAILED',
                        error = CASE
                            WHEN error IS NULL OR error = ''
                            THEN 'Run marked stale after backend/browser stopped before completion.'
                            ELSE error
                        END,
                        completed_at = ?
                    WHERE status = 'RUNNING'
                    """,
                    (now,),
                )
                recovered_runs = int(cur.rowcount or 0)

            if _table_exists("bulk_scrape_jobs"):
                cur = conn.execute(
                    """
                    UPDATE bulk_scrape_jobs
                    SET status = 'failed',
                        error = CASE
                            WHEN error IS NULL OR error = ''
                            THEN 'Bulk scrape marked stale after backend stopped before completion.'
                            ELSE error
                        END,
                        completed_at = COALESCE(completed_at, ?),
                        updated_at = ?
                    WHERE status IN ('queued', 'running')
                    """,
                    (now, now),
                )
                recovered_bulk_jobs = int(cur.rowcount or 0)

        if recovered_runs or recovered_bulk_jobs:
            logger.warning(
                "Recovered stale jobs on startup: runs=%s bulk_jobs=%s",
                recovered_runs,
                recovered_bulk_jobs,
            )

        return {
            "recovered_runs": recovered_runs,
            "recovered_bulk_jobs": recovered_bulk_jobs,
        }
    except Exception:
        logger.exception("Failed to recover stale running jobs")
        return {
            "recovered_runs": recovered_runs,
            "recovered_bulk_jobs": recovered_bulk_jobs,
            "error": "Failed to recover stale running jobs",
        }
