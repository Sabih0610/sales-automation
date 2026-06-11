##src\storage.py
import contextlib
import json
import sqlite3
import threading

from src.config import settings
from src.models import (
    AgentEvent,
    CampaignSequenceRules,
    CampaignSequenceStep,
    EnrichmentMode,
    EventType,
    Lead,
    LeadActivity,
    LeadSequenceState,
    LeadSourceSegment,
    LeadStatus,
    LeadUniverse,
    Optional,
    OutreachDraft,
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
                CREATE TABLE IF NOT EXISTS lead_universes (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    campaign_filename TEXT,
                    source_type TEXT DEFAULT 'sales_navigator',
                    description TEXT DEFAULT '',
                    target_leads INT DEFAULT 0,
                    total_scraped INT DEFAULT 0,
                    total_unique INT DEFAULT 0,
                    status TEXT DEFAULT 'queued',
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS lead_source_segments (
                    id TEXT PRIMARY KEY,
                    universe_id TEXT,
                    campaign_filename TEXT,
                    source_url TEXT,
                    label TEXT,
                    filters_json TEXT DEFAULT '{}',
                    expected_count INT DEFAULT 0,
                    scraped_count INT DEFAULT 0,
                    unique_count INT DEFAULT 0,
                    duplicate_count INT DEFAULT 0,
                    status TEXT DEFAULT 'queued',
                    stop_reason TEXT DEFAULT '',
                    last_run_id TEXT DEFAULT '',
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY(universe_id) REFERENCES lead_universes(id)
                );
                CREATE TABLE IF NOT EXISTS campaign_sequence_steps (
                    id TEXT PRIMARY KEY,
                    campaign_filename TEXT NOT NULL,
                    touch_number INT NOT NULL,
                    touch_name TEXT DEFAULT '',
                    delay_days INT DEFAULT 0,
                    delay_value INT DEFAULT 0,
                    delay_unit TEXT DEFAULT 'days',
                    delay_type TEXT DEFAULT 'calendar_days',
                    send_time_mode TEXT DEFAULT 'same_as_previous',
                    fixed_send_time TEXT DEFAULT '',
                    subject_template TEXT DEFAULT '',
                    email_body_template TEXT DEFAULT '',
                    linkedin_message_template TEXT DEFAULT '',
                    is_active INT DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS campaign_sequence_rules (
                    id TEXT PRIMARY KEY,
                    campaign_filename TEXT NOT NULL UNIQUE,
                    timezone TEXT DEFAULT 'Asia/Karachi',
                    mode TEXT DEFAULT 'review',
                    stop_on_reply INT DEFAULT 1,
                    stop_on_bounce INT DEFAULT 1,
                    stop_on_unsubscribe INT DEFAULT 1,
                    skip_no_email INT DEFAULT 1,
                    skip_weekends INT DEFAULT 1,
                    send_window_start TEXT DEFAULT '09:00',
                    send_window_end TEXT DEFAULT '17:00',
                    daily_send_limit INT DEFAULT 50,
                    delay_between_sends_seconds INT DEFAULT 60,
                    require_approval_for_touch1 INT DEFAULT 1,
                    require_approval_for_followups INT DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS outreach_drafts (
                    id TEXT PRIMARY KEY,
                    lead_id TEXT NOT NULL,
                    campaign_filename TEXT NOT NULL,
                    touch_number INT NOT NULL,
                    subject TEXT DEFAULT '',
                    body TEXT DEFAULT '',
                    linkedin_message TEXT DEFAULT '',
                    status TEXT DEFAULT 'draft',
                    scheduled_for TEXT,
                    sent_at TEXT,
                    error_message TEXT DEFAULT '',
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY(lead_id) REFERENCES leads(id)
                );
                CREATE TABLE IF NOT EXISTS lead_sequence_state (
                    id TEXT PRIMARY KEY,
                    lead_id TEXT NOT NULL,
                    campaign_filename TEXT NOT NULL,
                    current_touch INT DEFAULT 0,
                    status TEXT DEFAULT 'not_started',
                    last_touch_sent_at TEXT,
                    next_touch_due_at TEXT,
                    completed_at TEXT,
                    stop_reason TEXT DEFAULT '',
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY(lead_id) REFERENCES leads(id)
                );
                CREATE TABLE IF NOT EXISTS lead_activities (
                    id TEXT PRIMARY KEY,
                    lead_id TEXT NOT NULL,
                    campaign_filename TEXT NOT NULL,
                    run_id TEXT DEFAULT '',
                    activity_type TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '',
                    created_at TEXT,
                    FOREIGN KEY(lead_id) REFERENCES leads(id)
                );
                CREATE INDEX IF NOT EXISTS idx_leads_run ON leads(run_id);
                CREATE INDEX IF NOT EXISTS idx_events_run ON agent_events(run_id);
                CREATE INDEX IF NOT EXISTS idx_segments_universe
                    ON lead_source_segments(universe_id);
                CREATE INDEX IF NOT EXISTS idx_universes_campaign
                    ON lead_universes(campaign_filename);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sequence_steps_campaign_touch
                    ON campaign_sequence_steps(campaign_filename, touch_number);
                CREATE INDEX IF NOT EXISTS idx_outreach_drafts_campaign
                    ON outreach_drafts(campaign_filename, status, touch_number);
                CREATE INDEX IF NOT EXISTS idx_outreach_drafts_lead
                    ON outreach_drafts(lead_id, campaign_filename, touch_number);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_active_outreach_draft
                    ON outreach_drafts(lead_id, campaign_filename, touch_number)
                    WHERE status NOT IN ('failed', 'skipped');
                CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_sequence_state
                    ON lead_sequence_state(lead_id, campaign_filename);
                CREATE INDEX IF NOT EXISTS idx_lead_sequence_due
                    ON lead_sequence_state(campaign_filename, status, next_touch_due_at);
                CREATE INDEX IF NOT EXISTS idx_lead_activities_campaign
                    ON lead_activities(campaign_filename, created_at);
                CREATE INDEX IF NOT EXISTS idx_lead_activities_lead
                    ON lead_activities(lead_id, campaign_filename, created_at);
                """
            )
            draft_columns = [
                ("email_subject", "TEXT DEFAULT ''"),
                ("email_body", "TEXT DEFAULT ''"),
                ("linkedin_message", "TEXT DEFAULT ''"),
                ("research_summary", "TEXT DEFAULT ''"),
                ("campaign_name", "TEXT DEFAULT ''"),
                ("personalised_at", "TEXT"),
                ("email_sequence_status", "TEXT DEFAULT 'not_started'"),
                ("day1_sent_at", "TEXT"),
                ("day3_sent_at", "TEXT"),
                ("day7_sent_at", "TEXT"),
                ("email_sequence_error", "TEXT DEFAULT ''"),
            ]
            existing = {
                row[1]
                for row in conn.execute("PRAGMA table_info(leads)").fetchall()
            }
            lead_source_columns = [
                ("lead_universe_id", "TEXT DEFAULT ''"),
                ("lead_source_segment_id", "TEXT DEFAULT ''"),
            ]
            for col_name, col_def in lead_source_columns:
                if col_name not in existing:
                    conn.execute(
                        f"ALTER TABLE leads ADD COLUMN {col_name} {col_def}"
                    )
                    existing.add(col_name)
            for col_name, col_def in draft_columns:
                if col_name not in existing:
                    conn.execute(
                        f"ALTER TABLE leads ADD COLUMN {col_name} {col_def}"
                    )
            sequence_step_columns = [
                ("delay_value", "INT DEFAULT 0"),
                ("delay_unit", "TEXT DEFAULT 'days'"),
                ("delay_type", "TEXT DEFAULT 'calendar_days'"),
                ("send_time_mode", "TEXT DEFAULT 'same_as_previous'"),
                ("fixed_send_time", "TEXT DEFAULT ''"),
            ]
            existing_steps = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(campaign_sequence_steps)"
                ).fetchall()
            }
            for col_name, col_def in sequence_step_columns:
                if col_name not in existing_steps:
                    conn.execute(
                        f"ALTER TABLE campaign_sequence_steps ADD COLUMN {col_name} {col_def}"
                    )
                    existing_steps.add(col_name)
            conn.execute(
                """
                UPDATE campaign_sequence_steps
                SET delay_value = COALESCE(NULLIF(delay_value, 0), delay_days),
                    delay_unit = COALESCE(NULLIF(delay_unit, ''), 'days'),
                    delay_type = COALESCE(NULLIF(delay_type, ''), 'calendar_days'),
                    send_time_mode = COALESCE(NULLIF(send_time_mode, ''), 'same_as_previous')
                """
            )
            sequence_rule_columns = [
                ("timezone", "TEXT DEFAULT 'Asia/Karachi'"),
                ("mode", "TEXT DEFAULT 'review'"),
                ("require_approval_for_touch1", "INT DEFAULT 1"),
                ("require_approval_for_followups", "INT DEFAULT 1"),
            ]
            existing_rules = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(campaign_sequence_rules)"
                ).fetchall()
            }
            for col_name, col_def in sequence_rule_columns:
                if col_name not in existing_rules:
                    conn.execute(
                        f"ALTER TABLE campaign_sequence_rules ADD COLUMN {col_name} {col_def}"
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


class LeadUniverseRepository:
    def __init__(self, db: Database):
        self.db = db

    def save_universe(self, universe: LeadUniverse) -> None:
        universe.updated_at = datetime.utcnow()
        with self.db._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO lead_universes (
                    id, name, campaign_filename, source_type, description,
                    target_leads, total_scraped, total_unique, status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    universe.id,
                    universe.name,
                    universe.campaign_filename,
                    universe.source_type,
                    universe.description,
                    universe.target_leads,
                    universe.total_scraped,
                    universe.total_unique,
                    universe.status,
                    _dt_to_text(universe.created_at),
                    _dt_to_text(universe.updated_at),
                ),
            )

    def get_universe(self, universe_id: str) -> Optional[LeadUniverse]:
        row = self.db._conn().execute(
            "SELECT * FROM lead_universes WHERE id = ?",
            (universe_id,),
        ).fetchone()
        return self._row_to_universe(row) if row else None

    def list_universes(self, campaign_filename: str | None = None) -> list[LeadUniverse]:
        params: list = []
        where = ""
        if campaign_filename:
            where = "WHERE campaign_filename = ?"
            params.append(campaign_filename)
        rows = self.db._conn().execute(
            f"""
            SELECT * FROM lead_universes
            {where}
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()
        return [self._row_to_universe(row) for row in rows]

    def save_segment(self, segment: LeadSourceSegment) -> None:
        segment.updated_at = datetime.utcnow()
        with self.db._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO lead_source_segments (
                    id, universe_id, campaign_filename, source_url, label,
                    filters_json, expected_count, scraped_count, unique_count,
                    duplicate_count, status, stop_reason, last_run_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment.id,
                    segment.universe_id,
                    segment.campaign_filename,
                    segment.source_url,
                    segment.label,
                    segment.filters_json,
                    segment.expected_count,
                    segment.scraped_count,
                    segment.unique_count,
                    segment.duplicate_count,
                    segment.status,
                    segment.stop_reason,
                    segment.last_run_id,
                    _dt_to_text(segment.created_at),
                    _dt_to_text(segment.updated_at),
                ),
            )

    def get_segment(self, segment_id: str) -> Optional[LeadSourceSegment]:
        row = self.db._conn().execute(
            "SELECT * FROM lead_source_segments WHERE id = ?",
            (segment_id,),
        ).fetchone()
        return self._row_to_segment(row) if row else None

    def list_segments(self, universe_id: str) -> list[LeadSourceSegment]:
        rows = self.db._conn().execute(
            """
            SELECT * FROM lead_source_segments
            WHERE universe_id = ?
            ORDER BY created_at ASC
            """,
            (universe_id,),
        ).fetchall()
        return [self._row_to_segment(row) for row in rows]

    def list_segments_for_campaign(self, campaign_filename: str) -> list[LeadSourceSegment]:
        rows = self.db._conn().execute(
            """
            SELECT * FROM lead_source_segments
            WHERE campaign_filename = ?
            ORDER BY created_at ASC
            """,
            (campaign_filename,),
        ).fetchall()
        return [self._row_to_segment(row) for row in rows]

    def next_queued_segment(self, universe_id: str) -> Optional[LeadSourceSegment]:
        row = self.db._conn().execute(
            """
            SELECT * FROM lead_source_segments
            WHERE universe_id = ? AND status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (universe_id,),
        ).fetchone()
        return self._row_to_segment(row) if row else None

    def update_segment_status(
        self,
        segment_id: str,
        status: str,
        stop_reason: str = "",
        last_run_id: str = "",
    ) -> None:
        with self.db._conn() as conn:
            conn.execute(
                """
                UPDATE lead_source_segments
                SET status = ?,
                    stop_reason = COALESCE(NULLIF(?, ''), stop_reason),
                    last_run_id = COALESCE(NULLIF(?, ''), last_run_id),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    stop_reason,
                    last_run_id,
                    _dt_to_text(datetime.utcnow()),
                    segment_id,
                ),
            )

    def update_segment_counts(
        self,
        segment_id: str,
        scraped_count: int,
        unique_count: int,
        duplicate_count: int,
        status: str,
        stop_reason: str,
        last_run_id: str,
    ) -> None:
        with self.db._conn() as conn:
            conn.execute(
                """
                UPDATE lead_source_segments
                SET scraped_count = ?,
                    unique_count = ?,
                    duplicate_count = ?,
                    status = ?,
                    stop_reason = ?,
                    last_run_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    scraped_count,
                    unique_count,
                    duplicate_count,
                    status,
                    stop_reason,
                    last_run_id,
                    _dt_to_text(datetime.utcnow()),
                    segment_id,
                ),
            )

    def pause_queued_segments(self, universe_id: str) -> int:
        with self.db._conn() as conn:
            cur = conn.execute(
                """
                UPDATE lead_source_segments
                SET status = 'blocked',
                    stop_reason = 'manual_stop',
                    updated_at = ?
                WHERE universe_id = ? AND status IN ('queued', 'running')
                """,
                (_dt_to_text(datetime.utcnow()), universe_id),
            )
            return cur.rowcount

    def refresh_universe_totals(self, universe_id: str) -> None:
        row = self.db._conn().execute(
            """
            SELECT
                COALESCE(SUM(scraped_count), 0) AS scraped,
                COALESCE(SUM(unique_count), 0) AS unique_total,
                SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued,
                SUM(CASE WHEN status IN ('failed', 'blocked') THEN 1 ELSE 0 END) AS blocked,
                COUNT(*) AS total
            FROM lead_source_segments
            WHERE universe_id = ?
            """,
            (universe_id,),
        ).fetchone()
        status = "queued"
        if row["running"]:
            status = "running"
        elif row["queued"]:
            status = "queued"
        elif row["blocked"]:
            status = "blocked"
        elif row["total"]:
            status = "completed"
        with self.db._conn() as conn:
            conn.execute(
                """
                UPDATE lead_universes
                SET total_scraped = ?,
                    total_unique = ?,
                    status = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    row["scraped"] or 0,
                    row["unique_total"] or 0,
                    status,
                    _dt_to_text(datetime.utcnow()),
                    universe_id,
                ),
            )

    def campaign_coverage(self, campaign_filename: str) -> dict:
        row = self.db._conn().execute(
            """
            SELECT
                COUNT(*) AS total_segments,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_segments,
                SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_segments,
                COALESCE(SUM(scraped_count), 0) AS total_scraped,
                COALESCE(SUM(unique_count), 0) AS unique_leads,
                COALESCE(SUM(duplicate_count), 0) AS duplicates_removed
            FROM lead_source_segments
            WHERE campaign_filename = ?
            """,
            (campaign_filename,),
        ).fetchone()
        return {
            "total_source_segments": row["total_segments"] or 0,
            "completed_segments": row["completed_segments"] or 0,
            "running_segments": row["running_segments"] or 0,
            "total_scraped": row["total_scraped"] or 0,
            "unique_leads": row["unique_leads"] or 0,
            "duplicates_removed": row["duplicates_removed"] or 0,
        }

    def _row_to_universe(self, row: sqlite3.Row) -> LeadUniverse:
        return LeadUniverse(
            id=row["id"],
            name=row["name"] or "",
            campaign_filename=row["campaign_filename"] or "",
            source_type=row["source_type"] or "sales_navigator",
            description=row["description"] or "",
            target_leads=row["target_leads"] or 0,
            total_scraped=row["total_scraped"] or 0,
            total_unique=row["total_unique"] or 0,
            status=row["status"] or "queued",
            created_at=_text_to_dt(row["created_at"]) or datetime.utcnow(),
            updated_at=_text_to_dt(row["updated_at"]) or datetime.utcnow(),
        )

    def _row_to_segment(self, row: sqlite3.Row) -> LeadSourceSegment:
        return LeadSourceSegment(
            id=row["id"],
            universe_id=row["universe_id"] or "",
            campaign_filename=row["campaign_filename"] or "",
            source_url=row["source_url"] or "",
            label=row["label"] or "",
            filters_json=row["filters_json"] or "{}",
            expected_count=row["expected_count"] or 0,
            scraped_count=row["scraped_count"] or 0,
            unique_count=row["unique_count"] or 0,
            duplicate_count=row["duplicate_count"] or 0,
            status=row["status"] or "queued",
            stop_reason=row["stop_reason"] or "",
            last_run_id=row["last_run_id"] or "",
            created_at=_text_to_dt(row["created_at"]) or datetime.utcnow(),
            updated_at=_text_to_dt(row["updated_at"]) or datetime.utcnow(),
        )


def _bool_to_int(value: bool) -> int:
    return 1 if bool(value) else 0


def _int_to_bool(value) -> bool:
    return bool(int(value or 0))


class CampaignSequenceRepository:
    def __init__(self, db: Database):
        self.db = db

    def save_step(self, step: CampaignSequenceStep) -> None:
        step.updated_at = datetime.utcnow()
        with self.db._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO campaign_sequence_steps (
                    id, campaign_filename, touch_number, touch_name,
                    delay_days, delay_value, delay_unit, delay_type,
                    send_time_mode, fixed_send_time, subject_template,
                    email_body_template, linkedin_message_template, is_active,
                    created_at, updated_at
                )
                VALUES (
                    COALESCE(
                        (SELECT id FROM campaign_sequence_steps
                         WHERE campaign_filename = ? AND touch_number = ?),
                        ?
                    ),
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    COALESCE(
                        (SELECT created_at FROM campaign_sequence_steps
                         WHERE campaign_filename = ? AND touch_number = ?),
                        ?
                    ),
                    ?
                )
                """,
                (
                    step.campaign_filename,
                    step.touch_number,
                    step.id,
                    step.campaign_filename,
                    step.touch_number,
                    step.touch_name,
                    step.delay_days,
                    step.delay_value if step.delay_value else step.delay_days,
                    step.delay_unit or "days",
                    step.delay_type or "calendar_days",
                    step.send_time_mode or "same_as_previous",
                    step.fixed_send_time or "",
                    step.subject_template,
                    step.email_body_template,
                    step.linkedin_message_template,
                    _bool_to_int(step.is_active),
                    step.campaign_filename,
                    step.touch_number,
                    _dt_to_text(step.created_at),
                    _dt_to_text(step.updated_at),
                ),
            )

    def list_steps(
        self,
        campaign_filename: str,
        active_only: bool = False,
    ) -> list[CampaignSequenceStep]:
        where = "campaign_filename = ?"
        params: list = [campaign_filename]
        if active_only:
            where += " AND is_active = 1"
        rows = self.db._conn().execute(
            f"""
            SELECT * FROM campaign_sequence_steps
            WHERE {where}
            ORDER BY touch_number ASC
            """,
            params,
        ).fetchall()
        return [self._row_to_step(row) for row in rows]

    def get_step(
        self,
        campaign_filename: str,
        touch_number: int,
        active_only: bool = False,
    ) -> Optional[CampaignSequenceStep]:
        where = "campaign_filename = ? AND touch_number = ?"
        params: list = [campaign_filename, touch_number]
        if active_only:
            where += " AND is_active = 1"
        row = self.db._conn().execute(
            f"SELECT * FROM campaign_sequence_steps WHERE {where}",
            params,
        ).fetchone()
        return self._row_to_step(row) if row else None

    def save_rules(self, rules: CampaignSequenceRules) -> None:
        rules.updated_at = datetime.utcnow()
        with self.db._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO campaign_sequence_rules (
                    id, campaign_filename, timezone, mode, stop_on_reply, stop_on_bounce,
                    stop_on_unsubscribe, skip_no_email, skip_weekends,
                    send_window_start, send_window_end, daily_send_limit,
                    delay_between_sends_seconds, require_approval_for_touch1,
                    require_approval_for_followups, created_at, updated_at
                )
                VALUES (
                    COALESCE(
                        (SELECT id FROM campaign_sequence_rules
                         WHERE campaign_filename = ?),
                        ?
                    ),
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    COALESCE(
                        (SELECT created_at FROM campaign_sequence_rules
                         WHERE campaign_filename = ?),
                        ?
                    ),
                    ?
                )
                """,
                (
                    rules.campaign_filename,
                    rules.id,
                    rules.campaign_filename,
                    rules.timezone,
                    rules.mode,
                    _bool_to_int(rules.stop_on_reply),
                    _bool_to_int(rules.stop_on_bounce),
                    _bool_to_int(rules.stop_on_unsubscribe),
                    _bool_to_int(rules.skip_no_email),
                    _bool_to_int(rules.skip_weekends),
                    rules.send_window_start,
                    rules.send_window_end,
                    rules.daily_send_limit,
                    rules.delay_between_sends_seconds,
                    _bool_to_int(rules.require_approval_for_touch1),
                    _bool_to_int(rules.require_approval_for_followups),
                    rules.campaign_filename,
                    _dt_to_text(rules.created_at),
                    _dt_to_text(rules.updated_at),
                ),
            )

    def get_rules(
        self,
        campaign_filename: str,
    ) -> Optional[CampaignSequenceRules]:
        row = self.db._conn().execute(
            """
            SELECT * FROM campaign_sequence_rules
            WHERE campaign_filename = ?
            """,
            (campaign_filename,),
        ).fetchone()
        return self._row_to_rules(row) if row else None

    def ensure_defaults(
        self,
        campaign_filename: str,
        default_steps: list[dict] | None = None,
    ) -> tuple[list[CampaignSequenceStep], CampaignSequenceRules]:
        steps = self.list_steps(campaign_filename)
        if not steps:
            defaults = default_steps or [
                {"number": 1, "name": "Intro", "delay_days": 0},
                {"number": 2, "name": "Follow-up", "delay_days": 3},
                {"number": 3, "name": "Final touch", "delay_days": 4},
            ]
            for item in defaults:
                self.save_step(CampaignSequenceStep(
                    campaign_filename=campaign_filename,
                    touch_number=int(item.get("number") or item.get("touch_number") or 1),
                    touch_name=item.get("name") or item.get("touch_name") or "",
                    delay_days=int(item.get("delay_days") or 0),
                    delay_value=int(item.get("delay_value") or item.get("delay_days") or 0),
                    delay_unit=item.get("delay_unit") or "days",
                    delay_type=item.get("delay_type") or "calendar_days",
                    send_time_mode=item.get("send_time_mode") or "same_as_previous",
                    fixed_send_time=item.get("fixed_send_time") or "",
                    subject_template=item.get("subject_template", "") or "",
                    email_body_template=item.get("email_body_template", "") or "",
                    linkedin_message_template=item.get(
                        "linkedin_message_template",
                        "",
                    ) or "",
                    is_active=bool(item.get("is_active", True)),
                ))
            steps = self.list_steps(campaign_filename)

        rules = self.get_rules(campaign_filename)
        if not rules:
            rules = CampaignSequenceRules(campaign_filename=campaign_filename)
            self.save_rules(rules)
        return steps, rules

    def _row_to_step(self, row: sqlite3.Row) -> CampaignSequenceStep:
        return CampaignSequenceStep(
            id=row["id"],
            campaign_filename=row["campaign_filename"] or "",
            touch_number=row["touch_number"] or 1,
            touch_name=row["touch_name"] or "",
            delay_days=row["delay_days"] or 0,
            delay_value=row["delay_value"] or row["delay_days"] or 0,
            delay_unit=row["delay_unit"] or "days",
            delay_type=row["delay_type"] or "calendar_days",
            send_time_mode=row["send_time_mode"] or "same_as_previous",
            fixed_send_time=row["fixed_send_time"] or "",
            subject_template=row["subject_template"] or "",
            email_body_template=row["email_body_template"] or "",
            linkedin_message_template=row["linkedin_message_template"] or "",
            is_active=_int_to_bool(row["is_active"]),
            created_at=_text_to_dt(row["created_at"]) or datetime.utcnow(),
            updated_at=_text_to_dt(row["updated_at"]) or datetime.utcnow(),
        )

    def _row_to_rules(self, row: sqlite3.Row) -> CampaignSequenceRules:
        return CampaignSequenceRules(
            id=row["id"],
            campaign_filename=row["campaign_filename"] or "",
            timezone=row["timezone"] or "Asia/Karachi",
            mode=row["mode"] or "review",
            stop_on_reply=_int_to_bool(row["stop_on_reply"]),
            stop_on_bounce=_int_to_bool(row["stop_on_bounce"]),
            stop_on_unsubscribe=_int_to_bool(row["stop_on_unsubscribe"]),
            skip_no_email=_int_to_bool(row["skip_no_email"]),
            skip_weekends=_int_to_bool(row["skip_weekends"]),
            send_window_start=row["send_window_start"] or "09:00",
            send_window_end=row["send_window_end"] or "17:00",
            daily_send_limit=row["daily_send_limit"] or 50,
            delay_between_sends_seconds=(
                row["delay_between_sends_seconds"] or 60
            ),
            require_approval_for_touch1=_int_to_bool(row["require_approval_for_touch1"]),
            require_approval_for_followups=_int_to_bool(row["require_approval_for_followups"]),
            created_at=_text_to_dt(row["created_at"]) or datetime.utcnow(),
            updated_at=_text_to_dt(row["updated_at"]) or datetime.utcnow(),
        )


class OutreachRepository:
    def __init__(self, db: Database):
        self.db = db

    def save_draft(self, draft: OutreachDraft) -> None:
        draft.updated_at = datetime.utcnow()
        with self.db._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO outreach_drafts (
                    id, lead_id, campaign_filename, touch_number, subject,
                    body, linkedin_message, status, scheduled_for, sent_at,
                    error_message, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.id,
                    draft.lead_id,
                    draft.campaign_filename,
                    draft.touch_number,
                    draft.subject,
                    draft.body,
                    draft.linkedin_message,
                    draft.status,
                    _dt_to_text(draft.scheduled_for),
                    _dt_to_text(draft.sent_at),
                    draft.error_message,
                    _dt_to_text(draft.created_at),
                    _dt_to_text(draft.updated_at),
                ),
            )

    def get_draft(self, draft_id: str) -> Optional[OutreachDraft]:
        row = self.db._conn().execute(
            "SELECT * FROM outreach_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        return self._row_to_draft(row) if row else None

    def get_drafts_by_ids(self, draft_ids: list[str]) -> list[OutreachDraft]:
        if not draft_ids:
            return []
        placeholders = ",".join("?" for _ in draft_ids)
        rows = self.db._conn().execute(
            f"""
            SELECT * FROM outreach_drafts
            WHERE id IN ({placeholders})
            ORDER BY created_at ASC
            """,
            draft_ids,
        ).fetchall()
        return [self._row_to_draft(row) for row in rows]

    def find_active_draft(
        self,
        lead_id: str,
        campaign_filename: str,
        touch_number: int,
    ) -> Optional[OutreachDraft]:
        row = self.db._conn().execute(
            """
            SELECT * FROM outreach_drafts
            WHERE lead_id = ?
              AND campaign_filename = ?
              AND touch_number = ?
              AND status NOT IN ('failed', 'skipped')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (lead_id, campaign_filename, touch_number),
        ).fetchone()
        return self._row_to_draft(row) if row else None

    def list_drafts(
        self,
        campaign_filename: str,
        status: str = "",
        touch_number: int | None = None,
        lead_id: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        where = ["d.campaign_filename = ?"]
        params: list = [campaign_filename]
        if status:
            where.append("d.status = ?")
            params.append(status)
        if touch_number:
            where.append("d.touch_number = ?")
            params.append(touch_number)
        if lead_id:
            where.append("d.lead_id = ?")
            params.append(lead_id)
        params.extend([limit, offset])
        rows = self.db._conn().execute(
            f"""
            SELECT
                d.id AS draft_id, d.lead_id, d.campaign_filename,
                d.touch_number, d.subject, d.body, d.linkedin_message,
                d.status, d.scheduled_for, d.sent_at, d.error_message,
                d.created_at, d.updated_at,
                l.run_id, l.full_name, l.company, l.title, l.email,
                l.location
            FROM outreach_drafts d
            JOIN leads l ON l.id = d.lead_id
            WHERE {" AND ".join(where)}
            ORDER BY d.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def update_draft(
        self,
        draft_id: str,
        fields: dict,
    ) -> Optional[OutreachDraft]:
        allowed = {
            "subject",
            "body",
            "linkedin_message",
            "status",
            "scheduled_for",
            "sent_at",
            "error_message",
        }
        updates = {
            key: value
            for key, value in fields.items()
            if key in allowed and value is not None
        }
        if not updates:
            return self.get_draft(draft_id)
        updates["updated_at"] = _dt_to_text(datetime.utcnow())
        set_clause = ", ".join(f"{key} = ?" for key in updates)
        values = [
            _dt_to_text(value) if isinstance(value, datetime) else value
            for value in updates.values()
        ]
        values.append(draft_id)
        with self.db._conn() as conn:
            conn.execute(
                f"UPDATE outreach_drafts SET {set_clause} WHERE id = ?",
                values,
            )
        return self.get_draft(draft_id)

    def count_sent_today(self, campaign_filename: str) -> int:
        today = datetime.utcnow().date().isoformat()
        row = self.db._conn().execute(
            """
            SELECT COUNT(*) AS total
            FROM outreach_drafts
            WHERE campaign_filename = ?
              AND status = 'sent'
              AND substr(sent_at, 1, 10) = ?
            """,
            (campaign_filename, today),
        ).fetchone()
        return row["total"] or 0

    def mark_future_pending_skipped(
        self,
        lead_id: str,
        campaign_filename: str,
        reason: str,
    ) -> int:
        with self.db._conn() as conn:
            cur = conn.execute(
                """
                UPDATE outreach_drafts
                SET status = 'skipped',
                    error_message = ?,
                    updated_at = ?
                WHERE lead_id = ?
                  AND campaign_filename = ?
                  AND status IN ('draft', 'approved', 'scheduled', 'failed')
                """,
                (
                    reason,
                    _dt_to_text(datetime.utcnow()),
                    lead_id,
                    campaign_filename,
                ),
            )
            return cur.rowcount

    def get_state(
        self,
        lead_id: str,
        campaign_filename: str,
    ) -> Optional[LeadSequenceState]:
        row = self.db._conn().execute(
            """
            SELECT * FROM lead_sequence_state
            WHERE lead_id = ? AND campaign_filename = ?
            """,
            (lead_id, campaign_filename),
        ).fetchone()
        return self._row_to_state(row) if row else None

    def upsert_state(self, state: LeadSequenceState) -> None:
        existing = self.get_state(state.lead_id, state.campaign_filename)
        if existing:
            state.id = existing.id
            state.created_at = existing.created_at
        state.updated_at = datetime.utcnow()
        with self.db._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO lead_sequence_state (
                    id, lead_id, campaign_filename, current_touch, status,
                    last_touch_sent_at, next_touch_due_at, completed_at,
                    stop_reason, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.id,
                    state.lead_id,
                    state.campaign_filename,
                    state.current_touch,
                    state.status,
                    _dt_to_text(state.last_touch_sent_at),
                    _dt_to_text(state.next_touch_due_at),
                    _dt_to_text(state.completed_at),
                    state.stop_reason,
                    _dt_to_text(state.created_at),
                    _dt_to_text(state.updated_at),
                ),
            )

    def get_or_create_state(
        self,
        lead_id: str,
        campaign_filename: str,
    ) -> LeadSequenceState:
        state = self.get_state(lead_id, campaign_filename)
        if state:
            return state
        state = LeadSequenceState(
            lead_id=lead_id,
            campaign_filename=campaign_filename,
        )
        self.upsert_state(state)
        return state

    def add_activity(self, activity: LeadActivity) -> None:
        with self.db._conn() as conn:
            conn.execute(
                """
                INSERT INTO lead_activities (
                    id, lead_id, campaign_filename, run_id, activity_type,
                    title, description, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activity.id,
                    activity.lead_id,
                    activity.campaign_filename,
                    activity.run_id,
                    activity.activity_type,
                    activity.title,
                    activity.description,
                    activity.metadata_json,
                    _dt_to_text(activity.created_at),
                ),
            )

    def list_lead_activities(
        self,
        lead_id: str,
        campaign_filename: str = "",
        limit: int = 100,
    ) -> list[dict]:
        where = ["lead_id = ?"]
        params: list = [lead_id]
        if campaign_filename:
            where.append("campaign_filename = ?")
            params.append(campaign_filename)
        params.append(limit)
        rows = self.db._conn().execute(
            f"""
            SELECT * FROM lead_activities
            WHERE {" AND ".join(where)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def list_campaign_activities(
        self,
        campaign_filename: str,
        limit: int = 100,
    ) -> list[dict]:
        rows = self.db._conn().execute(
            """
            SELECT a.*, l.full_name, l.company, l.email
            FROM lead_activities a
            LEFT JOIN leads l ON l.id = a.lead_id
            WHERE a.campaign_filename = ?
            ORDER BY a.created_at DESC
            LIMIT ?
            """,
            (campaign_filename, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def _row_to_draft(self, row: sqlite3.Row) -> OutreachDraft:
        return OutreachDraft(
            id=row["id"],
            lead_id=row["lead_id"] or "",
            campaign_filename=row["campaign_filename"] or "",
            touch_number=row["touch_number"] or 1,
            subject=row["subject"] or "",
            body=row["body"] or "",
            linkedin_message=row["linkedin_message"] or "",
            status=row["status"] or "draft",
            scheduled_for=_text_to_dt(row["scheduled_for"]),
            sent_at=_text_to_dt(row["sent_at"]),
            error_message=row["error_message"] or "",
            created_at=_text_to_dt(row["created_at"]) or datetime.utcnow(),
            updated_at=_text_to_dt(row["updated_at"]) or datetime.utcnow(),
        )

    def _row_to_state(self, row: sqlite3.Row) -> LeadSequenceState:
        return LeadSequenceState(
            id=row["id"],
            lead_id=row["lead_id"] or "",
            campaign_filename=row["campaign_filename"] or "",
            current_touch=row["current_touch"] or 0,
            status=row["status"] or "not_started",
            last_touch_sent_at=_text_to_dt(row["last_touch_sent_at"]),
            next_touch_due_at=_text_to_dt(row["next_touch_due_at"]),
            completed_at=_text_to_dt(row["completed_at"]),
            stop_reason=row["stop_reason"] or "",
            created_at=_text_to_dt(row["created_at"]) or datetime.utcnow(),
            updated_at=_text_to_dt(row["updated_at"]) or datetime.utcnow(),
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

    def get_by_id(self, lead_id: str) -> Optional[Lead]:
        row = self.db._conn().execute(
            "SELECT * FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()
        return self._row_to_lead(row) if row else None

    def delete_for_run(self, run_id: str, lead_ids: list[str]) -> int:
        if not lead_ids:
            return 0
        placeholders = ",".join("?" for _ in lead_ids)
        with self.db._conn() as conn:
            cur = conn.execute(
                f"""
                DELETE FROM leads
                WHERE run_id = ? AND id IN ({placeholders})
                """,
                [run_id, *lead_ids],
            )
            return cur.rowcount

    def tag_source(
        self,
        run_id: str,
        lead_ids: list[str],
        universe_id: str,
        segment_id: str,
    ) -> None:
        if not lead_ids:
            return
        placeholders = ",".join("?" for _ in lead_ids)
        with self.db._conn() as conn:
            conn.execute(
                f"""
                UPDATE leads
                SET lead_universe_id = ?,
                    lead_source_segment_id = ?,
                    updated_at = ?
                WHERE run_id = ? AND id IN ({placeholders})
                """,
                [
                    universe_id,
                    segment_id,
                    _dt_to_text(datetime.utcnow()),
                    run_id,
                    *lead_ids,
                ],
            )

    def update_lead_enrichment(self, lead_id: str, fields: dict) -> bool:
        existing = self.get_by_id(lead_id)
        if not existing:
            return False

        email = (fields.get("email") or "").strip()
        phone = (fields.get("phone") or "").strip()
        company_domain = (fields.get("company_domain") or "").strip()
        title = (fields.get("title") or "").strip()
        location = (fields.get("location") or "").strip()
        linkedin_url = (fields.get("linkedin_url") or "").strip()
        company_linkedin_url = (fields.get("company_linkedin_url") or "").strip()

        if not any([email, phone, company_domain, title, location, linkedin_url, company_linkedin_url]):
            return False

        if not email and not phone and not company_domain and not (
            title and not existing.title
        ) and not (
            location and not existing.location
        ) and not (
            linkedin_url and not existing.linkedin_url
        ) and not (
            company_linkedin_url and not existing.company_linkedin_url
        ):
            return False

        with self.db._conn() as conn:
            conn.execute(
                """
                UPDATE leads
                SET
                    email = COALESCE(NULLIF(:email, ''), email),
                    phone = COALESCE(NULLIF(:phone, ''), phone),
                    company_domain = COALESCE(NULLIF(:company_domain, ''), company_domain),
                    email_confidence = CASE
                        WHEN NULLIF(:email, '') IS NOT NULL THEN 'zoominfo_verified'
                        ELSE email_confidence
                    END,
                    title = CASE
                        WHEN NULLIF(:title, '') IS NOT NULL
                          AND COALESCE(NULLIF(title, ''), '') = ''
                        THEN :title
                        ELSE title
                    END,
                    location = CASE
                        WHEN NULLIF(:location, '') IS NOT NULL
                          AND COALESCE(NULLIF(location, ''), '') = ''
                        THEN :location
                        ELSE location
                    END,
                    linkedin_url = CASE
                        WHEN NULLIF(:linkedin_url, '') IS NOT NULL
                          AND COALESCE(NULLIF(linkedin_url, ''), '') = ''
                        THEN :linkedin_url
                        ELSE linkedin_url
                    END,
                    company_linkedin_url = CASE
                        WHEN NULLIF(:company_linkedin_url, '') IS NOT NULL
                          AND COALESCE(NULLIF(company_linkedin_url, ''), '') = ''
                        THEN :company_linkedin_url
                        ELSE company_linkedin_url
                    END,
                    updated_at = :updated_at
                WHERE id = :lead_id
                """,
                {
                    "email": email,
                    "phone": phone,
                    "company_domain": company_domain,
                    "title": title,
                    "location": location,
                    "linkedin_url": linkedin_url,
                    "company_linkedin_url": company_linkedin_url,
                    "updated_at": datetime.utcnow().isoformat(),
                    "lead_id": lead_id,
                },
            )
        return True

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
            if zi_email:
                lead.email = zi_email
                lead.email_confidence = "zoominfo_verified"

            zi_phone = (
                row.get("Direct Phone Number", "")
                or row.get("Phone", "")
                or row.get("phone", "")
                or row.get("Company Phone", "")
            ).strip()
            if zi_phone:
                lead.phone = zi_phone

            zi_domain = (
                row.get("Company Website", "")
                or row.get("company_domain", "")
                or row.get("Website", "")
            ).strip()
            if zi_domain:
                import re

                zi_domain = re.sub(r"https?://(www\.)?", "", zi_domain).rstrip("/")
                if zi_domain:
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
        lead = Lead(
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
        setattr(lead, "run_id", row["run_id"] or "")
        optional_fields = {
            "email_subject": "",
            "email_body": "",
            "linkedin_message": "",
            "research_summary": "",
            "campaign_name": "",
            "personalised_at": None,
            "email_sequence_status": "not_started",
            "day1_sent_at": None,
            "day3_sent_at": None,
            "day7_sent_at": None,
            "email_sequence_error": "",
        }
        row_keys = set(row.keys())
        for field, default in optional_fields.items():
            if field in row_keys:
                setattr(lead, field, row[field] or default)
        return lead


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
lead_universe_repo = LeadUniverseRepository(db)
campaign_sequence_repo = CampaignSequenceRepository(db)
outreach_repo = OutreachRepository(db)
