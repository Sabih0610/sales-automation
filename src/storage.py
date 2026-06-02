import contextlib
import json
import sqlite3
import threading

from src.config import settings
from src.models import (
    AgentEvent,
    EnrichmentMode,
    EventType,
    Lead,
    LeadStatus,
    Optional,
    PipelineRun,
    RunStatus,
    Segment,
    datetime,
)


def _dt_to_text(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _text_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(value)
    return None


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id TEXT PRIMARY KEY,
                    status TEXT, filters TEXT, enrichment_mode TEXT,
                    total_scraped INT DEFAULT 0, total_enriched INT DEFAULT 0,
                    total_warm INT DEFAULT 0, total_cold INT DEFAULT 0,
                    total_no_email INT DEFAULT 0, total_exported INT DEFAULT 0,
                    error TEXT DEFAULT '', started_at TEXT, completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY, run_id TEXT,
                    full_name TEXT, first_name TEXT, last_name TEXT,
                    title TEXT, company TEXT, company_domain TEXT,
                    location TEXT, linkedin_url TEXT, company_linkedin_url TEXT,
                    email TEXT, email_confidence TEXT, phone TEXT,
                    intent_score REAL DEFAULT 0, segment TEXT, status TEXT,
                    created_at TEXT, updated_at TEXT,
                    FOREIGN KEY(run_id) REFERENCES pipeline_runs(id)
                );
                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT, event_type TEXT, agent_name TEXT,
                    payload TEXT, error TEXT, timestamp TEXT
                );
                CREATE TABLE IF NOT EXISTS run_checkpoints (
                    run_id TEXT PRIMARY KEY,
                    last_page INT DEFAULT 0,
                    leads_collected INT DEFAULT 0,
                    updated_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_leads_run ON leads(run_id);
                CREATE INDEX IF NOT EXISTS idx_events_run ON agent_events(run_id);
                """
            )


class RunRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, run: PipelineRun) -> None:
        with self.db._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pipeline_runs (
                    id, status, filters, enrichment_mode,
                    total_scraped, total_enriched, total_warm, total_cold,
                    total_no_email, total_exported, error, started_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.status.value,
                    json.dumps(run.filters, default=str),
                    run.enrichment_mode.value,
                    run.total_scraped,
                    run.total_enriched,
                    run.total_warm,
                    run.total_cold,
                    run.total_no_email,
                    run.total_exported,
                    run.error,
                    _dt_to_text(run.started_at),
                    _dt_to_text(run.completed_at),
                ),
            )

    def get(self, run_id: str) -> Optional[PipelineRun]:
        row = self.db._conn().execute(
            "SELECT * FROM pipeline_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def list_all(self) -> list[PipelineRun]:
        rows = self.db._conn().execute(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC"
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def update_status(
        self,
        run_id: str,
        status: RunStatus,
        error: str = "",
    ) -> None:
        with self.db._conn() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status = ?, error = ?
                WHERE id = ?
                """,
                (status.value, error, run_id),
            )

    def update_checkpoint(
        self,
        run_id: str,
        last_page: int,
        leads_collected: int,
    ) -> None:
        with self.db._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO run_checkpoints (
                    run_id, last_page, leads_collected, updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    run_id,
                    last_page,
                    leads_collected,
                    _dt_to_text(datetime.utcnow()),
                ),
            )

    def get_checkpoint(self, run_id: str) -> Optional[dict]:
        row = self.db._conn().execute(
            """
            SELECT last_page, leads_collected
            FROM run_checkpoints
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "last_page": row["last_page"] or 0,
            "leads_collected": row["leads_collected"] or 0,
        }

    def _row_to_run(self, row: sqlite3.Row) -> PipelineRun:
        return PipelineRun(
            id=row["id"],
            status=RunStatus(row["status"]),
            filters=json.loads(row["filters"] or "{}"),
            enrichment_mode=EnrichmentMode(row["enrichment_mode"]),
            total_scraped=row["total_scraped"] or 0,
            total_enriched=row["total_enriched"] or 0,
            total_warm=row["total_warm"] or 0,
            total_cold=row["total_cold"] or 0,
            total_no_email=row["total_no_email"] or 0,
            total_exported=row["total_exported"] or 0,
            error=row["error"] or "",
            started_at=_text_to_dt(row["started_at"]) or datetime.utcnow(),
            completed_at=_text_to_dt(row["completed_at"]),
        )


class LeadRepository:
    def __init__(self, db: Database):
        self.db = db

    def save_batch(self, run_id: str, leads: list[Lead]) -> None:
        rows = [
            (
                lead.id,
                run_id,
                lead.full_name,
                lead.first_name,
                lead.last_name,
                lead.title,
                lead.company,
                lead.company_domain,
                lead.location,
                lead.linkedin_url,
                lead.company_linkedin_url,
                lead.email,
                lead.email_confidence,
                lead.phone,
                lead.intent_score,
                lead.segment.value,
                lead.status.value,
                _dt_to_text(lead.created_at),
                _dt_to_text(lead.updated_at),
            )
            for lead in leads
        ]
        with self.db._conn() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO leads (
                    id, run_id, full_name, first_name, last_name,
                    title, company, company_domain, location, linkedin_url,
                    company_linkedin_url, email, email_confidence, phone,
                    intent_score, segment, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            sample = self.db._conn().execute(
                "SELECT full_name, phone FROM leads ORDER BY rowid DESC LIMIT 3"
            ).fetchall()
            import logging

            logging.getLogger(__name__).info(f"DB phone check: {sample}")

    def get_by_run(self, run_id: str) -> list[Lead]:
        rows = self.db._conn().execute(
            "SELECT * FROM leads WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
        return [self._row_to_lead(row) for row in rows]

    def count_by_segment(self, run_id: str) -> dict:
        counts = {"warm": 0, "cold": 0, "no_email": 0}
        rows = self.db._conn().execute(
            """
            SELECT segment, COUNT(*) AS total
            FROM leads
            WHERE run_id = ?
            GROUP BY segment
            """,
            (run_id,),
        ).fetchall()
        for row in rows:
            if row["segment"] == Segment.WARM.value:
                counts["warm"] = row["total"]
            elif row["segment"] == Segment.COLD.value:
                counts["cold"] = row["total"]
            elif row["segment"] == Segment.NO_EMAIL.value:
                counts["no_email"] = row["total"]
        return counts

    def _row_to_lead(self, row: sqlite3.Row) -> Lead:
        return Lead(
            id=row["id"],
            full_name=row["full_name"] or "",
            first_name=row["first_name"] or "",
            last_name=row["last_name"] or "",
            title=row["title"] or "",
            company=row["company"] or "",
            company_domain=row["company_domain"] or "",
            location=row["location"] or "",
            linkedin_url=row["linkedin_url"] or "",
            company_linkedin_url=row["company_linkedin_url"] or "",
            email=row["email"] or "",
            email_confidence=row["email_confidence"] or "",
            phone=row["phone"] or "",
            intent_score=row["intent_score"] or 0.0,
            segment=Segment(row["segment"]),
            status=LeadStatus(row["status"]),
            created_at=_text_to_dt(row["created_at"]) or datetime.utcnow(),
            updated_at=_text_to_dt(row["updated_at"]) or datetime.utcnow(),
        )


class EventRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, event: AgentEvent) -> None:
        with self.db._conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_events (
                    run_id, event_type, agent_name, payload, error, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.event_type.value,
                    event.agent_name,
                    json.dumps(event.payload, default=str),
                    event.error,
                    _dt_to_text(event.timestamp),
                ),
            )

    def get_by_run(self, run_id: str, limit: int = 100) -> list[dict]:
        rows = self.db._conn().execute(
            """
            SELECT run_id, event_type, agent_name, payload, error, timestamp
            FROM agent_events
            WHERE run_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "event_type": row["event_type"],
                "agent_name": row["agent_name"],
                "payload": json.loads(row["payload"] or "{}"),
                "error": row["error"] or "",
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]


db = Database(str(settings.db_path))
run_repo = RunRepository(db)
lead_repo = LeadRepository(db)
event_repo = EventRepository(db)
