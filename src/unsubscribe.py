import os

from itsdangerous import BadSignature, URLSafeSerializer


def _serializer() -> URLSafeSerializer:
    secret = os.getenv("UNSUBSCRIBE_SECRET", "").strip()
    if not secret:
        raise RuntimeError("UNSUBSCRIBE_SECRET is required for unsubscribe links")
    return URLSafeSerializer(secret, salt="email-unsubscribe")


def make_token(lead_id: str, email: str) -> str:
    return _serializer().dumps({
        "lead_id": (lead_id or "").strip(),
        "email": (email or "").strip().lower(),
    })


def parse_token(token: str) -> dict | None:
    try:
        data = _serializer().loads(token)
    except (BadSignature, RuntimeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    lead_id = (data.get("lead_id") or "").strip()
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return None
    return {"lead_id": lead_id, "email": email}


def make_unsubscribe_url(lead_id: str, email: str) -> str:
    base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("PUBLIC_BASE_URL is required for unsubscribe links")
    return f"{base_url}/u/{make_token(lead_id, email)}"
