import asyncio

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src import orchestrator as orchestrator_module
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
    phone: str
    email: str
    email_confidence: str
    location: str
    segment: str
    intent_score: float
    linkedin_url: str
    status: str
    email_subject: str = ""
    email_body: str = ""
    linkedin_message: str = ""
    research_summary: str = ""
    campaign_name: str = ""


class PersonaliseRequest(BaseModel):
    campaign: str


PERSONALISATION_FIELDS = [
    "email_subject",
    "email_body",
    "linkedin_message",
    "research_summary",
    "campaign_name",
]


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
        phone=lead.phone,
        email=lead.email,
        email_confidence=lead.email_confidence,
        location=lead.location,
        segment=lead.segment.value,
        intent_score=lead.intent_score,
        linkedin_url=lead.linkedin_url,
        status=lead.status.value,
        email_subject=getattr(lead, "email_subject", ""),
        email_body=getattr(lead, "email_body", ""),
        linkedin_message=getattr(lead, "linkedin_message", ""),
        research_summary=getattr(lead, "research_summary", ""),
        campaign_name=getattr(lead, "campaign_name", ""),
    )


def _attach_personalisation_fields(run_id: str, leads: list[Lead]) -> None:
    if not leads:
        return
    conn = db._conn()
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(leads)").fetchall()
    }
    if not set(PERSONALISATION_FIELDS).issubset(existing):
        return
    columns = ", ".join(PERSONALISATION_FIELDS)
    rows = conn.execute(
        f"SELECT id, {columns} FROM leads WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    for lead in leads:
        row = by_id.get(lead.id)
        if not row:
            continue
        for field in PERSONALISATION_FIELDS:
            setattr(lead, field, row[field] or "")


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
    _attach_personalisation_fields(run_id, leads)
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


@app.get("/api/status")
def get_status() -> dict:
    return orchestrator.get_status()


@app.post("/api/runs/{run_id}/personalise")
def personalise_run(run_id: str, request: PersonaliseRequest) -> dict:
    """Trigger Phase 2 personalisation for a run's leads."""
    run = run_repo.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    orchestrator = PersonalisationOrchestrator()
    result = orchestrator.run(
        run_id=run_id,
        campaign_name=request.campaign,
    )
    return result


@app.get("/api/campaigns")
def list_campaigns() -> list[dict]:
    """Return all available campaigns."""
    return KnowledgeBaseLoader.list_campaigns()


@app.get("/api/knowledge-bases")
def list_knowledge_bases() -> list[str]:
    """Return all available KB files."""
    return KnowledgeBaseLoader.list_kb_files()


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
