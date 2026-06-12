import logging
import threading
import time
import contextlib
from collections.abc import Callable

from src.storage import job_repo


logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"done", "failed", "cancelled"}
_HANDLER_OVERRIDES: dict[str, Callable[[dict, threading.Event], None]] = {}


def register_job_handler(
    job_type: str,
    handler: Callable[[dict, threading.Event], None],
) -> None:
    _HANDLER_OVERRIDES[job_type] = handler


def unregister_job_handler(job_type: str) -> None:
    _HANDLER_OVERRIDES.pop(job_type, None)


def _processed_ids(job: dict, key: str) -> set[str]:
    result = job.get("result") or {}
    items = result.get("items") or []
    return {
        str(item.get(key) or "")
        for item in items
        if item.get(key)
    }


def _send_item_result(result: dict, draft_id: str) -> tuple[int, int, dict]:
    details = result.get("details") or []
    detail = details[0] if details else {}
    status = (detail.get("status") or "").strip().lower()
    failed = int(result.get("failed") or 0)
    skipped = int(result.get("skipped") or 0)
    if not status:
        if result.get("sent"):
            status = "sent"
        elif failed:
            status = "failed"
        elif skipped:
            status = "skipped"
        else:
            status = "processed"
    if status == "failed" and not failed:
        failed = 1
    if status in {"skipped", "deferred"} and not skipped:
        skipped = 1
    item = {
        "draft_id": detail.get("draft_id") or draft_id,
        "lead_id": detail.get("lead_id", ""),
        "email": detail.get("email", ""),
        "status": status,
        "reason": detail.get("reason", ""),
        "message": detail.get("message") or result.get("message", ""),
        "touch_number": detail.get("touch_number"),
    }
    return failed, skipped, item


def _generate_item_result(result: dict, lead_id: str, touch_number: int) -> tuple[int, dict]:
    skips = result.get("skips") or []
    skip = skips[0] if skips else {}
    generated = int(result.get("generated") or 0)
    skipped = int(result.get("skipped") or 0)
    if generated:
        status = "generated"
    elif skipped:
        status = "skipped"
    else:
        status = "processed"
    return skipped, {
        "lead_id": skip.get("lead_id") or lead_id,
        "touch_number": touch_number,
        "status": status,
        "reason": skip.get("reason", ""),
        "generated": generated,
    }


def _run_send_selected_drafts(job: dict, stop_event: threading.Event) -> None:
    from src import api_helpers as api_module

    payload = job.get("payload") or {}
    draft_ids = [str(item) for item in payload.get("draft_ids") or []]
    processed = _processed_ids(job, "draft_id")

    for index, draft_id in enumerate(draft_ids):
        if stop_event.is_set():
            return
        current = job_repo.get(job["id"])
        if not current or current.get("cancel_requested"):
            job_repo.mark_cancelled(job["id"])
            return
        if draft_id in processed:
            continue
        result = api_module._send_selected_drafts([draft_id])
        failed, skipped, item = _send_item_result(result, draft_id)
        job_repo.update_progress(
            job["id"],
            done_delta=1,
            failed_delta=failed,
            skipped_delta=skipped,
            result_item=item,
        )
        processed.add(draft_id)
        reason = item.get("reason", "") or ""
        if reason.startswith("Daily cap") or reason.startswith("Outside send window"):
            for remaining_id in draft_ids[index + 1:]:
                if remaining_id in processed:
                    continue
                job_repo.update_progress(
                    job["id"],
                    done_delta=1,
                    skipped_delta=1,
                    result_item={
                        "draft_id": remaining_id,
                        "status": "deferred",
                        "reason": reason,
                    },
                )
                processed.add(remaining_id)
            break
        has_remaining = any(
            remaining_id not in processed
            for remaining_id in draft_ids[index + 1:]
        )
        if item.get("status") == "sent" and has_remaining:
            from src.send_policy import next_send_delay_seconds

            stop_event.wait(next_send_delay_seconds())


def _run_generate_campaign_drafts(job: dict, stop_event: threading.Event) -> None:
    from src import api_helpers as api_module

    payload = job.get("payload") or {}
    campaign_filename = payload.get("campaign_filename") or ""
    touch_number = int(payload.get("touch_number") or 1)
    overwrite = bool(payload.get("overwrite"))
    lead_ids = [str(item) for item in payload.get("lead_ids") or []]
    processed = _processed_ids(job, "lead_id")

    for lead_id in lead_ids:
        if stop_event.is_set():
            return
        current = job_repo.get(job["id"])
        if not current or current.get("cancel_requested"):
            job_repo.mark_cancelled(job["id"])
            return
        if lead_id in processed:
            continue
        result = api_module._generate_drafts_for_leads(
            campaign_filename=campaign_filename,
            lead_ids=[lead_id],
            touch_number=touch_number,
            overwrite=overwrite,
        )
        skipped, item = _generate_item_result(result, lead_id, touch_number)
        job_repo.update_progress(
            job["id"],
            done_delta=1,
            skipped_delta=skipped,
            result_item=item,
        )
        processed.add(lead_id)


def _run_generate_due_drafts(job: dict, stop_event: threading.Event) -> None:
    from src import api_helpers as api_module
    from src.storage import outreach_repo

    payload = job.get("payload") or {}
    campaign_filename = payload.get("campaign_filename") or ""
    due_items = payload.get("due_items") or []
    if not due_items:
        due_items = outreach_repo.due_items(
            campaign_filename,
            lead_ids=payload.get("lead_ids") or None,
            touch_number=payload.get("touch_number"),
        )

    processed = {
        f"{item.get('lead_id')}:{item.get('touch_number')}"
        for item in (job.get("result") or {}).get("items", [])
        if item.get("lead_id") and item.get("touch_number")
    }

    for due in due_items:
        if stop_event.is_set():
            return
        current = job_repo.get(job["id"])
        if not current or current.get("cancel_requested"):
            job_repo.mark_cancelled(job["id"])
            return
        lead_id = str(due.get("lead_id") or "")
        touch_number = int(due.get("touch_number") or payload.get("touch_number") or 1)
        processed_key = f"{lead_id}:{touch_number}"
        if due.get("draft_id"):
            processed.add(processed_key)
            continue
        if not lead_id or processed_key in processed:
            continue
        result = api_module._generate_drafts_for_leads(
            campaign_filename=campaign_filename,
            lead_ids=[lead_id],
            touch_number=touch_number,
            overwrite=False,
        )
        skipped, item = _generate_item_result(result, lead_id, touch_number)
        job_repo.update_progress(
            job["id"],
            done_delta=1,
            skipped_delta=skipped,
            result_item=item,
        )
        processed.add(processed_key)


class JobWorker:
    def __init__(self, poll_interval_seconds: float = 1.0):
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="job-worker",
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                job = job_repo.next_queued()
                if not job:
                    time.sleep(self.poll_interval_seconds)
                    continue
                self._process_job(job)
        finally:
            with contextlib.suppress(Exception):
                conn = getattr(job_repo.db._local, "conn", None)
                if conn:
                    conn.close()
                    job_repo.db._local.conn = None

    def _process_job(self, job: dict) -> None:
        job_id = job["id"]
        try:
            job_repo.mark_running(job_id)
            current = job_repo.get(job_id) or job
            if current.get("cancel_requested"):
                job_repo.mark_cancelled(job_id)
                return

            handler = _HANDLER_OVERRIDES.get(current["type"])
            if handler:
                handler(current, self._stop_event)
            elif current["type"] in {"send_selected_drafts", "send_drafts"}:
                _run_send_selected_drafts(current, self._stop_event)
            elif current["type"] in {"generate_campaign_drafts", "generate_drafts"}:
                _run_generate_campaign_drafts(current, self._stop_event)
            elif current["type"] == "generate_due_drafts":
                _run_generate_due_drafts(current, self._stop_event)
            else:
                raise ValueError(f"Unknown job type: {current['type']}")

            final = job_repo.get(job_id) or {}
            if final.get("status") not in TERMINAL_STATUSES:
                if final.get("cancel_requested") or self._stop_event.is_set():
                    job_repo.mark_cancelled(job_id)
                else:
                    job_repo.mark_done(job_id)
        except Exception as exc:
            logger.exception("Job failed: %s", job_id)
            job_repo.mark_failed(job_id, str(exc))


_worker = JobWorker()


def get_job_worker() -> JobWorker:
    return _worker
