from fastapi import APIRouter

from src.api_helpers import *
from src.storage import kv_repo


router = APIRouter()


@router.get("/api/status")
def get_status() -> dict:
    return orchestrator.get_status()

@router.get("/api/stats")
def get_stats() -> dict:
    """Dashboard overview stats aggregated across all runs."""
    return {
        "total_leads": lead_repo.count_all(),
        "emails_sent": lead_repo.count_sequence_statuses({
            "day1_sent",
            "day3_sent",
            "complete",
        }),
        "replies": lead_repo.count_sequence_statuses({"replied"}),
        "total_runs": run_repo.count_all(),
    }

@router.get("/api/suppression")
def list_suppression(
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[dict]:
    return suppression_repo.list_all(limit)

@router.post("/api/suppression")
def add_suppression(request: SuppressionRequest) -> dict:
    email = (request.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required")
    suppression_repo.add(
        email,
        request.reason or "manual",
        request.source_lead_id,
        request.source_campaign,
    )
    return {"added": True, "email": email}

@router.delete("/api/suppression/{email}")
def remove_suppression(email: str) -> dict:
    normalized = (email or "").strip().lower()
    removed = suppression_repo.remove(normalized)
    return {"removed": removed, "email": normalized}

@router.get("/api/settings")
def get_settings() -> dict:
    return {
        "sender_email": os.getenv("SENDER_EMAIL", ""),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "zoominfo_enabled": os.getenv("ZOOMINFO_ENABLED", "").lower() == "true",
        "max_emails_per_day": int(os.getenv("MAX_EMAILS_PER_DAY", "150") or 150),
        "send_delay_seconds": int(os.getenv("SEND_DELAY_SECONDS", "3") or 3),
        "azure_configured": bool(os.getenv("AZURE_CLIENT_SECRET")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "zoominfo_configured": bool(os.getenv("ZOOMINFO_PRIVATE_KEY")),
    }

@router.post("/api/settings")
def save_settings(request: SettingsRequest) -> dict:
    """
    Save settings to .env file.
    Only updates operational, non-secret settings.
    """
    env_path = Path(".env")
    existing = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                existing[key.strip()] = val.strip()

    mapping = {
        "SENDER_EMAIL": request.sender_email,
        "OPENAI_MODEL": request.openai_model,
        "ZOOMINFO_ENABLED": "true" if request.zoominfo_enabled else "false",
        "MAX_EMAILS_PER_DAY": str(request.max_emails_per_day),
        "SEND_DELAY_SECONDS": str(request.send_delay_seconds),
    }

    always_update = {
        "ZOOMINFO_ENABLED",
        "MAX_EMAILS_PER_DAY",
        "SEND_DELAY_SECONDS",
    }
    updated = []
    for key, value in mapping.items():
        if (value and value not in ("", "false")) or key in always_update:
            existing[key] = value
            updated.append(key)

    env_path.write_text(
        "\n".join(f"{key}={value}" for key, value in existing.items()) + "\n",
        encoding="utf-8",
    )
    for key, value in existing.items():
        os.environ[key] = value

    import importlib
    import src.config as config_module

    importlib.reload(config_module)
    globals()["settings"] = config_module.settings

    return {"saved": True, "updated": updated}

@router.post("/api/settings/test-email")
def test_email_connection() -> dict:
    """Send a test email to the sender's own address."""
    from dotenv import load_dotenv as _load_dotenv
    import msal as _msal
    import requests as _requests

    _load_dotenv(override=True)
    tenant_id = os.getenv("AZURE_TENANT_ID", "")
    client_id = os.getenv("AZURE_CLIENT_ID", "")
    client_secret = os.getenv("AZURE_CLIENT_SECRET", "")
    sender_email = os.getenv("SENDER_EMAIL", "")

    missing = []
    if not tenant_id:
        missing.append("AZURE_TENANT_ID")
    if not client_id:
        missing.append("AZURE_CLIENT_ID")
    if not client_secret:
        missing.append("AZURE_CLIENT_SECRET")
    if not sender_email:
        missing.append("SENDER_EMAIL")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing in .env: {', '.join(missing)}",
        )

    try:
        app_msal = _msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
        result = app_msal.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise HTTPException(
                status_code=401,
                detail=f"Token failed: {result.get('error_description')}",
            )

        response = _requests.post(
            f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail",
            headers={
                "Authorization": f"Bearer {result['access_token']}",
                "Content-Type": "application/json",
            },
            json={
                "message": {
                    "subject": "RC Sales Automation - Connection Test",
                    "body": {
                        "contentType": "Text",
                        "content": (
                            "This is a test email from RC Sales Automation.\n"
                            "Microsoft Graph API connection is working correctly."
                        ),
                    },
                    "toRecipients": [
                        {"emailAddress": {"address": sender_email}}
                    ],
                },
                "saveToSentItems": True,
            },
            timeout=15,
        )

        if response.status_code == 202:
            return {
                "success": True,
                "message": f"Test email sent to {sender_email}",
            }

        raise HTTPException(
            status_code=response.status_code,
            detail=f"Graph API error: {response.text[:200]}",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@router.get("/api/knowledge-bases")
def list_knowledge_bases() -> list[str]:
    return KnowledgeBaseLoader.list_kb_files()

@router.post("/api/knowledge-bases/upload")
async def upload_kb_file(file: UploadFile = File(...)) -> dict:
    """
    Upload a knowledge base file to the knowledge_base/ folder.
    Supports .txt, .pdf, .docx
    Converts PDF and DOCX to plain text automatically.
    """
    from pathlib import Path

    kb_dir = Path("knowledge_base")
    kb_dir.mkdir(exist_ok=True)

    filename = file.filename or "uploaded.txt"
    ext = Path(filename).suffix.lower()

    if ext not in (".txt", ".pdf", ".docx"):
        raise HTTPException(
            status_code=400,
            detail="Only .txt, .pdf, and .docx files are supported",
        )

    contents = await file.read()

    if ext == ".txt":
        text = contents.decode("utf-8", errors="ignore")

    elif ext == ".pdf":
        try:
            import io
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(contents))
            pages = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pages.append(t.strip())
            text = "\n\n".join(pages)
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="pypdf not installed. Run: pip install pypdf",
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"PDF read failed: {e}",
            )

    elif ext == ".docx":
        try:
            import io
            import docx

            doc = docx.Document(io.BytesIO(contents))
            text = "\n\n".join(
                p.text for p in doc.paragraphs if p.text.strip()
            )
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="python-docx not installed. Run: pip install python-docx",
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"DOCX read failed: {e}",
            )

    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="File appears to be empty or could not be read",
        )

    save_name = Path(filename).stem + ".txt"
    save_path = kb_dir / save_name

    counter = 1
    while save_path.exists():
        save_name = f"{Path(filename).stem}_{counter}.txt"
        save_path = kb_dir / save_name
        counter += 1

    save_path.write_text(text, encoding="utf-8")

    return {
        "uploaded": True,
        "filename": save_name,
        "characters": len(text),
        "message": f"Saved as {save_name} ({len(text):,} characters)",
    }

@router.get("/api/jobs")
def list_jobs(limit: int = Query(default=20, ge=1, le=200)) -> list[dict]:
    return job_repo.list_recent(limit)

@router.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = job_repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = job_repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job_repo.request_cancel(job_id)
    return job_repo.get(job_id) or job

@router.get("/api/send-policy/status")
def send_policy_status() -> dict:
    return SendPolicy().status()

@router.get("/api/inbox-monitor/status")
def inbox_monitor_status() -> dict:
    return get_inbox_monitor_status()

@router.get("/api/scheduler/status")
def scheduler_status() -> dict:
    enabled = os.getenv("SCHEDULER_ENABLED", "true").lower() != "false"
    last_tick_at = kv_repo.get("scheduler_last_tick") or None
    seconds_since_tick = None
    if last_tick_at:
        try:
            seconds_since_tick = int(
                (datetime.utcnow() - datetime.fromisoformat(last_tick_at))
                .total_seconds()
            )
        except ValueError:
            seconds_since_tick = None
    return {
        "enabled": enabled,
        "last_tick_at": last_tick_at,
        "seconds_since_tick": seconds_since_tick,
        "healthy": seconds_since_tick is not None and seconds_since_tick < 180,
    }

@router.get("/api/reply-monitor/status")
def reply_monitor_status() -> dict:
    # Backward-compatible alias for the Phase 1.2 endpoint name.
    return inbox_monitor_status()
