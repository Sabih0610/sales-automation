from fastapi import APIRouter

from src.api_helpers import *


router = APIRouter()


@router.post("/api/lead-universes")
def create_lead_universe(request: CreateLeadUniverseRequest) -> dict:
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Universe name is required")
    if not request.campaign_filename.strip():
        raise HTTPException(status_code=400, detail="campaign_filename is required")
    if request.source_type != "sales_navigator":
        raise HTTPException(
            status_code=400,
            detail="Only sales_navigator source_type is supported",
        )
    universe = LeadUniverse(
        name=request.name.strip(),
        campaign_filename=request.campaign_filename.strip(),
        source_type="sales_navigator",
        description=request.description.strip(),
        target_leads=max(0, int(request.target_leads or 0)),
        status="queued",
    )
    lead_universe_repo.save_universe(universe)
    return _universe_payload(universe)

@router.get("/api/lead-universes/{universe_id}")
def get_lead_universe(universe_id: str) -> dict:
    universe = lead_universe_repo.get_universe(universe_id)
    if not universe:
        raise HTTPException(status_code=404, detail="Lead universe not found")
    payload = _universe_payload(universe)
    payload["segments"] = [
        _segment_payload(segment)
        for segment in lead_universe_repo.list_segments(universe_id)
    ]
    return payload

@router.get("/api/campaigns/{campaign_filename}/lead-universes")
def get_campaign_lead_universes(campaign_filename: str) -> list[dict]:
    return [
        {
            **_universe_payload(universe),
            "segments": [
                _segment_payload(segment)
                for segment in lead_universe_repo.list_segments(universe.id)
            ],
        }
        for universe in lead_universe_repo.list_universes(campaign_filename)
    ]

@router.post("/api/lead-universes/{universe_id}/segments")
def create_lead_source_segment(
    universe_id: str,
    request: CreateLeadSourceSegmentRequest,
) -> dict:
    universe = lead_universe_repo.get_universe(universe_id)
    if not universe:
        raise HTTPException(status_code=404, detail="Lead universe not found")
    source_url = request.source_url.strip()
    if "linkedin.com/sales/search/people" not in source_url.lower():
        raise HTTPException(
            status_code=400,
            detail="Only LinkedIn Sales Navigator people search URLs are supported",
        )
    label = request.label.strip() or f"Segment {len(lead_universe_repo.list_segments(universe_id)) + 1}"
    segment = LeadSourceSegment(
        universe_id=universe_id,
        campaign_filename=universe.campaign_filename,
        source_url=source_url,
        label=label,
        filters_json=json.dumps(request.filters or {}, default=str),
        expected_count=max(1, int(request.expected_count or 50)),
        status="queued",
    )
    lead_universe_repo.save_segment(segment)
    lead_universe_repo.refresh_universe_totals(universe_id)
    return _segment_payload(segment)

@router.post("/api/segments/{segment_id}/run")
def run_lead_source_segment(segment_id: str) -> dict:
    segment = lead_universe_repo.get_segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    if segment.status == "running":
        raise HTTPException(status_code=409, detail="Segment is already running")
    if segment.id in _running_segment_ids:
        raise HTTPException(status_code=409, detail="Segment is already queued to run")
    _start_segment_thread(segment.id)
    return {"started": True, "segment": _segment_payload(segment)}

@router.post("/api/lead-universes/{universe_id}/run-next")
def run_next_lead_source_segment(universe_id: str) -> dict:
    universe = lead_universe_repo.get_universe(universe_id)
    if not universe:
        raise HTTPException(status_code=404, detail="Lead universe not found")
    if universe_id in _running_universe_ids:
        raise HTTPException(
            status_code=409,
            detail="This lead universe is already running",
        )

    if any(
        segment.id in _running_segment_ids or segment.status == "running"
        for segment in lead_universe_repo.list_segments(universe_id)
    ):
        raise HTTPException(
            status_code=409,
            detail="A segment in this lead universe is already running",
        )

    if universe_id in _running_universe_ids:
        raise HTTPException(
            status_code=409,
            detail="This lead universe is already running",
        )

    if any(
        segment.id in _running_segment_ids or segment.status == "running"
        for segment in lead_universe_repo.list_segments(universe_id)
    ):
        raise HTTPException(
            status_code=409,
            detail="A segment in this lead universe is already running",
        )

    segment = lead_universe_repo.next_queued_segment(universe_id)
    if not segment:
        return {"started": False, "message": "No queued segments"}
    _start_segment_thread(segment.id)
    return {"started": True, "segment": _segment_payload(segment)}

@router.post("/api/lead-universes/{universe_id}/run-all")
def run_all_lead_source_segments(universe_id: str) -> dict:
    universe = lead_universe_repo.get_universe(universe_id)
    if not universe:
        raise HTTPException(status_code=404, detail="Lead universe not found")
    if universe_id in _running_universe_ids:
        raise HTTPException(
            status_code=409,
            detail="This lead universe is already running",
        )

    segments = lead_universe_repo.list_segments(universe_id)
    if any(
        segment.id in _running_segment_ids or segment.status == "running"
        for segment in segments
    ):
        raise HTTPException(
            status_code=409,
            detail="A segment in this lead universe is already running",
        )

    queued = [
        segment for segment in segments
        if segment.status == "queued"
    ]
    if not queued:
        return {"started": False, "queued": 0, "message": "No queued segments"}

    _running_universe_ids.add(universe_id)
    thread = threading.Thread(
        target=_run_all_segments_now,
        args=(universe_id,),
        daemon=True,
        name=f"lead-universe-{universe_id[:8]}",
    )
    thread.start()
    return {"started": True, "queued": len(queued)}

@router.post("/api/lead-universes/{universe_id}/pause-all")
def pause_lead_source_segments(universe_id: str) -> dict:
    universe = lead_universe_repo.get_universe(universe_id)
    if not universe:
        raise HTTPException(status_code=404, detail="Lead universe not found")
    updated = lead_universe_repo.pause_queued_segments(universe_id)
    lead_universe_repo.refresh_universe_totals(universe_id)
    return {"paused": updated}
