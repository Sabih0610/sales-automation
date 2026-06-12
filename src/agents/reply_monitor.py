import json
import logging
import os
import re
import threading
import time
from datetime import datetime

import requests

from src.graph_client import get_graph_token
from src.models import LeadActivity
from src.storage import (
    kv_repo,
    lead_repo,
    outreach_repo,
    suppression_repo,
)


logger = logging.getLogger(__name__)

GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"

DELTA_LINK_KEY = "graph_inbox_delta_link"
LAST_POLL_KEY = "inbox_monitor_last_poll"
LAST_MESSAGES_SEEN_KEY = "inbox_monitor_last_messages_seen"
LAST_REPLIES_MATCHED_KEY = "inbox_monitor_last_replies_matched"
LAST_BOUNCES_MATCHED_KEY = "inbox_monitor_last_bounces_matched"
LAST_SOFT_BOUNCES_KEY = "inbox_monitor_last_soft_bounces"
LAST_ERROR_KEY = "inbox_monitor_last_error"

# Backward-compatible keys from the original Task 1.2 plan.
REPLY_LAST_POLL_KEY = "reply_monitor_last_poll"
REPLY_LAST_MATCHED_KEY = "reply_monitor_last_replies_matched"

TERMINAL_SEQUENCE_STATUSES = {
    "replied",
    "bounced",
    "unsubscribed",
    "do_not_contact",
    "complete",
    "completed",
    "skipped",
}

BOUNCE_SENDER_MARKERS = (
    "postmaster",
    "mailer-daemon",
    "microsoftexchange",
)

BOUNCE_SUBJECT_RE = re.compile(
    r"(undeliverable|delivery (has )?failed|delivery status notification|returned mail|mail delivery failed)",
    re.IGNORECASE,
)

EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)

SOFT_BOUNCE_MARKERS = (
    "mailbox full",
    "try again later",
    "temporarily unavailable",
    "temporarily rejected",
    "temporary failure",
    "4.2.",
    "4.3.",
    "4.4.",
    "4.5.",
)

HARD_BOUNCE_MARKERS = (
    "5.1.1",
    "does not exist",
    "recipient not found",
    "user unknown",
    "550",
    "no such user",
    "invalid recipient",
)


def _utcnow_text() -> str:
    return datetime.utcnow().isoformat()


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _sender_address(message: dict) -> str:
    return _normalize_email(
        (
            message.get("from", {})
            .get("emailAddress", {})
            .get("address", "")
        )
    )


def _message_subject(message: dict) -> str:
    return message.get("subject") or ""


def _message_received_at(message: dict) -> str:
    return message.get("receivedDateTime") or ""


def _is_internal_sender(email: str) -> bool:
    return email.endswith("@royalcyber.com")


def _is_automated_sender(email: str) -> bool:
    lowered = email.lower()
    return any(
        marker in lowered
        for marker in (
            "no-reply",
            "noreply",
            "postmaster",
            "mailer-daemon",
        )
    )


def _is_bounce_candidate(sender: str, subject: str) -> bool:
    lowered_sender = sender.lower()
    if any(marker in lowered_sender for marker in BOUNCE_SENDER_MARKERS):
        return True
    return bool(BOUNCE_SUBJECT_RE.search(subject or ""))


def _is_soft_bounce(body_text: str) -> bool:
    lowered = (body_text or "").lower()
    return any(marker in lowered for marker in SOFT_BOUNCE_MARKERS)


def _is_hard_bounce(body_text: str) -> bool:
    lowered = (body_text or "").lower()
    return any(marker in lowered for marker in HARD_BOUNCE_MARKERS)


def _find_leads_by_email(email: str):
    return lead_repo.get_by_email(_normalize_email(email))


def _add_activity(
    lead,
    campaign_filename: str,
    activity_type: str,
    title: str,
    description: str,
    metadata: dict | None = None,
) -> None:
    if not lead:
        return

    outreach_repo.add_activity(
        LeadActivity(
            lead_id=lead.id,
            campaign_filename=campaign_filename or "",
            run_id=getattr(lead, "run_id", "") or "",
            activity_type=activity_type,
            title=title,
            description=description or "",
            metadata_json=json.dumps(metadata or {}, default=str),
        )
    )


def _update_legacy_lead_status(
    lead_id: str,
    status: str,
    reason: str,
) -> None:
    lead_repo.update_sequence_status(lead_id, status, reason)


def _stop_sequence_for_state(
    lead,
    state,
    status: str,
    reason: str,
    activity_type: str,
    activity_title: str,
    metadata: dict | None = None,
) -> int:
    state.status = status
    state.stop_reason = reason or status
    state.completed_at = datetime.utcnow()
    state.next_touch_due_at = None
    outreach_repo.upsert_state(state)

    skipped = outreach_repo.mark_future_pending_skipped(
        lead.id,
        state.campaign_filename,
        reason or status,
    )

    _update_legacy_lead_status(lead.id, status, reason)

    final_metadata = dict(metadata or {})
    final_metadata["skipped_pending_drafts"] = skipped

    _add_activity(
        lead,
        state.campaign_filename,
        activity_type,
        activity_title,
        reason or "",
        final_metadata,
    )

    return skipped


class InboxMonitor:
    """
    Polls the Graph inbox delta feed and handles:
    - real human replies
    - hard bounces / NDRs
    - soft bounces as activity only

    This class is safe to import. It does not call Microsoft Graph until poll_once().
    """

    def __init__(self, mailbox: str | None = None):
        self.mailbox = mailbox or os.getenv("ACS_REPLY_TO_EMAIL", "")
        self.process_started_at = datetime.utcnow()

    def _initial_delta_url(self) -> str:
        select = (
            "id,from,subject,receivedDateTime,"
            "internetMessageId,conversationId"
        )
        return (
            f"{GRAPH_ENDPOINT}/users/{self.mailbox}"
            f"/mailFolders/inbox/messages/delta?$select={select}"
        )

    def _message_body_url(self, message_id: str) -> str:
        return (
            f"{GRAPH_ENDPOINT}/users/{self.mailbox}"
            f"/messages/{message_id}?$select=body"
        )

    def _graph_get_json(
        self,
        url: str,
        retry_after_unauthorized: bool = True,
    ) -> dict:
        token = get_graph_token()
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )

        if response.status_code == 401 and retry_after_unauthorized:
            token = get_graph_token(force_refresh=True)
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )

        if response.status_code == 410:
            kv_repo.delete(DELTA_LINK_KEY)
            raise RuntimeError(
                "Microsoft Graph delta link expired. "
                "The inbox monitor cursor was cleared; next poll will re-initialize."
            )

        response.raise_for_status()
        return response.json()

    def _fetch_message_body(self, message_id: str) -> str:
        if not message_id:
            return ""

        data = self._graph_get_json(self._message_body_url(message_id))
        body = data.get("body") or {}
        return body.get("content") or ""

    def _extract_external_recipients(self, body_text: str) -> set[str]:
        monitored = _normalize_email(self.mailbox)
        found = {
            _normalize_email(match.group(0))
            for match in EMAIL_RE.finditer(body_text or "")
        }

        return {
            email
            for email in found
            if email
            and email != monitored
            and not email.endswith("@royalcyber.com")
        }

    def _active_states_for_lead(self, lead_id: str):
        states = outreach_repo.list_states_for_lead(lead_id)
        return [
            state
            for state in states
            if (state.status or "").lower() not in TERMINAL_SEQUENCE_STATUSES
        ]

    def _handle_reply(self, message: dict) -> int:
        sender = _sender_address(message)
        subject = _message_subject(message)
        received_at = _message_received_at(message)

        if not sender:
            return 0
        if _is_internal_sender(sender):
            return 0
        if _is_automated_sender(sender):
            return 0

        leads = _find_leads_by_email(sender)
        if not leads:
            return 0

        matched = 0
        reason = f'Reply detected: "{subject}" at {received_at}'

        for lead in leads:
            for state in self._active_states_for_lead(lead.id):
                _stop_sequence_for_state(
                    lead,
                    state,
                    status="replied",
                    reason=reason,
                    activity_type="reply_detected",
                    activity_title="Lead replied",
                    metadata={
                        "sender": sender,
                        "subject": subject,
                        "received_at": received_at,
                        "conversation_id": message.get("conversationId", ""),
                        "internet_message_id": message.get("internetMessageId", ""),
                    },
                )
                matched += 1

        return matched

    def _handle_bounce(self, message: dict) -> tuple[int, int]:
        message_id = message.get("id") or ""
        subject = _message_subject(message)
        received_at = _message_received_at(message)

        body_text = self._fetch_message_body(message_id)
        recipients = self._extract_external_recipients(body_text)

        if not recipients:
            return 0, 0

        hard = _is_hard_bounce(body_text)
        soft = _is_soft_bounce(body_text) and not hard

        bounces_matched = 0
        soft_bounces = 0

        for recipient in recipients:
            leads = _find_leads_by_email(recipient)
            if not leads:
                continue

            for lead in leads:
                states = self._active_states_for_lead(lead.id)

                if hard:
                    suppression_repo.add(
                        recipient,
                        "bounced",
                        lead.id,
                        "",
                    )

                    for state in states:
                        suppression_repo.add(
                            recipient,
                            "bounced",
                            lead.id,
                            state.campaign_filename,
                        )
                        _stop_sequence_for_state(
                            lead,
                            state,
                            status="bounced",
                            reason="NDR detected",
                            activity_type="bounce_detected",
                            activity_title="Bounce detected",
                            metadata={
                                "recipient": recipient,
                                "subject": subject,
                                "received_at": received_at,
                                "message_id": message_id,
                            },
                        )
                        bounces_matched += 1

                elif soft:
                    for state in states:
                        _add_activity(
                            lead,
                            state.campaign_filename,
                            "soft_bounce",
                            "Soft bounce detected",
                            (
                                f"Soft bounce detected for {recipient}. "
                                "Sequence was not stopped."
                            ),
                            {
                                "recipient": recipient,
                                "subject": subject,
                                "received_at": received_at,
                                "message_id": message_id,
                            },
                        )
                        soft_bounces += 1

        return bounces_matched, soft_bounces

    def _handle_message(self, message: dict) -> dict:
        sender = _sender_address(message)
        subject = _message_subject(message)

        result = {
            "replies_matched": 0,
            "bounces_matched": 0,
            "soft_bounces": 0,
        }

        if _is_bounce_candidate(sender, subject):
            bounces, soft = self._handle_bounce(message)
            result["bounces_matched"] = bounces
            result["soft_bounces"] = soft
            return result

        result["replies_matched"] = self._handle_reply(message)
        return result

    def poll_once(self) -> dict:
        if not self.mailbox:
            raise ValueError("ACS_REPLY_TO_EMAIL missing in .env")

        delta_link = kv_repo.get(DELTA_LINK_KEY)
        first_run = not bool(delta_link)
        url = delta_link or self._initial_delta_url()

        messages_seen = 0
        replies_matched = 0
        bounces_matched = 0
        soft_bounces = 0

        while url:
            data = self._graph_get_json(url)

            for message in data.get("value", []):
                messages_seen += 1

                # First run is only cursor initialization.
                # This prevents historical inbox mail from stopping old leads.
                if first_run:
                    continue

                handled = self._handle_message(message)
                replies_matched += handled["replies_matched"]
                bounces_matched += handled["bounces_matched"]
                soft_bounces += handled["soft_bounces"]

            next_link = data.get("@odata.nextLink")
            new_delta_link = data.get("@odata.deltaLink")

            if next_link:
                url = next_link
                continue

            if new_delta_link:
                kv_repo.set(DELTA_LINK_KEY, new_delta_link)
            break

        now = _utcnow_text()

        kv_repo.set(LAST_POLL_KEY, now)
        kv_repo.set(REPLY_LAST_POLL_KEY, now)
        kv_repo.set(LAST_MESSAGES_SEEN_KEY, str(messages_seen))
        kv_repo.set(LAST_REPLIES_MATCHED_KEY, str(replies_matched))
        kv_repo.set(REPLY_LAST_MATCHED_KEY, str(replies_matched))
        kv_repo.set(LAST_BOUNCES_MATCHED_KEY, str(bounces_matched))
        kv_repo.set(LAST_SOFT_BOUNCES_KEY, str(soft_bounces))
        kv_repo.set(LAST_ERROR_KEY, "")

        return {
            "messages_seen": messages_seen,
            "replies_matched": replies_matched,
            "bounces_matched": bounces_matched,
            "soft_bounces": soft_bounces,
            "initialized_cursor": first_run,
        }

    def status(self) -> dict:
        return {
            "enabled": os.getenv("REPLY_MONITOR_ENABLED", "false").lower()
            == "true",
            "mailbox": self.mailbox,
            "last_poll_at": kv_repo.get(LAST_POLL_KEY) or None,
            "last_replies_matched": int(
                kv_repo.get(LAST_REPLIES_MATCHED_KEY) or "0"
            ),
            "last_bounces_matched": int(
                kv_repo.get(LAST_BOUNCES_MATCHED_KEY) or "0"
            ),
            "last_soft_bounces": int(
                kv_repo.get(LAST_SOFT_BOUNCES_KEY) or "0"
            ),
            "last_messages_seen": int(
                kv_repo.get(LAST_MESSAGES_SEEN_KEY) or "0"
            ),
            "last_error": kv_repo.get(LAST_ERROR_KEY) or "",
            "has_delta_cursor": bool(kv_repo.get(DELTA_LINK_KEY)),
        }


class ReplyMonitor(InboxMonitor):
    """Backward-compatible name for Task 1.2."""


class BounceMonitor(InboxMonitor):
    """Backward-compatible name for Task 1.3."""


def get_inbox_monitor_status() -> dict:
    return InboxMonitor().status()


def run_reply_monitor_loop(
    stop_event: threading.Event,
    interval_seconds: int = 300,
) -> None:
    monitor = InboxMonitor()

    while not stop_event.is_set():
        try:
            result = monitor.poll_once()
            logger.info("Inbox monitor poll result: %s", result)
        except Exception as exc:
            logger.exception("Inbox monitor poll failed")
            kv_repo.set(LAST_ERROR_KEY, str(exc))

        stop_event.wait(interval_seconds)
