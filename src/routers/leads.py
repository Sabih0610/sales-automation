from fastapi import APIRouter

from src.api_helpers import *


router = APIRouter()


@router.get("/api/leads")
def get_all_leads(
    segment: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """All leads across all runs with optional filters."""
    leads, _total = lead_repo.search(
        segment=segment,
        run_id=run_id or "",
        limit=limit,
        offset=offset,
        newest_first=True,
    )
    return [
        {
            "id": lead.id,
            "run_id": getattr(lead, "run_id", "") or "",
            "full_name": lead.full_name,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "title": lead.title,
            "company": lead.company,
            "company_domain": lead.company_domain,
            "linkedin_url": lead.linkedin_url,
            "email": lead.email,
            "email_confidence": lead.email_confidence,
            "intent_score": lead.intent_score,
            "segment": lead.segment.value,
            "status": lead.status.value,
            "phone": lead.phone,
            "location": lead.location,
            "email_subject": getattr(lead, "email_subject", "") or "",
            "email_sequence_status": getattr(
                lead,
                "email_sequence_status",
                "not_started",
            ),
            "campaign_name": getattr(lead, "campaign_name", "") or "",
        }
        for lead in leads
    ]

@router.post("/api/leads/{lead_id}/mark-replied")
def mark_lead_replied(
    lead_id: str,
    request: ManualLeadStatusRequest,
) -> dict:
    return _mark_lead_sequence_status(
        lead_id,
        request,
        "replied",
    )

@router.post("/api/leads/{lead_id}/mark-bounced")
def mark_lead_bounced(
    lead_id: str,
    request: ManualLeadStatusRequest,
) -> dict:
    return _mark_lead_sequence_status(
        lead_id,
        request,
        "bounced",
    )

@router.post("/api/leads/{lead_id}/mark-unsubscribed")
def mark_lead_unsubscribed(
    lead_id: str,
    request: ManualLeadStatusRequest,
) -> dict:
    return _mark_lead_sequence_status(
        lead_id,
        request,
        "unsubscribed",
    )

@router.post("/api/leads/{lead_id}/mark-do-not-contact")
def mark_lead_do_not_contact(
    lead_id: str,
    request: ManualLeadStatusRequest,
) -> dict:
    return _mark_lead_sequence_status(
        lead_id,
        request,
        "do_not_contact",
    )

@router.get("/api/leads/{lead_id}/activities")
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
