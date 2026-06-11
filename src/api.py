##src\api.py

import asyncio
import csv, io
import json
import json as _json
import logging
import os
import shutil
import threading
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi import UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src import orchestrator as orchestrator_module
from src.agents.email_agent import EmailAgent
from src.agents.export_agent import ExportAgent
from src.agents.scraper_agent import ScraperAgent
from src.agents.segment_agent import SegmentAgent
from src.config import settings
from src.models import (
    AgentEvent,
    CampaignSequenceRules,
    CampaignSequenceStep,
    EventType,
    Lead,
    LeadActivity,
    LeadSequenceState,
    LeadSourceSegment,
    LeadUniverse,
    OutreachDraft,
    PipelineRun,
    RunStatus,
)
from src.personalisation.knowledge_base import KnowledgeBaseLoader
from src.personalisation.orchestrator import PersonalisationOrchestrator
from src.storage import (
    campaign_sequence_repo,
    db,
    event_repo,
    lead_repo,
    lead_universe_repo,
    outreach_repo,
    run_repo,
)
from src.sequence import calculate_next_touch_due_at


logger = logging.getLogger(__name__)

app = FastAPI(title="Royal Cyber Lead Pipeline API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = orchestrator_module.PipelineOrchestrator()
_segment_runner_lock = threading.Lock()
_running_segment_ids: set[str] = set()


class StartPipelineRequest(BaseModel):
    titles: list[str] = ["CTO", "CIO", "CXO", "Head of Data", "VP Engineering"]
    industries: list[str] = []
    geos: list[str] = []
    company_sizes: list[str] = []
    keywords: str = "Microsoft Fabric"
    start_url: str = ""
    max_leads: int = 1000
    campaign: str = ""


class RunResponse(BaseModel):
    id: str
    status: str
    filters: dict
    total_scraped: int
    total_enriched: int
    total_warm: int
    total_cold: int
    total_no_email: int
    total_exported: int
    error: str
    started_at: str
    completed_at: Optional[str]


class LeadResponse(BaseModel):
    id: str
    full_name: str
    first_name: str
    last_name: str
    title: str
    company: str
    company_domain: str
    email: str
    email_confidence: str
    phone: str
    location: str
    linkedin_url: str
    company_linkedin_url: str
    segment: str
    intent_score: float
    status: str
    email_sequence_status: str = "not_started"


class DraftResponse(BaseModel):
    id: str
    full_name: str
    company: str
    title: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    email_subject: str = ""
    email_body: str = ""
    linkedin_message: str = ""
    research_summary: str = ""
    campaign_name: str = ""
    personalised_at: str | None = None
    email_sequence_status: str = "not_started"
    day1_sent_at: str | None = None
    day3_sent_at: str | None = None
    day7_sent_at: str | None = None


class PersonaliseRequest(BaseModel):
    campaign_name: str
    lead_ids: list[str] = []
    limit: int | None = None


class DraftUpdateRequest(BaseModel):
    email: str = ""
    email_subject: str = ""
    email_body: str = ""
    linkedin_message: str = ""


class SendTestCopyRequest(BaseModel):
    test_to_email: str = ""


class SendRunEmailsRequest(BaseModel):
    lead_ids: list[str] = []


class SequenceSendRequest(BaseModel):
    campaign: str = ""


class SequenceTouchRequest(BaseModel):
    number: int
    name: str
    delay_days: int = 0
    delay_value: int = 0
    delay_unit: str = "days"
    delay_type: str = "calendar_days"
    send_time_mode: str = "same_as_previous"
    fixed_send_time: str = ""
    subject_template: str = ""
    email_body_template: str = ""
    linkedin_message_template: str = ""
    is_active: bool = True


class SequenceRulesRequest(BaseModel):
    timezone: str = "Asia/Karachi"
    mode: str = "review"
    stop_on_reply: bool = True
    stop_on_bounce: bool = True
    stop_on_unsubscribe: bool = True
    skip_no_email: bool = True
    skip_weekends: bool = True
    send_window_start: str = "09:00"
    send_window_end: str = "17:00"
    daily_send_limit: int = 50
    delay_between_sends_seconds: int = 60
    require_approval_for_touch1: bool = True
    require_approval_for_followups: bool = True


class SequenceSettingsRequest(BaseModel):
    touches: list[SequenceTouchRequest] = []
    steps: list[SequenceTouchRequest] = []
    rules: SequenceRulesRequest | None = None


class GenerateDraftsRequest(BaseModel):
    lead_ids: list[str] = []
    touch_number: int = 1
    overwrite: bool = False


class OutreachDraftUpdateRequest(BaseModel):
    subject: str | None = None
    body: str | None = None
    linkedin_message: str | None = None
    status: str | None = None


class ApproveSelectedDraftsRequest(BaseModel):
    draft_ids: list[str] = []


class SkipDraftRequest(BaseModel):
    reason: str = ""


class SendSelectedDraftsRequest(BaseModel):
    draft_ids: list[str] = []


class DraftSendTestRequest(BaseModel):
    test_email: str = ""


class QueueGenerateDueRequest(BaseModel):
    lead_ids: list[str] = []
    touch_number: int | None = None


class ManualLeadStatusRequest(BaseModel):
    campaign_filename: str
    reason: str = ""


class SendEmailRequest(BaseModel):
    run_id: str
    day: int = 0


class SettingsRequest(BaseModel):
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    sender_email: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    zoominfo_enabled: bool = False
    zoominfo_client_id: str = ""
    zoominfo_private_key: str = ""
    max_emails_per_day: int = 150
    send_delay_seconds: int = 3


class CreateCampaignRequest(BaseModel):
    name: str
    description: str = ""
    knowledge_bases: list[str] = []
    target_personas: list[str] = []
    target_industries: list[str] = []
    tone: str = "professional"
    email_goal: str = "book a 20-minute discovery call"
    max_email_words: int = 150
    max_linkedin_chars: int = 280
    key_pain_points: list[str] = []


class CreateLeadUniverseRequest(BaseModel):
    name: str
    campaign_filename: str
    description: str = ""
    target_leads: int = 0
    source_type: str = "sales_navigator"


class CreateLeadSourceSegmentRequest(BaseModel):
    source_url: str
    label: str = ""
    filters: dict = {}
    expected_count: int = 50


def _dt(value) -> Optional[str]:
    return value.isoformat() if value else None


def _normalize_campaign(value: str) -> str:
    return (
        (value or "")
        .replace(".json", "")
        .replace("_", " ")
        .lower()
        .strip()
    )


def _match_campaign(run_campaign: str, target: str) -> bool:
    r = _normalize_campaign(run_campaign)
    t = _normalize_campaign(target)
    if not r or not t:
        return False
    return r == t or r in t or t in r


def _default_sequence_settings() -> dict:
    return {
        "touches": [
            {
                "number": 1,
                "name": "Intro",
                "delay_days": 0,
                "delay_value": 0,
                "delay_unit": "days",
                "delay_type": "calendar_days",
                "send_time_mode": "same_as_previous",
                "fixed_send_time": "",
                "subject_template": "{{company}} + quick idea",
                "email_body_template": (
                    "Hi {{first_name}},\n\n"
                    "I noticed your work at {{company}} and thought this "
                    "may be relevant.\n\n"
                    "{{campaign_value_prop}}\n\n"
                    "Would a quick conversation make sense?\n\n"
                    "Best,\n{{sender_name}}"
                ),
            },
            {
                "number": 2,
                "name": "Follow-up",
                "delay_days": 3,
                "delay_value": 3,
                "delay_unit": "days",
                "delay_type": "calendar_days",
                "send_time_mode": "same_as_previous",
                "fixed_send_time": "",
                "subject_template": "Re: {{touch1_subject}}",
                "email_body_template": (
                    "Hi {{first_name}},\n\n"
                    "Following up on my previous note about {{campaign_value_prop}}.\n\n"
                    "{{current_followup_goal}}\n\n"
                    "Would a short conversation still make sense?\n\n"
                    "Best,\n{{sender_name}}"
                ),
            },
            {
                "number": 3,
                "name": "Final follow-up",
                "delay_days": 4,
                "delay_value": 4,
                "delay_unit": "days",
                "delay_type": "calendar_days",
                "send_time_mode": "same_as_previous",
                "fixed_send_time": "",
                "subject_template": "Following up - {{company}}",
                "email_body_template": (
                    "Hi {{first_name}},\n\n"
                    "I do not want to keep filling your inbox, so I will "
                    "make this my final follow-up after my earlier note on "
                    "{{previous_subject}}.\n\n"
                    "Should I close the loop for now, or would you be open "
                    "to a quick discussion?\n\n"
                    "Best,\n{{sender_name}}"
                ),
            },
        ]
    }


def _legacy_sequence_settings_from_file(campaign_filename: str) -> dict:
    seq_path = Path("campaigns/sequences.json")
    default = _default_sequence_settings()

    if not seq_path.exists():
        return default

    try:
        all_settings = json.loads(seq_path.read_text(encoding="utf-8"))
        return all_settings.get(campaign_filename, default)
    except Exception:
        return default


def _step_payload(step: CampaignSequenceStep) -> dict:
    return {
        "id": step.id,
        "campaign_filename": step.campaign_filename,
        "touch_number": step.touch_number,
        "number": step.touch_number,
        "touch_name": step.touch_name,
        "name": step.touch_name,
        "delay_days": step.delay_days,
        "delay_value": step.delay_value if step.delay_value else step.delay_days,
        "delay_unit": step.delay_unit or "days",
        "delay_type": step.delay_type or "calendar_days",
        "send_time_mode": step.send_time_mode or "same_as_previous",
        "fixed_send_time": step.fixed_send_time or "",
        "subject_template": step.subject_template,
        "email_body_template": step.email_body_template,
        "is_active": step.is_active,
        "created_at": _dt(step.created_at),
        "updated_at": _dt(step.updated_at),
    }


def _rules_payload(rules: CampaignSequenceRules) -> dict:
    return {
        "id": rules.id,
        "campaign_filename": rules.campaign_filename,
        "timezone": rules.timezone,
        "mode": rules.mode or "review",
        "stop_on_reply": rules.stop_on_reply,
        "stop_on_bounce": rules.stop_on_bounce,
        "stop_on_unsubscribe": rules.stop_on_unsubscribe,
        "skip_no_email": rules.skip_no_email,
        "skip_weekends": rules.skip_weekends,
        "send_window_start": rules.send_window_start,
        "send_window_end": rules.send_window_end,
        "daily_send_limit": rules.daily_send_limit,
        "delay_between_sends_seconds": rules.delay_between_sends_seconds,
        "require_approval_for_touch1": rules.require_approval_for_touch1,
        "require_approval_for_followups": rules.require_approval_for_followups,
        "created_at": _dt(rules.created_at),
        "updated_at": _dt(rules.updated_at),
    }


def _load_sequence_settings(campaign_filename: str) -> dict:
    legacy = _legacy_sequence_settings_from_file(campaign_filename)
    steps, rules = campaign_sequence_repo.ensure_defaults(
        campaign_filename,
        default_steps=legacy.get("touches") or [],
    )
    step_rows = [_step_payload(step) for step in steps]
    return {
        "steps": step_rows,
        "touches": step_rows,
        "rules": _rules_payload(rules),
    }


def _save_sequence_settings(campaign_filename: str, settings: dict) -> None:
    seq_path = Path("campaigns/sequences.json")
    seq_path.parent.mkdir(parents=True, exist_ok=True)

    all_settings = {}
    if seq_path.exists():
        try:
            all_settings = json.loads(seq_path.read_text(encoding="utf-8"))
        except Exception:
            all_settings = {}

    touches = settings.get("touches") or settings.get("steps") or []
    all_settings[campaign_filename] = {"touches": touches}
    seq_path.write_text(json.dumps(all_settings, indent=2), encoding="utf-8")

    for item in touches:
        touch_number = int(item.get("touch_number") or item.get("number") or 0)
        if touch_number <= 0:
            raise HTTPException(
                status_code=400,
                detail="touch_number must be positive",
            )
        delay_days = int(item.get("delay_days") or 0)
        delay_value = int(item.get("delay_value") or delay_days or 0)
        delay_unit = (item.get("delay_unit") or "days").lower()
        delay_type = (item.get("delay_type") or "calendar_days").lower()
        send_time_mode = (item.get("send_time_mode") or "same_as_previous").lower()
        if delay_days < 0:
            raise HTTPException(
                status_code=400,
                detail="delay_days must be >= 0",
            )
        if delay_value < 0:
            raise HTTPException(
                status_code=400,
                detail="delay_value must be >= 0",
            )
        if delay_unit not in {"minutes", "hours", "days"}:
            raise HTTPException(
                status_code=400,
                detail="delay_unit must be minutes, hours, or days",
            )
        if delay_type not in {"calendar_days", "business_days"}:
            raise HTTPException(
                status_code=400,
                detail="delay_type must be calendar_days or business_days",
            )
        if send_time_mode not in {
            "same_as_previous",
            "fixed_time",
            "next_available_in_window",
        }:
            raise HTTPException(
                status_code=400,
                detail="Invalid send_time_mode",
            )
        campaign_sequence_repo.save_step(CampaignSequenceStep(
            campaign_filename=campaign_filename,
            touch_number=touch_number,
            touch_name=item.get("touch_name") or item.get("name") or "",
            delay_days=delay_days,
            delay_value=delay_value,
            delay_unit=delay_unit,
            delay_type=delay_type,
            send_time_mode=send_time_mode,
            fixed_send_time=item.get("fixed_send_time", "") or "",
            subject_template=item.get("subject_template", "") or "",
            email_body_template=item.get("email_body_template", "") or "",
            linkedin_message_template="",
            is_active=bool(item.get("is_active", True)),
        ))

    touch_numbers = [
        int(item.get("touch_number") or item.get("number") or 0)
        for item in touches
    ]
    if touch_numbers:
        placeholders = ",".join("?" for _ in touch_numbers)
        with db._conn() as conn:
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

    rules_data = settings.get("rules") or {}
    if rules_data:
        daily_limit = int(rules_data.get("daily_send_limit", 50) or 50)
        delay_seconds = int(
            rules_data.get("delay_between_sends_seconds", 60) or 0
        )
        if daily_limit <= 0:
            raise HTTPException(
                status_code=400,
                detail="daily_send_limit must be > 0",
            )
        if delay_seconds < 0:
            raise HTTPException(
                status_code=400,
                detail="delay_between_sends_seconds must be >= 0",
            )
        existing = campaign_sequence_repo.get_rules(campaign_filename)
        mode = (rules_data.get("mode") or "review").lower()
        if mode not in {"review", "autopilot"}:
            raise HTTPException(
                status_code=400,
                detail="mode must be review or autopilot",
            )
        rules = CampaignSequenceRules(
            campaign_filename=campaign_filename,
            timezone=rules_data.get("timezone", "Asia/Karachi") or "Asia/Karachi",
            mode=mode,
            stop_on_reply=bool(rules_data.get("stop_on_reply", True)),
            stop_on_bounce=bool(rules_data.get("stop_on_bounce", True)),
            stop_on_unsubscribe=bool(
                rules_data.get("stop_on_unsubscribe", True)
            ),
            skip_no_email=bool(rules_data.get("skip_no_email", True)),
            skip_weekends=bool(rules_data.get("skip_weekends", True)),
            send_window_start=rules_data.get("send_window_start", "09:00"),
            send_window_end=rules_data.get("send_window_end", "17:00"),
            daily_send_limit=daily_limit,
            delay_between_sends_seconds=delay_seconds,
            require_approval_for_touch1=bool(
                rules_data.get("require_approval_for_touch1", True)
            ),
            require_approval_for_followups=bool(
                rules_data.get("require_approval_for_followups", True)
            ),
        )
        if existing:
            rules.id = existing.id
        campaign_sequence_repo.save_rules(rules)


def _campaign_run_ids(campaign_filename: str) -> list[str]:
    all_runs = run_repo.list_all()
    ids = []

    for run in all_runs:
        filters = run.filters or {}
        run_campaign = (
            filters.get("campaign_key")
            or filters.get("campaign")
            or ""
        )

        if _match_campaign(run_campaign, campaign_filename):
            ids.append(run.id)

    return ids


def _run_response(run: PipelineRun) -> RunResponse:
    return RunResponse(
        id=run.id,
        status=run.status.value,
        filters=run.filters,
        total_scraped=run.total_scraped,
        total_enriched=run.total_enriched,
        total_warm=run.total_warm,
        total_cold=run.total_cold,
        total_no_email=run.total_no_email,
        total_exported=run.total_exported,
        error=run.error,
        started_at=_dt(run.started_at) or "",
        completed_at=_dt(run.completed_at),
    )


def _lead_response(lead: Lead) -> LeadResponse:
    return LeadResponse(
        id=lead.id,
        full_name=lead.full_name,
        first_name=lead.first_name,
        last_name=lead.last_name,
        title=lead.title,
        company=lead.company,
        company_domain=lead.company_domain,
        email=lead.email,
        email_confidence=lead.email_confidence,
        phone=lead.phone,
        location=lead.location,
        linkedin_url=lead.linkedin_url,
        company_linkedin_url=lead.company_linkedin_url,
        segment=lead.segment.value,
        intent_score=lead.intent_score,
        status=lead.status.value,
        email_sequence_status=getattr(
            lead,
            "email_sequence_status",
            "not_started",
        ),
    )


def _universe_payload(universe: LeadUniverse) -> dict:
    return universe.to_dict()


def _segment_payload(segment: LeadSourceSegment) -> dict:
    data = segment.to_dict()
    try:
        data["filters"] = json.loads(segment.filters_json or "{}")
    except Exception:
        data["filters"] = {}
    return data


def _draft_response(lead: Lead) -> DraftResponse:
    return DraftResponse(
        id=lead.id,
        full_name=lead.full_name,
        company=lead.company,
        title=lead.title,
        email=lead.email,
        phone=lead.phone,
        location=lead.location,
        email_subject=getattr(lead, "email_subject", "") or "",
        email_body=getattr(lead, "email_body", "") or "",
        linkedin_message=getattr(lead, "linkedin_message", "") or "",
        research_summary=getattr(lead, "research_summary", "") or "",
        campaign_name=getattr(lead, "campaign_name", "") or "",
        personalised_at=getattr(lead, "personalised_at", None) or None,
        email_sequence_status=getattr(
            lead,
            "email_sequence_status",
            "not_started",
        ) or "not_started",
        day1_sent_at=getattr(lead, "day1_sent_at", None) or None,
        day3_sent_at=getattr(lead, "day3_sent_at", None) or None,
        day7_sent_at=getattr(lead, "day7_sent_at", None) or None,
    )


def _ensure_draft_columns(run: PipelineRun) -> None:
    PersonalisationOrchestrator()
    EmailAgent(run, [])


def _draft_from_row(row) -> dict:
    return {
        "id": row["id"],
        "full_name": row["full_name"] or "",
        "company": row["company"] or "",
        "email": row["email"] or "",
        "phone": row["phone"] or "",
        "title": row["title"] or "",
        "location": row["location"] or "",
        "email_subject": row["email_subject"] or "",
        "email_body": row["email_body"] or "",
        "linkedin_message": row["linkedin_message"] or "",
        "research_summary": row["research_summary"] or "",
        "campaign_name": row["campaign_name"] or "",
        "personalised_at": row["personalised_at"] or "",
        "email_sequence_status": row["email_sequence_status"] or "not_started",
        "day1_sent_at": row["day1_sent_at"] or "",
        "day3_sent_at": row["day3_sent_at"] or "",
        "day7_sent_at": row["day7_sent_at"] or "",
    }


def _get_draft_row(run_id: str, lead_id: str):
    row = db._conn().execute(
        """
        SELECT id, run_id, full_name, company, email, phone, title, location,
               email_subject, email_body, linkedin_message, research_summary,
               campaign_name, personalised_at, email_sequence_status,
               day1_sent_at, day3_sent_at, day7_sent_at
        FROM leads
        WHERE run_id = ? AND id = ?
        """,
        (run_id, lead_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    return row


def _event_json(event: AgentEvent) -> dict:
    return {
        "event_type": event.event_type.value,
        "agent_name": event.agent_name,
        "payload": event.payload,
        "timestamp": _dt(event.timestamp),
        "error": event.error,
    }


def _filters(request: StartPipelineRequest) -> dict:
    return {
        "titles": request.titles,
        "industries": request.industries,
        "geos": request.geos,
        "company_sizes": request.company_sizes,
        "keywords": request.keywords,
        "start_url": request.start_url,
        "campaign": request.campaign or "",
        "campaign_key": request.campaign or "",
    }


@app.post("/api/runs/start", response_model=RunResponse)
def start_pipeline(request: StartPipelineRequest) -> RunResponse:
    settings.max_leads = request.max_leads
    try:
        run = orchestrator.start_pipeline(_filters(request))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run_repo.save(run)
    return _run_response(run)


@app.get("/api/runs", response_model=list[RunResponse])
def list_runs() -> list[RunResponse]:
    return [_run_response(run) for run in run_repo.list_all()]


@app.get("/api/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> RunResponse:
    run = run_repo.get(run_id)
    if run is None:
        active_run = orchestrator.get_active_run()
        if active_run and active_run.id == run_id:
            run = active_run
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_response(run)


@app.get("/api/runs/{run_id}/events")
def get_run_events(run_id: str, limit: int = Query(default=50, ge=1)) -> list[dict]:
    return event_repo.get_by_run(run_id, limit=limit)


@app.get("/api/leads")
def get_all_leads(
    segment: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """All leads across all runs with optional filters."""
    conn = db._conn()
    existing_cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(leads)").fetchall()
    }

    extra = []
    for col in [
        "phone",
        "location",
        "email_subject",
        "email_sequence_status",
        "campaign_name",
        "day1_sent_at",
        "day3_sent_at",
        "day7_sent_at",
    ]:
        if col in existing_cols:
            extra.append(col)
    extra_sql = (", " + ", ".join(extra)) if extra else ""

    where_parts = ["1=1"]
    params = []
    if segment:
        where_parts.append("segment = ?")
        params.append(segment.upper())
    if run_id:
        where_parts.append("run_id = ?")
        params.append(run_id)
    where_sql = " AND ".join(where_parts)

    rows = conn.execute(
        f"""
        SELECT id, run_id, full_name, first_name, last_name,
               title, company, company_domain, linkedin_url,
               email, email_confidence, intent_score,
               segment, status{extra_sql}
        FROM leads
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()

    return [dict(row) for row in rows]


@app.get("/api/runs/{run_id}/leads", response_model=list[LeadResponse])
def get_run_leads(
    run_id: str,
    segment: Optional[str] = None,
    limit: int = Query(default=100, ge=1),
    offset: int = Query(default=0, ge=0),
) -> list[LeadResponse]:
    leads = lead_repo.get_by_run(run_id)
    if segment:
        target = segment.upper()
        leads = [lead for lead in leads if lead.segment.value == target]
    return [_lead_response(lead) for lead in leads[offset : offset + limit]]


@app.get("/api/runs/{run_id}/leads/export")
def export_run_leads(run_id: str) -> dict:
    run = run_repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    leads = lead_repo.get_by_run(run_id)
    exporter = orchestrator_module.ExportAgent(run, leads)
    exporter.on_event(lambda event: event_repo.save(event))
    files = exporter.execute()
    run_repo.save(run)
    lead_repo.save_batch(run.id, leads)
    return {"files": files}


@app.get("/api/runs/{run_id}/leads/download-for-zoominfo")
def download_for_zoominfo(run_id: str):
    """
    Download leads as CSV formatted for ZoomInfo bulk upload.
    Columns: First Name, Last Name, Company Name, LinkedIn URL, Location
    This CSV is intentionally formatted for ZoomInfo bulk upload.
    It does not represent the full lead export and may intentionally
    exclude some internal fields. Use Export XLSX for the complete lead data.
    """
    from fastapi.responses import StreamingResponse

    leads = lead_repo.get_by_run(run_id)
    if not leads:
        raise HTTPException(status_code=404, detail="No leads found")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "First Name", "Last Name", "Company Name",
        "LinkedIn URL", "Location", "Job Title"
    ])
    writer.writeheader()
    campaign_filename = (
        (getattr(run_repo.get(run_id), "filters", {}) or {}).get("campaign_key")
        or (getattr(run_repo.get(run_id), "filters", {}) or {}).get("campaign")
        or ""
    )
    for lead in leads:
        writer.writerow({
            "First Name": lead.first_name,
            "Last Name": lead.last_name,
            "Company Name": lead.company,
            "LinkedIn URL": lead.linkedin_url,
            "Location": lead.location,
            "Job Title": lead.title,
        })
        if campaign_filename:
            _add_activity(
                lead,
                campaign_filename,
                "exported_for_zoominfo",
                "Lead exported for ZoomInfo",
                "Run ZoomInfo export downloaded",
                {"run_id": run_id},
            )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition":
                f"attachment; filename=leads_{run_id[:8]}_for_zoominfo.csv"
        }
    )


@app.post("/api/runs/{run_id}/leads/upload-enriched")
async def upload_enriched_csv(
    run_id: str,
    file: UploadFile = File(...)
) -> dict:
    """
    Accept ZoomInfo enriched CSV, match to existing leads,
    update with email/phone/intent data.
    """
    run = run_repo.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    contents = await file.read()
    text = contents.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    result = lead_repo.update_from_enrichment(run_id, rows)
    leads = lead_repo.get_by_run(run_id)
    segmenter = SegmentAgent(run, leads)
    segmenter.on_event(lambda event: event_repo.save(event))
    segmented = segmenter.execute()
    lead_repo.save_batch(run.id, segmented)
    run_repo.save(run)

    return {
        "message": "Enrichment import complete",
        "total_rows_in_file": len(rows),
        "matched": result.get("matched", 0),
        "unmatched": result.get("unmatched", 0),
        "updated": result.get("updated", 0),
        "total_warm": run.total_warm,
        "total_cold": run.total_cold,
        "total_no_email": run.total_no_email,
    }


@app.get("/api/status")
def get_status() -> dict:
    return orchestrator.get_status()


@app.get("/api/stats")
def get_stats() -> dict:
    """Dashboard overview stats aggregated across all runs."""
    conn = db._conn()
    existing_cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(leads)").fetchall()
    }

    total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] or 0
    emails_sent = 0
    replies = 0
    if "email_sequence_status" in existing_cols:
        emails_sent = conn.execute(
            """
            SELECT COUNT(*) FROM leads
            WHERE email_sequence_status IN
              ('day1_sent','day3_sent','complete')
            """
        ).fetchone()[0] or 0
        replies = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE email_sequence_status = 'replied'"
        ).fetchone()[0] or 0

    total_runs = (
        conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] or 0
    )

    return {
        "total_leads": total_leads,
        "emails_sent": emails_sent,
        "replies": replies,
        "total_runs": total_runs,
    }


@app.post("/api/settings")
def save_settings(request: SettingsRequest) -> dict:
    """
    Save settings to .env file.
    Only updates non-empty secret/text fields.
    """
    env_path = Path(".env")
    existing = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                existing[key.strip()] = val.strip()

    mapping = {
        "AZURE_TENANT_ID": request.azure_tenant_id,
        "AZURE_CLIENT_ID": request.azure_client_id,
        "AZURE_CLIENT_SECRET": request.azure_client_secret,
        "SENDER_EMAIL": request.sender_email,
        "OPENAI_API_KEY": request.openai_api_key,
        "OPENAI_MODEL": request.openai_model,
        "ZOOMINFO_ENABLED": "true" if request.zoominfo_enabled else "false",
        "ZOOMINFO_CLIENT_ID": request.zoominfo_client_id,
        "ZOOMINFO_PRIVATE_KEY": request.zoominfo_private_key,
        "MAX_EMAILS_PER_DAY": str(request.max_emails_per_day),
        "SEND_DELAY_SECONDS": str(request.send_delay_seconds),
    }

    always_update = {
        "ZOOMINFO_ENABLED",
        "MAX_EMAILS_PER_DAY",
        "SEND_DELAY_SECONDS",
    }
    updated = []
    for key, value in mapping.items():
        if (value and value not in ("", "false")) or key in always_update:
            existing[key] = value
            updated.append(key)

    env_path.write_text(
        "\n".join(f"{key}={value}" for key, value in existing.items()) + "\n",
        encoding="utf-8",
    )
    for key, value in existing.items():
        os.environ[key] = value

    import importlib
    import src.config as config_module

    importlib.reload(config_module)
    globals()["settings"] = config_module.settings

    return {"saved": True, "updated": updated}


@app.post("/api/settings/test-email")
def test_email_connection() -> dict:
    """Send a test email to the sender's own address."""
    from dotenv import load_dotenv as _load_dotenv
    import msal as _msal
    import requests as _requests

    _load_dotenv(override=True)
    tenant_id = os.getenv("AZURE_TENANT_ID", "")
    client_id = os.getenv("AZURE_CLIENT_ID", "")
    client_secret = os.getenv("AZURE_CLIENT_SECRET", "")
    sender_email = os.getenv("SENDER_EMAIL", "")

    missing = []
    if not tenant_id:
        missing.append("AZURE_TENANT_ID")
    if not client_id:
        missing.append("AZURE_CLIENT_ID")
    if not client_secret:
        missing.append("AZURE_CLIENT_SECRET")
    if not sender_email:
        missing.append("SENDER_EMAIL")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing in .env: {', '.join(missing)}",
        )

    try:
        app_msal = _msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
        result = app_msal.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise HTTPException(
                status_code=401,
                detail=f"Token failed: {result.get('error_description')}",
            )

        response = _requests.post(
            f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail",
            headers={
                "Authorization": f"Bearer {result['access_token']}",
                "Content-Type": "application/json",
            },
            json={
                "message": {
                    "subject": "RC Sales Automation - Connection Test",
                    "body": {
                        "contentType": "Text",
                        "content": (
                            "This is a test email from RC Sales Automation.\n"
                            "Microsoft Graph API connection is working correctly."
                        ),
                    },
                    "toRecipients": [
                        {"emailAddress": {"address": sender_email}}
                    ],
                },
                "saveToSentItems": True,
            },
            timeout=15,
        )

        if response.status_code == 202:
            return {
                "success": True,
                "message": f"Test email sent to {sender_email}",
            }

        raise HTTPException(
            status_code=response.status_code,
            detail=f"Graph API error: {response.text[:200]}",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/send-emails")
def send_emails(
    run_id: str,
    request: SendRunEmailsRequest | None = None,
) -> dict:
    """Send selected real emails, or all currently due drafts if no IDs supplied."""
    run = run_repo.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    _ensure_draft_columns(run)
    lead_ids = set((request.lead_ids if request else []) or [])
    conn = db._conn()

    where = ["run_id = ?"]
    params = [run_id]
    if lead_ids:
        placeholders = ",".join("?" for _ in lead_ids)
        where.append(f"id IN ({placeholders})")
        params.extend(list(lead_ids))
    else:
        where.extend([
            "email != ''",
            "email_subject != ''",
            "email_body != ''",
            "COALESCE(email_sequence_status, '') NOT IN "
            "('replied','unsubscribed','complete')",
        ])

    rows = conn.execute(
        f"""
        SELECT id, full_name, first_name, last_name, title, company,
               location, email, email_subject, email_body,
               email_sequence_status, day1_sent_at, day3_sent_at,
               day7_sent_at
        FROM leads
        WHERE {" AND ".join(where)}
        ORDER BY created_at ASC
        """,
        params,
    ).fetchall()

    if lead_ids:
        found = {row["id"] for row in rows}
        missing_results = [
            {
                "lead_id": lead_id,
                "email": "",
                "status": "skipped",
                "reason": "Lead not found in run",
            }
            for lead_id in lead_ids - found
        ]
    else:
        missing_results = []

    if not rows and not missing_results:
        raise HTTPException(status_code=404, detail="No leads found")

    agent = EmailAgent(run, [])
    results = list(missing_results)
    sent = 0
    skipped = len(missing_results)
    failed = 0

    from datetime import datetime

    for row in rows:
        lead_id = row["id"]
        email = row["email"] or ""
        subject = row["email_subject"] or ""
        body = row["email_body"] or ""
        status = row["email_sequence_status"] or ""

        reason = ""
        if not email:
            reason = "Missing email"
        elif not subject:
            reason = "Missing email subject"
        elif not body:
            reason = "Missing email body"
        elif status in ("replied", "unsubscribed", "complete"):
            reason = f"Sequence already {status}"

        lead_obj = Lead(
            id=lead_id,
            full_name=row["full_name"] or "",
            first_name=row["first_name"] or "",
            last_name=row["last_name"] or "",
            title=row["title"] or "",
            company=row["company"] or "",
            location=row["location"] or "",
            email=email,
        )
        setattr(lead_obj, "email_subject", subject)
        seq = {
            "day1_sent_at": row["day1_sent_at"] or "",
            "day3_sent_at": row["day3_sent_at"] or "",
            "day7_sent_at": row["day7_sent_at"] or "",
            "status": status,
        }
        day_to_send = agent._next_day_to_send(seq)
        if not reason and not day_to_send:
            reason = "No email due today for this lead"

        if reason:
            skipped += 1
            results.append({
                "lead_id": lead_id,
                "email": email,
                "status": "skipped",
                "reason": reason,
            })
            continue

        send_subject, send_body = agent._message_for_day(
            lead_obj,
            subject,
            body,
            day_to_send,
        )
        direct = agent.send_direct(email, send_subject, send_body)
        if direct.get("success"):
            day_col = f"day{day_to_send}_sent_at"
            timestamp = datetime.utcnow().isoformat()
            new_status = (
                "complete"
                if day_to_send == 7
                else f"day{day_to_send}_sent"
            )
            with conn:
                conn.execute(
                    f"""
                    UPDATE leads
                    SET {day_col} = ?,
                        email_sequence_status = ?,
                        updated_at = ?
                    WHERE id = ? AND run_id = ?
                    """,
                    (
                        timestamp,
                        new_status,
                        datetime.utcnow().isoformat(),
                        lead_id,
                        run_id,
                    ),
                )
            sent += 1
            results.append({
                "lead_id": lead_id,
                "email": email,
                "status": "sent",
                "day": day_to_send,
                "reason": "",
            })
        else:
            failed += 1
            results.append({
                "lead_id": lead_id,
                "email": email,
                "status": "failed",
                "reason": direct.get("error") or "Graph API send failed",
            })

    return {
        "message": "Email send complete",
        "total_leads": len(results),
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


@app.post("/api/sequences/send")
def send_sequences(request: SequenceSendRequest) -> dict:
    """
    Send today's email batch across all completed runs.
    Determines Day 1/3/7 automatically per lead.
    """
    completed_runs = [
        run for run in run_repo.list_all()
        if run.status.value == "COMPLETED"
    ]
    if not completed_runs:
        return {
            "sent": 0,
            "skipped": 0,
            "failed": 0,
            "message": "No completed runs found",
        }

    total_sent = 0
    total_skipped = 0
    total_failed = 0
    for run in completed_runs:
        leads = lead_repo.get_by_run(run.id)
        if not leads:
            continue
        agent = EmailAgent(run, leads)
        agent.on_event(lambda event: event_repo.save(event))
        agent.execute()
        total_sent += agent.sent_count
        total_skipped += agent.skipped_count
        total_failed += agent.failed_count

    return {
        "sent": total_sent,
        "skipped": total_skipped,
        "failed": total_failed,
        "total_leads": total_sent + total_skipped + total_failed,
        "message": (
            f"{total_sent} emails sent across {len(completed_runs)} runs"
        ),
    }


@app.get("/api/sequences/stats")
def get_sequence_stats() -> dict:
    """Email sequence counts across all leads."""
    conn = db._conn()
    existing_cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(leads)").fetchall()
    }
    required_cols = {
        "email_sequence_status",
        "day1_sent_at",
        "day3_sent_at",
        "day7_sent_at",
    }
    if not required_cols.issubset(existing_cols):
        return {
            "due_today": 0,
            "in_sequence": 0,
            "replied": 0,
            "complete": 0,
        }

    from datetime import datetime

    def days_since(iso_str):
        if not iso_str:
            return 999
        try:
            return (datetime.utcnow() - datetime.fromisoformat(iso_str)).days
        except Exception:
            return 999

    rows = conn.execute(
        """
        SELECT email_sequence_status,
               day1_sent_at, day3_sent_at, day7_sent_at,
               email
        FROM leads
        WHERE email != ''
        """
    ).fetchall()

    in_sequence = 0
    due_today = 0
    replied = 0
    complete = 0
    for row in rows:
        status = row["email_sequence_status"] or ""
        day1 = row["day1_sent_at"] or ""
        day3 = row["day3_sent_at"] or ""
        day7 = row["day7_sent_at"] or ""

        if status == "replied":
            replied += 1
        elif status == "complete":
            complete += 1
        elif status in ("day1_sent", "day3_sent", "day7_sent", ""):
            in_sequence += 1
            if not day1:
                due_today += 1
            elif not day3 and days_since(day1) >= 3:
                due_today += 1
            elif not day7 and days_since(day3) >= 4:
                due_today += 1

    return {
        "due_today": due_today,
        "in_sequence": in_sequence,
        "replied": replied,
        "complete": complete,
    }


@app.get("/api/runs/{run_id}/email-preview")
def email_preview(run_id: str) -> list[dict]:
    """
    Return all leads that are ready to send today
    with their personalised message preview.
    """
    run = run_repo.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    conn = db._conn()
    existing_cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(leads)").fetchall()
    }
    required_cols = {
        "email_subject",
        "email_body",
        "linkedin_message",
        "email_sequence_status",
        "day1_sent_at",
        "day3_sent_at",
        "day7_sent_at",
    }
    if not required_cols.issubset(existing_cols):
        return []

    rows = conn.execute(
        """
        SELECT id, full_name, first_name, last_name, email, title, company,
               location,
               email_subject, email_body, linkedin_message,
               email_sequence_status,
               day1_sent_at, day3_sent_at, day7_sent_at
        FROM leads
        WHERE run_id = ?
          AND email != ''
          AND email_subject != ''
          AND email_sequence_status NOT IN
              ('replied','unsubscribed','complete')
        ORDER BY created_at ASC
        """,
        (run_id,),
    ).fetchall()

    agent = EmailAgent(run, [])
    previews = []
    for row in rows:
        seq = {
            "day1_sent_at": row["day1_sent_at"] or "",
            "day3_sent_at": row["day3_sent_at"] or "",
            "day7_sent_at": row["day7_sent_at"] or "",
            "status": row["email_sequence_status"] or "",
        }
        day_due = agent._next_day_to_send(seq)

        if not day_due:
            continue

        subject = row["email_subject"] or ""
        body = row["email_body"] or ""
        lead_obj = Lead(
            id=row["id"],
            full_name=row["full_name"] or "",
            first_name=row["first_name"] or "",
            last_name=row["last_name"] or "",
            title=row["title"] or "",
            company=row["company"] or "",
            location=row["location"] or "",
            email=row["email"] or "",
        )
        send_subject, send_body = agent._message_for_day(
            lead_obj,
            subject,
            body,
            day_due,
        )
        linkedin_message = agent._linkedin_for_day(
            lead_obj,
            row["linkedin_message"] or "",
            day_due,
        )

        previews.append({
            "lead_id": row["id"],
            "full_name": row["full_name"],
            "email": row["email"],
            "title": row["title"],
            "company": row["company"],
            "day_due": day_due,
            "email_subject": send_subject,
            "email_body": send_body,
            "linkedin_message": linkedin_message,
        })

    return previews


@app.get("/api/runs/{run_id}/drafts", response_model=list[DraftResponse])
def get_run_drafts(
    run_id: str,
    campaign_name: str | None = None,
) -> list[DraftResponse]:
    run = run_repo.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    _ensure_draft_columns(run)
    leads = lead_repo.get_by_run(run_id)
    drafts = []
    for lead in leads:
        subject = getattr(lead, "email_subject", "") or ""
        body = getattr(lead, "email_body", "") or ""
        if not subject and not body:
            continue
        if campaign_name:
            lead_campaign = getattr(lead, "campaign_name", "") or ""
            if (
                lead_campaign != campaign_name
                and campaign_name.replace(".json", "") not in lead_campaign
                and lead_campaign.replace(".json", "") not in campaign_name
            ):
                continue
        drafts.append(_draft_response(lead))
    return drafts


@app.post("/api/runs/{run_id}/drafts/{lead_id}/update")
def update_draft(
    run_id: str,
    lead_id: str,
    request: DraftUpdateRequest,
) -> dict:
    run = run_repo.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    _ensure_draft_columns(run)
    from datetime import datetime

    with db._conn() as conn:
        cur = conn.execute(
            """
            UPDATE leads
            SET
              email = COALESCE(NULLIF(?, ''), email),
              email_subject = ?,
              email_body = ?,
              linkedin_message = ?,
              updated_at = ?
            WHERE id = ? AND run_id = ?
            """,
            (
                request.email,
                request.email_subject,
                request.email_body,
                request.linkedin_message,
                datetime.utcnow().isoformat(),
                lead_id,
                run_id,
            ),
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Draft not found")

    return _draft_from_row(_get_draft_row(run_id, lead_id))


@app.post("/api/runs/{run_id}/drafts/{lead_id}/send-test-copy")
def send_test_copy(
    run_id: str,
    lead_id: str,
    request: SendTestCopyRequest,
) -> dict:
    run = run_repo.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    test_to = (request.test_to_email or "").strip()
    if not test_to or "@" not in test_to:
        raise HTTPException(status_code=400, detail="Valid test email required")

    _ensure_draft_columns(run)
    row = _get_draft_row(run_id, lead_id)
    subject = row["email_subject"] or ""
    body = row["email_body"] or ""
    if not subject or not body:
        raise HTTPException(status_code=400, detail="Draft has no email body")

    test_subject = f"[TEST COPY] {subject}"
    test_body = (
        "TEST COPY\n"
        f"Original lead: {row['full_name'] or ''}, {row['company'] or ''}\n"
        f"Original recipient: {row['email'] or ''}\n\n"
        "----\n\n"
        f"{body}"
    )
    result = EmailAgent(run, []).send_direct(test_to, test_subject, test_body)
    return {
        "success": bool(result.get("success")),
        "error": result.get("error", ""),
        "to": test_to,
    }


class UpdateEmailContentRequest(BaseModel):
    email_subject: str = ""
    email_body: str = ""
    linkedin_message: str = ""
    recipient_email: str = ""


@app.put("/api/leads/{lead_id}/email-content")
def update_email_content(
    lead_id: str,
    request: UpdateEmailContentRequest,
) -> dict:
    """
    Save edited email content back to DB for a specific lead.
    Called when user edits subject/body in the compose window.
    """
    conn = db._conn()

    # ensure columns exist
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(leads)").fetchall()
    }
    updates = {}
    if request.email_subject and "email_subject" in existing:
        updates["email_subject"] = request.email_subject
    if request.email_body and "email_body" in existing:
        updates["email_body"] = request.email_body
    if request.linkedin_message and "linkedin_message" in existing:
        updates["linkedin_message"] = request.linkedin_message
    if request.recipient_email and "email" in existing:
        updates["email"] = request.recipient_email

    if not updates:
        return {"updated": False, "reason": "nothing to update"}

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [lead_id]
    with conn:
        conn.execute(
            f"UPDATE leads SET {set_clause} WHERE id = ?",
            values,
        )
    return {"updated": True, "fields": list(updates.keys())}


@app.post("/api/leads/{lead_id}/send-email")
def send_single_email(lead_id: str) -> dict:
    """Send email to one specific lead."""
    conn = db._conn()
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(leads)").fetchall()
    }

    required = {"email", "run_id"}
    if not required.issubset(existing):
        raise HTTPException(status_code=400, detail="Missing columns")

    row = conn.execute(
        "SELECT * FROM leads WHERE id = ?",
        (lead_id,),
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not row["email"]:
        raise HTTPException(status_code=400, detail="Lead has no email address")

    subject = (
        row["email_subject"] if "email_subject" in existing else ""
    ) or ""
    body = (
        row["email_body"] if "email_body" in existing else ""
    ) or ""
    if not subject or not body:
        raise HTTPException(
            status_code=400,
            detail="No personalised message. Run personalisation first.",
        )

    run = run_repo.get(row["run_id"])
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    day1 = (row["day1_sent_at"] if "day1_sent_at" in existing else "") or ""
    day3 = (row["day3_sent_at"] if "day3_sent_at" in existing else "") or ""
    day7 = (row["day7_sent_at"] if "day7_sent_at" in existing else "") or ""
    status = (
        row["email_sequence_status"]
        if "email_sequence_status" in existing
        else ""
    ) or ""

    if status in ("replied", "unsubscribed", "complete"):
        raise HTTPException(
            status_code=400,
            detail=f"Sequence already: {status}",
        )

    from src.models import Lead as _Lead, LeadStatus, Segment

    lead_obj = _Lead(
        id=row["id"],
        full_name=row["full_name"] or "",
        first_name=row["first_name"] or "",
        last_name=row["last_name"] or "",
        title=row["title"] or "",
        company=row["company"] or "",
        location=row["location"] or "",
        email=row["email"] or "",
        status=LeadStatus.ENRICHED,
        segment=Segment.COLD,
    )
    setattr(lead_obj, "email_subject", subject)

    agent = EmailAgent(run, [lead_obj])
    day_to_send = agent._next_day_to_send({
        "day1_sent_at": day1,
        "day3_sent_at": day3,
        "day7_sent_at": day7,
        "status": status,
    })
    if not day_to_send:
        raise HTTPException(
            status_code=400,
            detail="No email due today for this lead.",
        )

    send_subject, send_body = agent._message_for_day(
        lead_obj,
        subject,
        body,
        day_to_send,
    )

    success = agent._send_email(row["email"], send_subject, send_body)

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Microsoft Graph API send failed. Check Azure credentials."
        )

    day_col = f"day{day_to_send}_sent_at"
    new_status = "complete" if day_to_send == 7 else f"day{day_to_send}_sent"
    from datetime import datetime

    with conn:
        conn.execute(
            f"""
            UPDATE leads
            SET {day_col} = ?,
                email_sequence_status = ?
            WHERE id = ?
            """,
            (datetime.utcnow().isoformat(), new_status, lead_id),
        )

    return {
        "sent": True,
        "lead_id": lead_id,
        "to": row["email"],
        "subject": send_subject,
        "day": day_to_send,
        "new_status": new_status,
    }


@app.get("/api/runs/{run_id}/email-status")
def get_email_status(run_id: str) -> list[dict]:
    """Return email sequence status for all leads in a run."""
    run = run_repo.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    EmailAgent(run, [])
    rows = db._conn().execute(
        """
        SELECT id, full_name, email, email_sequence_status,
               day1_sent_at, day3_sent_at, day7_sent_at
        FROM leads
        WHERE run_id = ?
        ORDER BY created_at ASC
        """,
        (run_id,),
    ).fetchall()
    return [
        {
            "lead_id": row["id"],
            "name": row["full_name"],
            "email": row["email"],
            "status": row["email_sequence_status"] or "not_started",
            "day1_sent_at": row["day1_sent_at"] or "",
            "day3_sent_at": row["day3_sent_at"] or "",
            "day7_sent_at": row["day7_sent_at"] or "",
        }
        for row in rows
    ]


@app.post("/api/runs/{run_id}/personalise")
def personalise_run(run_id: str, request: PersonaliseRequest) -> dict:
    logger.info(
        "Personalise request run=%s campaign=%s lead_ids=%s limit=%s",
        run_id,
        request.campaign_name,
        len(request.lead_ids),
        request.limit,
    )
    run = run_repo.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not request.campaign_name:
        raise HTTPException(status_code=400, detail="campaign_name is required")
    if not request.lead_ids and not request.limit:
        raise HTTPException(
            status_code=400,
            detail="Select leads or provide a limit",
        )

    personalisation_orchestrator = PersonalisationOrchestrator()
    result = personalisation_orchestrator.run(
        run_id=run_id,
        campaign_name=request.campaign_name,
        lead_ids=request.lead_ids,
        limit=request.limit,
        prefer_email=True,
    )
    return {
        "success": not result.get("error"),
        "generated": result.get("success", 0),
        "skipped": result.get("skipped", 0),
        "failed": result.get("failed", 0),
        "results": result.get("results", []),
        "campaign": result.get("campaign", request.campaign_name),
        "error": result.get("error", ""),
    }


def _lead_table_columns() -> set[str]:
    conn = db._conn()
    return {
        row[1]
        for row in conn.execute("PRAGMA table_info(leads)").fetchall()
    }


def _campaign_runs(campaign_filename: str) -> list[PipelineRun]:
    run_ids = set(_campaign_run_ids(campaign_filename))
    if not run_ids:
        return []
    return [run for run in run_repo.list_all() if run.id in run_ids]


def _row_dict(row) -> dict:
    return dict(row)


def _campaign_lead_rows(
    campaign_filename: str,
    segment: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: Optional[int] = 500,
    offset: int = 0,
    drafts_only: bool = False,
) -> list[dict]:
    conn = db._conn()
    existing = _lead_table_columns()
    run_ids = [run_id] if run_id else _campaign_run_ids(campaign_filename)
    if not run_ids:
        return []

    columns = [
        "id",
        "run_id",
        "full_name",
        "company",
        "title",
        "email",
        "phone",
        "location",
        "segment",
        "status",
        "email_sequence_status",
        "personalised_at",
        "day1_sent_at",
        "day3_sent_at",
        "day7_sent_at",
        "email_subject",
        "email_body",
        "linkedin_message",
        "research_summary",
        "campaign_name",
    ]
    select_cols = [col for col in columns if col in existing]
    placeholders = ",".join("?" for _ in run_ids)
    where = [f"run_id IN ({placeholders})"]
    params: list = list(run_ids)

    if segment and segment.lower() not in {"all", ""}:
        value = segment.upper().replace("-", "_")
        where.append("segment = ?")
        params.append(value)

    if drafts_only:
        draft_checks = []
        if "email_subject" in existing:
            draft_checks.append("COALESCE(email_subject, '') != ''")
        if "email_body" in existing:
            draft_checks.append("COALESCE(email_body, '') != ''")
        if not draft_checks:
            return []
        where.append("(" + " OR ".join(draft_checks) + ")")

    order_sql = "created_at ASC" if "created_at" in existing else "id ASC"
    limit_sql = ""
    if limit is not None:
        limit_sql = " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

    rows = conn.execute(
        f"""
        SELECT {", ".join(select_cols)}
        FROM leads
        WHERE {" AND ".join(where)}
        ORDER BY {order_sql}
        {limit_sql}
        """,
        params,
    ).fetchall()
    return [_row_dict(row) for row in rows]


def _campaign_lead_payload(row: dict) -> dict:
    return {
        "id": row.get("id", ""),
        "run_id": row.get("run_id", ""),
        "full_name": row.get("full_name", "") or "",
        "company": row.get("company", "") or "",
        "title": row.get("title", "") or "",
        "email": row.get("email", "") or "",
        "phone": row.get("phone", "") or "",
        "location": row.get("location", "") or "",
        "segment": row.get("segment", "") or "",
        "status": row.get("status", "") or "",
        "email_sequence_status": (
            row.get("email_sequence_status", "") or "not_started"
        ),
        "personalised_at": row.get("personalised_at") or "",
        "day1_sent_at": row.get("day1_sent_at") or "",
        "day3_sent_at": row.get("day3_sent_at") or "",
        "day7_sent_at": row.get("day7_sent_at") or "",
    }


def _campaign_draft_payload(row: dict) -> dict:
    payload = _campaign_lead_payload(row)
    payload.update({
        "email_subject": row.get("email_subject", "") or "",
        "email_body": row.get("email_body", "") or "",
        "linkedin_message": row.get("linkedin_message", "") or "",
        "research_summary": row.get("research_summary", "") or "",
        "campaign_name": row.get("campaign_name", "") or "",
    })
    return payload


def _campaign_leads(
    campaign_filename: str,
    exclude_run_id: str = "",
) -> list[Lead]:
    leads = []
    for run_id in _campaign_run_ids(campaign_filename):
        if exclude_run_id and run_id == exclude_run_id:
            continue
        leads.extend(lead_repo.get_by_run(run_id))
    return leads


def _norm_key(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _row_value(row: dict, *names: str) -> str:
    normalized = {_norm_key(key): value for key, value in row.items()}
    for name in names:
        value = normalized.get(_norm_key(name))
        if value is not None:
            return str(value).strip()
    return ""


def _norm_url(value: str) -> str:
    return (
        (value or "")
        .strip()
        .lower()
        .rstrip("/")
        .split("?")[0]
    )


def _norm_name_company(name: str, company: str) -> str:
    return f"{(name or '').strip().lower()}|{(company or '').strip().lower()}"


def _normalize_match(value: str) -> str:
    return (value or "").strip().lower()


def _split_location(row: dict) -> str:
    location = _row_value(row, "Location", "location")
    if location:
        return location
    parts = [
        _row_value(row, "City"),
        _row_value(row, "State"),
        _row_value(row, "Country"),
    ]
    return ", ".join(part for part in parts if part)


def _lead_dedupe_keys(lead: Lead) -> list[tuple[str, str]]:
    keys = []
    if lead.linkedin_url:
        keys.append(("url", _norm_url(lead.linkedin_url)))
    if lead.full_name and lead.company:
        keys.append(("name_company", _norm_name_company(
            lead.full_name,
            lead.company,
        )))
    if lead.full_name and (lead.title or lead.location):
        keys.append((
            "name_title_location",
            "|".join([
                _normalize_match(lead.full_name),
                _normalize_match(lead.title),
                _normalize_match(lead.location),
            ]),
        ))
    return [(kind, value) for kind, value in keys if value and value != "||"]


def _campaign_dedupe_index(
    campaign_filename: str,
    exclude_run_id: str = "",
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for lead in _campaign_leads(campaign_filename, exclude_run_id=exclude_run_id):
        keys.update(_lead_dedupe_keys(lead))
    return keys


def _dedupe_segment_run(
    campaign_filename: str,
    run_id: str,
    universe_id: str,
    segment_id: str,
) -> tuple[int, int, int, list[Lead]]:
    raw_leads = lead_repo.get_by_run(run_id)
    raw_count = len(raw_leads)
    seen = _campaign_dedupe_index(campaign_filename, exclude_run_id=run_id)
    accepted: list[Lead] = []
    accepted_ids: list[str] = []
    duplicate_ids: list[str] = []

    for lead in raw_leads:
        keys = _lead_dedupe_keys(lead)
        is_duplicate = bool(keys and any(key in seen for key in keys))
        if is_duplicate:
            duplicate_ids.append(lead.id)
            continue
        accepted.append(lead)
        accepted_ids.append(lead.id)
        seen.update(keys)

    duplicate_count = lead_repo.delete_for_run(run_id, duplicate_ids)
    lead_repo.tag_source(run_id, accepted_ids, universe_id, segment_id)
    return raw_count, len(accepted), duplicate_count, accepted


def _run_segment_now(segment_id: str) -> None:
    with _segment_runner_lock:
        if segment_id in _running_segment_ids:
            return
        _running_segment_ids.add(segment_id)

        segment = lead_universe_repo.get_segment(segment_id)
        if not segment:
            _running_segment_ids.discard(segment_id)
            return

        universe = lead_universe_repo.get_universe(segment.universe_id)
        if not universe:
            lead_universe_repo.update_segment_status(
                segment.id,
                "failed",
                "unknown",
            )
            _running_segment_ids.discard(segment_id)
            return

        if "linkedin.com/sales/search/people" not in segment.source_url.lower():
            lead_universe_repo.update_segment_status(
                segment.id,
                "failed",
                "unknown",
            )
            lead_universe_repo.refresh_universe_totals(segment.universe_id)
            _running_segment_ids.discard(segment_id)
            return

        max_leads = max(1, int(segment.expected_count or 50))
        filters = {
            "titles": [],
            "industries": [],
            "geos": [],
            "company_sizes": [],
            "keywords": segment.label,
            "start_url": segment.source_url,
            "campaign": segment.campaign_filename,
            "campaign_key": segment.campaign_filename,
            "lead_universe_id": segment.universe_id,
            "lead_source_segment_id": segment.id,
            "source_segment_label": segment.label,
        }
        run = PipelineRun(
            filters=filters,
            enrichment_mode=settings.enrichment_mode,
        )
        settings.max_leads = max_leads
        run.status = RunStatus.RUNNING
        run_repo.save(run)
        lead_universe_repo.update_segment_status(
            segment.id,
            "running",
            last_run_id=run.id,
        )
        lead_universe_repo.refresh_universe_totals(segment.universe_id)
        event_repo.save(AgentEvent(
            EventType.PIPELINE_STARTED,
            "LeadUniverseRunner",
            run.id,
            payload={"segment_id": segment.id, "universe_id": universe.id},
        ))

        try:
            scraper = ScraperAgent(run, filters)
            scraper.on_event(lambda event: event_repo.save(event))
            scraper.execute()

            raw_count, unique_count, duplicate_count, unique_leads = (
                _dedupe_segment_run(
                    segment.campaign_filename,
                    run.id,
                    segment.universe_id,
                    segment.id,
                )
            )

            segmenter = SegmentAgent(run, unique_leads)
            segmenter.on_event(lambda event: event_repo.save(event))
            segmented = segmenter.execute()
            if segmented:
                lead_repo.save_batch(run.id, segmented)
                for lead in segmented:
                    setattr(lead, "run_id", run.id)
                    _add_activity(
                        lead,
                        segment.campaign_filename,
                        "lead_scraped",
                        "Lead scraped from Sales Navigator",
                        segment.label or segment.source_url,
                        {
                            "run_id": run.id,
                            "segment_id": segment.id,
                            "source_url": segment.source_url,
                        },
                    )

            counts = lead_repo.count_by_segment(run.id)
            run.total_scraped = unique_count
            run.total_enriched = 0
            run.total_warm = counts["warm"]
            run.total_cold = counts["cold"]
            run.total_no_email = counts["no_email"]

            exporter = ExportAgent(run, segmented)
            exporter.on_event(lambda event: event_repo.save(event))
            output_files = exporter.execute()
            run.status = RunStatus.COMPLETED
            run.completed_at = datetime.utcnow()
            run_repo.save(run)

            stop_reason = getattr(scraper, "_sales_nav_stop_reason", "unknown")
            if raw_count == 0 and stop_reason == "unknown":
                stop_reason = "blocked_or_captcha"
            status = "completed" if unique_count or raw_count else "exhausted"
            lead_universe_repo.update_segment_counts(
                segment.id,
                raw_count,
                unique_count,
                duplicate_count,
                status,
                stop_reason,
                run.id,
            )
            lead_universe_repo.refresh_universe_totals(segment.universe_id)
            event_repo.save(AgentEvent(
                EventType.PIPELINE_COMPLETED,
                "LeadUniverseRunner",
                run.id,
                payload={
                    "segment_id": segment.id,
                    "universe_id": universe.id,
                    "files": output_files,
                    "scraped_count": raw_count,
                    "unique_count": unique_count,
                    "duplicate_count": duplicate_count,
                    "stop_reason": stop_reason,
                },
            ))
        except Exception as exc:
            run.status = RunStatus.FAILED
            run.error = str(exc)
            run.completed_at = datetime.utcnow()
            run_repo.save(run)
            lead_universe_repo.update_segment_counts(
                segment.id,
                segment.scraped_count,
                segment.unique_count,
                segment.duplicate_count,
                "failed",
                "unknown",
                run.id,
            )
            lead_universe_repo.refresh_universe_totals(segment.universe_id)
            event_repo.save(AgentEvent(
                EventType.PIPELINE_FAILED,
                "LeadUniverseRunner",
                run.id,
                payload={"segment_id": segment.id, "universe_id": universe.id},
                error=str(exc),
            ))
            logger.exception("Lead universe segment failed")
        finally:
            _running_segment_ids.discard(segment_id)


def _start_segment_thread(segment_id: str) -> None:
    thread = threading.Thread(
        target=_run_segment_now,
        args=(segment_id,),
        daemon=True,
        name=f"lead-segment-{segment_id[:8]}",
    )
    thread.start()


def _run_all_segments_now(universe_id: str) -> None:
    while True:
        segment = lead_universe_repo.next_queued_segment(universe_id)
        if not segment:
            lead_universe_repo.refresh_universe_totals(universe_id)
            return
        _run_segment_now(segment.id)


async def _read_enriched_rows(file: UploadFile) -> list[dict]:
    contents = await file.read()
    filename = (file.filename or "").lower()
    if filename.endswith(".xlsx"):
        try:
            import openpyxl

            workbook = openpyxl.load_workbook(
                io.BytesIO(contents),
                read_only=True,
                data_only=True,
            )
            sheet = workbook.active
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                return []
            headers = [str(cell or "").strip() for cell in rows[0]]
            parsed = []
            for values in rows[1:]:
                parsed.append({
                    headers[idx]: "" if value is None else str(value).strip()
                    for idx, value in enumerate(values)
                    if idx < len(headers) and headers[idx]
                })
            return parsed
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail="openpyxl not installed. Run: pip install openpyxl",
            ) from exc
    if filename.endswith(".csv") or not filename:
        text = contents.decode("utf-8-sig", errors="ignore")
        return list(csv.DictReader(io.StringIO(text)))
    raise HTTPException(
        status_code=400,
        detail="Only .csv and .xlsx files are supported",
    )


def _update_segments_for_runs(run_ids: set[str]) -> None:
    from datetime import datetime

    for run_id in run_ids:
        run = run_repo.get(run_id)
        if not run:
            continue
        leads = lead_repo.get_by_run(run_id)
        segmenter = SegmentAgent(run, leads)
        segmenter.on_event(lambda event: event_repo.save(event))
        segmented = segmenter.execute()
        with db._conn() as conn:
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
                        datetime.utcnow().isoformat(),
                        lead.id,
                        run_id,
                    )
                    for lead in segmented
                ],
            )
        run_repo.save(run)


def _sequence_delay(settings: dict, touch_number: int, fallback: int) -> int:
    for touch in settings.get("touches", []):
        try:
            if int(touch.get("number", 0)) == touch_number:
                return int(touch.get("delay_days", fallback))
        except (TypeError, ValueError):
            continue
    return fallback


STOPPED_SEQUENCE_STATUSES = {
    "replied",
    "bounced",
    "unsubscribed",
    "do_not_contact",
    "completed",
    "skipped",
}
VALID_DRAFT_STATUSES = {
    "draft",
    "approved",
    "scheduled",
    "sent",
    "failed",
    "skipped",
}


def _campaign_value_prop(campaign_filename: str) -> str:
    campaign_path = Path("campaigns") / campaign_filename
    if campaign_path.exists():
        try:
            data = json.loads(campaign_path.read_text(encoding="utf-8"))
            value = (
                data.get("email_goal")
                or data.get("value_proposition")
                or data.get("description")
                or ""
            )
            if value:
                return str(value)
        except Exception:
            logger.warning("Could not read campaign value prop for %s", campaign_filename)
    normalized = campaign_filename.replace(".json", "").replace("_", " ").lower()
    if "fabric" in normalized and "finance" in normalized:
        return "governed Microsoft Fabric analytics"
    if "fabric" in normalized:
        return "unified data and Microsoft Fabric analytics"
    if "sap" in normalized:
        return "lower-risk SAP migration and modernization"
    if "ai" in normalized or "foundry" in normalized:
        return "secure enterprise AI adoption"
    return "practical enterprise technology modernization"


def _campaign_context(campaign_filename: str) -> dict[str, str]:
    campaign_path = Path("campaigns") / campaign_filename
    data: dict = {}
    if campaign_path.exists():
        try:
            data = json.loads(campaign_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Could not read campaign context for %s", campaign_filename)
    campaign_name = data.get("name") or campaign_filename.replace(".json", "").replace("_", " ")
    campaign_goal = data.get("email_goal") or "book a 20-minute discovery call"
    description = data.get("description") or ""
    pain_points = data.get("key_pain_points") or []
    if isinstance(pain_points, list):
        pain_points_text = "; ".join(str(point) for point in pain_points if point)
    else:
        pain_points_text = str(pain_points)
    return {
        "campaign_name": campaign_name,
        "campaign_description": description,
        "campaign_goal": campaign_goal,
        "campaign_pain_points": pain_points_text,
        "campaign_value_prop": _campaign_value_prop(campaign_filename),
    }


def _followup_goal(step: CampaignSequenceStep, touch_number: int) -> str:
    if touch_number == 2:
        return (
            "Use this email as a concise, helpful reminder that adds one clear reason "
            "the conversation could be useful."
        )
    if touch_number == 3:
        return (
            "Use this email to close the loop politely and give the lead an easy way "
            "to say whether the topic is worth revisiting."
        )
    label = step.touch_name or f"Email {touch_number}"
    return f"Continue the campaign conversation for {label} without repeating the previous email."


def _build_followup_body(
    lead: Lead,
    campaign_filename: str,
    previous_sent: OutreachDraft | None,
    step: CampaignSequenceStep,
    touch_number: int,
) -> str:
    first_name = lead.first_name or (lead.full_name.split()[0] if lead.full_name else "there")
    previous_subject = previous_sent.subject if previous_sent else "my earlier note"
    return (
        f"Hi {first_name or 'there'},\n\n"
        f"I wanted to follow up on my previous note, {previous_subject}. "
        f"{_followup_goal(step, touch_number)}\n\n"
        f"If {_campaign_value_prop(campaign_filename)} is relevant for your team, "
        "would a quick conversation make sense?\n\n"
        f"Best,\n{os.getenv('SENDER_NAME', 'Royal Cyber Team')}"
    )


def render_template(
    template: str,
    lead: Lead,
    campaign_filename: str,
    context: dict | None = None,
) -> str:
    context = context or {}
    campaign_context = _campaign_context(campaign_filename)
    first_name = lead.first_name or (
        lead.full_name.split()[0] if lead.full_name else ""
    )
    full_name = lead.full_name or first_name or "there"
    values = {
        "first_name": first_name or full_name or "there",
        "full_name": full_name,
        "company": lead.company or "your team",
        "title": lead.title or "your role",
        "location": lead.location or "your market",
        "lead_context": (
            lead.title
            or lead.company
            or lead.location
            or "your current priorities"
        ),
        "campaign_name": campaign_context["campaign_name"],
        "campaign_description": campaign_context["campaign_description"],
        "campaign_goal": campaign_context["campaign_goal"],
        "campaign_pain_points": campaign_context["campaign_pain_points"],
        "campaign_value_prop": campaign_context["campaign_value_prop"],
        "sender_name": os.getenv("SENDER_NAME", "Royal Cyber Team"),
        "touch1_subject": context.get("touch1_subject") or "my earlier note",
        "previous_subject": context.get("previous_subject") or "my earlier note",
        "previous_body": context.get("previous_body") or "",
        "previous_sent_at": context.get("previous_sent_at") or "",
        "current_followup_goal": context.get("current_followup_goal") or "",
    }
    output = template or ""
    for key, value in values.items():
        output = output.replace("{{" + key + "}}", str(value))

    import re

    unresolved = re.findall(r"{{\s*[^}]+\s*}}", output)
    if unresolved:
        logger.warning(
            "Unresolved template variables for lead %s in %s: %s",
            lead.id,
            campaign_filename,
            ", ".join(sorted(set(unresolved))),
        )
        output = re.sub(r"{{\s*[^}]+\s*}}", "there", output)

    output = re.sub(
        r"\b(undefined|None|null)\b",
        "there",
        output,
        flags=re.IGNORECASE,
    )
    return output


def _render_template(
    template: str,
    lead: Lead,
    campaign_filename: str,
    touch1_subject: str = "",
) -> str:
    return render_template(
        template,
        lead,
        campaign_filename,
        {"touch1_subject": touch1_subject},
    )


def _draft_payload(row_or_draft) -> dict:
    if isinstance(row_or_draft, OutreachDraft):
        draft = row_or_draft
        lead = lead_repo.get_by_id(draft.lead_id)
        previous = _previous_sent_draft(
            draft.lead_id,
            draft.campaign_filename,
            draft.touch_number,
        )
        return {
            "draft_id": draft.id,
            "id": draft.lead_id,
            "lead_id": draft.lead_id,
            "run_id": getattr(lead, "run_id", "") if lead else "",
            "campaign_filename": draft.campaign_filename,
            "full_name": lead.full_name if lead else "",
            "company": lead.company if lead else "",
            "title": lead.title if lead else "",
            "email": lead.email if lead else "",
            "touch_number": draft.touch_number,
            "subject": draft.subject,
            "email_subject": draft.subject,
            "body": draft.body,
            "email_body": draft.body,
            "linkedin_message": draft.linkedin_message,
            "status": draft.status,
            "email_sequence_status": draft.status,
            "scheduled_for": _dt(draft.scheduled_for),
            "sent_at": _dt(draft.sent_at),
            "error_message": draft.error_message,
            "previous_touch_number": previous.touch_number if previous else None,
            "previous_subject": previous.subject if previous else "",
            "previous_body": previous.body if previous else "",
            "previous_sent_at": _dt(previous.sent_at) if previous else "",
            "created_at": _dt(draft.created_at),
            "updated_at": _dt(draft.updated_at),
        }
    row = dict(row_or_draft)
    previous = _previous_sent_draft(
        row.get("lead_id", ""),
        row.get("campaign_filename", ""),
        int(row.get("touch_number") or 1),
    )
    return {
        "draft_id": row.get("draft_id", ""),
        "id": row.get("lead_id", ""),
        "lead_id": row.get("lead_id", ""),
        "run_id": row.get("run_id", ""),
        "campaign_filename": row.get("campaign_filename", ""),
        "full_name": row.get("full_name", "") or "",
        "company": row.get("company", "") or "",
        "title": row.get("title", "") or "",
        "email": row.get("email", "") or "",
        "location": row.get("location", "") or "",
        "touch_number": row.get("touch_number") or 1,
        "subject": row.get("subject", "") or "",
        "email_subject": row.get("subject", "") or "",
        "body": row.get("body", "") or "",
        "email_body": row.get("body", "") or "",
        "linkedin_message": row.get("linkedin_message", "") or "",
        "status": row.get("status", "") or "draft",
        "email_sequence_status": row.get("status", "") or "draft",
        "scheduled_for": row.get("scheduled_for") or "",
        "sent_at": row.get("sent_at") or "",
        "error_message": row.get("error_message") or "",
        "previous_touch_number": previous.touch_number if previous else None,
        "previous_subject": previous.subject if previous else "",
        "previous_body": previous.body if previous else "",
        "previous_sent_at": _dt(previous.sent_at) if previous else "",
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
    }


def _activity_payload(row: dict) -> dict:
    data = dict(row)
    try:
        data["metadata"] = json.loads(data.get("metadata_json") or "{}")
    except Exception:
        data["metadata"] = {}
    return data


def _add_activity(
    lead: Lead | None,
    campaign_filename: str,
    activity_type: str,
    title: str,
    description: str = "",
    metadata: dict | None = None,
    run_id: str = "",
) -> None:
    if not lead:
        return
    outreach_repo.add_activity(LeadActivity(
        lead_id=lead.id,
        campaign_filename=campaign_filename,
        run_id=run_id or getattr(lead, "run_id", "") or "",
        activity_type=activity_type,
        title=title,
        description=description,
        metadata_json=json.dumps(metadata or {}, default=str),
    ))


def _latest_draft_for_touch(
    lead_id: str,
    campaign_filename: str,
    touch_number: int,
) -> OutreachDraft | None:
    row = db._conn().execute(
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
    if not row:
        return None
    return OutreachDraft(
        id=row["id"],
        lead_id=row["lead_id"],
        campaign_filename=row["campaign_filename"],
        touch_number=row["touch_number"],
        subject=row["subject"] or "",
        body=row["body"] or "",
        linkedin_message=row["linkedin_message"] or "",
        status=row["status"] or "draft",
        scheduled_for=_text_to_dt(row["scheduled_for"]) if "_text_to_dt" in globals() else None,
    )


def _touch1_subject(lead_id: str, campaign_filename: str) -> str:
    row = db._conn().execute(
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


def _previous_sent_draft(
    lead_id: str,
    campaign_filename: str,
    touch_number: int,
) -> OutreachDraft | None:
    row = db._conn().execute(
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
    if not row:
        return None
    return outreach_repo._row_to_draft(row)


def _campaign_lead_ids(campaign_filename: str) -> set[str]:
    return {lead.id for lead in _campaign_leads(campaign_filename)}


def _is_state_stopped(state: LeadSequenceState | None) -> bool:
    return bool(state and state.status in STOPPED_SEQUENCE_STATUSES)


def _set_lead_sequence_columns(
    lead_id: str,
    status: str,
    error: str = "",
    touch_number: int | None = None,
    sent_at: datetime | None = None,
) -> None:
    existing = _lead_table_columns()
    updates: dict[str, str] = {}
    if "email_sequence_status" in existing:
        updates["email_sequence_status"] = status
    if "email_sequence_error" in existing:
        updates["email_sequence_error"] = error
    if sent_at and touch_number:
        legacy_day = {1: "day1_sent_at", 2: "day3_sent_at", 3: "day7_sent_at"}.get(
            int(touch_number),
        )
        if legacy_day and legacy_day in existing:
            updates[legacy_day] = sent_at.isoformat()
    if "updated_at" in existing:
        updates["updated_at"] = datetime.utcnow().isoformat()
    if not updates:
        return
    set_clause = ", ".join(f"{key} = ?" for key in updates)
    with db._conn() as conn:
        conn.execute(
            f"UPDATE leads SET {set_clause} WHERE id = ?",
            [*updates.values(), lead_id],
        )


def _generate_drafts_for_leads(
    campaign_filename: str,
    lead_ids: list[str],
    touch_number: int,
    overwrite: bool = False,
) -> dict:
    if touch_number <= 0:
        raise HTTPException(
            status_code=400,
            detail="touch_number must be positive",
        )
    _load_sequence_settings(campaign_filename)
    step = campaign_sequence_repo.get_step(
        campaign_filename,
        touch_number,
        active_only=True,
    )
    if not step:
        raise HTTPException(status_code=404, detail="Sequence step not found")

    campaign_leads = _campaign_lead_ids(campaign_filename)
    generated = 0
    skipped = 0
    skips = []

    for lead_id in lead_ids:
        lead = lead_repo.get_by_id(lead_id)
        if not lead or lead.id not in campaign_leads:
            skipped += 1
            skips.append({"lead_id": lead_id, "reason": "not_in_campaign"})
            continue
        if not lead.email:
            skipped += 1
            skips.append({"lead_id": lead_id, "reason": "no_email"})
            _add_activity(
                lead,
                campaign_filename,
                "skipped",
                "Draft skipped",
                "Lead has no email address",
            )
            continue
        state = outreach_repo.get_or_create_state(lead.id, campaign_filename)
        if _is_state_stopped(state):
            skipped += 1
            skips.append({"lead_id": lead.id, "reason": state.status})
            continue

        previous_step = _previous_active_step(campaign_filename, touch_number)
        if previous_step and not _sent_draft_exists(
            lead.id,
            campaign_filename,
            previous_step.touch_number,
        ):
            skipped += 1
            skips.append({
                "lead_id": lead.id,
                "reason": "previous_touch_not_sent",
                "required_touch": previous_step.touch_number,
            })
            continue
        if previous_step:
            if not state.next_touch_due_at:
                skipped += 1
                skips.append({"lead_id": lead.id, "reason": "followup_not_scheduled"})
                continue
            if state.next_touch_due_at > datetime.utcnow():
                skipped += 1
                skips.append({
                    "lead_id": lead.id,
                    "reason": "followup_not_due",
                    "next_touch_due_at": _dt(state.next_touch_due_at),
                })
                continue

        existing = outreach_repo.find_active_draft(
            lead.id,
            campaign_filename,
            touch_number,
        )
        if existing and not overwrite:
            skipped += 1
            skips.append({"lead_id": lead.id, "reason": "duplicate_draft"})
            continue

        touch1_subject = _touch1_subject(lead.id, campaign_filename)
        previous_sent = _previous_sent_draft(
            lead.id,
            campaign_filename,
            touch_number,
        )
        template_context = {
            "touch1_subject": touch1_subject,
            "previous_subject": previous_sent.subject if previous_sent else "",
            "previous_body": previous_sent.body if previous_sent else "",
            "previous_sent_at": _dt(previous_sent.sent_at) if previous_sent else "",
            "current_followup_goal": _followup_goal(step, touch_number),
            **_campaign_context(campaign_filename),
        }
        subject = render_template(
            step.subject_template,
            lead,
            campaign_filename,
            template_context,
        )
        body = render_template(
            step.email_body_template,
            lead,
            campaign_filename,
            template_context,
        )
        if touch_number > 1 and previous_sent and not step.email_body_template.strip():
            body = _build_followup_body(
                lead,
                campaign_filename,
                previous_sent,
                step,
                touch_number,
            )
        if (
            touch_number > 1
            and previous_sent
            and body.strip()
            and body.strip() == previous_sent.body.strip()
        ):
            body = _build_followup_body(
                lead,
                campaign_filename,
                previous_sent,
                step,
                touch_number,
            )
        if existing and overwrite:
            draft = outreach_repo.update_draft(
                existing.id,
                {
                    "subject": subject,
                    "body": body,
                    "linkedin_message": "",
                    "status": "draft",
                    "error_message": "",
                },
            ) or existing
        else:
            draft = OutreachDraft(
                lead_id=lead.id,
                campaign_filename=campaign_filename,
                touch_number=touch_number,
                subject=subject,
                body=body,
                linkedin_message="",
                status="draft",
            )
            outreach_repo.save_draft(draft)
        state.current_touch = max(state.current_touch, touch_number)
        state.status = "draft_generated"
        outreach_repo.upsert_state(state)
        _set_lead_sequence_columns(lead.id, state.status)
        _add_activity(
            lead,
            campaign_filename,
            "followup_draft_generated" if touch_number > 1 else "draft_generated",
            f"Touch {touch_number} draft generated",
            draft.subject,
            {
                "draft_id": draft.id,
                "touch_number": touch_number,
                "previous_touch_number": previous_sent.touch_number if previous_sent else None,
                "previous_subject": previous_sent.subject if previous_sent else "",
                "previous_sent_at": _dt(previous_sent.sent_at) if previous_sent else "",
            },
        )
        generated += 1

    return {"generated": generated, "skipped": skipped, "skips": skips}


def _active_steps(campaign_filename: str) -> list[CampaignSequenceStep]:
    _load_sequence_settings(campaign_filename)
    return campaign_sequence_repo.list_steps(campaign_filename, active_only=True)


def _next_active_step(
    campaign_filename: str,
    current_touch: int,
) -> CampaignSequenceStep | None:
    for step in _active_steps(campaign_filename):
        if step.touch_number > current_touch:
            return step
    return None


def _previous_active_step(
    campaign_filename: str,
    touch_number: int,
) -> CampaignSequenceStep | None:
    previous = None
    for step in _active_steps(campaign_filename):
        if step.touch_number >= touch_number:
            break
        previous = step
    return previous


def _sent_draft_exists(
    lead_id: str,
    campaign_filename: str,
    touch_number: int,
) -> bool:
    row = db._conn().execute(
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


def _due_items(
    campaign_filename: str,
    lead_ids: list[str] | None = None,
    touch_number: int | None = None,
) -> list[dict]:
    active = _active_steps(campaign_filename)
    if not active:
        return []
    allowed_ids = set(lead_ids or [])
    now = datetime.utcnow()
    due = []

    for lead in _campaign_leads(campaign_filename):
        if allowed_ids and lead.id not in allowed_ids:
            continue
        if not lead.email:
            continue
        state = outreach_repo.get_or_create_state(lead.id, campaign_filename)
        if _is_state_stopped(state):
            continue

        due_touch = None
        if state.current_touch > 0 and state.next_touch_due_at and state.next_touch_due_at <= now:
            if not _sent_draft_exists(
                lead.id,
                campaign_filename,
                state.current_touch,
            ):
                continue
            next_step = _next_active_step(campaign_filename, state.current_touch)
            if next_step and not _sent_draft_exists(
                lead.id,
                campaign_filename,
                next_step.touch_number,
            ):
                if not outreach_repo.find_active_draft(
                    lead.id,
                    campaign_filename,
                    next_step.touch_number,
                ):
                    due_touch = next_step.touch_number

        if touch_number and due_touch != touch_number:
            continue
        if due_touch:
            if state.status == "waiting_followup":
                state.status = "followup_due"
                outreach_repo.upsert_state(state)
                _add_activity(
                    lead,
                    campaign_filename,
                    "followup_due",
                    f"Touch {due_touch} is due",
                    "",
                    {"touch_number": due_touch},
                )
            due.append({
                "lead_id": lead.id,
                "full_name": lead.full_name,
                "company": lead.company,
                "title": lead.title,
                "email": lead.email,
                "touch_number": due_touch,
                "next_touch_due_at": _dt(state.next_touch_due_at),
                "status": state.status,
                "due_label": "Due now",
            })
    return due


def _parse_clock(value: str, fallback: time) -> time:
    try:
        parts = (value or "").split(":")
        return time(int(parts[0]), int(parts[1] if len(parts) > 1 else 0))
    except Exception:
        return fallback


def _inside_send_window(rules: CampaignSequenceRules) -> bool:
    now_time = datetime.now().time()
    start = _parse_clock(rules.send_window_start, time(9, 0))
    end = _parse_clock(rules.send_window_end, time(17, 0))
    if start <= end:
        return start <= now_time <= end
    return now_time >= start or now_time <= end


@app.post("/api/lead-universes")
def create_lead_universe(request: CreateLeadUniverseRequest) -> dict:
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Universe name is required")
    if not request.campaign_filename.strip():
        raise HTTPException(status_code=400, detail="campaign_filename is required")
    if request.source_type != "sales_navigator":
        raise HTTPException(
            status_code=400,
            detail="Only sales_navigator source_type is supported",
        )
    universe = LeadUniverse(
        name=request.name.strip(),
        campaign_filename=request.campaign_filename.strip(),
        source_type="sales_navigator",
        description=request.description.strip(),
        target_leads=max(0, int(request.target_leads or 0)),
        status="queued",
    )
    lead_universe_repo.save_universe(universe)
    return _universe_payload(universe)


@app.get("/api/lead-universes/{universe_id}")
def get_lead_universe(universe_id: str) -> dict:
    universe = lead_universe_repo.get_universe(universe_id)
    if not universe:
        raise HTTPException(status_code=404, detail="Lead universe not found")
    payload = _universe_payload(universe)
    payload["segments"] = [
        _segment_payload(segment)
        for segment in lead_universe_repo.list_segments(universe_id)
    ]
    return payload


@app.get("/api/campaigns/{campaign_filename}/lead-universes")
def get_campaign_lead_universes(campaign_filename: str) -> list[dict]:
    return [
        {
            **_universe_payload(universe),
            "segments": [
                _segment_payload(segment)
                for segment in lead_universe_repo.list_segments(universe.id)
            ],
        }
        for universe in lead_universe_repo.list_universes(campaign_filename)
    ]


@app.post("/api/lead-universes/{universe_id}/segments")
def create_lead_source_segment(
    universe_id: str,
    request: CreateLeadSourceSegmentRequest,
) -> dict:
    universe = lead_universe_repo.get_universe(universe_id)
    if not universe:
        raise HTTPException(status_code=404, detail="Lead universe not found")
    source_url = request.source_url.strip()
    if "linkedin.com/sales/search/people" not in source_url.lower():
        raise HTTPException(
            status_code=400,
            detail="Only LinkedIn Sales Navigator people search URLs are supported",
        )
    label = request.label.strip() or f"Segment {len(lead_universe_repo.list_segments(universe_id)) + 1}"
    segment = LeadSourceSegment(
        universe_id=universe_id,
        campaign_filename=universe.campaign_filename,
        source_url=source_url,
        label=label,
        filters_json=json.dumps(request.filters or {}, default=str),
        expected_count=max(1, int(request.expected_count or 50)),
        status="queued",
    )
    lead_universe_repo.save_segment(segment)
    lead_universe_repo.refresh_universe_totals(universe_id)
    return _segment_payload(segment)


@app.post("/api/segments/{segment_id}/run")
def run_lead_source_segment(segment_id: str) -> dict:
    segment = lead_universe_repo.get_segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    if segment.status == "running":
        raise HTTPException(status_code=409, detail="Segment is already running")
    if segment.id in _running_segment_ids:
        raise HTTPException(status_code=409, detail="Segment is already queued to run")
    _start_segment_thread(segment.id)
    return {"started": True, "segment": _segment_payload(segment)}


@app.post("/api/lead-universes/{universe_id}/run-next")
def run_next_lead_source_segment(universe_id: str) -> dict:
    universe = lead_universe_repo.get_universe(universe_id)
    if not universe:
        raise HTTPException(status_code=404, detail="Lead universe not found")
    segment = lead_universe_repo.next_queued_segment(universe_id)
    if not segment:
        return {"started": False, "message": "No queued segments"}
    _start_segment_thread(segment.id)
    return {"started": True, "segment": _segment_payload(segment)}


@app.post("/api/lead-universes/{universe_id}/run-all")
def run_all_lead_source_segments(universe_id: str) -> dict:
    universe = lead_universe_repo.get_universe(universe_id)
    if not universe:
        raise HTTPException(status_code=404, detail="Lead universe not found")
    queued = [
        segment for segment in lead_universe_repo.list_segments(universe_id)
        if segment.status == "queued"
    ]
    if not queued:
        return {"started": False, "queued": 0, "message": "No queued segments"}
    thread = threading.Thread(
        target=_run_all_segments_now,
        args=(universe_id,),
        daemon=True,
        name=f"lead-universe-{universe_id[:8]}",
    )
    thread.start()
    return {"started": True, "queued": len(queued)}


@app.post("/api/lead-universes/{universe_id}/pause-all")
def pause_lead_source_segments(universe_id: str) -> dict:
    universe = lead_universe_repo.get_universe(universe_id)
    if not universe:
        raise HTTPException(status_code=404, detail="Lead universe not found")
    updated = lead_universe_repo.pause_queued_segments(universe_id)
    lead_universe_repo.refresh_universe_totals(universe_id)
    return {"paused": updated}


@app.get("/api/campaigns/{campaign_filename}/runs")
def get_campaign_runs(campaign_filename: str) -> list[dict]:
    runs = _campaign_runs(campaign_filename)
    return [
        {
            "id": run.id,
            "status": run.status.value,
            "started_at": _dt(run.started_at) or "",
            "completed_at": _dt(getattr(run, "completed_at", None)),
            "total_scraped": run.total_scraped,
            "total_warm": run.total_warm,
            "total_cold": run.total_cold,
            "total_no_email": run.total_no_email,
            "start_url": (run.filters or {}).get("start_url", ""),
            "campaign": (
                (run.filters or {}).get("campaign")
                or (run.filters or {}).get("campaign_key")
                or ""
            ),
        }
        for run in runs
    ]


@app.get("/api/campaigns/{campaign_filename}/overview")
def get_campaign_overview(campaign_filename: str) -> dict:
    runs = get_campaign_runs(campaign_filename)
    rows = _campaign_lead_rows(
        campaign_filename,
        limit=None,
    )
    total_leads = len(rows)
    with_email = sum(1 for row in rows if row.get("email"))
    no_email = total_leads - with_email

    coverage = lead_universe_repo.campaign_coverage(campaign_filename)
    coverage.update({
        "needs_enrichment": no_email,
        "with_email": with_email,
    })

    conn = db._conn()
    draft_rows = conn.execute(
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
    draft_total_row = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM outreach_drafts
        WHERE campaign_filename = ?
        """,
        (campaign_filename,),
    ).fetchone()
    drafts_generated = draft_total_row["total"] or 0
    unique_row = conn.execute(
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
    drafted_unique = unique_row["drafted"] or 0
    approved_unique = unique_row["approved"] or 0
    sent_unique = unique_row["sent"] or 0
    state_rows = conn.execute(
        """
        SELECT status, COUNT(*) AS total
        FROM lead_sequence_state
        WHERE campaign_filename = ?
        GROUP BY status
        """,
        (campaign_filename,),
    ).fetchall()
    state_counts = {
        row["status"] or "not_started": row["total"] or 0
        for row in state_rows
    }
    active_sequence_steps = len(_active_steps(campaign_filename))
    approved_drafts = draft_counts.get("approved", 0)
    scheduled = (
        draft_counts.get("scheduled", 0)
        + draft_counts.get("approved", 0)
    )
    emails_sent = draft_counts.get("sent", 0)
    followups_due = len(_due_items(campaign_filename))
    replies = state_counts.get("replied", 0)
    bounces = state_counts.get("bounced", 0)
    unsubscribed = state_counts.get("unsubscribed", 0)
    completed = state_counts.get("completed", 0)

    return {
        "campaign_filename": campaign_filename,
        "total_leads": total_leads,
        "needs_enrichment": no_email,
        "with_email": with_email,
        "no_email": no_email,
        "drafts_generated": drafts_generated,
        "approved_drafts": approved_drafts,
        "scheduled": scheduled,
        "emails_sent": emails_sent,
        "followups_due": followups_due,
        "replies": replies,
        "bounces": bounces,
        "unsubscribed": unsubscribed,
        "completed": completed,
        "active_sequence_steps": active_sequence_steps,
        "pipeline": {
            "scraped": total_leads,
            "enriched": with_email,
            "drafted": drafted_unique,
            "approved": approved_unique,
            "sent": sent_unique,
            "replied": replies,
            "completed": completed,
        },
        "total_runs": len(runs),
        "runs": runs,
        "lead_collection": coverage,
    }


@app.get("/api/campaigns/{campaign_filename}/leads")
def get_campaign_leads(
    campaign_filename: str,
    segment: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    rows = _campaign_lead_rows(
        campaign_filename,
        segment=segment,
        run_id=run_id,
        limit=limit,
        offset=offset,
    )
    return [_campaign_lead_payload(row) for row in rows]


@app.get("/api/campaigns/{campaign_filename}/drafts")
def get_campaign_drafts(
    campaign_filename: str,
    status: Optional[str] = None,
    touch_number: Optional[int] = None,
    lead_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    drafts = outreach_repo.list_drafts(
        campaign_filename,
        status=status or "",
        touch_number=touch_number,
        lead_id=lead_id or "",
        limit=limit,
        offset=offset,
    )
    if drafts:
        return [_draft_payload(row) for row in drafts]

    if status or touch_number or lead_id:
        return []

    rows = _campaign_lead_rows(
        campaign_filename,
        limit=None,
        drafts_only=True,
    )
    return [_campaign_draft_payload(row) for row in rows]


@app.post("/api/campaigns/{campaign_filename}/drafts/generate")
def generate_campaign_drafts(
    campaign_filename: str,
    request: GenerateDraftsRequest,
) -> dict:
    if not request.lead_ids:
        raise HTTPException(status_code=400, detail="lead_ids are required")
    return _generate_drafts_for_leads(
        campaign_filename=campaign_filename,
        lead_ids=request.lead_ids,
        touch_number=request.touch_number,
        overwrite=request.overwrite,
    )


@app.put("/api/drafts/{draft_id}")
def update_outreach_draft(
    draft_id: str,
    request: OutreachDraftUpdateRequest,
) -> dict:
    draft = outreach_repo.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    updates = {}
    if request.subject is not None:
        updates["subject"] = request.subject
    if request.body is not None:
        updates["body"] = request.body
    if request.linkedin_message is not None:
        updates["linkedin_message"] = request.linkedin_message
    if request.status is not None:
        if request.status not in VALID_DRAFT_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid draft status")
        updates["status"] = request.status
    updated = outreach_repo.update_draft(draft_id, updates)
    lead = lead_repo.get_by_id(draft.lead_id)
    _add_activity(
        lead,
        draft.campaign_filename,
        "draft_edited",
        f"Touch {draft.touch_number} draft edited",
        "",
        {"draft_id": draft.id, "fields": list(updates.keys())},
    )
    return _draft_payload(updated)


@app.post("/api/drafts/{draft_id}/approve")
def approve_outreach_draft(draft_id: str) -> dict:
    draft = outreach_repo.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status not in {"draft", "failed", "scheduled"}:
        raise HTTPException(
            status_code=400,
            detail=f"Draft cannot be approved from status {draft.status}",
        )
    updated = outreach_repo.update_draft(draft.id, {"status": "approved"})
    state = outreach_repo.get_or_create_state(
        draft.lead_id,
        draft.campaign_filename,
    )
    if not _is_state_stopped(state):
        state.status = "approved"
        state.current_touch = max(state.current_touch, draft.touch_number)
        outreach_repo.upsert_state(state)
    lead = lead_repo.get_by_id(draft.lead_id)
    _add_activity(
        lead,
        draft.campaign_filename,
        "draft_approved",
        f"Touch {draft.touch_number} draft approved",
        "",
        {"draft_id": draft.id},
    )
    return _draft_payload(updated)


@app.post("/api/drafts/approve-selected")
def approve_selected_outreach_drafts(
    request: ApproveSelectedDraftsRequest,
) -> dict:
    approved = 0
    skipped = 0
    details = []
    for draft_id in request.draft_ids:
        try:
            payload = approve_outreach_draft(draft_id)
            approved += 1
            details.append({
                "draft_id": draft_id,
                "status": "approved",
                "lead_id": payload.get("lead_id", ""),
            })
        except HTTPException as exc:
            skipped += 1
            details.append({
                "draft_id": draft_id,
                "status": "skipped",
                "reason": exc.detail,
            })
    return {"approved": approved, "skipped": skipped, "details": details}


@app.post("/api/drafts/{draft_id}/skip")
def skip_outreach_draft(
    draft_id: str,
    request: SkipDraftRequest | None = None,
) -> dict:
    draft = outreach_repo.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    reason = (request.reason if request else "") or "manual_skip"
    updated = outreach_repo.update_draft(
        draft.id,
        {"status": "skipped", "error_message": reason},
    )
    lead = lead_repo.get_by_id(draft.lead_id)
    _add_activity(
        lead,
        draft.campaign_filename,
        "skipped",
        f"Touch {draft.touch_number} draft skipped",
        reason,
        {"draft_id": draft.id},
    )
    return _draft_payload(updated)


def _send_selected_drafts(draft_ids: list[str]) -> dict:
    sent = 0
    failed = 0
    skipped = 0
    details = []
    messages: list[str] = []
    drafts = outreach_repo.get_drafts_by_ids(draft_ids)
    found_ids = {draft.id for draft in drafts}
    for missing_id in set(draft_ids) - found_ids:
        skipped += 1
        details.append({
            "draft_id": missing_id,
            "status": "skipped",
            "reason": "not_found",
        })

    sent_by_campaign: dict[str, int] = {}

    for draft in drafts:
        lead = lead_repo.get_by_id(draft.lead_id)
        if not lead:
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "status": "skipped",
                "reason": "lead_not_found",
            })
            continue
        if draft.status != "approved":
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "not_approved",
            })
            continue
        if not lead.email:
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "no_email",
            })
            continue

        state = outreach_repo.get_or_create_state(
            lead.id,
            draft.campaign_filename,
        )
        if _is_state_stopped(state):
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": state.status,
            })
            continue

        if _sent_draft_exists(lead.id, draft.campaign_filename, draft.touch_number):
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "already_sent",
            })
            continue

        previous_step = _previous_active_step(
            draft.campaign_filename,
            draft.touch_number,
        )
        if previous_step and not _sent_draft_exists(
            lead.id,
            draft.campaign_filename,
            previous_step.touch_number,
        ):
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "previous_touch_not_sent",
                "required_touch": previous_step.touch_number,
            })
            continue
        if previous_step and state.next_touch_due_at and state.next_touch_due_at > datetime.utcnow():
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "followup_not_due",
                "next_touch_due_at": _dt(state.next_touch_due_at),
            })
            continue

        _, rules = campaign_sequence_repo.ensure_defaults(
            draft.campaign_filename,
            default_steps=(
                _legacy_sequence_settings_from_file(
                    draft.campaign_filename
                ).get("touches") or []
            ),
        )
        already_sent = outreach_repo.count_sent_today(draft.campaign_filename)
        already_sent += sent_by_campaign.get(draft.campaign_filename, 0)
        if already_sent >= rules.daily_send_limit:
            skipped += 1
            message = (
                f"Daily send limit reached for this campaign "
                f"({rules.daily_send_limit})."
            )
            messages.append(message)
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "daily_send_limit_reached",
                "message": message,
            })
            continue
        if rules.skip_weekends and datetime.now().weekday() >= 5:
            skipped += 1
            message = "Weekend sending is blocked by campaign rules."
            messages.append(message)
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "weekend_send_blocked",
                "message": message,
            })
            continue
        if not _inside_send_window(rules):
            skipped += 1
            message = (
                "Outside campaign send window. Schedule or send during "
                f"{rules.send_window_start}-{rules.send_window_end}."
            )
            messages.append(message)
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "outside_send_window",
                "message": message,
            })
            continue

        if sent_by_campaign.get(draft.campaign_filename, 0) > 0 and rules.delay_between_sends_seconds > 0:
            import time as time_module

            time_module.sleep(max(0, rules.delay_between_sends_seconds))

        run = run_repo.get(getattr(lead, "run_id", "") or "")
        if not run:
            run = PipelineRun(
                filters={
                    "campaign": draft.campaign_filename,
                    "campaign_key": draft.campaign_filename,
                }
            )
        result = EmailAgent(run, []).send_direct(
            lead.email,
            draft.subject,
            draft.body,
        )
        if result.get("success"):
            now = datetime.utcnow()
            outreach_repo.update_draft(
                draft.id,
                {"status": "sent", "sent_at": now, "error_message": ""},
            )
            next_step = _next_active_step(
                draft.campaign_filename,
                draft.touch_number,
            )
            state.current_touch = draft.touch_number
            state.last_touch_sent_at = now
            state.next_touch_due_at = None
            state.stop_reason = ""
            if next_step:
                state.status = "waiting_followup"
                state.next_touch_due_at = calculate_next_touch_due_at(
                    now,
                    next_step,
                    rules,
                )
            else:
                state.status = "completed"
                state.completed_at = now
            outreach_repo.upsert_state(state)
            _set_lead_sequence_columns(
                lead.id,
                state.status,
                "",
                draft.touch_number,
                now,
            )
            _add_activity(
                lead,
                draft.campaign_filename,
                "email_sent",
                f"Touch {draft.touch_number} email sent",
                draft.subject,
                {"draft_id": draft.id, "touch_number": draft.touch_number},
            )
            if next_step:
                _add_activity(
                    lead,
                    draft.campaign_filename,
                    "followup_due_calculated",
                    f"Touch {next_step.touch_number} due time calculated",
                    _dt(state.next_touch_due_at) or "",
                    {
                        "previous_touch": draft.touch_number,
                        "next_touch": next_step.touch_number,
                        "previous_sent_at": _dt(now),
                        "due_at": _dt(state.next_touch_due_at),
                    },
                )
                _add_activity(
                    lead,
                    draft.campaign_filename,
                    "followup_scheduled",
                    f"Touch {next_step.touch_number} scheduled",
                    _dt(state.next_touch_due_at) or "",
                    {
                        "touch_number": next_step.touch_number,
                        "due_at": _dt(state.next_touch_due_at),
                    },
                )
            else:
                _add_activity(
                    lead,
                    draft.campaign_filename,
                    "sequence_completed",
                    "Sequence completed",
                    f"Final touch {draft.touch_number} sent",
                    {"draft_id": draft.id, "touch_number": draft.touch_number},
                )
            sent_by_campaign[draft.campaign_filename] = (
                sent_by_campaign.get(draft.campaign_filename, 0) + 1
            )
            sent += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "email": lead.email,
                "status": "sent",
                "touch_number": draft.touch_number,
                "next_touch_due_at": _dt(state.next_touch_due_at),
            })
        else:
            error = result.get("error") or "Graph API send failed"
            invalid_recipient = any(
                marker in error.lower()
                for marker in (
                    "invalid recipient",
                    "recipient",
                    "does not exist",
                    "undeliverable",
                    "bounce",
                    "invalid email",
                )
            )
            outreach_repo.update_draft(
                draft.id,
                {"status": "failed", "error_message": error},
            )
            if invalid_recipient:
                state.status = "bounced"
                state.stop_reason = error
                state.next_touch_due_at = None
                state.completed_at = datetime.utcnow()
                outreach_repo.upsert_state(state)
                outreach_repo.mark_future_pending_skipped(
                    lead.id,
                    draft.campaign_filename,
                    "bounced",
                )
                _set_lead_sequence_columns(lead.id, "bounced", error)
                _add_activity(
                    lead,
                    draft.campaign_filename,
                    "bounced",
                    "Lead marked bounced from send error",
                    error,
                    {"draft_id": draft.id},
                )
            _add_activity(
                lead,
                draft.campaign_filename,
                "failed",
                f"Touch {draft.touch_number} email failed",
                error,
                {"draft_id": draft.id},
            )
            failed += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "email": lead.email,
                "status": "failed",
                "reason": error,
            })
    message = ""
    if messages:
        message = messages[0]
    return {
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "message": message,
        "details": details,
    }


@app.post("/api/drafts/send-selected")
def send_selected_outreach_drafts(
    request: SendSelectedDraftsRequest,
) -> dict:
    if not request.draft_ids:
        raise HTTPException(status_code=400, detail="draft_ids are required")
    return _send_selected_drafts(request.draft_ids)


@app.post("/api/campaigns/{campaign_filename}/queue/send-selected")
def send_selected_campaign_queue_drafts(
    campaign_filename: str,
    request: SendSelectedDraftsRequest,
) -> dict:
    if not request.draft_ids:
        raise HTTPException(status_code=400, detail="draft_ids are required")
    drafts = outreach_repo.get_drafts_by_ids(request.draft_ids)
    invalid = [
        draft.id for draft in drafts
        if draft.campaign_filename != campaign_filename
    ]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Drafts do not belong to campaign: {', '.join(invalid)}",
        )
    return _send_selected_drafts(request.draft_ids)


@app.post("/api/drafts/{draft_id}/send-test")
def send_outreach_draft_test(
    draft_id: str,
    request: DraftSendTestRequest,
) -> dict:
    draft = outreach_repo.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    test_email = (request.test_email or "").strip()
    if not test_email or "@" not in test_email:
        raise HTTPException(status_code=400, detail="Valid test_email required")
    lead = lead_repo.get_by_id(draft.lead_id)
    run = run_repo.get(getattr(lead, "run_id", "") or "") if lead else None
    if not run:
        run = PipelineRun(filters={"campaign": draft.campaign_filename})
    test_subject = f"[TEST COPY] {draft.subject}"
    test_body = (
        "TEST COPY\n"
        f"Original lead: {lead.full_name if lead else draft.lead_id}\n"
        f"Original recipient: {lead.email if lead else ''}\n\n"
        "----\n\n"
        f"{draft.body}"
    )
    result = EmailAgent(run, []).send_direct(test_email, test_subject, test_body)
    _add_activity(
        lead,
        draft.campaign_filename,
        "test_sent" if result.get("success") else "failed",
        "Test copy sent" if result.get("success") else "Test copy failed",
        result.get("error", ""),
        {"draft_id": draft.id, "test_email": test_email},
    )
    return {
        "success": bool(result.get("success")),
        "error": result.get("error", ""),
        "to": test_email,
    }


@app.get("/api/campaigns/{campaign_filename}/queue")
def get_campaign_queue(campaign_filename: str) -> dict:
    due_today = _due_items(campaign_filename)
    drafts = [
        _draft_payload(row)
        for row in outreach_repo.list_drafts(
            campaign_filename,
            limit=1000,
            offset=0,
        )
    ]
    grouped = {
        "due_today": due_today,
        "scheduled": [],
        "waiting": [],
        "sent": [],
        "failed": [],
        "skipped": [],
    }
    for draft in drafts:
        status = draft.get("status", "")
        if status in {"draft", "approved", "scheduled"} and int(draft.get("touch_number") or 1) > 1:
            draft["due_label"] = "Due now"
            grouped["scheduled"].append(draft)
        elif status == "sent":
            grouped["sent"].append(draft)
        elif status == "failed":
            grouped["failed"].append(draft)
        elif status == "skipped":
            grouped["skipped"].append(draft)

    now_text = datetime.utcnow().isoformat()
    waiting_rows = db._conn().execute(
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
    grouped["waiting"] = [dict(row) for row in waiting_rows]
    for row in grouped["waiting"]:
        row["due_label"] = "Waiting follow-up"
    stopped_rows = db._conn().execute(
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
    grouped["skipped"].extend(dict(row) for row in stopped_rows)
    return grouped


@app.post("/api/campaigns/{campaign_filename}/queue/generate-due")
def generate_due_campaign_drafts(
    campaign_filename: str,
    request: QueueGenerateDueRequest,
) -> dict:
    due = _due_items(
        campaign_filename,
        lead_ids=request.lead_ids or None,
        touch_number=request.touch_number,
    )
    if not due:
        return {"generated": 0, "skipped": 0, "skips": []}

    totals = {"generated": 0, "skipped": 0, "skips": []}
    by_touch: dict[int, list[str]] = {}
    for item in due:
        by_touch.setdefault(int(item["touch_number"]), []).append(item["lead_id"])

    for touch, ids in by_touch.items():
        result = _generate_drafts_for_leads(
            campaign_filename,
            ids,
            touch,
            overwrite=False,
        )
        totals["generated"] += result.get("generated", 0)
        totals["skipped"] += result.get("skipped", 0)
        totals["skips"].extend(result.get("skips", []))
    return totals


def _mark_lead_sequence_status(
    lead_id: str,
    request: ManualLeadStatusRequest,
    status: str,
    activity_type: str,
    title: str,
) -> dict:
    lead = lead_repo.get_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    campaign_filename = request.campaign_filename
    state = outreach_repo.get_or_create_state(lead_id, campaign_filename)
    state.status = status
    state.stop_reason = request.reason or status
    state.completed_at = datetime.utcnow()
    state.next_touch_due_at = None
    outreach_repo.upsert_state(state)
    skipped = outreach_repo.mark_future_pending_skipped(
        lead_id,
        campaign_filename,
        request.reason or status,
    )
    with db._conn() as conn:
        conn.execute(
            """
            UPDATE leads
            SET email_sequence_status = ?,
                email_sequence_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                request.reason or status,
                datetime.utcnow().isoformat(),
                lead_id,
            ),
        )
    _add_activity(
        lead,
        campaign_filename,
        activity_type,
        title,
        request.reason or "",
        {"skipped_pending_drafts": skipped},
    )
    return {
        "updated": True,
        "lead_id": lead_id,
        "campaign_filename": campaign_filename,
        "status": status,
        "skipped_pending_drafts": skipped,
    }


@app.post("/api/leads/{lead_id}/mark-replied")
def mark_lead_replied(
    lead_id: str,
    request: ManualLeadStatusRequest,
) -> dict:
    return _mark_lead_sequence_status(
        lead_id,
        request,
        "replied",
        "replied",
        "Lead marked replied",
    )


@app.post("/api/leads/{lead_id}/mark-bounced")
def mark_lead_bounced(
    lead_id: str,
    request: ManualLeadStatusRequest,
) -> dict:
    return _mark_lead_sequence_status(
        lead_id,
        request,
        "bounced",
        "bounced",
        "Lead marked bounced",
    )


@app.post("/api/leads/{lead_id}/mark-unsubscribed")
def mark_lead_unsubscribed(
    lead_id: str,
    request: ManualLeadStatusRequest,
) -> dict:
    return _mark_lead_sequence_status(
        lead_id,
        request,
        "unsubscribed",
        "unsubscribed",
        "Lead marked unsubscribed",
    )


@app.post("/api/leads/{lead_id}/mark-do-not-contact")
def mark_lead_do_not_contact(
    lead_id: str,
    request: ManualLeadStatusRequest,
) -> dict:
    return _mark_lead_sequence_status(
        lead_id,
        request,
        "do_not_contact",
        "do_not_contact",
        "Lead marked do not contact",
    )


@app.get("/api/leads/{lead_id}/activities")
def get_lead_activities(
    lead_id: str,
    campaign_filename: str = "",
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    return [
        _activity_payload(row)
        for row in outreach_repo.list_lead_activities(
            lead_id,
            campaign_filename=campaign_filename,
            limit=limit,
        )
    ]


@app.get("/api/campaigns/{campaign_filename}/activities")
def get_campaign_activities(
    campaign_filename: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    return [
        _activity_payload(row)
        for row in outreach_repo.list_campaign_activities(
            campaign_filename,
            limit=limit,
        )
    ]


@app.get("/api/campaigns/{campaign_filename}/export-zoominfo")
def export_campaign_for_zoominfo(campaign_filename: str):
    from fastapi.responses import StreamingResponse

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Lead ID",
        "Run ID",
        "First Name",
        "Last Name",
        "Full Name",
        "Company Name",
        "Job Title",
        "LinkedIn URL",
        "Company LinkedIn URL",
        "Location",
        "Email",
        "Phone",
    ])
    safe_name = campaign_filename.replace(".json", "")
    for lead in _campaign_leads(campaign_filename):
        first_name = lead.first_name
        last_name = lead.last_name
        if not first_name and lead.full_name:
            parts = lead.full_name.split()
            first_name = parts[0]
            last_name = " ".join(parts[1:])
        writer.writerow([
            lead.id,
            getattr(lead, "run_id", "") or "",
            first_name,
            last_name,
            lead.full_name,
            lead.company,
            lead.title,
            lead.linkedin_url,
            lead.company_linkedin_url,
            lead.location,
            lead.email,
            lead.phone,
        ])
        _add_activity(
            lead,
            campaign_filename,
            "exported_for_zoominfo",
            "Lead exported for ZoomInfo",
            "Campaign ZoomInfo export downloaded",
            {"filename": f"{safe_name}_zoominfo_export.csv"},
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename={safe_name}_zoominfo_export.csv"
            )
        },
    )


@app.post("/api/campaigns/{campaign_filename}/upload-enriched")
async def upload_campaign_enriched(
    campaign_filename: str,
    file: UploadFile = File(...),
) -> dict:
    rows = await _read_enriched_rows(file)
    total_rows = len(rows)
    if not rows:
        return {
            "success": True,
            "total_rows": 0,
            "matched": 0,
            "updated": 0,
            "unmatched": 0,
            "ambiguous": 0,
            "errors": [],
            "message": "No rows found in uploaded file",
        }

    run_ids = {
        _row_value(row, "Run ID", "run_id")
        for row in rows
        if _row_value(row, "Run ID", "run_id")
    }
    campaign_run_ids = set(_campaign_run_ids(campaign_filename))
    if run_ids:
        run_ids = {rid for rid in run_ids if rid in campaign_run_ids}

    if run_ids:
        leads = []
        for run_id in run_ids:
            leads.extend(lead_repo.get_by_run(run_id))
    else:
        leads = _campaign_leads(campaign_filename)

    from collections import defaultdict
    from datetime import datetime

    by_id = {lead.id: lead for lead in leads}
    by_linkedin: dict[str, list[Lead]] = defaultdict(list)
    by_email: dict[str, list[Lead]] = defaultdict(list)
    by_name_company: dict[str, list[Lead]] = defaultdict(list)
    by_first_last_company: dict[str, list[Lead]] = defaultdict(list)

    for lead in leads:
        if lead.linkedin_url:
            by_linkedin[_norm_url(lead.linkedin_url)].append(lead)
        if lead.email:
            by_email[lead.email.strip().lower()].append(lead)
        if lead.full_name and lead.company:
            by_name_company[_norm_name_company(lead.full_name, lead.company)].append(lead)
        if lead.first_name and lead.last_name and lead.company:
            key = _norm_name_company(
                f"{lead.first_name} {lead.last_name}",
                lead.company,
            )
            by_first_last_company[key].append(lead)

    matched = 0
    updated = 0
    unmatched = 0
    ambiguous = 0
    errors = []
    affected_runs: set[str] = set()

    for idx, row in enumerate(rows, start=2):
        lead_id = _row_value(row, "Lead ID", "lead_id", "id")
        linkedin = _norm_url(_row_value(
            row,
            "LinkedIn URL",
            "Person LinkedIn URL",
            "linkedin_url",
        ))
        email = _row_value(
            row,
            "Email",
            "Work Email",
            "Business Email",
            "Email Address",
            "email",
        )
        full_name = _row_value(row, "Full Name", "Name", "full_name")
        company = _row_value(
            row,
            "Company Name",
            "Company",
            "Account Name",
            "company",
        )
        first_name = _row_value(row, "First Name", "first_name")
        last_name = _row_value(row, "Last Name", "last_name")

        lead = None
        if lead_id:
            lead = by_id.get(lead_id)
        if not lead and linkedin:
            candidates = by_linkedin.get(linkedin, [])
            if len(candidates) == 1:
                lead = candidates[0]
            elif len(candidates) > 1:
                ambiguous += 1
                continue
        if not lead and email:
            candidates = by_email.get(email.strip().lower(), [])
            if len(candidates) == 1:
                lead = candidates[0]
            elif len(candidates) > 1:
                ambiguous += 1
                continue
        if not lead and full_name and company:
            candidates = by_name_company.get(_norm_name_company(full_name, company), [])
            if len(candidates) == 1:
                lead = candidates[0]
            elif len(candidates) > 1:
                ambiguous += 1
                continue
        if not lead and first_name and last_name and company:
            candidates = by_first_last_company.get(
                _norm_name_company(f"{first_name} {last_name}", company),
                [],
            )
            if len(candidates) == 1:
                lead = candidates[0]
            elif len(candidates) > 1:
                ambiguous += 1
                continue

        if not lead:
            unmatched += 1
            continue

        matched += 1
        updates: dict[str, str] = {}

        email_value = email
        phone = _row_value(
            row,
            "Phone",
            "Direct Phone",
            "Mobile Phone",
            "Cell",
            "Phone Number",
            "phone",
        )
        domain = _row_value(
            row,
            "Company Domain",
            "Domain",
            "Website",
            "Company Website",
            "company_domain",
        )
        title = _row_value(row, "Job Title", "Title", "title")
        location = _split_location(row)
        linkedin_url = _norm_url(_row_value(
            row,
            "LinkedIn URL",
            "Person LinkedIn URL",
            "linkedin_url",
        ))
        company_linkedin_url = _norm_url(_row_value(
            row,
            "Company LinkedIn URL",
            "company_linkedin_url",
        ))

        if domain:
            import re
            domain = re.sub(r"https?://(www\.)?", "", domain, flags=re.IGNORECASE).rstrip("/")

        if email_value:
            updates["email"] = email_value
        if phone:
            updates["phone"] = phone
        if domain:
            updates["company_domain"] = domain
        if title:
            updates["title"] = title
        if location:
            updates["location"] = location
        if linkedin_url:
            updates["linkedin_url"] = linkedin_url
        if company_linkedin_url:
            updates["company_linkedin_url"] = company_linkedin_url

        try:
            if lead_repo.update_lead_enrichment(lead.id, updates):
                updated += 1
                affected_runs.add(lead.run_id)
                refreshed = lead_repo.get_by_id(lead.id) or lead
                if email_value:
                    state = outreach_repo.get_or_create_state(
                        lead.id,
                        campaign_filename,
                    )
                    if state.status in {"not_started", "enriched"}:
                        state.status = "enriched"
                        outreach_repo.upsert_state(state)
                        _set_lead_sequence_columns(lead.id, "enriched")
                _add_activity(
                    refreshed,
                    campaign_filename,
                    "enriched",
                    "Lead enriched from uploaded file",
                    "ZoomInfo enrichment data matched and updated this lead",
                    {
                        "fields": sorted(updates.keys()),
                        "row": idx,
                    },
                )
        except Exception as exc:
            errors.append(f"Row {idx}: {exc}")

    _update_segments_for_runs({run_id for run_id in affected_runs if run_id})

    return {
        "success": True,
        "total_rows": total_rows,
        "matched": matched,
        "updated": updated,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
        "errors": errors,
        "message": (
            "No matching leads found. Make sure the file includes Lead ID, LinkedIn URL, or Full Name + Company."
            if matched == 0 and total_rows > 0
            else "Enriched leads uploaded successfully"
        ),
    }


@app.get("/api/campaigns/{campaign_filename}/sequence-settings")
def get_campaign_sequence_settings(campaign_filename: str) -> dict:
    return _load_sequence_settings(campaign_filename)


@app.post("/api/campaigns/{campaign_filename}/sequence-settings")
def save_campaign_sequence_settings(
    campaign_filename: str,
    request: SequenceSettingsRequest,
) -> dict:
    touches = []
    incoming = request.steps or request.touches
    if not incoming:
        raise HTTPException(
            status_code=400,
            detail="At least one sequence step is required",
        )
    for touch in incoming:
        if touch.number <= 0:
            raise HTTPException(
                status_code=400,
                detail="touch_number must be positive",
            )
        if touch.delay_days < 0:
            raise HTTPException(
                status_code=400,
                detail="delay_days cannot be negative",
            )
        if hasattr(touch, "model_dump"):
            item = touch.model_dump()
        else:
            item = touch.dict()
        item["touch_number"] = item.get("touch_number") or item.get("number")
        item["touch_name"] = item.get("touch_name") or item.get("name")
        touches.append(item)
    rules = request.rules.model_dump() if request.rules else {}
    _save_sequence_settings(
        campaign_filename,
        {"touches": touches, "steps": touches, "rules": rules},
    )
    return {
        "saved": True,
        "campaign": campaign_filename,
        **_load_sequence_settings(campaign_filename),
    }


@app.post("/api/campaigns")
def create_campaign(request: CreateCampaignRequest) -> dict:
    """Create a new campaign JSON file in campaigns/ folder."""
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Campaign name is required")

    campaigns_dir = Path("campaigns")
    campaigns_dir.mkdir(exist_ok=True)

    import re as _re

    filename = (
        _re.sub(r"[^a-z0-9]+", "_", request.name.lower()).strip("_")
        + ".json"
    )
    path = campaigns_dir / filename

    if path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Campaign '{request.name}' already exists",
        )

    data = {
        "name": request.name,
        "description": request.description,
        "knowledge_bases": request.knowledge_bases,
        "target_personas": request.target_personas,
        "target_industries": request.target_industries,
        "tone": request.tone,
        "email_goal": request.email_goal,
        "max_email_words": request.max_email_words,
        "max_linkedin_chars": request.max_linkedin_chars,
        "key_pain_points": request.key_pain_points,
    }

    path.write_text(
        _json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "created": True,
        "filename": filename,
        "name": request.name,
    }


@app.get("/api/campaigns")
def list_campaigns() -> list[dict]:
    return KnowledgeBaseLoader.list_campaigns()


@app.get("/api/knowledge-bases")
def list_knowledge_bases() -> list[str]:
    return KnowledgeBaseLoader.list_kb_files()


@app.post("/api/knowledge-bases/upload")
async def upload_kb_file(file: UploadFile = File(...)) -> dict:
    """
    Upload a knowledge base file to the knowledge_base/ folder.
    Supports .txt, .pdf, .docx
    Converts PDF and DOCX to plain text automatically.
    """
    from pathlib import Path

    kb_dir = Path("knowledge_base")
    kb_dir.mkdir(exist_ok=True)

    filename = file.filename or "uploaded.txt"
    ext = Path(filename).suffix.lower()

    if ext not in (".txt", ".pdf", ".docx"):
        raise HTTPException(
            status_code=400,
            detail="Only .txt, .pdf, and .docx files are supported",
        )

    contents = await file.read()

    if ext == ".txt":
        text = contents.decode("utf-8", errors="ignore")

    elif ext == ".pdf":
        try:
            import io
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(contents))
            pages = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pages.append(t.strip())
            text = "\n\n".join(pages)
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="pypdf not installed. Run: pip install pypdf",
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"PDF read failed: {e}",
            )

    elif ext == ".docx":
        try:
            import io
            import docx

            doc = docx.Document(io.BytesIO(contents))
            text = "\n\n".join(
                p.text for p in doc.paragraphs if p.text.strip()
            )
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="python-docx not installed. Run: pip install python-docx",
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"DOCX read failed: {e}",
            )

    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="File appears to be empty or could not be read",
        )

    save_name = Path(filename).stem + ".txt"
    save_path = kb_dir / save_name

    counter = 1
    while save_path.exists():
        save_name = f"{Path(filename).stem}_{counter}.txt"
        save_path = kb_dir / save_name
        counter += 1

    save_path.write_text(text, encoding="utf-8")

    return {
        "uploaded": True,
        "filename": save_name,
        "characters": len(text),
        "message": f"Saved as {save_name} ({len(text):,} characters)",
    }


@app.websocket("/ws/runs/{run_id}")
async def websocket_run_events(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    loop = asyncio.get_running_loop()

    def handler(event: AgentEvent) -> None:
        if event.run_id != run_id:
            return
        asyncio.run_coroutine_threadsafe(websocket.send_json(_event_json(event)), loop)

    orchestrator.on_event(handler)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if handler in orchestrator._event_handlers:
            orchestrator._event_handlers.remove(handler)


@app.on_event("startup")
def startup() -> None:
    def persist_event(event: AgentEvent) -> None:
        event_repo.save(event)
        active_run = orchestrator.get_active_run()
        if active_run and active_run.id == event.run_id:
            run_repo.save(active_run)

    orchestrator.on_event(persist_event)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
