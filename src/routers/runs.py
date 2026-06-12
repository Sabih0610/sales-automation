from fastapi import APIRouter

from src.api_helpers import *


router = APIRouter()


@router.post("/api/runs/start", response_model=RunResponse)
def start_pipeline(request: StartPipelineRequest) -> RunResponse:
    settings.max_leads = request.max_leads
    try:
        run = orchestrator.start_pipeline(_filters(request))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run_repo.save(run)
    return _run_response(run)

@router.get("/api/runs", response_model=list[RunResponse])
def list_runs() -> list[RunResponse]:
    return [_run_response(run) for run in run_repo.list_all()]

@router.get("/api/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> RunResponse:
    run = run_repo.get(run_id)
    if run is None:
        active_run = orchestrator.get_active_run()
        if active_run and active_run.id == run_id:
            run = active_run
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_response(run)

@router.get("/api/runs/{run_id}/events")
def get_run_events(run_id: str, limit: int = Query(default=50, ge=1)) -> list[dict]:
    return event_repo.get_by_run(run_id, limit=limit)

@router.get("/api/runs/{run_id}/leads", response_model=list[LeadResponse])
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

@router.get("/api/runs/{run_id}/leads/export")
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

@router.get("/api/runs/{run_id}/leads/download-for-zoominfo")
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

@router.post("/api/runs/{run_id}/leads/upload-enriched")
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
