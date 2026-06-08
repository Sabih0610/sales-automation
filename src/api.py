##src\api.py

import asyncio
import csv, io
import json as _json
import os
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi import UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src import orchestrator as orchestrator_module
from src.agents.email_agent import EmailAgent
from src.config import settings
from src.models import AgentEvent, Lead, Optional, PipelineRun
from src.personalisation.knowledge_base import KnowledgeBaseLoader
from src.personalisation.orchestrator import PersonalisationOrchestrator
from src.storage import db, event_repo, lead_repo, run_repo


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
    title: str
    company: str
    email: str
    email_confidence: str
    segment: str
    intent_score: float
    linkedin_url: str
    status: str


class PersonaliseRequest(BaseModel):
    campaign: str


class SendEmailRequest(BaseModel):
    run_id: str
    day: int = 0


class SequenceSendRequest(BaseModel):
    campaign: str = ""


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
        title=lead.title,
        company=lead.company,
        email=lead.email,
        email_confidence=lead.email_confidence,
        segment=lead.segment.value,
        intent_score=lead.intent_score,
        linkedin_url=lead.linkedin_url,
        status=lead.status.value,
    )


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
    return {
        "message": "Enrichment import complete",
        "total_rows_in_file": len(rows),
        **result
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
def send_emails(run_id: str) -> dict:
    """
    Trigger email sequence for a run's leads.
    Automatically determines which day each lead should receive.
    Only sends to leads that have been personalised.
    """
    run = run_repo.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    leads = lead_repo.get_by_run(run_id)
    if not leads:
        raise HTTPException(status_code=404, detail="No leads found")

    agent = EmailAgent(run, leads)
    agent.on_event(lambda event: event_repo.save(event))
    agent.execute()

    return {
        "message": "Email sequence run complete",
        "total_leads": len(leads),
        "sent": agent.sent_count,
        "skipped": agent.skipped_count,
        "failed": agent.failed_count,
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
        SELECT id, full_name, email, title, company,
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

    from datetime import datetime

    def days_since(iso_str):
        if not iso_str:
            return 999
        try:
            return (datetime.utcnow() - datetime.fromisoformat(iso_str)).days
        except Exception:
            return 999

    previews = []
    for row in rows:
        day1 = row["day1_sent_at"] or ""
        day3 = row["day3_sent_at"] or ""
        day7 = row["day7_sent_at"] or ""

        day_due = None
        if not day1:
            day_due = 1
        elif not day3 and days_since(day1) >= 3:
            day_due = 3
        elif not day7 and days_since(day3) >= 4:
            day_due = 7

        if not day_due:
            continue

        subject = row["email_subject"] or ""
        if day_due == 3:
            subject = f"Re: {subject}"
        elif day_due == 7:
            subject = f"Following up - {subject}"

        previews.append({
            "lead_id": row["id"],
            "full_name": row["full_name"],
            "email": row["email"],
            "title": row["title"],
            "company": row["company"],
            "day_due": day_due,
            "email_subject": subject,
            "email_body": row["email_body"] or "",
            "linkedin_message": row["linkedin_message"] or "",
        })

    return previews


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

    from datetime import datetime

    def days_since(iso_str):
        if not iso_str:
            return 999
        try:
            return (datetime.utcnow() - datetime.fromisoformat(iso_str)).days
        except Exception:
            return 999

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

    if not day1:
        day_to_send = 1
    elif not day3 and days_since(day1) >= 3:
        day_to_send = 3
    elif not day7 and days_since(day3) >= 4:
        day_to_send = 7
    else:
        raise HTTPException(
            status_code=400,
            detail="No email due today for this lead.",
        )

    if day_to_send == 3:
        send_subject = f"Re: {subject}"
    elif day_to_send == 7:
        send_subject = f"Following up - {subject}"
    else:
        send_subject = subject

    from src.models import Lead as _Lead, LeadStatus, Segment

    lead_obj = _Lead(
        id=row["id"],
        full_name=row["full_name"] or "",
        email=row["email"] or "",
        status=LeadStatus.ENRICHED,
        segment=Segment.COLD,
    )

    agent = EmailAgent(run, [lead_obj])
    success = agent._send_email(row["email"], send_subject, body)

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Microsoft Graph API send failed. Check Azure credentials."
        )

    day_col = f"day{day_to_send}_sent_at"
    new_status = "complete" if day_to_send == 7 else f"day{day_to_send}_sent"
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
    run = run_repo.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    personalisation_orchestrator = PersonalisationOrchestrator()
    return personalisation_orchestrator.run(
        run_id=run_id,
        campaign_name=request.campaign,
    )


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
