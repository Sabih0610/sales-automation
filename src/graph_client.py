import os
import threading
import time

import msal
import requests


_GRAPH_TOKEN = ""
_GRAPH_TOKEN_EXPIRY = 0.0
_TOKEN_LOCK = threading.Lock()


def get_graph_token(force_refresh: bool = False) -> str:
    """Get or refresh a Microsoft Graph application access token."""
    global _GRAPH_TOKEN, _GRAPH_TOKEN_EXPIRY

    with _TOKEN_LOCK:
        if (
            not force_refresh
            and _GRAPH_TOKEN
            and time.time() < _GRAPH_TOKEN_EXPIRY - 60
        ):
            return _GRAPH_TOKEN

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

        _GRAPH_TOKEN = result["access_token"]
        _GRAPH_TOKEN_EXPIRY = time.time() + result.get("expires_in", 3600)
        return _GRAPH_TOKEN


def send_via_graph(
    to_email: str,
    subject: str,
    body: str,
    extra_headers: list[dict] | None = None,
    sender_email: str | None = None,
    reply_to_email: str | None = None,
) -> tuple[bool, str]:
    """Send a plain-text email via Microsoft Graph sendMail."""
    try:
        resolved_sender_email = (sender_email or os.getenv("SENDER_EMAIL", "")).strip()
        if not resolved_sender_email:
            return False, "Missing sender_email. Configure campaign sender_email or SENDER_EMAIL in .env"

        message = {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body,
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": to_email,
                    },
                }
            ],
        }
        resolved_reply_to = (reply_to_email or resolved_sender_email).strip()
        if resolved_reply_to:
            message["replyTo"] = [
                {
                    "emailAddress": {
                        "address": resolved_reply_to,
                    }
                }
            ]
        if extra_headers:
            message["internetMessageHeaders"] = extra_headers

        response = requests.post(
            f"https://graph.microsoft.com/v1.0/users/{resolved_sender_email}/sendMail",
            headers={
                "Authorization": f"Bearer {get_graph_token()}",
                "Content-Type": "application/json",
            },
            json={
                "message": message,
                "saveToSentItems": True,
            },
            timeout=30,
        )
        if response.status_code == 202:
            return True, ""
        return (
            False,
            f"Graph API error {response.status_code}: {response.text[:200]}",
        )
    except Exception as exc:
        return False, str(exc)
