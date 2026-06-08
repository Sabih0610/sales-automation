##src\storage.py
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

    def update_from_enrichment(
        self,
        run_id: str,
        enriched_leads: list[dict],
    ) -> dict:
        """
        Update existing leads with enrichment data from ZoomInfo CSV.
        Matches by LinkedIn URL first, then first+last+company fallback.
        Only updates fields that ZoomInfo provided - never overwrites
        with empty values.

        enriched_leads: list of dicts with ZoomInfo column names
        Returns: {"matched": N, "unmatched": N, "updated": N}
        """
        existing = self.get_by_run(run_id)
        if not existing:
            return {"matched": 0, "unmatched": len(enriched_leads), "updated": 0}

        by_linkedin: dict[str, Lead] = {}
        by_name_company: dict[str, Lead] = {}

        for lead in existing:
            if lead.linkedin_url:
                key = lead.linkedin_url.lower().rstrip("/").split("?")[0]
                by_linkedin[key] = lead
            name_key = (
                f"{lead.first_name.lower().strip()}"
                f"|{lead.last_name.lower().strip()}"
                f"|{lead.company.lower().strip()}"
            )
            by_name_company[name_key] = lead

        matched = 0
        unmatched = 0
        updated_leads = []

        for row in enriched_leads:
            zi_linkedin = (
                row.get("LinkedIn URL", "")
                or row.get("linkedin_url", "")
                or row.get("LinkedIn", "")
            ).lower().rstrip("/").split("?")[0]

            lead = None
            if zi_linkedin:
                lead = by_linkedin.get(zi_linkedin)

            if not lead:
                zi_first = (
                    row.get("First Name", "")
                    or row.get("first_name", "")
                ).lower().strip()
                zi_last = (
                    row.get("Last Name", "")
                    or row.get("last_name", "")
                ).lower().strip()
                zi_company = (
                    row.get("Company Name", "")
                    or row.get("company", "")
                    or row.get("Company", "")
                ).lower().strip()
                name_key = f"{zi_first}|{zi_last}|{zi_company}"
                lead = by_name_company.get(name_key)

            if not lead:
                unmatched += 1
                continue

            matched += 1

            zi_email = (
                row.get("Email Address", "")
                or row.get("email", "")
                or row.get("Email", "")
            ).strip()
            if zi_email and not lead.email:
                lead.email = zi_email
                lead.email_confidence = "zoominfo_verified"

            zi_phone = (
                row.get("Direct Phone Number", "")
                or row.get("Phone", "")
                or row.get("phone", "")
                or row.get("Company Phone", "")
            ).strip()
            if zi_phone and not lead.phone:
                lead.phone = zi_phone

            zi_domain = (
                row.get("Company Website", "")
                or row.get("company_domain", "")
                or row.get("Website", "")
            ).strip()
            if zi_domain:
                import re

                zi_domain = re.sub(r"https?://(www\.)?", "", zi_domain).rstrip("/")
                if zi_domain and not lead.company_domain:
                    lead.company_domain = zi_domain

            zi_title = (
                row.get("Job Title", "")
                or row.get("title", "")
                or row.get("Title", "")
            ).strip()
            if zi_title and not lead.title:
                lead.title = zi_title

            zi_intent = (
                row.get("Intent Score", "")
                or row.get("intent_score", "")
                or row.get("IntentScore", "")
            )
            try:
                intent_val = float(zi_intent)
                if intent_val > 0:
                    lead.intent_score = intent_val
            except (ValueError, TypeError):
                pass

            zi_location_parts = []
            for col in ["City", "State", "Country"]:
                val = row.get(col, "").strip()
                if val:
                    zi_location_parts.append(val)
            if zi_location_parts and not lead.location:
                lead.location = ", ".join(zi_location_parts)

            from datetime import datetime

            lead.updated_at = datetime.utcnow()
            updated_leads.append(lead)

        if updated_leads:
            self.save_batch(run_id, updated_leads)

        return {
            "matched": matched,
            "unmatched": unmatched,
            "updated": len(updated_leads),
        }

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
