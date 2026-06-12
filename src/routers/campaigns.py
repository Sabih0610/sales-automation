from fastapi import APIRouter

from src.api_helpers import *


router = APIRouter()


@router.get("/api/dashboard/summary")
def get_dashboard_summary() -> dict:
    policy = SendPolicy().status()
    campaigns = campaign_repo.list_all()
    return {
        "totals": {
            "leads": lead_repo.count_all(),
            "sent_today": send_log_repo.count_today(),
            "todays_cap": policy.get("todays_cap", 0),
            "replies_total": outreach_repo.count_states_by_status("replied"),
            "active_campaigns": len(campaigns),
        },
        "recent_activities": outreach_repo.recent_activities(15),
        "due_today_total": sum(
            len(outreach_repo.due_items(c["filename"], None, None))
            for c in campaigns
        ),
    }


@router.get("/api/campaigns/{campaign_filename}/runs")
def get_campaign_runs(campaign_filename: str) -> list[dict]:
    runs = _campaign_runs(campaign_filename)
    return [
        {
            "id": run.id,
            "label": _run_label(run),
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

@router.get("/api/campaigns/{campaign_filename}/overview")
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

    counts = outreach_repo.campaign_overview_counts(campaign_filename)
    draft_counts = counts["draft_counts"]
    drafts_generated = counts["drafts_generated"]
    drafted_unique = counts["drafted_unique"]
    approved_unique = counts["approved_unique"]
    sent_unique = counts["sent_unique"]
    state_counts = counts["state_counts"]
    active_sequence_steps = len(_active_steps(campaign_filename))
    approved_drafts = draft_counts.get("approved", 0)
    scheduled = (
        draft_counts.get("scheduled", 0)
        + draft_counts.get("approved", 0)
    )
    emails_sent = draft_counts.get("sent", 0)
    followups_due = len(outreach_repo.due_items(campaign_filename))
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

@router.get("/api/campaigns/{campaign_filename}/leads")
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

@router.get("/api/campaigns/{campaign_filename}/activities")
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

@router.get("/api/campaigns/{campaign_filename}/export-zoominfo")
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

@router.post("/api/campaigns/{campaign_filename}/upload-enriched")
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
                    if not (lead.email or "").strip():
                        lead_repo.mark_duplicate_if_any(
                            lead.id,
                            campaign_filename,
                        )
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

@router.get("/api/campaigns/{campaign_filename}/sequence-settings")
def get_campaign_sequence_settings(campaign_filename: str) -> dict:
    return _load_sequence_settings(campaign_filename)

@router.post("/api/campaigns/{campaign_filename}/sequence-settings")
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

@router.post("/api/campaigns")
def create_campaign(request: CreateCampaignRequest) -> dict:
    """Create a new campaign in the local SQLite database."""
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Campaign name is required")

    config = request.model_dump(exclude={"name", "description"})
    try:
        campaign = campaign_repo.create(
            request.name.strip(),
            request.description,
            config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "created": True,
        "filename": campaign["filename"],
        "name": campaign["name"],
    }

@router.get("/api/campaigns")
def list_campaigns() -> list[dict]:
    return campaign_repo.list_all()
