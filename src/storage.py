##src\storage.py
import contextlib
import json
import re
import sqlite3
import threading
from uuid import uuid4
from datetime import date, timedelta
from src.campaign_config import validate_campaign_config
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
from src.sequence_modes import normalize_sequence_mode


def _dt_to_text(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _text_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(value)
    return None


STOPPED_SEQUENCE_STATUSES = {
    "replied",
    "bounced",
    "unsubscribed",
    "do_not_contact",
    "completed",
    "skipped",
}


def _normalize_campaign(value: str) -> str:
    return (
        (value or "")
        .replace(".json", "")
        .replace("_", " ")
        .lower()
        .strip()
    )


def _match_campaign(run_campaign: str, target: str) -> bool:
    current = _normalize_campaign(run_campaign)
    expected = _normalize_campaign(target)
    if not current or not expected:
        return False
    return current == expected or current in expected or expected in current


def _campaign_run_ids(
    conn: sqlite3.Connection,
    campaign_filename: str,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT id, filters
        FROM pipeline_runs
        ORDER BY started_at DESC
        """
    ).fetchall()
    ids = []
    for row in rows:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            filters = json.loads(row["filters"] or "{}")
            run_campaign = (
                filters.get("campaign_key")
                or filters.get("campaign")
                or ""
            )
            if _match_campaign(run_campaign, campaign_filename):
                ids.append(row["id"])
    return ids


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        from src.migrations_runner import apply_migrations

        apply_migrations(self.conn())

    def conn(self) -> sqlite3.Connection:
        # internal use only
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn


class RunRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, run: PipelineRun) -> None:
        with self.db.conn() as conn:
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
        row = self.db.conn().execute(
            "SELECT * FROM pipeline_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def list_all(self) -> list[PipelineRun]:
        rows = self.db.conn().execute(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC"
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def count_all(self) -> int:
        row = self.db.conn().execute(
            "SELECT COUNT(*) AS total FROM pipeline_runs"
        ).fetchone()
        return int(row["total"] or 0) if row else 0

    def ids_for_campaign(self, campaign_filename: str) -> list[str]:
        return _campaign_run_ids(self.db.conn(), campaign_filename)

    def list_for_campaign(self, campaign_filename: str) -> list[PipelineRun]:
        ids = set(self.ids_for_campaign(campaign_filename))
        if not ids:
            return []
        return [run for run in self.list_all() if run.id in ids]

    def update_status(
        self,
        run_id: str,
        status: RunStatus,
        error: str = "",
    ) -> None:
        with self.db.conn() as conn:
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
        with self.db.conn() as conn:
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
        row = self.db.conn().execute(
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
        with self.db.conn() as conn:
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
        row = self.db.conn().execute(
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
        rows = self.db.conn().execute(
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
        with self.db.conn() as conn:
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
        row = self.db.conn().execute(
            "SELECT * FROM lead_source_segments WHERE id = ?",
            (segment_id,),
        ).fetchone()
        return self._row_to_segment(row) if row else None

    def list_segments(self, universe_id: str) -> list[LeadSourceSegment]:
        rows = self.db.conn().execute(
            """
            SELECT * FROM lead_source_segments
            WHERE universe_id = ?
            ORDER BY created_at ASC
            """,
            (universe_id,),
        ).fetchall()
        return [self._row_to_segment(row) for row in rows]

    def list_segments_for_campaign(self, campaign_filename: str) -> list[LeadSourceSegment]:
        rows = self.db.conn().execute(
            """
            SELECT * FROM lead_source_segments
            WHERE campaign_filename = ?
            ORDER BY created_at ASC
            """,
            (campaign_filename,),
        ).fetchall()
        return [self._row_to_segment(row) for row in rows]

    def segment_for_run(self, run_id: str) -> dict | None:
        row = self.db.conn().execute(
            """
            SELECT id, label
            FROM lead_source_segments
            WHERE last_run_id = ?
            """,
            (run_id,),
        ).fetchone()
        return dict(row) if row else None

    def next_queued_segment(self, universe_id: str) -> Optional[LeadSourceSegment]:
        row = self.db.conn().execute(
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
        with self.db.conn() as conn:
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
        with self.db.conn() as conn:
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
        with self.db.conn() as conn:
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
        row = self.db.conn().execute(
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
        with self.db.conn() as conn:
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
        row = self.db.conn().execute(
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


class CampaignRepo:
    CONFIG_FIELDS = {
        "knowledge_bases",
        "target_personas",
        "target_industries",
        "tone",
        "max_email_words",
        "max_linkedin_chars",
        "email_goal",
        "key_pain_points",
    }

    def __init__(self, db: Database):
        self.db = db

    def _normalize_filename(self, filename: str) -> str:
        value = (filename or "").strip()
        if not value:
            return ""
        return value if value.endswith(".json") else f"{value}.json"

    def _slug(self, name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
        return slug or "campaign"

    def _unique_filename(self, name: str) -> str:
        base = self._slug(name)
        candidate = f"{base}.json"
        index = 2
        while self.get_by_filename(candidate):
            candidate = f"{base}_{index}.json"
            index += 1
        return candidate

    def _row_to_campaign(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        try:
            config = json.loads(row["config"] or "{}")
        except json.JSONDecodeError:
            config = {}
        data = {
            "id": row["id"],
            "filename": row["filename"] or "",
            "name": row["name"] or "",
            "description": row["description"] or "",
            "config": config,
            "created_at": row["created_at"] or "",
            "updated_at": row["updated_at"] or "",
        }
        data.update(config)
        return data

    def _file_parts(self, filename: str, data: dict) -> tuple[str, str, dict]:
        name = str(data.get("name") or filename.replace(".json", "")).strip()
        description = str(data.get("description") or "").strip()
        config = {
            key: value
            for key, value in data.items()
            if key not in {"name", "description"}
        }
        return name, description, config

    def _validate_config(self, config: dict | None) -> dict:
        return validate_campaign_config(config)

    def get_by_filename(self, filename: str) -> dict | None:
        normalized = self._normalize_filename(filename)
        row = self.db.conn().execute(
            """
            SELECT *
            FROM campaigns
            WHERE filename = ?
            """,
            (normalized,),
        ).fetchone()
        return self._row_to_campaign(row)

    def get_by_id(self, campaign_id: str) -> dict | None:
        row = self.db.conn().execute(
            """
            SELECT *
            FROM campaigns
            WHERE id = ?
            """,
            (campaign_id,),
        ).fetchone()
        return self._row_to_campaign(row)

    def list_all(self) -> list[dict]:
        rows = self.db.conn().execute(
            """
            SELECT *
            FROM campaigns
            ORDER BY name ASC
            """
        ).fetchall()
        return [
            campaign
            for campaign in (self._row_to_campaign(row) for row in rows)
            if campaign
        ]

    def create(
        self,
        name: str,
        description: str = "",
        config: dict | None = None,
    ) -> dict:
        config = self._validate_config(config)
        filename = self._unique_filename(name)
        campaign_id = uuid4().hex
        now = _dt_to_text(datetime.utcnow())
        with self.db.conn() as conn:
            conn.execute(
                """
                INSERT INTO campaigns (
                    id, filename, name, description, config,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    filename,
                    name,
                    description or "",
                    json.dumps(config, default=str),
                    now,
                    now,
                ),
            )
        return self.get_by_id(campaign_id)

    def update_config(self, filename: str, config: dict) -> dict | None:
        config = self._validate_config(config)
        normalized = self._normalize_filename(filename)
        now = _dt_to_text(datetime.utcnow())
        with self.db.conn() as conn:
            conn.execute(
                """
                UPDATE campaigns
                SET config = ?,
                    updated_at = ?
                WHERE filename = ?
                """,
                (json.dumps(config or {}, default=str), now, normalized),
            )
        return self.get_by_filename(normalized)

    def upsert_from_file(self, filename: str, data: dict) -> dict:
        normalized = self._normalize_filename(filename)
        name, description, config = self._file_parts(normalized, data or {})
        config = self._validate_config(config)
        existing = self.get_by_filename(normalized)
        now = _dt_to_text(datetime.utcnow())
        campaign_id = existing["id"] if existing else uuid4().hex
        created_at = existing.get("created_at") if existing else now
        with self.db.conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO campaigns (
                    id, filename, name, description, config,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    normalized,
                    name,
                    description,
                    json.dumps(config, default=str),
                    created_at or now,
                    now,
                ),
            )
        return self.get_by_filename(normalized)


class CampaignSequenceRepository:
    def __init__(self, db: Database):
        self.db = db

    def save_step(self, step: CampaignSequenceStep) -> None:
        step.updated_at = datetime.utcnow()
        with self.db.conn() as conn:
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

    def deactivate_missing_steps(
        self,
        campaign_filename: str,
        touch_numbers: list[int],
    ) -> None:
        if not touch_numbers:
            return
        placeholders = ",".join("?" for _ in touch_numbers)
        with self.db.conn() as conn:
            conn.execute(
                f"""
                UPDATE campaign_sequence_steps
                SET is_active = 0,
                    updated_at = ?
                WHERE campaign_filename = ?
                  AND touch_number NOT IN ({placeholders})
                """,
                [
                    datetime.utcnow().isoformat(),
                    campaign_filename,
                    *touch_numbers,
                ],
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
        rows = self.db.conn().execute(
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
        row = self.db.conn().execute(
            f"SELECT * FROM campaign_sequence_steps WHERE {where}",
            params,
        ).fetchone()
        return self._row_to_step(row) if row else None

    def save_rules(self, rules: CampaignSequenceRules) -> None:
        rules.updated_at = datetime.utcnow()
        rules.mode = normalize_sequence_mode(rules.mode)
        with self.db.conn() as conn:
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
        row = self.db.conn().execute(
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
            if default_steps is None:
                defaults = [
                    {"number": 1, "name": "Intro", "delay_days": 0},
                    {"number": 2, "name": "Follow-up", "delay_days": 3},
                    {"number": 3, "name": "Final touch", "delay_days": 4},
                ]
            else:
                defaults = default_steps
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
            mode=normalize_sequence_mode(row["mode"]),
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
        with self.db.conn() as conn:
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
        row = self.db.conn().execute(
            "SELECT * FROM outreach_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        return self._row_to_draft(row) if row else None

    def get_drafts_by_ids(self, draft_ids: list[str]) -> list[OutreachDraft]:
        if not draft_ids:
            return []
        placeholders = ",".join("?" for _ in draft_ids)
        rows = self.db.conn().execute(
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
        row = self.db.conn().execute(
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
        rows = self.db.conn().execute(
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
        with self.db.conn() as conn:
            conn.execute(
                f"UPDATE outreach_drafts SET {set_clause} WHERE id = ?",
                values,
            )
        return self.get_draft(draft_id)

    def count_sent_today(self, campaign_filename: str) -> int:
        today = datetime.utcnow().date().isoformat()
        row = self.db.conn().execute(
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
        with self.db.conn() as conn:
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
        row = self.db.conn().execute(
            """
            SELECT * FROM lead_sequence_state
            WHERE lead_id = ? AND campaign_filename = ?
            """,
            (lead_id, campaign_filename),
        ).fetchone()
        return self._row_to_state(row) if row else None

    def list_states_for_lead(self, lead_id: str) -> list[LeadSequenceState]:
        rows = self.db.conn().execute(
            """
            SELECT * FROM lead_sequence_state
            WHERE lead_id = ?
            ORDER BY created_at ASC
            """,
            (lead_id,),
        ).fetchall()
        return [self._row_to_state(row) for row in rows]

    def upsert_state(self, state: LeadSequenceState) -> None:
        existing = self.get_state(state.lead_id, state.campaign_filename)
        if existing:
            state.id = existing.id
            state.created_at = existing.created_at
        state.updated_at = datetime.utcnow()
        with self.db.conn() as conn:
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
        with self.db.conn() as conn:
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
        rows = self.db.conn().execute(
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
        rows = self.db.conn().execute(
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

    def count_states_by_status(self, status: str) -> int:
        row = self.db.conn().execute(
            """
            SELECT COUNT(*) AS total
            FROM lead_sequence_state
            WHERE status = ?
            """,
            (status,),
        ).fetchone()
        return int(row["total"] or 0) if row else 0

    def recent_activities(self, limit: int = 15) -> list[dict]:
        rows = self.db.conn().execute(
            """
            SELECT
                a.activity_type,
                a.title,
                a.created_at,
                a.campaign_filename,
                l.full_name AS lead_name
            FROM lead_activities a
            LEFT JOIN leads l ON l.id = a.lead_id
            ORDER BY a.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def campaign_overview_counts(self, campaign_filename: str) -> dict:
        draft_rows = self.db.conn().execute(
            """
            SELECT status, COUNT(*) AS total
            FROM outreach_drafts
            WHERE campaign_filename = ?
            GROUP BY status
            """,
            (campaign_filename,),
        ).fetchall()
        draft_counts = {
            row["status"] or "draft": row["total"] or 0
            for row in draft_rows
        }
        draft_total_row = self.db.conn().execute(
            """
            SELECT COUNT(*) AS total
            FROM outreach_drafts
            WHERE campaign_filename = ?
            """,
            (campaign_filename,),
        ).fetchone()
        unique_row = self.db.conn().execute(
            """
            SELECT
                COUNT(DISTINCT lead_id) AS drafted,
                COUNT(DISTINCT CASE WHEN status = 'approved' THEN lead_id END) AS approved,
                COUNT(DISTINCT CASE WHEN status = 'sent' THEN lead_id END) AS sent
            FROM outreach_drafts
            WHERE campaign_filename = ?
            """,
            (campaign_filename,),
        ).fetchone()
        state_rows = self.db.conn().execute(
            """
            SELECT status, COUNT(*) AS total
            FROM lead_sequence_state
            WHERE campaign_filename = ?
            GROUP BY status
            """,
            (campaign_filename,),
        ).fetchall()
        return {
            "draft_counts": {
                key: int(value or 0)
                for key, value in draft_counts.items()
            },
            "drafts_generated": int(draft_total_row["total"] or 0)
            if draft_total_row else 0,
            "drafted_unique": int(unique_row["drafted"] or 0)
            if unique_row else 0,
            "approved_unique": int(unique_row["approved"] or 0)
            if unique_row else 0,
            "sent_unique": int(unique_row["sent"] or 0)
            if unique_row else 0,
            "state_counts": {
                row["status"] or "not_started": int(row["total"] or 0)
                for row in state_rows
            },
        }

    def queue_waiting_items(self, campaign_filename: str) -> list[dict]:
        now_text = datetime.utcnow().isoformat()
        rows = self.db.conn().execute(
            """
            SELECT s.*, l.full_name, l.company, l.title, l.email
            FROM lead_sequence_state s
            JOIN leads l ON l.id = s.lead_id
            WHERE s.campaign_filename = ?
              AND s.status = 'waiting_followup'
              AND (
                s.next_touch_due_at IS NULL
                OR s.next_touch_due_at > ?
              )
            ORDER BY s.next_touch_due_at ASC
            LIMIT 1000
            """,
            (campaign_filename, now_text),
        ).fetchall()
        return [dict(row) for row in rows]

    def queue_stopped_items(self, campaign_filename: str) -> list[dict]:
        rows = self.db.conn().execute(
            """
            SELECT s.*, l.full_name, l.company, l.title, l.email
            FROM lead_sequence_state s
            JOIN leads l ON l.id = s.lead_id
            WHERE s.campaign_filename = ?
              AND s.status IN ('replied', 'bounced', 'unsubscribed', 'do_not_contact', 'skipped')
            ORDER BY s.updated_at DESC
            LIMIT 1000
            """,
            (campaign_filename,),
        ).fetchall()
        return [dict(row) for row in rows]

    def latest_draft_for_touch(
        self,
        lead_id: str,
        campaign_filename: str,
        touch_number: int,
    ) -> OutreachDraft | None:
        row = self.db.conn().execute(
            """
            SELECT * FROM outreach_drafts
            WHERE lead_id = ?
              AND campaign_filename = ?
              AND touch_number = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (lead_id, campaign_filename, touch_number),
        ).fetchone()
        return self._row_to_draft(row) if row else None

    def touch1_subject(self, lead_id: str, campaign_filename: str) -> str:
        row = self.db.conn().execute(
            """
            SELECT subject
            FROM outreach_drafts
            WHERE lead_id = ?
              AND campaign_filename = ?
              AND touch_number = 1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (lead_id, campaign_filename),
        ).fetchone()
        return (row["subject"] if row else "") or ""

    def previous_sent_draft(
        self,
        lead_id: str,
        campaign_filename: str,
        touch_number: int,
    ) -> OutreachDraft | None:
        row = self.db.conn().execute(
            """
            SELECT * FROM outreach_drafts
            WHERE lead_id = ?
              AND campaign_filename = ?
              AND touch_number < ?
              AND status = 'sent'
            ORDER BY touch_number DESC, sent_at DESC
            LIMIT 1
            """,
            (lead_id, campaign_filename, touch_number),
        ).fetchone()
        return self._row_to_draft(row) if row else None

    def sent_draft_exists(
        self,
        lead_id: str,
        campaign_filename: str,
        touch_number: int,
    ) -> bool:
        row = self.db.conn().execute(
            """
            SELECT 1 FROM outreach_drafts
            WHERE lead_id = ?
              AND campaign_filename = ?
              AND touch_number = ?
              AND status = 'sent'
            LIMIT 1
            """,
            (lead_id, campaign_filename, touch_number),
        ).fetchone()
        return bool(row)

    def campaigns_with_state_for_lead(self, lead_id: str) -> list[str]:
        rows = self.db.conn().execute(
            """
            SELECT DISTINCT campaign_filename
            FROM lead_sequence_state
            WHERE lead_id = ?
            ORDER BY campaign_filename ASC
            """,
            (lead_id,),
        ).fetchall()
        return [row["campaign_filename"] or "" for row in rows]

    def _active_touch_numbers(self, campaign_filename: str) -> list[int]:
        rows = self.db.conn().execute(
            """
            SELECT touch_number
            FROM campaign_sequence_steps
            WHERE campaign_filename = ?
              AND is_active = 1
            ORDER BY touch_number ASC
            """,
            (campaign_filename,),
        ).fetchall()
        return [int(row["touch_number"] or 0) for row in rows]

    def _next_active_touch(
        self,
        campaign_filename: str,
        current_touch: int,
    ) -> int | None:
        for number in self._active_touch_numbers(campaign_filename):
            if number > current_touch:
                return number
        return None

    def _campaign_lead_rows_for_due(self, campaign_filename: str) -> list[dict]:
        rows: list[dict] = []
        for run_id in _campaign_run_ids(self.db.conn(), campaign_filename):
            run_rows = self.db.conn().execute(
                """
                SELECT *
                FROM leads
                WHERE run_id = ?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
            rows.extend(dict(row) for row in run_rows)
        return rows

    def due_items(
        self,
        campaign_filename: str,
        lead_ids: list[str] | set[str] | None = None,
        touch_number: int | None = None,
    ) -> list[dict]:
        if not self._active_touch_numbers(campaign_filename):
            return []

        allowed_ids = set(lead_ids or [])
        now = datetime.utcnow()
        due = []

        for lead in self._campaign_lead_rows_for_due(campaign_filename):
            lead_id = lead["id"] or ""
            if allowed_ids and lead_id not in allowed_ids:
                continue
            if not (lead["email"] or ""):
                continue

            state = self.get_or_create_state(lead_id, campaign_filename)
            if state.status in STOPPED_SEQUENCE_STATUSES:
                continue

            due_touch = None
            if (
                state.current_touch > 0
                and state.next_touch_due_at
                and state.next_touch_due_at <= now
            ):
                if not self.sent_draft_exists(
                    lead_id,
                    campaign_filename,
                    state.current_touch,
                ):
                    continue
                next_touch = self._next_active_touch(
                    campaign_filename,
                    state.current_touch,
                )
                if next_touch and not self.sent_draft_exists(
                    lead_id,
                    campaign_filename,
                    next_touch,
                ):
                    due_touch = next_touch

            if touch_number and due_touch != touch_number:
                continue
            if not due_touch:
                continue

            draft = self.latest_draft_for_touch(
                lead_id,
                campaign_filename,
                due_touch,
            )
            draft_id = ""
            draft_status = ""
            if draft and draft.status in {"draft", "approved"}:
                draft_id = draft.id
                draft_status = draft.status

            if state.status == "waiting_followup":
                state.status = "followup_due"
                self.upsert_state(state)
                self.add_activity(LeadActivity(
                    lead_id=lead_id,
                    campaign_filename=campaign_filename,
                    run_id=lead["run_id"] or "",
                    activity_type="followup_due",
                    title=f"Touch {due_touch} is due",
                    description="",
                    metadata_json=json.dumps({"touch_number": due_touch}),
                ))

            due.append({
                "lead_id": lead_id,
                "full_name": lead["full_name"] or "",
                "company": lead["company"] or "",
                "title": lead["title"] or "",
                "email": lead["email"] or "",
                "touch_number": due_touch,
                "draft_id": draft_id,
                "draft_status": draft_status,
                "next_touch_due_at": _dt_to_text(state.next_touch_due_at),
                "status": state.status,
                "due_label": "Due now",
            })
        return due

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
                getattr(lead, "duplicate_of_lead_id", "") or "",
                lead.intent_score,
                lead.segment.value,
                lead.status.value,
                _dt_to_text(lead.created_at),
                _dt_to_text(lead.updated_at),
            )
            for lead in leads
        ]
        with self.db.conn() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO leads (
                    id, run_id, full_name, first_name, last_name,
                    title, company, company_domain, location, linkedin_url,
                    company_linkedin_url, email, email_confidence, phone,
                    duplicate_of_lead_id,
                    intent_score, segment, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            sample = self.db.conn().execute(
                "SELECT full_name, phone FROM leads ORDER BY rowid DESC LIMIT 3"
            ).fetchall()
            import logging

            logging.getLogger(__name__).info(f"DB phone check: {sample}")

    def get_by_run(self, run_id: str) -> list[Lead]:
        rows = self.db.conn().execute(
            "SELECT * FROM leads WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
        return [self._row_to_lead(row) for row in rows]

    def get_by_id(self, lead_id: str) -> Optional[Lead]:
        row = self.db.conn().execute(
            "SELECT * FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()
        return self._row_to_lead(row) if row else None

    def get_by_email(self, email: str) -> list[Lead]:
        normalized = (email or "").strip().lower()
        if not normalized:
            return []
        rows = self.db.conn().execute(
            """
            SELECT *
            FROM leads
            WHERE LOWER(COALESCE(email, '')) = ?
            ORDER BY created_at ASC
            """,
            (normalized,),
        ).fetchall()
        return [self._row_to_lead(row) for row in rows]

    def _normalize_linkedin_url(self, value: str) -> str:
        return (value or "").strip().split("?", 1)[0].rstrip("/").lower()

    def find_global_duplicate(
        self,
        linkedin_url: str,
        email: str,
        exclude_id: str = "",
    ) -> dict | None:
        exclude_id = (exclude_id or "").strip()
        normalized_url = self._normalize_linkedin_url(linkedin_url)
        if normalized_url:
            rows = self.db.conn().execute(
                """
                SELECT id, run_id, linkedin_url
                FROM leads
                WHERE id != ?
                  AND COALESCE(linkedin_url, '') != ''
                ORDER BY created_at ASC
                """,
                (exclude_id,),
            ).fetchall()
            for row in rows:
                if self._normalize_linkedin_url(row["linkedin_url"]) == normalized_url:
                    return {
                        "id": row["id"] or "",
                        "run_id": row["run_id"] or "",
                    }

        normalized_email = (email or "").strip().lower()
        if normalized_email:
            row = self.db.conn().execute(
                """
                SELECT id, run_id
                FROM leads
                WHERE id != ?
                  AND LOWER(COALESCE(email, '')) = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (exclude_id, normalized_email),
            ).fetchone()
            if row:
                return {
                    "id": row["id"] or "",
                    "run_id": row["run_id"] or "",
                }

        return None

    def set_duplicate_of(
        self,
        lead_id: str,
        duplicate_of_lead_id: str,
    ) -> None:
        with self.db.conn() as conn:
            conn.execute(
                """
                UPDATE leads
                SET duplicate_of_lead_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    duplicate_of_lead_id or "",
                    _dt_to_text(datetime.utcnow()),
                    lead_id,
                ),
            )

    def mark_duplicate_if_any(
        self,
        lead_id: str,
        campaign_filename: str = "",
    ) -> dict | None:
        lead = self.get_by_id(lead_id)
        if not lead:
            return None

        hit = self.find_global_duplicate(
            lead.linkedin_url,
            lead.email,
            lead.id,
        )
        if not hit or not hit.get("id"):
            return None

        existing_duplicate = getattr(lead, "duplicate_of_lead_id", "") or ""
        if existing_duplicate == hit["id"]:
            return hit

        self.set_duplicate_of(lead.id, hit["id"])
        with self.db.conn() as conn:
            conn.execute(
                """
                INSERT INTO lead_activities (
                    id, lead_id, campaign_filename, run_id, activity_type,
                    title, description, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    lead.id,
                    campaign_filename or "",
                    getattr(lead, "run_id", "") or "",
                    "duplicate_detected",
                    "Also exists in another campaign",
                    "",
                    json.dumps({
                        "duplicate_of_lead_id": hit["id"],
                        "duplicate_run_id": hit.get("run_id", ""),
                    }),
                    _dt_to_text(datetime.utcnow()),
                ),
            )
        return hit

    def get_by_campaign(
        self,
        campaign_filename: str,
        exclude_run_id: str = "",
    ) -> list[Lead]:
        leads: list[Lead] = []
        for run_id in _campaign_run_ids(self.db.conn(), campaign_filename):
            if exclude_run_id and run_id == exclude_run_id:
                continue
            leads.extend(self.get_by_run(run_id))
        return leads

    def search(
        self,
        campaign_filename: str = "",
        q: str = "",
        segment: str | None = None,
        limit: int | None = 500,
        offset: int = 0,
        run_id: str = "",
        drafts_only: bool = False,
        newest_first: bool = False,
    ) -> tuple[list[Lead], int]:
        where: list[str] = []
        params: list = []

        if campaign_filename:
            run_ids = (
                [run_id]
                if run_id
                else _campaign_run_ids(self.db.conn(), campaign_filename)
            )
            if not run_ids:
                return [], 0
            placeholders = ",".join("?" for _ in run_ids)
            where.append(f"run_id IN ({placeholders})")
            params.extend(run_ids)
        elif run_id:
            where.append("run_id = ?")
            params.append(run_id)

        if segment and segment.lower() not in {"all", ""}:
            where.append("segment = ?")
            params.append(segment.upper().replace("-", "_"))

        if q:
            like = f"%{q.strip()}%"
            where.append(
                """
                (
                    full_name LIKE ?
                    OR company LIKE ?
                    OR title LIKE ?
                    OR email LIKE ?
                )
                """
            )
            params.extend([like, like, like, like])

        if drafts_only:
            where.append(
                "(COALESCE(email_subject, '') != '' OR COALESCE(email_body, '') != '')"
            )

        where_sql = " AND ".join(where) if where else "1=1"
        count_row = self.db.conn().execute(
            f"SELECT COUNT(*) AS total FROM leads WHERE {where_sql}",
            params,
        ).fetchone()
        total = int(count_row["total"] or 0) if count_row else 0

        order = "DESC" if newest_first else "ASC"
        limit_sql = ""
        query_params = list(params)
        if limit is not None:
            limit_sql = " LIMIT ? OFFSET ?"
            query_params.extend([limit, offset])

        rows = self.db.conn().execute(
            f"""
            SELECT *
            FROM leads
            WHERE {where_sql}
            ORDER BY created_at {order}
            {limit_sql}
            """,
            query_params,
        ).fetchall()
        return [self._row_to_lead(row) for row in rows], total

    def find_sendable(
        self,
        run_id: str,
        lead_ids: set | None = None,
    ) -> list[Lead]:
        where = [
            "run_id = ?",
            "email != ''",
            "email_subject != ''",
            "email_body != ''",
            """
            COALESCE(email_sequence_status, '') NOT IN
            ('replied', 'unsubscribed', 'complete', 'completed')
            """,
        ]
        params: list = [run_id]
        if lead_ids:
            placeholders = ",".join("?" for _ in lead_ids)
            where.append(f"id IN ({placeholders})")
            params.extend(list(lead_ids))
        rows = self.db.conn().execute(
            f"""
            SELECT *
            FROM leads
            WHERE {" AND ".join(where)}
            ORDER BY created_at ASC
            """,
            params,
        ).fetchall()
        return [self._row_to_lead(row) for row in rows]

    def update_sequence_status(
        self,
        lead_id: str,
        status: str,
        error: str = "",
    ) -> None:
        with self.db.conn() as conn:
            conn.execute(
                """
                UPDATE leads
                SET email_sequence_status = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, _dt_to_text(datetime.utcnow()), lead_id),
            )

    def update_segments(self, run_id: str, leads: list[Lead]) -> None:
        if not leads:
            return
        with self.db.conn() as conn:
            conn.executemany(
                """
                UPDATE leads
                SET segment = ?, status = ?, updated_at = ?
                WHERE id = ? AND run_id = ?
                """,
                [
                    (
                        lead.segment.value,
                        lead.status.value,
                        _dt_to_text(datetime.utcnow()),
                        lead.id,
                        run_id,
                    )
                    for lead in leads
                ],
            )

    def save_personalised_message(
        self,
        lead_id: str,
        email_subject: str,
        email_body: str,
        linkedin_message: str,
        research_summary: str,
        campaign_name: str,
    ) -> None:
        with self.db.conn() as conn:
            conn.execute(
                """
                UPDATE leads SET
                    email_subject = ?,
                    email_body = ?,
                    linkedin_message = ?,
                    research_summary = ?,
                    personalised_at = ?,
                    campaign_name = ?
                WHERE id = ?
                """,
                (
                    email_subject,
                    email_body,
                    linkedin_message,
                    research_summary,
                    _dt_to_text(datetime.utcnow()),
                    campaign_name,
                    lead_id,
                ),
            )

    def count_all(self) -> int:
        row = self.db.conn().execute(
            "SELECT COUNT(*) AS total FROM leads"
        ).fetchone()
        return int(row["total"] or 0) if row else 0

    def count_sequence_statuses(self, statuses: set[str]) -> int:
        if not statuses:
            return 0
        placeholders = ",".join("?" for _ in statuses)
        row = self.db.conn().execute(
            f"""
            SELECT COUNT(*) AS total
            FROM leads
            WHERE email_sequence_status IN ({placeholders})
            """,
            list(statuses),
        ).fetchone()
        return int(row["total"] or 0) if row else 0

    def delete_for_run(self, run_id: str, lead_ids: list[str]) -> int:
        if not lead_ids:
            return 0
        placeholders = ",".join("?" for _ in lead_ids)
        with self.db.conn() as conn:
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
        with self.db.conn() as conn:
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

        with self.db.conn() as conn:
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

    def _segment_count_payload(self, rows: list[sqlite3.Row]) -> dict:
        counts = {"warm": 0, "cold": 0, "no_email": 0}
        for row in rows:
            if row["segment"] == Segment.WARM.value:
                counts["warm"] = row["total"]
            elif row["segment"] == Segment.COLD.value:
                counts["cold"] = row["total"]
            elif row["segment"] == Segment.NO_EMAIL.value:
                counts["no_email"] = row["total"]
        return counts

    def count_by_segment(self, campaign_filename: str) -> dict:
        run_ids = _campaign_run_ids(self.db.conn(), campaign_filename)
        if not run_ids:
            return {"warm": 0, "cold": 0, "no_email": 0}
        placeholders = ",".join("?" for _ in run_ids)
        rows = self.db.conn().execute(
            f"""
            SELECT segment, COUNT(*) AS total
            FROM leads
            WHERE run_id IN ({placeholders})
            GROUP BY segment
            """,
            run_ids,
        ).fetchall()
        return self._segment_count_payload(rows)

    def count_by_segment_for_run(self, run_id: str) -> dict:
        rows = self.db.conn().execute(
            """
            SELECT segment, COUNT(*) AS total
            FROM leads
            WHERE run_id = ?
            GROUP BY segment
            """,
            (run_id,),
        ).fetchall()
        return self._segment_count_payload(rows)

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
            "duplicate_of_lead_id": "",
        }
        row_keys = set(row.keys())
        for field, default in optional_fields.items():
            if field in row_keys:
                setattr(lead, field, row[field] or default)
        return lead

class JobRepo:
    TERMINAL_STATUSES = {"done", "failed", "cancelled"}

    def __init__(self, db: Database):
        self.db = db

    def _json_loads(self, value: str | None) -> dict:
        if not value:
            return {}
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _row_to_job(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        data = dict(row)
        data["payload"] = self._json_loads(data.pop("payload_json", "{}"))
        data["result"] = self._json_loads(data.pop("result_json", "{}"))
        data["cancel_requested"] = bool(data.get("cancel_requested"))
        return data

    def create(self, type: str, payload: dict, total: int = 0) -> dict:
        now = _dt_to_text(datetime.utcnow())
        job_id = str(uuid4())
        with self.db.conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, type, status, total, done, failed, skipped,
                    payload_json, result_json, error, cancel_requested,
                    created_at, started_at, finished_at, updated_at
                )
                VALUES (?, ?, 'queued', ?, 0, 0, 0, ?, '{}', '', 0, ?, '', '', ?)
                """,
                (
                    job_id,
                    type,
                    int(total or 0),
                    json.dumps(payload or {}, default=str),
                    now,
                    now,
                ),
            )
        return self.get(job_id) or {
            "id": job_id,
            "type": type,
            "status": "queued",
            "total": int(total or 0),
            "done": 0,
            "failed": 0,
            "skipped": 0,
            "payload": payload or {},
            "result": {},
            "error": "",
            "cancel_requested": False,
            "created_at": now,
            "started_at": "",
            "finished_at": "",
            "updated_at": now,
        }

    def get(self, job_id: str) -> dict | None:
        row = self.db.conn().execute(
            """
            SELECT *
            FROM jobs
            WHERE id = ?
            """,
            ((job_id or "").strip(),),
        ).fetchone()
        return self._row_to_job(row)

    def list_recent(self, limit: int = 20) -> list[dict]:
        rows = self.db.conn().execute(
            """
            SELECT *
            FROM jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit or 20), 200)),),
        ).fetchall()
        return [job for row in rows if (job := self._row_to_job(row))]

    def mark_running(self, job_id: str) -> None:
        now = _dt_to_text(datetime.utcnow())
        with self.db.conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    started_at = CASE WHEN started_at = '' THEN ? ELSE started_at END,
                    updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )

    def update_progress(
        self,
        job_id: str,
        done_delta: int = 0,
        failed_delta: int = 0,
        skipped_delta: int = 0,
        result_item: dict | None = None,
    ) -> None:
        job = self.get(job_id)
        if not job:
            return

        result = dict(job.get("result") or {})
        if result_item is not None:
            items = list(result.get("items") or [])
            items.append(result_item)
            result["items"] = items
            status = (result_item.get("status") or "").strip().lower()
            if status:
                result[status] = int(result.get(status) or 0) + 1
            if result_item.get("message") and not result.get("message"):
                result["message"] = result_item.get("message")
            if result_item.get("reason") and not result.get("first_reason"):
                result["first_reason"] = result_item.get("reason")

        now = _dt_to_text(datetime.utcnow())
        with self.db.conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET done = done + ?,
                    failed = failed + ?,
                    skipped = skipped + ?,
                    result_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    int(done_delta or 0),
                    int(failed_delta or 0),
                    int(skipped_delta or 0),
                    json.dumps(result, default=str),
                    now,
                    job_id,
                ),
            )

    def mark_done(self, job_id: str) -> None:
        now = _dt_to_text(datetime.utcnow())
        with self.db.conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'done',
                    finished_at = CASE WHEN finished_at = '' THEN ? ELSE finished_at END,
                    updated_at = ?
                WHERE id = ? AND status NOT IN ('done', 'failed', 'cancelled')
                """,
                (now, now, job_id),
            )

    def mark_cancelled(self, job_id: str) -> None:
        now = _dt_to_text(datetime.utcnow())
        with self.db.conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'cancelled',
                    finished_at = CASE WHEN finished_at = '' THEN ? ELSE finished_at END,
                    updated_at = ?
                WHERE id = ? AND status NOT IN ('done', 'failed', 'cancelled')
                """,
                (now, now, job_id),
            )

    def mark_failed(self, job_id: str, error: str) -> None:
        now = _dt_to_text(datetime.utcnow())
        with self.db.conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    error = ?,
                    finished_at = CASE WHEN finished_at = '' THEN ? ELSE finished_at END,
                    updated_at = ?
                WHERE id = ? AND status NOT IN ('done', 'failed', 'cancelled')
                """,
                ((error or "")[:2000], now, now, job_id),
            )

    def delete_many(self, job_ids: list[str]) -> int:
        if not job_ids:
            return 0
        placeholders = ",".join("?" for _ in job_ids)
        with self.db.conn() as conn:
            cur = conn.execute(
                f"DELETE FROM jobs WHERE id IN ({placeholders})",
                job_ids,
            )
            return cur.rowcount

    def request_cancel(self, job_id: str) -> None:
        now = _dt_to_text(datetime.utcnow())
        with self.db.conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET cancel_requested = 1,
                    updated_at = ?
                WHERE id = ? AND status NOT IN ('done', 'failed', 'cancelled')
                """,
                (now, job_id),
            )

    def next_queued(self) -> dict | None:
        row = self.db.conn().execute(
            """
            SELECT *
            FROM jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
        return self._row_to_job(row)

    def reset_stale_running_to_failed_on_startup(self) -> None:
        now = _dt_to_text(datetime.utcnow())
        with self.db.conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    error = 'Job was running when the API stopped',
                    finished_at = CASE WHEN finished_at = '' THEN ? ELSE finished_at END,
                    updated_at = ?
                WHERE status = 'running'
                """,
                (now, now),
            )


class SendLogRepo:
    def __init__(self, db: Database):
        self.db = db

    def _normalize_email(self, email: str) -> str:
        return (email or "").strip().lower()

    def _domain_for_email(self, email: str) -> str:
        normalized = self._normalize_email(email)
        if "@" not in normalized:
            return ""
        return normalized.rsplit("@", 1)[-1].strip().lower()

    def _karachi_today_bounds_utc(self) -> tuple[str, str]:
        """
        Return today's Asia/Karachi day boundaries as UTC ISO strings.

        The DB stores sent_at using datetime.utcnow().isoformat().
        Karachi is UTC+05:00, so local midnight = previous UTC day 19:00.
        """
        now_karachi = datetime.utcnow() + timedelta(hours=5)
        start_karachi = now_karachi.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end_karachi = start_karachi + timedelta(days=1)

        start_utc = start_karachi - timedelta(hours=5)
        end_utc = end_karachi - timedelta(hours=5)

        return _dt_to_text(start_utc), _dt_to_text(end_utc)

    def record(
        self,
        lead_id: str,
        campaign_filename: str,
        to_email: str,
        touch_number: int,
    ) -> None:
        normalized_email = self._normalize_email(to_email)
        to_domain = self._domain_for_email(normalized_email)

        with self.db.conn() as conn:
            conn.execute(
                """
                INSERT INTO send_log (
                    lead_id, campaign_filename, to_email, to_domain,
                    touch_number, sent_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    lead_id or "",
                    campaign_filename or "",
                    normalized_email,
                    to_domain,
                    int(touch_number or 0),
                    _dt_to_text(datetime.utcnow()),
                ),
            )

    def delete_for_lead(self, lead_id: str) -> int:
        with self.db.conn() as conn:
            cur = conn.execute(
                """
                DELETE FROM send_log
                WHERE lead_id = ?
                """,
                (lead_id,),
            )
            return cur.rowcount

    def delete_for_lead_prefix(self, lead_id_prefix: str) -> int:
        with self.db.conn() as conn:
            cur = conn.execute(
                """
                DELETE FROM send_log
                WHERE lead_id LIKE ?
                """,
                (f"{lead_id_prefix}%",),
            )
            return cur.rowcount

    def count_today(self) -> int:
        start_utc, end_utc = self._karachi_today_bounds_utc()
        row = self.db.conn().execute(
            """
            SELECT COUNT(*) AS total
            FROM send_log
            WHERE sent_at >= ? AND sent_at < ?
            """,
            (start_utc, end_utc),
        ).fetchone()
        return int(row["total"] or 0) if row else 0

    def count_today_for_domain(self, domain: str) -> int:
        normalized_domain = (domain or "").strip().lower()
        if not normalized_domain:
            return 0

        start_utc, end_utc = self._karachi_today_bounds_utc()
        row = self.db.conn().execute(
            """
            SELECT COUNT(*) AS total
            FROM send_log
            WHERE to_domain = ?
              AND sent_at >= ?
              AND sent_at < ?
            """,
            (normalized_domain, start_utc, end_utc),
        ).fetchone()
        return int(row["total"] or 0) if row else 0

    def last_send_for_email(self, email: str) -> dict | None:
        normalized_email = self._normalize_email(email)
        if not normalized_email:
            return None

        row = self.db.conn().execute(
            """
            SELECT campaign_filename, sent_at
            FROM send_log
            WHERE to_email = ?
            ORDER BY sent_at DESC
            LIMIT 1
            """,
            (normalized_email,),
        ).fetchone()
        if not row:
            return None
        return {
            "campaign_filename": row["campaign_filename"] or "",
            "sent_at": row["sent_at"] or "",
        }

    def first_send_date(self) -> date | None:
        row = self.db.conn().execute(
            """
            SELECT MIN(sent_at) AS first_sent_at
            FROM send_log
            WHERE sent_at IS NOT NULL AND sent_at != ''
            """
        ).fetchone()

        if not row or not row["first_sent_at"]:
            return None

        try:
            return datetime.fromisoformat(row["first_sent_at"]).date()
        except ValueError:
            return None

class KvRepo:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str) -> str:
        normalized_key = (key or "").strip()
        if not normalized_key:
            return ""

        row = self.db.conn().execute(
            """
            SELECT value
            FROM kv_store
            WHERE key = ?
            """,
            (normalized_key,),
        ).fetchone()

        if not row:
            return ""
        return row["value"] or ""

    def set(self, key: str, value: str) -> None:
        normalized_key = (key or "").strip()
        if not normalized_key:
            return

        with self.db.conn() as conn:
            conn.execute(
                """
                INSERT INTO kv_store (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_key,
                    value or "",
                    _dt_to_text(datetime.utcnow()),
                ),
            )

    def delete(self, key: str) -> bool:
        normalized_key = (key or "").strip()
        if not normalized_key:
            return False

        with self.db.conn() as conn:
            cur = conn.execute(
                """
                DELETE FROM kv_store
                WHERE key = ?
                """,
                (normalized_key,),
            )
            return cur.rowcount > 0


class SuppressionRepo:
    VALID_REASONS = {"unsubscribed", "bounced", "manual", "complained"}

    def __init__(self, db: Database):
        self.db = db

    def _normalize_email(self, email: str) -> str:
        return (email or "").strip().lower()

    def _normalize_reason(self, reason: str) -> str:
        reason = (reason or "").strip().lower()
        if reason not in self.VALID_REASONS:
            reason = "manual"
        return reason

    def add(
        self,
        email: str,
        reason: str,
        source_lead_id: str = "",
        source_campaign: str = "",
    ) -> None:
        normalized = self._normalize_email(email)
        if not normalized:
            return
        with self.db.conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO suppression (
                    email, reason, source_lead_id, source_campaign, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    normalized,
                    self._normalize_reason(reason),
                    source_lead_id or "",
                    source_campaign or "",
                    _dt_to_text(datetime.utcnow()),
                ),
            )

    def is_suppressed(self, email: str) -> bool:
        normalized = self._normalize_email(email)
        if not normalized:
            return False
        row = self.db.conn().execute(
            "SELECT 1 FROM suppression WHERE email = ?",
            (normalized,),
        ).fetchone()
        return row is not None

    def bulk_check(self, emails: list[str]) -> set[str]:
        normalized = sorted({
            self._normalize_email(email)
            for email in emails
            if self._normalize_email(email)
        })
        suppressed: set[str] = set()
        for i in range(0, len(normalized), 500):
            chunk = normalized[i:i + 500]
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            rows = self.db.conn().execute(
                f"""
                SELECT email
                FROM suppression
                WHERE email IN ({placeholders})
                """,
                chunk,
            ).fetchall()
            suppressed.update(row["email"] for row in rows)
        return suppressed

    def list_all(self, limit: int = 500) -> list[dict]:
        rows = self.db.conn().execute(
            """
            SELECT email, reason, source_lead_id, source_campaign, created_at
            FROM suppression
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def remove(self, email: str) -> bool:
        normalized = self._normalize_email(email)
        if not normalized:
            return False
        with self.db.conn() as conn:
            cur = conn.execute(
                "DELETE FROM suppression WHERE email = ?",
                (normalized,),
            )
            return cur.rowcount > 0


class EventRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, event: AgentEvent) -> None:
        with self.db.conn() as conn:
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
        rows = self.db.conn().execute(
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
campaign_repo = CampaignRepo(db)
campaign_sequence_repo = CampaignSequenceRepository(db)
outreach_repo = OutreachRepository(db)
job_repo = JobRepo(db)
send_log_repo = SendLogRepo(db)
kv_repo = KvRepo(db)
suppression_repo = SuppressionRepo(db)
