import json
import logging
import threading
import time
from datetime import datetime
from uuid import uuid4

from src.config import settings
from src.models import RunStatus
from src.storage import db, lead_repo, run_repo


logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.utcnow().isoformat()


def _json_loads(value: str, fallback):
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


class BulkScrapeManager:
    """
    Parent bulk scraping manager.

    The user starts one bulk job with a large target count.
    Internally this manager runs normal child scrape runs in batches.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._orchestrator = None
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with db.conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bulk_scrape_jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    start_url TEXT NOT NULL,
                    campaign_key TEXT,
                    target_leads INTEGER NOT NULL DEFAULT 0,
                    batch_max_leads INTEGER NOT NULL DEFAULT 1000,
                    batch_page_limit INTEGER NOT NULL DEFAULT 25,
                    current_page INTEGER NOT NULL DEFAULT 1,
                    total_saved INTEGER NOT NULL DEFAULT 0,
                    child_run_ids TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )

    def _row_to_job(self, row) -> dict | None:
        if row is None:
            return None

        return {
            "id": row["id"],
            "status": row["status"],
            "start_url": row["start_url"],
            "campaign_key": row["campaign_key"] or "",
            "target_leads": int(row["target_leads"] or 0),
            "batch_max_leads": int(row["batch_max_leads"] or 1000),
            "batch_page_limit": int(row["batch_page_limit"] or 25),
            "current_page": int(row["current_page"] or 1),
            "total_saved": int(row["total_saved"] or 0),
            "child_run_ids": _json_loads(row["child_run_ids"], []),
            "error": row["error"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
            "progress_pct": (
                round((int(row["total_saved"] or 0) / int(row["target_leads"] or 1)) * 100, 2)
                if int(row["target_leads"] or 0) > 0
                else 0
            ),
        }

    def get(self, job_id: str) -> dict | None:
        row = db.conn().execute(
            """
            SELECT *
            FROM bulk_scrape_jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
        return self._row_to_job(row)

    def list_recent(self, limit: int = 20) -> list[dict]:
        rows = db.conn().execute(
            """
            SELECT *
            FROM bulk_scrape_jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def find_job_by_child_run_id(self, run_id: str) -> dict | None:
        rows = db.conn().execute(
            """
            SELECT *
            FROM bulk_scrape_jobs
            ORDER BY created_at DESC
            """
        ).fetchall()

        for row in rows:
            job = self._row_to_job(row)
            if job and run_id in set(job.get("child_run_ids") or []):
                return job

        return None

    def _request_stop_for_latest_child(self, job: dict) -> str:
        child_run_ids = list(job.get("child_run_ids") or [])
        for child_run_id in reversed(child_run_ids):
            child = run_repo.get(child_run_id)
            if child and child.status == RunStatus.RUNNING:
                try:
                    run_repo.request_control(child_run_id, "stop")
                except Exception:
                    logger.exception("Could not request stop for child run %s", child_run_id)
                return child_run_id
        return ""

    def _update(self, job_id: str, **fields) -> None:
        if not fields:
            return

        fields["updated_at"] = _utcnow()

        columns = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values())

        with db.conn() as conn:
            conn.execute(
                f"""
                UPDATE bulk_scrape_jobs
                SET {columns}
                WHERE id = ?
                """,
                [*values, job_id],
            )

    def _count_child_leads(self, child_run_ids: list[str]) -> int:
        if not child_run_ids:
            return 0

        placeholders = ",".join("?" for _ in child_run_ids)
        row = db.conn().execute(
            f"""
            SELECT COUNT(*) AS total
            FROM leads
            WHERE run_id IN ({placeholders})
            """,
            child_run_ids,
        ).fetchone()

        return int(row["total"] or 0) if row else 0

    def start(
        self,
        orchestrator,
        *,
        start_url: str,
        campaign_key: str = "",
        target_leads: int,
        batch_max_leads: int = 1000,
        batch_page_limit: int = 25,
    ) -> dict:
        start_url = (start_url or "").strip()
        campaign_key = (campaign_key or "").strip()

        if not start_url:
            raise ValueError("start_url is required")

        target_leads = max(1, int(target_leads or 1))
        batch_max_leads = max(1, min(int(batch_max_leads or 1000), 5000))
        batch_page_limit = max(1, min(int(batch_page_limit or 25), 250))

        job_id = uuid4().hex
        now = _utcnow()

        with db.conn() as conn:
            conn.execute(
                """
                INSERT INTO bulk_scrape_jobs (
                    id, status, start_url, campaign_key,
                    target_leads, batch_max_leads, batch_page_limit,
                    current_page, total_saved, child_run_ids,
                    error, created_at, updated_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    "queued",
                    start_url,
                    campaign_key,
                    target_leads,
                    batch_max_leads,
                    batch_page_limit,
                    1,
                    0,
                    "[]",
                    "",
                    now,
                    now,
                    None,
                ),
            )

        self._orchestrator = orchestrator
        self._spawn(job_id)

        return self.get(job_id)

    def pause(self, job_id: str) -> dict:
        job = self.get(job_id)
        if not job:
            raise ValueError("Bulk scrape job not found")
        if job["status"] in {"completed", "cancelled"}:
            return job

        self._request_stop_for_latest_child(job)
        self._update(
            job_id,
            status="paused",
            error="Paused by user. Current scrape child was stopped safely.",
        )
        return self.get(job_id)

    def cancel(self, job_id: str) -> dict:
        job = self.get(job_id)
        if not job:
            raise ValueError("Bulk scrape job not found")

        self._request_stop_for_latest_child(job)
        self._update(
            job_id,
            status="cancelled",
            error="Cancelled by user. Current scrape child was stopped safely.",
            completed_at=_utcnow(),
        )
        return self.get(job_id)

    def resume(self, orchestrator, job_id: str) -> dict:
        job = self.get(job_id)
        if not job:
            raise ValueError("Bulk scrape job not found")

        if job["status"] == "completed":
            return job

        self._orchestrator = orchestrator
        self._update(job_id, status="queued", error="")
        self._spawn(job_id)

        return self.get(job_id)

    def _spawn(self, job_id: str) -> None:
        with self._lock:
            existing = self._threads.get(job_id)
            if existing and existing.is_alive():
                return

            thread = threading.Thread(
                target=self._run_job,
                args=(job_id,),
                daemon=True,
                name=f"bulk-scrape-{job_id[:8]}",
            )
            self._threads[job_id] = thread
            thread.start()

    def _run_job(self, job_id: str) -> None:
        if self._orchestrator is None:
            self._update(
                job_id,
                status="failed",
                error="Bulk scrape manager has no orchestrator attached.",
                completed_at=_utcnow(),
            )
            return

        self._update(job_id, status="running", error="")

        consecutive_failures = 0

        while True:
            job = self.get(job_id)
            if not job:
                return

            if job["status"] in {"paused", "cancelled", "completed"}:
                return

            if job["total_saved"] >= job["target_leads"]:
                self._update(job_id, status="completed", completed_at=_utcnow())
                return

            remaining = max(1, job["target_leads"] - job["total_saved"])
            child_target = min(job["batch_max_leads"], remaining)

            filters = {
                "start_url": job["start_url"],
                "campaign_key": job["campaign_key"],
                "campaign": job["campaign_key"],
                "start_page": job["current_page"],
                "batch_page_limit": job["batch_page_limit"],
                "bulk_scrape_job_id": job_id,
            }

            before_saved = job["total_saved"]
            current_child_runs = list(job["child_run_ids"])

            try:
                settings.max_leads = child_target
                run = self._orchestrator.start_pipeline(filters)

                current_child_runs.append(run.id)
                self._update(
                    job_id,
                    child_run_ids=json.dumps(current_child_runs),
                    error="",
                )

                while True:
                    child = run_repo.get(run.id)
                    if child and child.status in {
                        RunStatus.COMPLETED,
                        RunStatus.FAILED,
                    }:
                        break

                    latest_job = self.get(job_id)
                    if latest_job and latest_job["status"] in {"paused", "cancelled"}:
                        try:
                            run_repo.request_control(run.id, "stop")
                        except Exception:
                            logger.exception("Could not request stop for child run %s", run.id)
                        return

                    time.sleep(5)

                child = run_repo.get(run.id)
                checkpoint = run_repo.get_checkpoint(run.id)
                total_saved = self._count_child_leads(current_child_runs)

                next_page = job["current_page"]
                if checkpoint:
                    next_page = max(
                        next_page,
                        int(checkpoint.get("last_page") or next_page) + 1,
                    )

                self._update(
                    job_id,
                    total_saved=total_saved,
                    current_page=next_page,
                    child_run_ids=json.dumps(current_child_runs),
                )

                if child and child.status == RunStatus.COMPLETED:
                    if total_saved <= before_saved:
                        self._update(
                            job_id,
                            status="paused",
                            error=(
                                "No new leads were saved in the latest scrape batch. "
                                "Paused to avoid repeated Sales Navigator requests. "
                                "Check LinkedIn for Too Many Requests or exhausted results before resuming."
                            ),
                        )
                        return

                    consecutive_failures = 0
                    time.sleep(int(os.getenv("BULK_SCRAPE_BATCH_COOLDOWN_SECONDS", "300")))
                    continue

                consecutive_failures += 1
                error = child.error if child else "Child scrape run failed"
                if (
                    "too many requests" in (error or "").lower()
                    or "rate limit" in (error or "").lower()
                    or "try again later" in (error or "").lower()
                ):
                    self._update(
                        job_id,
                        status="paused",
                        error=(
                            "LinkedIn rate limit detected. Bulk scrape paused automatically. "
                            "Wait before resuming to avoid more requests."
                        ),
                    )
                    return
                    
                if "stopped by user" in (error or "").lower() or "stop requested" in (error or "").lower():
                    self._update(
                        job_id,
                        status="cancelled",
                        error="Stopped by user. Parent bulk scrape cancelled, no more child runs will start.",
                        completed_at=_utcnow(),
                    )
                    return

                # If we made progress, keep going. If not, retry a few times.
                if total_saved > before_saved:
                    consecutive_failures = 0
                    self._update(job_id, error=f"Recovered after child error: {error}")
                    continue

                if consecutive_failures >= 3:
                    self._update(
                        job_id,
                        status="failed",
                        error=error,
                        completed_at=_utcnow(),
                    )
                    return

                self._update(
                    job_id,
                    error=f"Child run failed, retrying ({consecutive_failures}/3): {error}",
                )
                time.sleep(10)

            except Exception as exc:
                consecutive_failures += 1
                logger.exception("Bulk scrape child batch failed")
                error = str(exc) or repr(exc)

                if "stopped by user" in (error or "").lower() or "stop requested" in (error or "").lower():
                    self._update(
                        job_id,
                        status="cancelled",
                        error="Stopped by user. Parent bulk scrape cancelled, no more child runs will start.",
                        completed_at=_utcnow(),
                    )
                    return

                if consecutive_failures >= 3:
                    self._update(
                        job_id,
                        status="failed",
                        error=error,
                        completed_at=_utcnow(),
                    )
                    return

                self._update(
                    job_id,
                    error=f"Bulk scrape retrying ({consecutive_failures}/3): {error}",
                )
                time.sleep(10)


bulk_scrape_manager = BulkScrapeManager()
