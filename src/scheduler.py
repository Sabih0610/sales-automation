import logging
import threading
from collections import defaultdict
from datetime import datetime

from src.storage import (
    campaign_repo,
    campaign_sequence_repo,
    job_repo,
    kv_repo,
    outreach_repo,
)


logger = logging.getLogger(__name__)
ACTIVE_JOB_STATUSES = {"queued", "running"}


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat()


def _has_active_campaign_job(job_type: str, campaign_filename: str) -> bool:
    for job in job_repo.list_recent(50):
        if job.get("type") != job_type:
            continue
        if job.get("status") not in ACTIVE_JOB_STATUSES:
            continue
        payload = job.get("payload") or {}
        if payload.get("campaign_filename") == campaign_filename:
            return True
    return False


def _missing_draft_groups(due_items: list[dict]) -> dict[int, list[str]]:
    groups: dict[int, list[str]] = defaultdict(list)
    for item in due_items:
        if item.get("draft_id"):
            continue
        lead_id = str(item.get("lead_id") or "")
        touch_number = int(item.get("touch_number") or 0)
        if lead_id and touch_number > 0:
            groups[touch_number].append(lead_id)
    return groups


def run_scheduler_tick() -> None:
    kv_repo.set("scheduler_last_tick", _utcnow_iso())

    for campaign in campaign_repo.list_all():
        campaign_filename = campaign.get("filename") or ""
        if not campaign_filename:
            continue

        due_items = outreach_repo.due_items(campaign_filename, None, None)
        if not due_items:
            continue

        if not _has_active_campaign_job("generate_drafts", campaign_filename):
            for touch_number, lead_ids in _missing_draft_groups(due_items).items():
                job_repo.create(
                    "generate_drafts",
                    {
                        "campaign_filename": campaign_filename,
                        "lead_ids": lead_ids,
                        "touch_number": touch_number,
                        "overwrite": False,
                    },
                    total=len(lead_ids),
                )
                logger.info(
                    "Scheduler queued generate_drafts for %s touch %s (%s leads)",
                    campaign_filename,
                    touch_number,
                    len(lead_ids),
                )

        rules = campaign_sequence_repo.get_rules(campaign_filename)
        if not rules or rules.mode != "auto":
            continue

        approved_draft_ids = [
            str(item.get("draft_id") or "")
            for item in due_items
            if item.get("draft_status") == "approved" and item.get("draft_id")
        ]
        if not approved_draft_ids:
            continue
        if _has_active_campaign_job("send_drafts", campaign_filename):
            continue

        # Auto mode never approves drafts; only drafts already approved by a human can send.
        job_repo.create(
            "send_drafts",
            {
                "campaign_filename": campaign_filename,
                "draft_ids": approved_draft_ids,
            },
            total=len(approved_draft_ids),
        )
        logger.info(
            "Scheduler queued send_drafts for %s (%s approved drafts)",
            campaign_filename,
            len(approved_draft_ids),
        )


def run_scheduler_loop(
    stop_event: threading.Event,
    interval_seconds: int = 60,
) -> None:
    while not stop_event.is_set():
        try:
            run_scheduler_tick()
        except Exception:
            logger.exception("Scheduler tick failed")
        stop_event.wait(interval_seconds)
