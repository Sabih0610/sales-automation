from fastapi import APIRouter

from src.api_helpers import *


router = APIRouter()


@router.post("/api/campaigns/{campaign_filename}/queue/send-selected")
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
    job = job_repo.create(
        "send_selected_drafts",
        {
            "draft_ids": request.draft_ids,
            "campaign_filename": campaign_filename,
        },
        total=len(request.draft_ids),
    )
    return _queued_job_response(job)

@router.get("/api/campaigns/{campaign_filename}/queue")
def get_campaign_queue(campaign_filename: str) -> dict:
    due_today = [
        item for item in outreach_repo.due_items(campaign_filename)
        if not item.get("draft_id")
    ]
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

    grouped["waiting"] = outreach_repo.queue_waiting_items(campaign_filename)
    for row in grouped["waiting"]:
        row["due_label"] = "Waiting follow-up"
    grouped["skipped"].extend(
        outreach_repo.queue_stopped_items(campaign_filename)
    )
    return grouped

@router.post("/api/campaigns/{campaign_filename}/queue/generate-due")
def generate_due_campaign_drafts(
    campaign_filename: str,
    request: QueueGenerateDueRequest,
) -> dict:
    due = outreach_repo.due_items(
        campaign_filename,
        lead_ids=request.lead_ids or None,
        touch_number=request.touch_number,
    )
    due = [item for item in due if not item.get("draft_id")]
    job = job_repo.create(
        "generate_due_drafts",
        {
            "campaign_filename": campaign_filename,
            "lead_ids": request.lead_ids,
            "touch_number": request.touch_number,
            "due_items": due,
        },
        total=len(due),
    )
    return _queued_job_response(job)
