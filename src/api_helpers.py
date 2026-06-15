##src\api.py
import secrets
import asyncio
import csv, io
import html
import json
import json as _json
import logging
import os
import shutil
import threading
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi import UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from src import orchestrator as orchestrator_module
from src.agents.reply_monitor import (
    get_inbox_monitor_status,
    run_reply_monitor_loop,
)

from src.campaign_config import CampaignConfigModel
from src.send_policy import SendPolicy, next_send_delay_seconds
from src.job_worker import get_job_worker


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
from src.graph_client import send_via_graph
from src.storage import (
    campaign_repo,
    campaign_sequence_repo,
    event_repo,
    job_repo,
    lead_repo,
    lead_universe_repo,
    outreach_repo,
    run_repo,
    send_log_repo,
    suppression_repo,
)

from src.sequence import calculate_next_touch_due_at
from src.sequence_modes import normalize_sequence_mode
from src.unsubscribe import make_unsubscribe_url, parse_token


from src.personalisation.agents.context_agent import ContextAgent
from src.personalisation.agents.web_research_agent import WebResearchAgent
from src.personalisation.agents.writer_agent import WriterAgent
from src.personalisation.knowledge_base import KnowledgeBaseLoader
from src.personalisation.models import ResearchResult

logger = logging.getLogger(__name__)
COMPANY_FOOTER_ADDRESS = (
    "Royal Cyber Inc., 55 Shuman Blvd, Suite 275, Naperville, IL 60563"
)

orchestrator = orchestrator_module.PipelineOrchestrator()
_segment_runner_lock = threading.Lock()
_running_segment_ids: set[str] = set()
_running_universe_ids: set[str] = set()


def _apply_unsubscribe_token(token: str) -> dict | None:
    payload = parse_token(token)
    if not payload:
        return None
    email = payload["email"]
    lead_id = payload.get("lead_id", "")
    suppression_repo.add(email, "unsubscribed", lead_id)
    if lead_id and lead_repo.get_by_id(lead_id):
        for state in outreach_repo.list_states_for_lead(lead_id):
            _stop_sequence(
                lead_id,
                state.campaign_filename,
                "unsubscribed",
                "unsubscribed",
            )
    return payload


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
    label: str = ""
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
    duplicate_of_lead_id: str = ""


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
    mode: str = "manual"
    stop_on_reply: bool = True
    stop_on_bounce: bool = True
    stop_on_unsubscribe: bool = True
    skip_no_email: bool = True
    skip_weekends: bool = False
    send_window_start: str = "09:00"
    send_window_end: str = "17:00"
    daily_send_limit: int = 50
    delay_between_sends_seconds: int = 60
    require_approval_for_touch1: bool = True
    require_approval_for_followups: bool = True


class SequenceSettingsRequest(BaseModel):
    name: str = ""
    sequence_name: str = ""
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


class ScheduleApprovedDraftsRequest(BaseModel):
    draft_ids: list[str] = []
    schedule_for: str = "next_allowed"


class ScheduleSendDraftsRequest(BaseModel):
    draft_ids: list[str] = []
    mode: str = "send_now"
    rate_per_minute: int = 20


class ApproveScheduleDraftsRequest(BaseModel):
    draft_ids: list[str] = []
    start_mode: str = "now"
    start_at: str = ""
    rate_per_minute: int = 20


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
    sender_email: str = ""
    openai_model: str = "gpt-4o-mini"
    zoominfo_enabled: bool = False
    max_emails_per_day: int = 150
    send_delay_seconds: int = 3


class SuppressionRequest(BaseModel):
    email: str
    reason: str = "manual"
    source_lead_id: str = ""
    source_campaign: str = ""


class CreateCampaignRequest(CampaignConfigModel):
    name: str
    description: str = ""


class CampaignUpdateRequest(BaseModel):
    sender_name: Optional[str] = None
    sender_title: Optional[str] = None
    sender_email: Optional[str] = None
    reply_to_email: Optional[str] = None


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
        "mode": normalize_sequence_mode(rules.mode),
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
    steps, rules = campaign_sequence_repo.ensure_defaults(
        campaign_filename,
        default_steps=[],
    )
    step_rows = [_step_payload(step) for step in steps]
    return {
        "steps": step_rows,
        "touches": step_rows,
        "rules": _rules_payload(rules),
    }


def _save_sequence_settings(campaign_filename: str, settings: dict) -> None:
    touches = settings.get("touches") or settings.get("steps") or []
    sequence_name = str(
        settings.get("sequence_name") or settings.get("name") or ""
    ).strip()
    if sequence_name:
        campaign = campaign_repo.get_by_filename(campaign_filename) or {}
        config = {
            **(campaign.get("config") or {}),
            "sequence_name": sequence_name,
        }
        campaign_repo.update_config(campaign_filename, config)
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
        campaign_sequence_repo.deactivate_missing_steps(
            campaign_filename,
            touch_numbers,
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
        mode = normalize_sequence_mode(rules_data.get("mode"))
        if mode not in {"manual", "auto"}:
            raise HTTPException(
                status_code=400,
                detail="mode must be manual or auto",
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
            skip_weekends=bool(rules_data.get("skip_weekends", False)),
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
    return run_repo.ids_for_campaign(campaign_filename)


def _run_label(run: PipelineRun) -> str:
    started = run.started_at
    started_text = _dt(started) or ""
    segment = lead_universe_repo.segment_for_run(run.id)
    if segment and segment.get("label"):
        return f"{segment['label']} · {started:%b %d, %H:%M}"
    return f"Run {run.id[:8]} · {started_text}"


def _run_response(run: PipelineRun) -> RunResponse:
    return RunResponse(
        id=run.id,
        label=_run_label(run),
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
        duplicate_of_lead_id=getattr(lead, "duplicate_of_lead_id", "") or "",
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


def _campaign_runs(campaign_filename: str) -> list[PipelineRun]:
    return run_repo.list_for_campaign(campaign_filename)


def _lead_campaign_row(lead: Lead) -> dict:
    return {
        "id": lead.id,
        "run_id": getattr(lead, "run_id", "") or "",
        "full_name": lead.full_name,
        "company": lead.company,
        "title": lead.title,
        "email": lead.email,
        "phone": lead.phone,
        "location": lead.location,
        "segment": lead.segment.value,
        "status": lead.status.value,
        "email_sequence_status": getattr(
            lead,
            "email_sequence_status",
            "not_started",
        ),
        "personalised_at": getattr(lead, "personalised_at", "") or "",
        "email_subject": getattr(lead, "email_subject", "") or "",
        "email_body": getattr(lead, "email_body", "") or "",
        "linkedin_message": getattr(lead, "linkedin_message", "") or "",
        "research_summary": getattr(lead, "research_summary", "") or "",
        "campaign_name": getattr(lead, "campaign_name", "") or "",
        "duplicate_of_lead_id": getattr(lead, "duplicate_of_lead_id", "") or "",
    }


def _campaign_lead_rows(
    campaign_filename: str,
    segment: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: Optional[int] = 500,
    offset: int = 0,
    drafts_only: bool = False,
) -> list[dict]:
    leads, _total = lead_repo.search(
        campaign_filename=campaign_filename,
        segment=segment,
        limit=limit,
        offset=offset,
        run_id=run_id or "",
        drafts_only=drafts_only,
    )
    return [_lead_campaign_row(lead) for lead in leads]


def _campaign_lead_payload(row: dict) -> dict:
    email = row.get("email", "") or ""

    return {
        "id": row.get("id", ""),
        "run_id": row.get("run_id", ""),
        "full_name": row.get("full_name", "") or "",
        "company": row.get("company", "") or "",
        "title": row.get("title", "") or "",
        "email": email,
        "email_confidence": row.get("email_confidence", "") or "",
        "email_verification_status": row.get("email_verification_status") or "",
        "email_verification_reason": row.get("email_verification_reason") or "",
        "email_verification_checked_at": row.get("email_verification_checked_at") or "",
        "phone": row.get("phone", "") or "",
        "location": row.get("location", "") or "",
        "linkedin_url": row.get("linkedin_url", "") or "",
        "company_linkedin_url": row.get("company_linkedin_url", "") or "",
        "segment": row.get("segment", "") or "",
        "status": row.get("status", "") or "",
        "email_sequence_status": (
            row.get("email_sequence_status", "") or "not_started"
        ),
        "sequence_status": (
            row.get("sequence_status")
            or row.get("email_sequence_status")
            or "not_started"
        ),
        "personalised_at": row.get("personalised_at") or "",
        "duplicate_of_lead_id": row.get("duplicate_of_lead_id", "") or "",
        "last_activity_at": row.get("last_activity_at") or "",
        "last_activity_title": row.get("last_activity_title") or "",
        "is_suppressed": suppression_repo.is_suppressed(email) if email else False,
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
    return lead_repo.get_by_campaign(
        campaign_filename,
        exclude_run_id=exclude_run_id,
    )


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

            counts = lead_repo.count_by_segment_for_run(run.id)
            run.total_scraped = unique_count
            run.total_enriched = 0
            run.total_warm = counts["warm"]
            run.total_cold = counts["cold"]
            run.total_no_email = counts["no_email"]

            exporter = ExportAgent(run, segmented)
            exporter.on_event(lambda event: event_repo.save(event))
            output_files = exporter.execute()
            stop_reason = getattr(scraper, "_sales_nav_stop_reason", "unknown")
            if raw_count == 0 and stop_reason == "unknown":
                stop_reason = "blocked_or_captcha"

            scraper_failed = (
                raw_count == 0
                and stop_reason in {
                    "blocked_or_captcha",
                    "chrome_cdp_error",
                    "browser_error",
                    "content_timeout",
                    "login_required",
                }
            )

            if scraper_failed:
                status = "failed"
                run.status = RunStatus.FAILED
                run.error = (
                    "Scraper produced no usable leads. "
                    f"Stop reason: {stop_reason}."
                )
            else:
                status = "completed" if unique_count or raw_count else "exhausted"
                run.status = RunStatus.COMPLETED
                run.error = ""

            run.completed_at = datetime.utcnow()
            run_repo.save(run)

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
    try:
        while True:
            segment = lead_universe_repo.next_queued_segment(universe_id)
            if not segment:
                break
            _run_segment_now(segment.id)
    finally:
        _running_universe_ids.discard(universe_id)


def _update_segments_for_runs(run_ids: set[str]) -> None:
    for run_id in run_ids:
        run = run_repo.get(run_id)
        if not run:
            continue
        leads = lead_repo.get_by_run(run_id)
        segmenter = SegmentAgent(run, leads)
        segmenter.on_event(lambda event: event_repo.save(event))
        segmented = segmenter.execute()
        lead_repo.update_segments(run_id, segmented)
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
    "sending",
    "sent",
    "failed",
    "skipped",
}

def _safe_json_list(value) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _campaign_config_for_review(campaign_filename: str) -> dict:
    campaign = campaign_repo.get_by_filename(campaign_filename) or {}
    config = campaign.get("config") or {}
    return config if isinstance(config, dict) else {}


def compute_risk_flags(
    subject: str,
    body: str,
    lead,
    campaign_config: dict,
    research_summary: str = "",
) -> list[str]:
    flags: list[str] = []
    text = f"{subject or ''}\n{body or ''}"

    if "{{" in text or "}}" in text:
        flags.append("template_leak")

    first_name = (getattr(lead, "first_name", "") or "").strip()
    if not first_name or first_name.lower() not in (body or "").lower():
        flags.append("missing_first_name")

    try:
        max_words = int((campaign_config or {}).get("max_email_words", 200) or 200)
    except Exception:
        max_words = 200

    if len((body or "").split()) > max_words:
        flags.append("too_long")

    company = (getattr(lead, "company", "") or "").strip()
    if not (research_summary or "").strip() and (
        not company or company.lower() not in (body or "").lower()
    ):
        flags.append("no_personalisation")

    email_verification_status = (
        getattr(lead, "email_verification_status", "") or ""
    ).lower()
    if email_verification_status in {"risky", "invalid"}:
        flags.append("risky_email")

    return flags


def _draft_review_updates(
    lead,
    campaign_filename: str,
    subject: str,
    body: str,
    research_summary: str = "",
    kb_sources: list | None = None,
) -> dict:
    campaign_config = _campaign_config_for_review(campaign_filename)

    if kb_sources is None:
        kb_sources = campaign_config.get("knowledge_bases") or []
    if not isinstance(kb_sources, list):
        kb_sources = []

    risk_flags = compute_risk_flags(
        subject=subject,
        body=body,
        lead=lead,
        campaign_config=campaign_config,
        research_summary=research_summary,
    )

    return {
        "research_summary": research_summary or "",
        "kb_sources": json.dumps(kb_sources),
        "risk_flags": json.dumps(risk_flags),
    }

def _campaign_value_prop(campaign_filename: str) -> str:
    campaign = campaign_repo.get_by_filename(campaign_filename) or {}
    config = campaign.get("config") or {}
    value = (
        config.get("email_goal")
        or config.get("value_proposition")
        or campaign.get("description")
        or ""
    )
    if value:
        return str(value)
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

def _campaign_sender_identity(campaign_filename: str) -> dict[str, str]:
    campaign = campaign_repo.get_by_filename(campaign_filename) or {}
    config = campaign.get("config") or {}

    sender_email = (
        config.get("sender_email")
        or os.getenv("SENDER_EMAIL", "")
        or ""
    ).strip()

    reply_to_email = (
        config.get("reply_to_email")
        or sender_email
        or os.getenv("SENDER_EMAIL", "")
        or ""
    ).strip()

    return {
        "sender_name": (
            config.get("sender_name")
            or os.getenv("SENDER_NAME", "Royal Cyber Team")
            or "Royal Cyber Team"
        ).strip(),
        "sender_title": (config.get("sender_title") or "").strip(),
        "sender_email": sender_email,
        "reply_to_email": reply_to_email,
    }


def _campaign_sender_signature(campaign_filename: str) -> str:
    sender = _campaign_sender_identity(campaign_filename)
    lines = [sender["sender_name"] or "Royal Cyber Team"]

    if sender.get("sender_title"):
        lines.append(sender["sender_title"])

    return "\n".join(lines)

def _ensure_sender_signature(body: str, campaign_filename: str) -> str:
    signature = _campaign_sender_signature(campaign_filename).strip()
    text = (body or "").rstrip()

    if not signature:
        return text

    if signature in text:
        return text

    return f"{text}\n\n{signature}".strip()

def _campaign_context(campaign_filename: str) -> dict[str, str]:
    campaign = campaign_repo.get_by_filename(campaign_filename) or {}
    config = campaign.get("config") or {}
    campaign_name = (
        campaign.get("name")
        or campaign_filename.replace(".json", "").replace("_", " ")
    )
    campaign_goal = (
        config.get("email_goal")
        or "book a 20-minute discovery call"
    )
    description = campaign.get("description") or ""
    pain_points = config.get("key_pain_points") or []
    if isinstance(pain_points, list):
        pain_points_text = "; ".join(str(point) for point in pain_points if point)
    else:
        pain_points_text = str(pain_points)

    sender = _campaign_sender_identity(campaign_filename)

    return {
        "campaign_name": campaign_name,
        "campaign_description": description,
        "campaign_goal": campaign_goal,
        "campaign_pain_points": pain_points_text,
        "campaign_value_prop": _campaign_value_prop(campaign_filename),
        "sender_name": sender["sender_name"],
        "sender_title": sender["sender_title"],
        "sender_email": sender["sender_email"],
        "reply_to_email": sender["reply_to_email"],
        "sender_signature": _campaign_sender_signature(campaign_filename),
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
        f"Best,\n{_campaign_sender_signature(campaign_filename)}"
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
        "sender_name": campaign_context["sender_name"],
        "sender_title": campaign_context["sender_title"],
        "sender_email": campaign_context["sender_email"],
        "reply_to_email": campaign_context["reply_to_email"],
        "sender_signature": campaign_context["sender_signature"],
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
            "research_summary": draft.research_summary or "",
            "kb_sources": _safe_json_list(draft.kb_sources),
            "risk_flags": _safe_json_list(draft.risk_flags),
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
        "research_summary": row.get("research_summary") or "",
        "kb_sources": _safe_json_list(row.get("kb_sources")),
        "risk_flags": _safe_json_list(row.get("risk_flags")),
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
    return outreach_repo.latest_draft_for_touch(
        lead_id,
        campaign_filename,
        touch_number,
    )


def _touch1_subject(lead_id: str, campaign_filename: str) -> str:
    return outreach_repo.touch1_subject(lead_id, campaign_filename)


def _previous_sent_draft(
    lead_id: str,
    campaign_filename: str,
    touch_number: int,
) -> OutreachDraft | None:
    return outreach_repo.previous_sent_draft(
        lead_id,
        campaign_filename,
        touch_number,
    )


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
    lead_repo.update_sequence_status(lead_id, status, error)




def _block_risky_verified_emails() -> bool:
    return (
        os.getenv("EMAIL_VERIFICATION_BLOCK_RISKY", "false")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )


def _email_verification_block_reason(lead) -> str:
    status = (
        getattr(lead, "email_verification_status", "") or ""
    ).strip().lower()

    if status == "invalid":
        return "invalid_email"

    if status == "risky" and _block_risky_verified_emails():
        return "risky_email"

    return ""

def _graph_retry_delay_minutes() -> int:
    raw = os.getenv("GRAPH_RETRY_DELAY_MINUTES", "15")
    try:
        value = int(raw)
    except ValueError:
        value = 15
    return max(5, min(value, 120))


def _is_transient_graph_error(error: str) -> bool:
    text = (error or "").lower()
    return any(
        marker in text
        for marker in (
            "graph api error 429",
            "too many requests",
            "throttl",
            "temporarily unavailable",
            "timeout",
            "timed out",
            "connection",
            "graph api error 500",
            "graph api error 502",
            "graph api error 503",
            "graph api error 504",
            "service unavailable",
            "gateway",
        )
    )

def _with_unsubscribe_footer(
    body: str,
    lead_id: str,
    email: str,
) -> tuple[str, str]:

    if os.getenv("UNSUBSCRIBE_FOOTER_ENABLED", "false").strip().lower() != "true":
        return body, ""
    unsubscribe_url = make_unsubscribe_url(lead_id, email)
    one_click_url = f"{unsubscribe_url}/one-click"
    if unsubscribe_url:
        body = (
            f"{body}\n\n--\n"
            f"{COMPANY_FOOTER_ADDRESS}\n"
            "If you'd prefer not to hear from us: "
            f"{unsubscribe_url}"
        )
    return body, one_click_url


def _validate_generate_drafts_for_leads(
    campaign_filename: str,
    touch_number: int,
) -> CampaignSequenceStep:
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

    if not (step.subject_template or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Sequence subject direction is empty. Add a subject direction before generating drafts.",
        )

    if not (step.email_body_template or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Sequence AI writing instructions are empty. Add instructions before generating drafts.",
        )

    return step



def _ai_personalised_drafts_enabled() -> bool:
    return os.getenv("AI_PERSONALISED_DRAFTS_ENABLED", "true").strip().lower() != "false"


def _sequence_step_template_payload(step: CampaignSequenceStep) -> dict:
    return {
        "touch_number": step.touch_number,
        "touch_name": step.touch_name,
        "subject_template": step.subject_template or "",
        "email_body_template": step.email_body_template or "",
        "linkedin_message_template": step.linkedin_message_template or "",
        "delay_days": step.delay_days,
        "delay_value": step.delay_value,
        "delay_unit": step.delay_unit,
        "delay_type": step.delay_type,
    }


def _template_draft_content(
    lead: Lead,
    campaign_filename: str,
    step: CampaignSequenceStep,
    touch_number: int,
    previous_sent: OutreachDraft | None,
) -> dict:
    touch1_subject = _touch1_subject(lead.id, campaign_filename)
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

    body = _strip_ai_signature_artifacts(body, campaign_filename)
    body = _ensure_sender_signature(body, campaign_filename)
    review_updates = _draft_review_updates(
        lead=lead,
        campaign_filename=campaign_filename,
        subject=subject,
        body=body,
        research_summary="",
    )

    return {
        "subject": subject,
        "body": body,
        "linkedin_message": linkedin_message,
        "review_updates": review_updates,
    }


def _combined_research_for_lead(
    lead: Lead,
    research_agent: WebResearchAgent,
    research_cache: dict[str, ResearchResult],
) -> ResearchResult:
    domain = (getattr(lead, "company_domain", "") or "").strip().lower()
    company = (getattr(lead, "company", "") or "").strip().lower()
    cache_key = domain or f"company:{company}"

    base_research = None
    if domain or company:
        base_research = research_cache.get(cache_key)
        if base_research is None:
            base_research = research_agent.research(lead)
            research_cache[cache_key] = base_research

    role_research = research_agent._infer_from_role(lead)

    if base_research:
        source_parts = [
            part
            for part in [base_research.research_source, role_research.research_source]
            if part
        ]
        return ResearchResult(
            lead_id=lead.id,
            company_name=lead.company,
            website_text=base_research.website_text,
            person_context=role_research.person_context,
            research_source="+".join(source_parts) or "combined",
            error=base_research.error,
        )

    return role_research



def _strip_ai_signature_artifacts(body: str, campaign_filename: str) -> str:
    text = (body or "").replace("{{sender_name}}", "").strip()
    if not text:
        return ""

    sender = _campaign_sender_identity(campaign_filename)
    signature_names = {
        (sender.get("sender_name") or "").strip(),
        "Royal Cyber Team",
        "Enterprise Solutions Team",
    }
    signature_names = {value for value in signature_names if value}

    lines = text.splitlines()
    cut_at = None

    for index, line in enumerate(lines):
        normalized = line.strip().lower().rstrip(",")
        if normalized in {"best", "best regards", "regards", "thanks", "thank you"}:
            cut_at = index
            break

    if cut_at is not None:
        lines = lines[:cut_at]

    while lines and lines[-1].strip() in signature_names:
        lines.pop()

    return "\n".join(lines).strip()


def _ai_personalised_draft_content(
    lead: Lead,
    campaign_filename: str,
    step: CampaignSequenceStep,
    research_agent: WebResearchAgent,
    context_agent: ContextAgent,
    writer_agent: WriterAgent,
    research_cache: dict[str, ResearchResult],
) -> dict:
    research = _combined_research_for_lead(
        lead,
        research_agent,
        research_cache,
    )
    context = context_agent.get_context(lead, research)
    message = writer_agent.write(lead, research, context)

    if message.error:
        raise RuntimeError(message.error)

    subject = (message.email_subject or "").strip()
    body = (message.email_body or "").strip()
    linkedin_message = (message.linkedin_message or "").strip()

    if not subject or not body:
        raise RuntimeError("AI returned empty subject or body")

    body = _ensure_sender_signature(body, campaign_filename)
    review_updates = _draft_review_updates(
        lead=lead,
        campaign_filename=campaign_filename,
        subject=subject,
        body=body,
        research_summary=message.research_summary,
        kb_sources=message.kb_files_used,
    )

    return {
        "subject": subject,
        "body": body,
        "linkedin_message": linkedin_message,
        "review_updates": review_updates,
    }



def _generate_drafts_for_leads(
    campaign_filename: str,
    lead_ids: list[str],
    touch_number: int,
    overwrite: bool = False,
) -> dict:
    step = _validate_generate_drafts_for_leads(campaign_filename, touch_number)
    campaign_leads = _campaign_lead_ids(campaign_filename)
    generated = 0
    skipped = 0
    skips = []

    ai_enabled = _ai_personalised_drafts_enabled()
    research_cache: dict[str, ResearchResult] = {}

    campaign_config = None
    research_agent = None
    context_agent = None
    writer_agent = None

    if ai_enabled:
        campaign_config = KnowledgeBaseLoader.load_campaign(campaign_filename)
        research_agent = WebResearchAgent()
        context_agent = ContextAgent(campaign_config)
        writer_agent = WriterAgent(
            campaign_config,
            touch1_template=_sequence_step_template_payload(step),
        )

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

        previous_sent = _previous_sent_draft(
            lead.id,
            campaign_filename,
            touch_number,
        )

        try:
            if ai_enabled:
                content = _ai_personalised_draft_content(
                    lead=lead,
                    campaign_filename=campaign_filename,
                    step=step,
                    research_agent=research_agent,
                    context_agent=context_agent,
                    writer_agent=writer_agent,
                    research_cache=research_cache,
                )
            else:
                content = _template_draft_content(
                    lead=lead,
                    campaign_filename=campaign_filename,
                    step=step,
                    touch_number=touch_number,
                    previous_sent=previous_sent,
                )
        except Exception as exc:
            skipped += 1
            skips.append({
                "lead_id": lead.id,
                "reason": "ai_personalisation_failed" if ai_enabled else "template_generation_failed",
                "error": str(exc),
            })
            _add_activity(
                lead,
                campaign_filename,
                "draft_generation_failed",
                "Draft generation failed",
                str(exc),
                {
                    "touch_number": touch_number,
                    "ai_enabled": ai_enabled,
                },
            )
            continue

        subject = content["subject"]
        body = content["body"]
        linkedin_message = content["linkedin_message"]
        review_updates = content["review_updates"]

        if existing and overwrite:
            draft = outreach_repo.update_draft(
                existing.id,
                {
                    "subject": subject,
                    "body": body,
                    "linkedin_message": "",
                    "status": "draft",
                    "error_message": "",
                    **review_updates,
                },
            ) or existing
        else:
            draft = OutreachDraft(
                lead_id=lead.id,
                campaign_filename=campaign_filename,
                touch_number=touch_number,
                subject=subject,
                body=body,
                linkedin_message=linkedin_message,
                status="draft",
                research_summary=review_updates["research_summary"],
                kb_sources=review_updates["kb_sources"],
                risk_flags=review_updates["risk_flags"],
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
    return outreach_repo.sent_draft_exists(
        lead_id,
        campaign_filename,
        touch_number,
    )


def _parse_clock(value: str, fallback: time) -> time:
    try:
        parts = (value or "").split(":")
        return time(int(parts[0]), int(parts[1] if len(parts) > 1 else 0))
    except Exception:
        return fallback


def _send_window_enabled() -> bool:
    return os.getenv("SEND_WINDOW_ENABLED", "false").strip().lower() == "true"


def _inside_send_window(rules: CampaignSequenceRules) -> bool:
    if not _send_window_enabled():
        return True

    now_time = datetime.now().time()
    start = _parse_clock(rules.send_window_start, time(9, 0))
    end = _parse_clock(rules.send_window_end, time(17, 0))
    if start <= end:
        return start <= now_time <= end
    return now_time >= start or now_time <= end

def _bulk_send_rate_per_minute(value: int | None = None) -> int:
    if value:
        return max(1, min(int(value), 30))
    try:
        configured = int(os.getenv("BULK_SEND_RATE_PER_MINUTE", "30") or 30)
    except ValueError:
        configured = 20
    return max(1, min(configured, 30))


def _campaign_rule_block_message(rules: CampaignSequenceRules) -> str:
    if not _inside_send_window(rules):
        return (
            "Outside campaign send window. Schedule or send during "
            f"{rules.send_window_start}-{rules.send_window_end}."
        )
    return ""


def _next_allowed_send_at(
    rules: CampaignSequenceRules,
    from_dt: datetime | None = None,
) -> datetime:
    now = (from_dt or datetime.now()).replace(second=0, microsecond=0)

    if not _send_window_enabled():
        return now
    start = _parse_clock(rules.send_window_start, time(9, 0))
    end = _parse_clock(rules.send_window_end, time(17, 0))
    candidate = now

    for _ in range(14):
        window_start = datetime.combine(candidate.date(), start)
        window_end = datetime.combine(candidate.date(), end)

        if start <= end:
            if candidate < window_start:
                return window_start
            if candidate <= window_end:
                return candidate
            candidate = datetime.combine(
                (candidate + timedelta(days=1)).date(),
                start,
            )
            continue

        if candidate.time() >= start or candidate.time() <= end:
            return candidate
        return window_start

    return datetime.combine((now + timedelta(days=1)).date(), time(9, 0))


def _karachi_local_to_utc(value: datetime) -> datetime:
    """Convert a UI-selected Asia/Karachi local datetime into naive UTC for DB storage."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    # Pakistan is UTC+05:00 and does not currently use daylight saving time.
    return value - timedelta(hours=5)


def _parse_schedule_datetime(value: str) -> datetime:
    raw = (value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="start_at is required when start_mode is later")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="start_at must be a valid ISO datetime",
        ) from exc

    return _karachi_local_to_utc(parsed).replace(second=0, microsecond=0)


def _rate_limited_slots(
    count: int,
    start_at: datetime,
    rate_per_minute: int,
) -> list[datetime]:
    start = start_at.replace(second=0, microsecond=0)
    return [
        start + timedelta(minutes=index // rate_per_minute)
        for index in range(count)
    ]


def _throttled_send_slots(
    count: int,
    rules: CampaignSequenceRules,
    start_at: datetime,
    rate_per_minute: int,
) -> list[datetime]:
    slots = []
    current = start_at.replace(second=0, microsecond=0)
    in_current_minute = 0

    for _ in range(count):
        current = _next_allowed_send_at(rules, current)
        slots.append(current)
        in_current_minute += 1
        if in_current_minute >= rate_per_minute:
            current = current + timedelta(minutes=1)
            in_current_minute = 0

    return slots


def _queued_job_response(job: dict) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        content={"job_id": job["id"], "status": job["status"]},
    )


def _schedule_approved_drafts(
    campaign_filename: str,
    request: ScheduleApprovedDraftsRequest,
) -> dict:
    return _schedule_send_drafts(
        campaign_filename,
        ScheduleSendDraftsRequest(
            draft_ids=request.draft_ids,
            mode="schedule",
            rate_per_minute=_bulk_send_rate_per_minute(),
        ),
    )


def _schedule_send_drafts(
    campaign_filename: str,
    request: ScheduleSendDraftsRequest,
) -> dict:
    mode = request.mode or "send_now"
    if mode == "schedule_next_allowed":
        mode = "schedule"
    if mode not in {"send_now", "schedule"}:
        raise HTTPException(
            status_code=400,
            detail="mode must be send_now or schedule",
        )

    rate_per_minute = _bulk_send_rate_per_minute(request.rate_per_minute)
    _, rules = campaign_sequence_repo.ensure_defaults(
        campaign_filename,
        default_steps=[],
    )

    blocked_message = _campaign_rule_block_message(rules)
    if mode == "send_now" and blocked_message:
        raise HTTPException(
            status_code=409,
            detail=(
                "Sending is not available right now. "
                f"{blocked_message}"
            ),
        )

    requested_ids = [draft_id for draft_id in request.draft_ids if draft_id]
    drafts = (
        outreach_repo.get_drafts_by_ids(requested_ids)
        if requested_ids
        else outreach_repo.list_approved_drafts(campaign_filename)
    )

    scheduled = 0
    skipped = 0
    details = []
    found_ids = {draft.id for draft in drafts}
    eligible = []

    for missing_id in set(requested_ids) - found_ids:
        skipped += 1
        details.append({
            "draft_id": missing_id,
            "status": "skipped",
            "reason": "not_found",
        })

    for draft in drafts:
        if draft.campaign_filename != campaign_filename:
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "status": "skipped",
                "reason": "wrong_campaign",
            })
            continue

        if draft.status != "approved":
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "status": "skipped",
                "reason": "not_approved",
            })
            continue

        lead = lead_repo.get_by_id(draft.lead_id)
        if not lead:
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "status": "skipped",
                "reason": "lead_not_found",
            })
            continue

        if not (lead.email or "").strip():
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "no_email",
            })
            continue

        if (getattr(lead, "email_verification_status", "") or "").lower() == "invalid":
            outreach_repo.update_draft(
                draft.id,
                {
                    "status": "failed",
                    "error_message": (
                        "Blocked: email verification marked this address invalid "
                        f"({getattr(lead, 'email_verification_reason', '') or 'invalid'})."
                    ),
                },
            )
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "email": lead.email,
                "status": "skipped",
                "reason": "invalid_email",
            })
            continue

        state = outreach_repo.get_or_create_state(
            draft.lead_id,
            campaign_filename,
        )
        if _is_state_stopped(state):
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "email": lead.email,
                "status": "skipped",
                "reason": state.status,
            })
            continue

        if suppression_repo.is_suppressed(lead.email):
            outreach_repo.update_draft(
                draft.id,
                {"status": "skipped", "error_message": "suppressed"},
            )
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "email": lead.email,
                "status": "skipped",
                "reason": "suppressed",
            })
            continue

        eligible.append((draft, lead, state))

    start_at = (
        datetime.now().replace(second=0, microsecond=0)
        if mode == "send_now"
        else _next_allowed_send_at(rules)
    )
    slots = _throttled_send_slots(
        len(eligible),
        rules,
        _next_allowed_send_at(rules, start_at),
        rate_per_minute,
    )

    first_scheduled_for = slots[0] if slots else None
    last_scheduled_for = slots[-1] if slots else None

    for (draft, lead, state), scheduled_for in zip(eligible, slots):
        updated = outreach_repo.update_draft(
            draft.id,
            {
                "status": "scheduled",
                "scheduled_for": scheduled_for,
                "error_message": "",
            },
        )
        if not updated:
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "status": "skipped",
                "reason": "update_failed",
            })
            continue

        if not _is_state_stopped(state):
            state.status = "scheduled"
            state.current_touch = max(state.current_touch, draft.touch_number)
            outreach_repo.upsert_state(state)

        _add_activity(
            lead,
            campaign_filename,
            "followup_scheduled" if draft.touch_number > 1 else "scheduled",
            f"Touch {draft.touch_number} scheduled",
            _dt(scheduled_for) or "",
            {
                "draft_id": draft.id,
                "touch_number": draft.touch_number,
                "scheduled_for": _dt(scheduled_for),
            },
        )
        scheduled += 1
        details.append({
            "draft_id": draft.id,
            "lead_id": draft.lead_id,
            "status": "scheduled",
            "scheduled_for": _dt(scheduled_for),
        })

    due_now_ids = [
        detail["draft_id"]
        for detail in details
        if detail.get("status") == "scheduled"
        and detail.get("scheduled_for")
        and datetime.fromisoformat(detail["scheduled_for"]) <= datetime.now()
    ][:rate_per_minute]
    job = None
    if due_now_ids:
        job = job_repo.create(
            "send_drafts",
            {
                "campaign_filename": campaign_filename,
                "draft_ids": due_now_ids,
                "rate_per_minute": rate_per_minute,
            },
            total=len(due_now_ids),
        )

    return {
        "scheduled": scheduled,
        "skipped": skipped,
        "rate_per_minute": rate_per_minute,
        "first_scheduled_for": _dt(first_scheduled_for),
        "last_scheduled_for": _dt(last_scheduled_for),
        "first_time": _dt(first_scheduled_for),
        "last_time": _dt(last_scheduled_for),
        "scheduled_for": _dt(first_scheduled_for),
        "job_id": job["id"] if job else "",
        "message": f"Scheduled {scheduled} emails at {rate_per_minute} per minute.",
        "details": details,
    }


def _approve_schedule_drafts(
    campaign_filename: str,
    request: ApproveScheduleDraftsRequest,
) -> dict:
    requested_ids = list(dict.fromkeys(
        str(draft_id).strip()
        for draft_id in (request.draft_ids or [])
        if str(draft_id).strip()
    ))
    if not requested_ids:
        raise HTTPException(status_code=400, detail="draft_ids are required")

    start_mode = (request.start_mode or "now").strip().lower()
    if start_mode not in {"now", "later"}:
        raise HTTPException(
            status_code=400,
            detail="start_mode must be now or later",
        )

    rate_per_minute = _bulk_send_rate_per_minute(request.rate_per_minute)
    start_at = (
        datetime.utcnow().replace(second=0, microsecond=0)
        if start_mode == "now"
        else _parse_schedule_datetime(request.start_at)
    )

    _, rules = campaign_sequence_repo.ensure_defaults(
        campaign_filename,
        default_steps=[],
    )

    drafts = outreach_repo.get_drafts_by_ids(requested_ids)
    found_ids = {draft.id for draft in drafts}
    scheduled = 0
    skipped_invalid = 0
    skipped_not_eligible = 0
    details: list[dict] = []
    eligible: list[tuple[OutreachDraft, Lead, LeadSequenceState, bool]] = []

    for missing_id in set(requested_ids) - found_ids:
        skipped_not_eligible += 1
        details.append({
            "draft_id": missing_id,
            "status": "skipped",
            "reason": "not_found",
        })

    for draft in drafts:
        if draft.campaign_filename != campaign_filename:
            skipped_not_eligible += 1
            details.append({
                "draft_id": draft.id,
                "status": "skipped",
                "reason": "wrong_campaign",
            })
            continue

        if draft.status not in {"draft", "approved"}:
            skipped_not_eligible += 1
            details.append({
                "draft_id": draft.id,
                "status": "skipped",
                "reason": "not_schedulable",
                "draft_status": draft.status,
            })
            continue

        lead = lead_repo.get_by_id(draft.lead_id)
        if not lead:
            skipped_not_eligible += 1
            details.append({
                "draft_id": draft.id,
                "status": "skipped",
                "reason": "lead_not_found",
            })
            continue

        if not (lead.email or "").strip():
            skipped_not_eligible += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "no_email",
            })
            continue

        if (getattr(lead, "email_verification_status", "") or "").lower() == "invalid":
            outreach_repo.update_draft(
                draft.id,
                {
                    "status": "failed",
                    "error_message": (
                        "Blocked: email verification marked this address invalid "
                        f"({getattr(lead, 'email_verification_reason', '') or 'invalid'})."
                    ),
                },
            )
            skipped_invalid += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "email": lead.email,
                "status": "skipped",
                "reason": "invalid_email",
            })
            continue

        if _email_verification_block_reason(lead) == "risky_email":
            outreach_repo.update_draft(
                draft.id,
                {
                    "status": "failed",
                    "error_message": (
                        "Blocked: email verification marked this address risky "
                        f"({getattr(lead, 'email_verification_reason', '') or 'risky'})."
                    ),
                },
            )
            skipped_invalid += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "email": lead.email,
                "status": "skipped",
                "reason": "risky_email",
            })
            continue

        state = outreach_repo.get_or_create_state(
            draft.lead_id,
            campaign_filename,
        )
        if _is_state_stopped(state):
            skipped_not_eligible += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "email": lead.email,
                "status": "skipped",
                "reason": state.status,
            })
            continue

        if suppression_repo.is_suppressed(lead.email):
            outreach_repo.update_draft(
                draft.id,
                {"status": "skipped", "error_message": "suppressed"},
            )
            skipped_not_eligible += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "email": lead.email,
                "status": "skipped",
                "reason": "suppressed",
            })
            continue

        eligible.append((draft, lead, state, draft.status == "draft"))

    slots = _rate_limited_slots(len(eligible), start_at, rate_per_minute)
    first_scheduled_for = slots[0] if slots else None
    last_scheduled_for = slots[-1] if slots else None

    for (draft, lead, state, needs_approval), scheduled_for in zip(eligible, slots):
        if needs_approval:
            approved = outreach_repo.update_draft(
                draft.id,
                {
                    "status": "approved",
                    "error_message": "",
                },
            )
            if not approved:
                skipped_not_eligible += 1
                details.append({
                    "draft_id": draft.id,
                    "status": "skipped",
                    "reason": "approval_failed",
                })
                continue

        updated = outreach_repo.update_draft(
            draft.id,
            {
                "status": "scheduled",
                "scheduled_for": scheduled_for,
                "error_message": "",
            },
        )
        if not updated:
            skipped_not_eligible += 1
            details.append({
                "draft_id": draft.id,
                "status": "skipped",
                "reason": "update_failed",
            })
            continue

        if needs_approval:
            _add_activity(
                lead,
                campaign_filename,
                "draft_approved",
                f"Touch {draft.touch_number} draft approved",
                "Approved during schedule",
                {"draft_id": draft.id},
            )

        if not _is_state_stopped(state):
            state.status = "scheduled"
            state.current_touch = max(state.current_touch, draft.touch_number)
            outreach_repo.upsert_state(state)

        _add_activity(
            lead,
            campaign_filename,
            "followup_scheduled" if draft.touch_number > 1 else "scheduled",
            f"Touch {draft.touch_number} scheduled",
            _dt(scheduled_for) or "",
            {
                "draft_id": draft.id,
                "touch_number": draft.touch_number,
                "scheduled_for": _dt(scheduled_for),
                "rate_per_minute": rate_per_minute,
            },
        )
        scheduled += 1
        details.append({
            "draft_id": draft.id,
            "lead_id": draft.lead_id,
            "email": lead.email,
            "status": "scheduled",
            "scheduled_for": _dt(scheduled_for),
            "touch_number": draft.touch_number,
        })

    due_now_ids = [
        detail["draft_id"]
        for detail in details
        if detail.get("status") == "scheduled"
        and detail.get("scheduled_for")
        and datetime.fromisoformat(detail["scheduled_for"]) <= datetime.utcnow()
    ][:rate_per_minute]

    job = None
    if due_now_ids:
        job = job_repo.create(
            "send_drafts",
            {
                "campaign_filename": campaign_filename,
                "draft_ids": due_now_ids,
                "rate_per_minute": rate_per_minute,
            },
            total=len(due_now_ids),
        )

    return {
        "scheduled": scheduled,
        "skipped_invalid": skipped_invalid,
        "skipped_not_eligible": skipped_not_eligible,
        "skipped": skipped_invalid + skipped_not_eligible,
        "rate_per_minute": rate_per_minute,
        "first_scheduled_for": _dt(first_scheduled_for),
        "last_scheduled_for": _dt(last_scheduled_for),
        "job_id": job["id"] if job else "",
        "message": f"Scheduled {scheduled} emails. Sending will start automatically.",
        "details": details,
    }


def _defer_draft_send(
    lead: Lead,
    draft: OutreachDraft,
    reason: str,
    details: list[dict],
) -> None:
    """
    Record a send-policy deferral without changing the draft status.

    Important: the draft remains approved so it can be retried later
    when the daily cap/window/domain policy allows it.
    """
    _add_activity(
        lead,
        draft.campaign_filename,
        "deferred",
        f"Touch {draft.touch_number} send deferred",
        reason,
        {
            "draft_id": draft.id,
            "email": lead.email,
            "touch_number": draft.touch_number,
        },
    )
    details.append({
        "draft_id": draft.id,
        "lead_id": lead.id,
        "email": lead.email,
        "status": "deferred",
        "reason": reason,
        "touch_number": draft.touch_number,
    })


def _defer_remaining_policy_drafts(
    drafts: list[OutreachDraft],
    current_index: int,
    reason: str,
    details: list[dict],
) -> int:
    """
    Defer remaining approved drafts in this batch after a global stop reason.

    Used for:
    - Daily cap reached
    - Outside send window

    Returns how many draft items were deferred.
    """
    deferred = 0

    for remaining_draft in drafts[current_index + 1:]:
        if remaining_draft.status != "approved":
            continue

        remaining_lead = lead_repo.get_by_id(remaining_draft.lead_id)
        if not remaining_lead or not remaining_lead.email:
            continue

        _defer_draft_send(
            remaining_lead,
            remaining_draft,
            reason,
            details,
        )
        deferred += 1

    return deferred


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

    for draft_index, draft in enumerate(drafts):

        lead = lead_repo.get_by_id(draft.lead_id)
        if not lead:
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "status": "skipped",
                "reason": "lead_not_found",
            })
            continue
        if lead and (getattr(lead, "email_verification_status", "") or "").lower() == "invalid":
            outreach_repo.update_draft(
                draft.id,
                {
                    "status": "failed",
                    "error_message": (
                        "Blocked: email verification marked this address invalid "
                        f"({getattr(lead, 'email_verification_reason', '') or 'invalid'})."
                    ),
                },
            )
            details.append(
                {
                    "draft_id": draft.id,
                    "status": "failed",
                    "reason": "invalid_email",
                    "message": "Email verification marked this address invalid.",
                }
            )
            failed += 1
            continue
        if draft.status == "scheduled":
            if not draft.scheduled_for or draft.scheduled_for > datetime.utcnow():
                skipped += 1
                details.append({
                    "draft_id": draft.id,
                    "lead_id": lead.id,
                    "status": "skipped",
                    "reason": "scheduled_not_due",
                    "scheduled_for": _dt(draft.scheduled_for),
                })
                continue
        elif draft.status != "approved":
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
            default_steps=[],
        )
        already_sent = outreach_repo.count_sent_today(draft.campaign_filename)
        already_sent += sent_by_campaign.get(draft.campaign_filename, 0)
        campaign_daily_limit_enabled = (
            os.getenv("CAMPAIGN_DAILY_LIMIT_ENABLED", "false").strip().lower() == "true"
        )
        if campaign_daily_limit_enabled and already_sent >= rules.daily_send_limit:
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

        if suppression_repo.is_suppressed(lead.email):
            outreach_repo.update_draft(
                draft.id,
                {"status": "skipped", "error_message": "suppressed"},
            )
            _add_activity(
                lead,
                draft.campaign_filename,
                "suppressed",
                "Draft skipped: suppressed",
                "Email is globally suppressed",
                {"draft_id": draft.id, "email": lead.email},
            )
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "email": lead.email,
                "status": "skipped",
                "reason": "suppressed",
            })
            continue

        allowed, policy_reason = SendPolicy().check(
            lead.email,
            draft.campaign_filename,
        )

        if not allowed:
            skipped += 1
            _defer_draft_send(
                lead,
                draft,
                policy_reason,
                details,
            )

            if policy_reason.startswith("Daily cap") or (
                policy_reason == "Outside send window" and _send_window_enabled()
            ):
                skipped += _defer_remaining_policy_drafts(
                    drafts,
                    draft_index,
                    policy_reason,
                    details,
                )
                messages.append(policy_reason)
                break

            continue

        if sent_by_campaign.get(draft.campaign_filename, 0) > 0:
            import time as time_module

            time_module.sleep(next_send_delay_seconds())

        claimed = outreach_repo.acquire_sendable_draft(draft.id)
        if not claimed:
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "already_claimed_or_not_due",
                "scheduled_for": _dt(draft.scheduled_for),
            })
            continue
        draft = claimed

        lead = lead_repo.get_by_id(draft.lead_id)
        if not lead:
            outreach_repo.update_draft(
                draft.id,
                {"status": "skipped", "error_message": "lead_not_found"},
            )
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "status": "skipped",
                "reason": "lead_not_found_after_claim",
            })
            continue

        if not lead.email:
            outreach_repo.update_draft(
                draft.id,
                {"status": "skipped", "error_message": "no_email"},
            )
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": "no_email_after_claim",
            })
            continue

        if (getattr(lead, "email_verification_status", "") or "").lower() == "invalid":
            outreach_repo.update_draft(
                draft.id,
                {
                    "status": "failed",
                    "error_message": (
                        "Blocked before send: email verification marked this address invalid "
                        f"({getattr(lead, 'email_verification_reason', '') or 'invalid'})."
                    ),
                },
            )
            failed += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "failed",
                "reason": "invalid_email_after_claim",
            })
            continue

        if _email_verification_block_reason(lead) == "risky_email":
            outreach_repo.update_draft(
                draft.id,
                {
                    "status": "failed",
                    "error_message": (
                        "Blocked before send: email verification marked this address risky "
                        f"({getattr(lead, 'email_verification_reason', '') or 'risky'})."
                    ),
                },
            )
            failed += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "failed",
                "reason": "risky_email_after_claim",
            })
            continue

        state = outreach_repo.get_or_create_state(
            lead.id,
            draft.campaign_filename,
        )
        if _is_state_stopped(state):
            outreach_repo.update_draft(
                draft.id,
                {"status": "skipped", "error_message": state.status},
            )
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "status": "skipped",
                "reason": state.status,
            })
            continue

        if suppression_repo.is_suppressed(lead.email):
            outreach_repo.update_draft(
                draft.id,
                {"status": "skipped", "error_message": "suppressed"},
            )
            skipped += 1
            details.append({
                "draft_id": draft.id,
                "lead_id": lead.id,
                "email": lead.email,
                "status": "skipped",
                "reason": "suppressed_after_claim",
            })
            continue
        try:
            send_body, one_click_url = _with_unsubscribe_footer(
                draft.body,
                lead.id,
                lead.email,
            )
            sender_identity = _campaign_sender_identity(draft.campaign_filename)

            success, error = send_via_graph(
                lead.email,
                draft.subject,
                send_body,
                [
                    {
                        "name": "X-List-Unsubscribe",
                        "value": f"<{one_click_url}>",
                    },
                    {
                        "name": "X-List-Unsubscribe-Post",
                        "value": "List-Unsubscribe=One-Click",
                    },
                ],
                sender_email=sender_identity["sender_email"],
                reply_to_email=sender_identity["reply_to_email"],
            )
        except Exception as exc:
            success, error = False, str(exc)
        if success:
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
            send_log_repo.record(
                lead.id,
                draft.campaign_filename,
                lead.email,
                draft.touch_number,
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
            error = error or "Graph API send failed"
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
            if _is_transient_graph_error(error):
                retry_at = datetime.utcnow() + timedelta(
                    minutes=_graph_retry_delay_minutes(),
                )
                outreach_repo.update_draft(
                    draft.id,
                    {
                        "status": "scheduled",
                        "scheduled_for": retry_at,
                        "error_message": (
                            "Deferred after transient Graph error: "
                            f"{error}"
                        ),
                    },
                )
                state.status = "scheduled"
                state.current_touch = max(state.current_touch, draft.touch_number)
                outreach_repo.upsert_state(state)
                _set_lead_sequence_columns(lead.id, "scheduled", error)
                _add_activity(
                    lead,
                    draft.campaign_filename,
                    "send_deferred",
                    "Send deferred after transient Graph error",
                    _dt(retry_at) or "",
                    {
                        "draft_id": draft.id,
                        "touch_number": draft.touch_number,
                        "reason": error,
                        "retry_at": _dt(retry_at),
                    },
                )
                skipped += 1
                details.append({
                    "draft_id": draft.id,
                    "lead_id": lead.id,
                    "email": lead.email,
                    "status": "deferred",
                    "reason": "transient_graph_error",
                    "message": error,
                    "retry_at": _dt(retry_at),
                })
                continue
            outreach_repo.update_draft(
                draft.id,
                {"status": "failed", "error_message": error},
            )
            if invalid_recipient:
                suppression_repo.add(
                    lead.email,
                    "bounced",
                    lead.id,
                    draft.campaign_filename,
                )
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


def _stop_sequence(
    lead_id: str,
    campaign_filename: str,
    status: str,
    reason: str,
) -> dict:
    lead = lead_repo.get_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    state = outreach_repo.get_or_create_state(lead_id, campaign_filename)
    state.status = status
    state.stop_reason = reason or status
    state.completed_at = datetime.utcnow()
    state.next_touch_due_at = None
    outreach_repo.upsert_state(state)
    skipped = outreach_repo.mark_future_pending_skipped(
        lead_id,
        campaign_filename,
        reason or status,
    )
    lead_repo.update_sequence_status(lead_id, status, reason or status)
    _add_activity(
        lead,
        campaign_filename,
        status,
        f"Lead marked {status.replace('_', ' ')}",
        reason or "",
        {"skipped_pending_drafts": skipped},
    )
    return {
        "updated": True,
        "lead_id": lead_id,
        "campaign_filename": campaign_filename,
        "status": status,
        "skipped_pending_drafts": skipped,
    }


def _mark_lead_sequence_status(
    lead_id: str,
    request: ManualLeadStatusRequest,
    status: str,
) -> dict:
    campaign_filename = request.campaign_filename
    reason = request.reason or status
    result = _stop_sequence(lead_id, campaign_filename, status, reason)
    lead = lead_repo.get_by_id(lead_id)
    if lead and lead.email:
        suppression_reason = {
            "bounced": "bounced",
            "unsubscribed": "unsubscribed",
            "do_not_contact": "manual",
        }.get(status)
        if suppression_reason:
            suppression_repo.add(
                lead.email,
                suppression_reason,
                lead.id,
                campaign_filename,
            )
    return result

__all__ = [name for name in globals() if not name.startswith("__")]
