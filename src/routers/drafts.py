from fastapi import APIRouter

from src.api_helpers import *


router = APIRouter()


@router.get("/api/campaigns/{campaign_filename}/drafts")
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

@router.post("/api/campaigns/{campaign_filename}/drafts/generate")
def generate_campaign_drafts(
    campaign_filename: str,
    request: GenerateDraftsRequest,
) -> dict:
    if not request.lead_ids:
        raise HTTPException(status_code=400, detail="lead_ids are required")
    _validate_generate_drafts_for_leads(campaign_filename, request.touch_number)
    job = job_repo.create(
        "generate_campaign_drafts",
        {
            "campaign_filename": campaign_filename,
            "lead_ids": request.lead_ids,
            "touch_number": request.touch_number,
            "overwrite": request.overwrite,
        },
        total=len(request.lead_ids),
    )
    return _queued_job_response(job)

@router.put("/api/drafts/{draft_id}")
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

@router.post("/api/drafts/{draft_id}/approve")
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

@router.post("/api/drafts/approve-selected")
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

@router.post("/api/drafts/{draft_id}/skip")
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

@router.post("/api/drafts/send-selected")
def send_selected_outreach_drafts(
    request: SendSelectedDraftsRequest,
) -> dict:
    if not request.draft_ids:
        raise HTTPException(status_code=400, detail="draft_ids are required")
    job = job_repo.create(
        "send_selected_drafts",
        {"draft_ids": request.draft_ids},
        total=len(request.draft_ids),
    )
    return _queued_job_response(job)

@router.post("/api/drafts/{draft_id}/send-test")
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
    test_subject = f"[TEST COPY] {draft.subject}"
    test_body = (
        "TEST COPY\n"
        f"Original lead: {lead.full_name if lead else draft.lead_id}\n"
        f"Original recipient: {lead.email if lead else ''}\n\n"
        "----\n\n"
        f"{draft.body}"
    )
    success, error = send_via_graph(
        test_email,
        test_subject,
        test_body,
    )
    _add_activity(
        lead,
        draft.campaign_filename,
        "test_sent" if success else "failed",
        "Test copy sent" if success else "Test copy failed",
        error,
        {"draft_id": draft.id, "test_email": test_email},
    )
    return {
        "success": bool(success),
        "error": error,
        "to": test_email,
    }
