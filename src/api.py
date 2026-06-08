##src\api.py

import asyncio
import csv, io
import json
import json as _json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi import UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src import orchestrator as orchestrator_module
from src.agents.email_agent import EmailAgent
from src.agents.segment_agent import SegmentAgent
from src.config import settings
from src.models import AgentEvent, Lead, PipelineRun
from src.personalisation.knowledge_base import KnowledgeBaseLoader
from src.personalisation.orchestrator import PersonalisationOrchestrator
from src.storage import db, event_repo, lead_repo, run_repo


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
    delay_days: int
    subject_template: str = ""
    email_body_template: str = ""
    linkedin_message_template: str = ""


class SequenceSettingsRequest(BaseModel):
    touches: list[SequenceTouchRequest]


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
                "subject_template": "{{company}} + quick idea",
                "email_body_template": (
                    "Hi {{first_name}},\n\n"
                    "I noticed your work at {{company}} and thought this "
                    "may be relevant.\n\n"
                    "{{campaign_value_prop}}\n\n"
                    "Would a quick conversation make sense?\n\n"
                    "Best,\n{{sender_name}}"
                ),
                "linkedin_message_template": (
                    "Hi {{first_name}}, noticed your work at {{company}}. "
                    "Happy to connect."
                ),
            },
            {
                "number": 2,
                "name": "Follow-up",
                "delay_days": 3,
                "subject_template": "Re: {{touch1_subject}}",
                "email_body_template": (
                    "Hi {{first_name}},\n\n"
                    "Just following up on my note about {{company}}.\n\n"
                    "Would a short conversation make sense?\n\n"
                    "Best,\n{{sender_name}}"
                ),
                "linkedin_message_template": (
                    "Hi {{first_name}}, following up here as well. "
                    "Happy to share a quick idea if relevant."
                ),
            },
            {
                "number": 3,
                "name": "Final touch",
                "delay_days": 4,
                "subject_template": "Following up - {{company}}",
                "email_body_template": (
                    "Hi {{first_name}},\n\n"
                    "I do not want to keep filling your inbox, so I will "
                    "make this my final follow-up.\n\n"
                    "Should I close the loop for now, or would you be open "
                    "to a quick discussion?\n\n"
                    "Best,\n{{sender_name}}"
                ),
                "linkedin_message_template": (
                    "Hi {{first_name}}, final follow-up from my side. "
                    "Happy to connect if this is relevant."
                ),
            },
        ]
    }


def _load_sequence_settings(campaign_filename: str) -> dict:
    seq_path = Path("campaigns/sequences.json")
    default = _default_sequence_settings()

    if not seq_path.exists():
        return default

    try:
        all_settings = json.loads(seq_path.read_text(encoding="utf-8"))
        return all_settings.get(campaign_filename, default)
    except Exception:
        return default


def _save_sequence_settings(campaign_filename: str, settings: dict) -> None:
    seq_path = Path("campaigns/sequences.json")
    seq_path.parent.mkdir(parents=True, exist_ok=True)

    all_settings = {}
    if seq_path.exists():
        try:
            all_settings = json.loads(seq_path.read_text(encoding="utf-8"))
        except Exception:
            all_settings = {}

    all_settings[campaign_filename] = settings
    seq_path.write_text(json.dumps(all_settings, indent=2), encoding="utf-8")


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
    for lead in leads:
        writer.writerow({
            "First Name": lead.first_name,
            "Last Name": lead.last_name,
            "Company Name": lead.company,
            "LinkedIn URL": lead.linkedin_url,
            "Location": lead.location,
            "Job Title": lead.title,
        })

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


def _campaign_leads(campaign_filename: str) -> list[Lead]:
    leads = []
    for run_id in _campaign_run_ids(campaign_filename):
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
    settings_data = _load_sequence_settings(campaign_filename)
    touch2_delay = _sequence_delay(settings_data, 2, 3)
    touch3_delay = _sequence_delay(settings_data, 3, 4)

    from datetime import datetime

    def days_since(value: str) -> int:
        if not value:
            return 999
        try:
            return (datetime.utcnow() - datetime.fromisoformat(value)).days
        except Exception:
            return 999

    total_leads = len(rows)
    with_email = 0
    no_email = 0
    drafts_generated = 0
    emails_sent = 0
    followups_due = 0
    replies = 0
    completed = 0

    for row in rows:
        email = row.get("email", "") or ""
        segment = row.get("segment", "") or ""
        subject = row.get("email_subject", "") or ""
        body = row.get("email_body", "") or ""
        status = row.get("email_sequence_status", "") or ""
        day1 = row.get("day1_sent_at", "") or ""
        day3 = row.get("day3_sent_at", "") or ""
        day7 = row.get("day7_sent_at", "") or ""
        has_draft = bool(subject or body)

        if email:
            with_email += 1
        if not email or segment == "NO_EMAIL":
            no_email += 1
        if has_draft:
            drafts_generated += 1
        if status in ("day1_sent", "day3_sent", "day7_sent", "complete") or day1 or day3 or day7:
            emails_sent += 1
        if status == "replied":
            replies += 1
        if status == "complete" or day7:
            completed += 1
        if (
            email
            and has_draft
            and status not in {"replied", "unsubscribed", "complete"}
        ):
            if day1 and not day3 and days_since(day1) >= touch2_delay:
                followups_due += 1
            elif day3 and not day7 and days_since(day3) >= touch3_delay:
                followups_due += 1

    return {
        "campaign_filename": campaign_filename,
        "total_leads": total_leads,
        "with_email": with_email,
        "no_email": no_email,
        "drafts_generated": drafts_generated,
        "emails_sent": emails_sent,
        "followups_due": followups_due,
        "replies": replies,
        "completed": completed,
        "total_runs": len(runs),
        "runs": runs,
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
def get_campaign_drafts(campaign_filename: str) -> list[dict]:
    rows = _campaign_lead_rows(
        campaign_filename,
        limit=None,
        drafts_only=True,
    )
    return [_campaign_draft_payload(row) for row in rows]


@app.get("/api/campaigns/{campaign_filename}/export-zoominfo")
def export_campaign_for_zoominfo(campaign_filename: str):
    from fastapi.responses import StreamingResponse

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "First Name",
        "Last Name",
        "Full Name",
        "Company Name",
        "Job Title",
        "LinkedIn URL",
        "Company LinkedIn URL",
        "Location",
        "Run ID",
        "Lead ID",
    ])
    for lead in _campaign_leads(campaign_filename):
        first_name = lead.first_name
        last_name = lead.last_name
        if not first_name and lead.full_name:
            parts = lead.full_name.split()
            first_name = parts[0]
            last_name = " ".join(parts[1:])
        writer.writerow([
            first_name,
            last_name,
            lead.full_name,
            lead.company,
            lead.title,
            lead.linkedin_url,
            lead.company_linkedin_url,
            lead.location,
            getattr(lead, "run_id", "") or "",
            lead.id,
        ])
    output.seek(0)
    safe_name = campaign_filename.replace(".json", "")
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
    if not rows:
        return {
            "total_rows": 0,
            "matched": 0,
            "updated": 0,
            "unmatched": 0,
            "errors": [],
        }

    leads = _campaign_leads(campaign_filename)
    by_id = {lead.id: lead for lead in leads}
    by_linkedin = {
        _norm_url(lead.linkedin_url): lead
        for lead in leads
        if lead.linkedin_url
    }
    by_email = {
        (lead.email or "").strip().lower(): lead
        for lead in leads
        if lead.email
    }
    by_name_company = {
        _norm_name_company(lead.full_name, lead.company): lead
        for lead in leads
        if lead.full_name and lead.company
    }

    matched = 0
    updated = 0
    unmatched = 0
    errors = []
    affected_runs: set[str] = set()

    from datetime import datetime
    import re

    with db._conn() as conn:
        for idx, row in enumerate(rows, start=2):
            lead_id = _row_value(row, "Lead ID", "lead_id", "id")
            linkedin = _norm_url(_row_value(
                row,
                "LinkedIn URL",
                "Person LinkedIn URL",
                "LinkedIn",
                "linkedin_url",
            ))
            email = _row_value(
                row,
                "Email Address",
                "Email",
                "email",
                "Work Email",
            )
            full_name = _row_value(row, "Full Name", "Name", "full_name")
            company = _row_value(
                row,
                "Company Name",
                "Company",
                "company",
            )

            lead = None
            if lead_id:
                lead = by_id.get(lead_id)
            if not lead and linkedin:
                lead = by_linkedin.get(linkedin)
            if not lead and email:
                lead = by_email.get(email.strip().lower())
            if not lead and full_name and company:
                lead = by_name_company.get(_norm_name_company(
                    full_name,
                    company,
                ))

            if not lead:
                unmatched += 1
                continue

            matched += 1
            updates = []
            params = []

            phone = _row_value(
                row,
                "Direct Phone Number",
                "Mobile Phone",
                "Phone",
                "Company Phone",
                "phone",
            )
            domain = _row_value(
                row,
                "Company Website",
                "Company Domain",
                "Website",
                "company_domain",
            )
            title = _row_value(row, "Job Title", "Title", "title")
            location = _split_location(row)
            company_linkedin = _row_value(
                row,
                "Company LinkedIn URL",
                "Company LinkedIn",
                "company_linkedin_url",
            )

            if domain:
                domain = re.sub(
                    r"https?://(www\.)?",
                    "",
                    domain,
                    flags=re.IGNORECASE,
                ).rstrip("/")

            if email:
                updates.extend(["email = ?", "email_confidence = ?"])
                params.extend([email, "zoominfo_verified"])
                lead.email = email
                lead.email_confidence = "zoominfo_verified"
            if phone:
                updates.append("phone = ?")
                params.append(phone)
                lead.phone = phone
            if domain:
                updates.append("company_domain = ?")
                params.append(domain)
                lead.company_domain = domain
            if title and not lead.title:
                updates.append("title = ?")
                params.append(title)
                lead.title = title
            if location and not lead.location:
                updates.append("location = ?")
                params.append(location)
                lead.location = location
            if linkedin and not lead.linkedin_url:
                updates.append("linkedin_url = ?")
                params.append(linkedin)
                lead.linkedin_url = linkedin
            if company_linkedin and not lead.company_linkedin_url:
                updates.append("company_linkedin_url = ?")
                params.append(company_linkedin)
                lead.company_linkedin_url = company_linkedin

            if not updates:
                continue

            updates.append("updated_at = ?")
            params.append(datetime.utcnow().isoformat())
            params.extend([lead.id, getattr(lead, "run_id", "")])
            try:
                conn.execute(
                    f"""
                    UPDATE leads
                    SET {", ".join(updates)}
                    WHERE id = ? AND run_id = ?
                    """,
                    params,
                )
                updated += 1
                affected_runs.add(getattr(lead, "run_id", ""))
            except Exception as exc:
                errors.append(f"Row {idx}: {exc}")

    _update_segments_for_runs({run_id for run_id in affected_runs if run_id})

    return {
        "total_rows": len(rows),
        "matched": matched,
        "updated": updated,
        "unmatched": unmatched,
        "errors": errors,
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
    for touch in request.touches:
        if touch.delay_days < 0:
            raise HTTPException(
                status_code=400,
                detail="delay_days cannot be negative",
            )
        if touch.number > 1 and touch.delay_days < 1:
            raise HTTPException(
                status_code=400,
                detail="Follow-up delay_days must be at least 1",
            )
        if hasattr(touch, "model_dump"):
            touches.append(touch.model_dump())
        else:
            touches.append(touch.dict())
    _save_sequence_settings(campaign_filename, {"touches": touches})
    return {"saved": True, "campaign": campaign_filename}


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
