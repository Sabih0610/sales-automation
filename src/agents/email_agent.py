import os
import random
import time
from dataclasses import dataclass
from datetime import datetime

import msal
import requests

from src.agents.base import BaseAgent
from src.models import EventType, Lead, PipelineRun
from src.storage import db


@dataclass
class EmailSequenceStatus:
    lead_id: str
    day1_sent_at: str = ""
    day3_sent_at: str = ""
    day7_sent_at: str = ""
    last_status: str = ""
    error: str = ""


class EmailAgent(BaseAgent):
    """
    Sends personalised emails via Microsoft Graph API.
    Respects sequence timing: Day 1, Day 3, Day 7.
    Rate limited to stay safely below 30 emails per minute.
    Never sends to a lead that replied or unsubscribed.
    """

    GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
    RATE_LIMIT_DELAY = 2.5

    def __init__(self, run: PipelineRun, leads: list[Lead]):
        super().__init__(run)
        self.leads = leads
        self._token: str = ""
        self._token_expiry: float = 0.0
        self._sender = os.getenv("SENDER_EMAIL", "")
        self.sent_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self._has_personalisation_columns = False
        self._ensure_db_columns()

    def _ensure_db_columns(self) -> None:
        """Add email sequence tracking columns if they do not exist."""
        new_cols = [
            ("day1_sent_at", "TEXT DEFAULT ''"),
            ("day3_sent_at", "TEXT DEFAULT ''"),
            ("day7_sent_at", "TEXT DEFAULT ''"),
            ("email_sequence_status", "TEXT DEFAULT ''"),
            ("email_sequence_error", "TEXT DEFAULT ''"),
        ]
        conn = db._conn()
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(leads)").fetchall()
        }
        self._has_personalisation_columns = {
            "email_subject",
            "email_body",
        }.issubset(existing)
        for col_name, col_def in new_cols:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE leads ADD COLUMN {col_name} {col_def}")
                conn.commit()

    def _get_token(self) -> str:
        """Get or refresh a Microsoft Graph access token."""
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        tenant_id = os.getenv("AZURE_TENANT_ID", "")
        client_id = os.getenv("AZURE_CLIENT_ID", "")
        client_secret = os.getenv("AZURE_CLIENT_SECRET", "")

        if not all([tenant_id, client_id, client_secret]):
            raise ValueError(
                "Missing Azure credentials in .env. Required: "
                "AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET"
            )

        app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )

        if "access_token" not in result:
            raise RuntimeError(
                f"Failed to get token: {result.get('error_description')}"
            )

        self._token = result["access_token"]
        self._token_expiry = time.time() + result.get("expires_in", 3600)
        return self._token

    def _send_email(self, to_email: str, subject: str, body: str) -> bool:
        """Send a single email via Microsoft Graph API."""
        if not to_email or "@" not in to_email:
            return False

        try:
            token = self._get_token()
            response = requests.post(
                f"{self.GRAPH_ENDPOINT}/users/{self._sender}/sendMail",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "message": {
                        "subject": subject,
                        "body": {
                            "contentType": "Text",
                            "content": body,
                        },
                        "toRecipients": [
                            {"emailAddress": {"address": to_email}}
                        ],
                    },
                    "saveToSentItems": True,
                },
                timeout=15,
            )

            if response.status_code == 202:
                return True

            self.logger.warning(
                f"Graph API error {response.status_code}: "
                f"{response.text[:200]}"
            )
            return False
        except Exception as exc:
            self.logger.error(f"Send failed to {to_email}: {exc}")
            return False

    def _get_sequence_status(self, lead: Lead) -> dict:
        """Read current sequence status for a lead from SQLite."""
        row = db._conn().execute(
            """
            SELECT day1_sent_at, day3_sent_at, day7_sent_at,
                   email_sequence_status
            FROM leads
            WHERE id = ?
            """,
            (lead.id,),
        ).fetchone()
        if not row:
            return {}
        return {
            "day1_sent_at": row["day1_sent_at"] or "",
            "day3_sent_at": row["day3_sent_at"] or "",
            "day7_sent_at": row["day7_sent_at"] or "",
            "status": row["email_sequence_status"] or "",
        }

    def _get_email_content(self, lead: Lead) -> tuple[str, str]:
        """Read personalised subject/body for a lead from SQLite."""
        if not self._has_personalisation_columns:
            return "", ""
        row = db._conn().execute(
            """
            SELECT email_subject, email_body
            FROM leads
            WHERE id = ?
            """,
            (lead.id,),
        ).fetchone()
        if not row:
            return "", ""
        return row["email_subject"] or "", row["email_body"] or ""

    def _update_sequence_status(
        self,
        lead_id: str,
        day_col: str,
        status: str,
        error: str = "",
    ) -> None:
        """Update sequence tracking in SQLite."""
        if day_col not in {"day1_sent_at", "day3_sent_at", "day7_sent_at"}:
            raise ValueError(f"Invalid sequence column: {day_col}")
        with db._conn() as conn:
            conn.execute(
                f"""
                UPDATE leads
                SET {day_col} = ?,
                    email_sequence_status = ?,
                    email_sequence_error = ?
                WHERE id = ?
                """,
                (datetime.utcnow().isoformat(), status, error, lead_id),
            )

    def _update_sequence_error(self, lead_id: str, error: str) -> None:
        with db._conn() as conn:
            conn.execute(
                """
                UPDATE leads
                SET email_sequence_error = ?
                WHERE id = ?
                """,
                (error, lead_id),
            )

    def _days_since(self, iso_str: str) -> int:
        """Return how many full days have passed since an ISO datetime."""
        if not iso_str:
            return 999
        try:
            sent = datetime.fromisoformat(iso_str)
            return (datetime.utcnow() - sent).days
        except Exception:
            return 999

    def _should_send_day(self, seq: dict, day: int) -> bool:
        """
        Determine if this lead should receive a Day N email today.
        Day 1: never sent before.
        Day 3: Day 1 sent 3+ days ago and Day 3 not sent.
        Day 7: Day 3 sent 4+ days ago and Day 7 not sent.
        """
        status = seq.get("status", "")
        if status in ("replied", "unsubscribed", "complete"):
            return False

        if day == 1:
            return not seq.get("day1_sent_at")
        if day == 3:
            return (
                bool(seq.get("day1_sent_at"))
                and not seq.get("day3_sent_at")
                and self._days_since(seq.get("day1_sent_at", "")) >= 3
            )
        if day == 7:
            return (
                bool(seq.get("day3_sent_at"))
                and not seq.get("day7_sent_at")
                and self._days_since(seq.get("day3_sent_at", "")) >= 4
            )
        return False

    def _next_day_to_send(self, seq: dict) -> int | None:
        if self._should_send_day(seq, 1):
            return 1
        if self._should_send_day(seq, 3):
            return 3
        if self._should_send_day(seq, 7):
            return 7
        return None

    def _subject_for_day(self, subject: str, day: int) -> str:
        if day == 1:
            return subject
        if day == 3:
            return f"Re: {subject}"
        return f"Following up - {subject}"

    def run_agent(self) -> list[Lead]:
        if not self._sender:
            raise ValueError("SENDER_EMAIL missing in .env")

        for lead in self.leads:
            if not lead.email:
                self.skipped_count += 1
                continue

            subject, body = self._get_email_content(lead)
            if not subject or not body:
                self.skipped_count += 1
                continue

            seq = self._get_sequence_status(lead)
            if seq.get("status") in ("replied", "unsubscribed", "complete"):
                self.skipped_count += 1
                continue

            day_to_send = self._next_day_to_send(seq)
            if not day_to_send:
                self.skipped_count += 1
                continue

            send_subject = self._subject_for_day(subject, day_to_send)
            self.logger.info(
                f"Sending Day {day_to_send} to "
                f"{lead.full_name} <{lead.email}>"
            )

            success = self._send_email(lead.email, send_subject, body)
            if success:
                day_col = f"day{day_to_send}_sent_at"
                new_status = (
                    "complete"
                    if day_to_send == 7
                    else f"day{day_to_send}_sent"
                )
                self._update_sequence_status(lead.id, day_col, new_status)
                setattr(lead, "email_sequence_status", new_status)
                self.emit(
                    EventType.LEAD_EXPORTED,
                    {
                        "lead_id": lead.id,
                        "name": lead.full_name,
                        "email": lead.email,
                        "day": day_to_send,
                        "status": "sent",
                    },
                )
                self.sent_count += 1
            else:
                self.failed_count += 1
                self._update_sequence_error(lead.id, "Graph API send failed")

            time.sleep(self.RATE_LIMIT_DELAY + random.uniform(0.5, 1.5))

        self.logger.info(
            "Email run complete. "
            f"Sent: {self.sent_count}, "
            f"Skipped: {self.skipped_count}, "
            f"Failed: {self.failed_count}"
        )
        return self.leads
