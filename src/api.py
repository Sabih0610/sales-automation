from src.stale_run_recovery import recover_stale_running_runs
import asyncio
import sys

if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import asyncio
import logging
import os
import secrets
import threading

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.agents.reply_monitor import run_reply_monitor_loop
from src.api_helpers import (
    AgentEvent,
    _event_json,
    orchestrator,
)
from src.campaign_importer import import_campaign_seed_files_once
from src.job_worker import get_job_worker
from src.routers import campaigns, drafts, leads, public, queue, runs, settings, universes
from src.scheduler import run_scheduler_loop
from src.storage import event_repo, job_repo, outreach_repo, run_repo


logger = logging.getLogger(__name__)
send_policy_status = settings.send_policy_status
inbox_monitor_status = settings.inbox_monitor_status

def _is_production_env() -> bool:
    value = (
        os.getenv("APP_ENV", "")
        or os.getenv("ENVIRONMENT", "")
        or os.getenv("FASTAPI_ENV", "")
    ).strip().lower()
    return value in {"prod", "production"}


def _load_dashboard_api_key() -> str:
    api_key = os.getenv("DASHBOARD_API_KEY", "").strip()

    if api_key:
        if len(api_key) < 24:
            message = (
                "DASHBOARD_API_KEY is too short. Use at least 24 characters."
            )
            if _is_production_env():
                raise RuntimeError(message)
            logger.warning(message)
        return api_key

    if _is_production_env():
        raise RuntimeError(
            "DASHBOARD_API_KEY is required when APP_ENV=production "
            "or ENVIRONMENT=production."
        )

    generated_key = secrets.token_urlsafe(32)
    logger.warning(
        "DASHBOARD_API_KEY is missing. Generated a temporary development key. "
        "Set DASHBOARD_API_KEY in .env for stable dashboard access."
    )
    return generated_key


_DASHBOARD_API_KEY = _load_dashboard_api_key()


async def require_api_key(x_api_key: str = Header(default="")) -> None:
    if x_api_key != _DASHBOARD_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
        )


def validate_api_key_value(api_key: str) -> bool:
    return bool(api_key) and api_key == _DASHBOARD_API_KEY


def _cors_allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()

    if raw:
        origins = [
            origin.strip().rstrip("/")
            for origin in raw.split(",")
            if origin.strip()
        ]
        if _is_production_env() and "*" in origins:
            raise RuntimeError(
                "CORS_ALLOWED_ORIGINS cannot contain '*' in production."
            )
        return origins

    return [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]


app = FastAPI(title="Royal Cyber Lead Pipeline API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _request_api_key(request: Request) -> str:
    x_api_key = (request.headers.get("x-api-key") or "").strip()
    if x_api_key:
        return x_api_key

    authorization = (request.headers.get("authorization") or "").strip()
    prefix = "bearer "
    if authorization.lower().startswith(prefix):
        return authorization[len(prefix):].strip()
    return ""


@app.middleware("http")
async def protect_api_routes(request: Request, call_next):
    path = request.url.path
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    if path == "/api/health" or path.startswith("/u/"):
        return await call_next(request)
    if not path.startswith("/api/"):
        return await call_next(request)
    if validate_api_key_value(_request_api_key(request)):
        return await call_next(request)
    return JSONResponse(
        status_code=401,
        content={"detail": "Invalid or missing API key"},
    )


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


app.include_router(public.router)
app.include_router(runs.router)
app.include_router(campaigns.router)
app.include_router(universes.router)
app.include_router(drafts.router)
app.include_router(queue.router)
app.include_router(leads.router)
app.include_router(settings.router)


@app.websocket("/ws/runs/{run_id}")
async def websocket_run_events(websocket: WebSocket, run_id: str) -> None:
    api_key = (websocket.query_params.get("api_key") or "").strip()
    if not validate_api_key_value(api_key):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()


    def handler(event: AgentEvent) -> None:
        if event.run_id != run_id:
            return
        asyncio.run_coroutine_threadsafe(websocket.send_json(_event_json(event)), loop)

    orchestrator.on_event(handler)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if handler in orchestrator._event_handlers:
            orchestrator._event_handlers.remove(handler)


@app.on_event("startup")
def startup() -> None:
    def persist_event(event: AgentEvent) -> None:
        event_repo.save(event)
        active_run = orchestrator.get_active_run()
        if active_run and active_run.id == event.run_id:
            run_repo.save(active_run)

    orchestrator.on_event(persist_event)

    import_campaign_seed_files_once()

    job_repo.reset_stale_running_to_failed_on_startup()
    reset_drafts = outreach_repo.reset_stale_sending_to_failed_on_startup()
    if reset_drafts:
        logger.warning(
            "Reset %s interrupted sending drafts to failed on startup",
            reset_drafts,
        )
    job_worker = get_job_worker()
    app.state.job_worker = job_worker
    job_worker.start()
    logger.info("Job worker started")

    scheduler_enabled = os.getenv("SCHEDULER_ENABLED", "true").lower() != "false"
    if scheduler_enabled:
        existing_thread = getattr(app.state, "scheduler_thread", None)
        if not existing_thread or not existing_thread.is_alive():
            interval_seconds = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))
            stop_event = threading.Event()
            thread = threading.Thread(
                target=run_scheduler_loop,
                args=(stop_event, interval_seconds),
                daemon=True,
                name="scheduler",
            )
            app.state.scheduler_stop_event = stop_event
            app.state.scheduler_thread = thread
            thread.start()
            logger.info(
                "Scheduler started. Interval: %ss",
                interval_seconds,
            )

    reply_monitor_enabled = (
        os.getenv("REPLY_MONITOR_ENABLED", "false").lower() == "true"
    )
    if reply_monitor_enabled:
        existing_thread = getattr(app.state, "inbox_monitor_thread", None)
        if not existing_thread or not existing_thread.is_alive():
            interval_seconds = int(
                os.getenv("REPLY_MONITOR_INTERVAL_SECONDS", "300")
            )
            stop_event = threading.Event()
            thread = threading.Thread(
                target=run_reply_monitor_loop,
                args=(stop_event, interval_seconds),
                daemon=True,
                name="inbox-monitor",
            )

            app.state.inbox_monitor_stop_event = stop_event
            app.state.inbox_monitor_thread = thread
            thread.start()

            logger.info(
                "Inbox monitor started for replies and bounces. "
                f"Interval: {interval_seconds}s"
            )


@app.on_event("shutdown")
def shutdown() -> None:
    job_worker = getattr(app.state, "job_worker", None)
    if job_worker:
        job_worker.stop()
        logger.info("Job worker stopped")

    scheduler_stop_event = getattr(app.state, "scheduler_stop_event", None)
    if scheduler_stop_event:
        scheduler_stop_event.set()

    scheduler_thread = getattr(app.state, "scheduler_thread", None)
    if scheduler_thread and scheduler_thread.is_alive():
        scheduler_thread.join(timeout=5)

    stop_event = getattr(app.state, "inbox_monitor_stop_event", None)
    if stop_event:
        stop_event.set()

    thread = getattr(app.state, "inbox_monitor_thread", None)
    if thread and thread.is_alive():
        thread.join(timeout=5)

    logger.info("Inbox monitor stopped")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)

@app.on_event("startup")
def _recover_stale_running_runs_on_startup() -> None:
    recover_stale_running_runs()

