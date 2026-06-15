from datetime import datetime


from fastapi import APIRouter

from src.api_helpers import *


router = APIRouter()


def _queue_active_touch_numbers(campaign_filename: str) -> list[int]:
    steps = campaign_sequence_repo.list_steps(campaign_filename, active_only=True)
    numbers = [
        int(step.touch_number or 0)
        for step in steps
        if int(step.touch_number or 0) > 0
    ]
    return numbers or [1]


def _queue_total_touches(campaign_filename: str) -> int:
    return len(_queue_active_touch_numbers(campaign_filename))


def _queue_next_touch_number(
    active_touch_numbers: list[int],
    current_touch: int,
) -> int:
    for number in active_touch_numbers:
        if number > current_touch:
            return number
    return current_touch + 1


def _parse_queue_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    if parsed.tzinfo:
        parsed = parsed.replace(tzinfo=None)
    return parsed


def _queue_wait_reason(
    touch_number: int,
    previous_sent_at,
    next_due_at,
) -> str:
    previous_dt = _parse_queue_datetime(previous_sent_at)
    due_dt = _parse_queue_datetime(next_due_at)

    if not previous_dt or not due_dt:
        return ""

    previous_touch = max(1, int(touch_number or 1) - 1)
    days_ago = max(0, (datetime.utcnow() - previous_dt).days)

    return (
        f"Email {previous_touch} sent {days_ago}d ago · "
        f"due {due_dt.strftime('%b %d %H:%M')}"
    )


def _enrich_due_queue_item(
    item: dict,
    campaign_filename: str,
    total_touches: int,
) -> dict:
    touch_number = int(item.get("touch_number") or 1)
    previous = outreach_repo.previous_sent_draft(
        item.get("lead_id", ""),
        campaign_filename,
        touch_number,
    )
    previous_sent_at = _dt(previous.sent_at) if previous else ""
    next_due_at = item.get("next_touch_due_at") or item.get("next_due_at") or ""

    enriched = dict(item)
    enriched.update({
        "lead_name": item.get("lead_name") or item.get("full_name") or "",
        "total_touches": total_touches,
        "previous_sent_at": previous_sent_at,
        "next_due_at": next_due_at,
        "draft_status": item.get("draft_status") or "none",
        "draft_id": item.get("draft_id") or "",
        "wait_reason": _queue_wait_reason(
            touch_number,
            previous_sent_at,
            next_due_at,
        ),
    })
    return enriched


def _enrich_draft_queue_item(
    draft: dict,
    total_touches: int,
) -> dict:
    touch_number = int(draft.get("touch_number") or 1)
    next_due_at = (
        draft.get("scheduled_for")
        or draft.get("next_due_at")
        or datetime.utcnow().isoformat()
    )
    previous_sent_at = draft.get("previous_sent_at") or ""

    enriched = dict(draft)
    enriched.update({
        "lead_name": draft.get("lead_name") or draft.get("full_name") or "",
        "total_touches": total_touches,
        "previous_sent_at": previous_sent_at,
        "next_due_at": next_due_at,
        "draft_status": draft.get("status") or "none",
        "draft_id": draft.get("draft_id") or draft.get("id") or "",
        "wait_reason": _queue_wait_reason(
            touch_number,
            previous_sent_at,
            next_due_at,
        ),
    })
    return enriched


def _enrich_waiting_queue_item(
    row: dict,
    active_touch_numbers: list[int],
    total_touches: int,
) -> dict:
    current_touch = int(row.get("current_touch") or 0)
    touch_number = _queue_next_touch_number(active_touch_numbers, current_touch)
    previous_sent_at = row.get("last_touch_sent_at") or ""
    next_due_at = row.get("next_touch_due_at") or ""

    enriched = dict(row)
    enriched.update({
        "lead_name": row.get("lead_name") or row.get("full_name") or "",
        "touch_number": touch_number,
        "total_touches": total_touches,
        "previous_sent_at": previous_sent_at,
        "next_due_at": next_due_at,
        "draft_status": "none",
        "draft_id": "",
        "wait_reason": _queue_wait_reason(
            touch_number,
            previous_sent_at,
            next_due_at,
        ),
        "due_label": "Waiting follow-up",
    })
    return enriched


def _enrich_history_queue_item(
    row: dict,
    total_touches: int,
) -> dict:
    touch_number = int(row.get("touch_number") or row.get("current_touch") or 1)

    enriched = dict(row)
    enriched.update({
        "lead_name": row.get("lead_name") or row.get("full_name") or "",
        "touch_number": touch_number,
        "total_touches": total_touches,
        "previous_sent_at": row.get("previous_sent_at") or row.get("last_touch_sent_at") or "",
        "next_due_at": row.get("next_due_at") or row.get("next_touch_due_at") or "",
        "draft_status": row.get("status") or row.get("draft_status") or "",
        "draft_id": row.get("draft_id") or "",
    })
    return enriched



@router.post("/api/campaigns/{campaign_filename}/queue/send-selected")
def send_selected_campaign_queue_drafts(
    campaign_filename: str,
    request: SendSelectedDraftsRequest,
) -> dict:
    if not request.draft_ids:
        raise HTTPException(status_code=400, detail="draft_ids are required")
    return _schedule_send_drafts(
        campaign_filename,
        ScheduleSendDraftsRequest(
            draft_ids=request.draft_ids,
            mode="send_now",
            rate_per_minute=_bulk_send_rate_per_minute(),
        ),
    )

@router.get("/api/campaigns/{campaign_filename}/queue")
def get_campaign_queue(campaign_filename: str) -> dict:
    active_touch_numbers = _queue_active_touch_numbers(campaign_filename)
    total_touches = len(active_touch_numbers)

    due_today = [
        _enrich_due_queue_item(item, campaign_filename, total_touches)
        for item in outreach_repo.due_items(campaign_filename)
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
        touch_number = int(draft.get("touch_number") or 1)
        enriched = _enrich_draft_queue_item(draft, total_touches)

        if status == "scheduled" or (
            status in {"draft", "approved"} and touch_number > 1
        ):
            enriched["due_label"] = "Due now"
            grouped["scheduled"].append(enriched)
        elif status == "sent":
            grouped["sent"].append(
                _enrich_history_queue_item(enriched, total_touches)
            )
        elif status == "failed":
            grouped["failed"].append(
                _enrich_history_queue_item(enriched, total_touches)
            )
        elif status == "skipped":
            grouped["skipped"].append(
                _enrich_history_queue_item(enriched, total_touches)
            )

    grouped["waiting"] = [
        _enrich_waiting_queue_item(row, active_touch_numbers, total_touches)
        for row in outreach_repo.queue_waiting_items(campaign_filename)
    ]

    stopped_items = [
        _enrich_history_queue_item(row, total_touches)
        for row in outreach_repo.queue_stopped_items(campaign_filename)
    ]
    grouped["skipped"].extend(stopped_items)

    grouped["items"] = [
        *grouped["due_today"],
        *grouped["scheduled"],
        *grouped["waiting"],
    ]

    grouped["history"] = [
        *grouped["sent"],
        *grouped["failed"],
        *grouped["skipped"],
    ]

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
