import json
import re
from datetime import datetime, timedelta

import dns.exception
import dns.resolver

from src.storage import kv_repo


EMAIL_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)

ROLE_BASED_LOCAL_PARTS = {
    "admin",
    "administrator",
    "billing",
    "contact",
    "enquiries",
    "hello",
    "hr",
    "info",
    "inquiries",
    "mail",
    "marketing",
    "office",
    "postmaster",
    "sales",
    "support",
    "team",
    "webmaster",
}

DISPOSABLE_DOMAINS = {
    "10minutemail.com",
    "20minutemail.com",
    "33mail.com",
    "anonaddy.com",
    "burnermail.io",
    "dispostable.com",
    "emailondeck.com",
    "fakeinbox.com",
    "guerrillamail.com",
    "guerrillamail.net",
    "maildrop.cc",
    "mailinator.com",
    "mailnesia.com",
    "moakt.com",
    "sharklasers.com",
    "tempmail.com",
    "tempmail.net",
    "throwawaymail.com",
    "trashmail.com",
    "yopmail.com",
}

CACHE_DAYS = 7


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def email_domain(email: str) -> str:
    normalized = normalize_email(email)
    if "@" not in normalized:
        return ""
    return normalized.rsplit("@", 1)[-1].strip().lower()


def email_local_part(email: str) -> str:
    normalized = normalize_email(email)
    if "@" not in normalized:
        return ""
    return normalized.split("@", 1)[0].strip().lower()


def verify_syntax(email: str) -> bool:
    normalized = normalize_email(email)
    if not normalized or len(normalized) > 254:
        return False

    if normalized.count("@") != 1:
        return False

    local, domain = normalized.split("@", 1)

    if not local or not domain:
        return False

    if len(local) > 64:
        return False

    if local.startswith(".") or local.endswith(".") or ".." in local:
        return False

    if ".." in domain:
        return False

    return bool(EMAIL_RE.match(normalized))


def _cache_key(domain: str) -> str:
    return f"mx:{domain}"


def _read_cached_domain_result(domain: str) -> str:
    raw = kv_repo.get(_cache_key(domain))
    if not raw:
        return ""

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""

    checked_at = data.get("checked_at") or ""
    result = data.get("result") or ""

    if not checked_at or not result:
        return ""

    try:
        checked_dt = datetime.fromisoformat(checked_at)
    except ValueError:
        return ""

    if datetime.utcnow() - checked_dt > timedelta(days=CACHE_DAYS):
        return ""

    return result


def _write_cached_domain_result(domain: str, result: str) -> None:
    kv_repo.set(
        _cache_key(domain),
        json.dumps(
            {
                "result": result,
                "checked_at": datetime.utcnow().isoformat(),
            }
        ),
    )


def verify_domain(domain: str) -> str:
    """
    Returns:
    - ok
    - no_mx
    - dns_error

    If a domain has no MX but has an A record, we treat it as ok because
    SMTP technically allows fallback to A records.
    """
    normalized = (domain or "").strip().lower()
    if not normalized:
        return "no_mx"

    cached = _read_cached_domain_result(normalized)
    if cached:
        return cached

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4
    resolver.timeout = 2

    try:
        mx_answers = resolver.resolve(normalized, "MX")
        if list(mx_answers):
            _write_cached_domain_result(normalized, "ok")
            return "ok"
    except dns.resolver.NXDOMAIN:
        _write_cached_domain_result(normalized, "no_mx")
        return "no_mx"
    except dns.resolver.NoAnswer:
        pass
    except dns.resolver.NoNameservers:
        _write_cached_domain_result(normalized, "dns_error")
        return "dns_error"
    except dns.exception.Timeout:
        _write_cached_domain_result(normalized, "dns_error")
        return "dns_error"
    except Exception:
        _write_cached_domain_result(normalized, "dns_error")
        return "dns_error"

    try:
        a_answers = resolver.resolve(normalized, "A")
        if list(a_answers):
            _write_cached_domain_result(normalized, "ok")
            return "ok"
    except dns.resolver.NXDOMAIN:
        _write_cached_domain_result(normalized, "no_mx")
        return "no_mx"
    except dns.resolver.NoAnswer:
        _write_cached_domain_result(normalized, "no_mx")
        return "no_mx"
    except dns.resolver.NoNameservers:
        _write_cached_domain_result(normalized, "dns_error")
        return "dns_error"
    except dns.exception.Timeout:
        _write_cached_domain_result(normalized, "dns_error")
        return "dns_error"
    except Exception:
        _write_cached_domain_result(normalized, "dns_error")
        return "dns_error"

    _write_cached_domain_result(normalized, "no_mx")
    return "no_mx"


def classify_email(email: str) -> dict:
    normalized = normalize_email(email)

    if not verify_syntax(normalized):
        return {
            "email": normalized,
            "status": "invalid",
            "reason": "bad_syntax",
            "domain_result": "",
        }

    domain = email_domain(normalized)
    local = email_local_part(normalized)

    if domain in DISPOSABLE_DOMAINS:
        return {
            "email": normalized,
            "status": "risky",
            "reason": "disposable_domain",
            "domain_result": "ok",
        }

    domain_result = verify_domain(domain)

    if domain_result == "no_mx":
        return {
            "email": normalized,
            "status": "invalid",
            "reason": "no_mx",
            "domain_result": domain_result,
        }

    if domain_result == "dns_error":
        return {
            "email": normalized,
            "status": "risky",
            "reason": "dns_error",
            "domain_result": domain_result,
        }

    if local in ROLE_BASED_LOCAL_PARTS:
        return {
            "email": normalized,
            "status": "risky",
            "reason": "role_based",
            "domain_result": domain_result,
        }

    return {
        "email": normalized,
        "status": "valid",
        "reason": "mx_ok",
        "domain_result": domain_result,
    }


def classify(email: str) -> str:
    return classify_email(email)["status"]


def verify_email(email: str) -> dict:
    result = classify_email(email)
    result["checked_at"] = datetime.utcnow().isoformat()
    return result