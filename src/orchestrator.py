##src\orchestrator.py

import logging
import threading
from typing import Callable, Optional

from src.agents.base import BaseAgent
from src.agents.export_agent import ExportAgent
from src.agents.scraper_agent import ScraperAgent
from src.agents.segment_agent import SegmentAgent
from src.config import settings
from src.models import AgentEvent, EventType, PipelineRun, RunStatus, datetime
from src.storage import lead_repo, run_repo


def _error_text(exc: Exception, fallback: str = "Unknown pipeline error") -> str:
    return str(exc) or repr(exc) or fallback


class PipelineOrchestrator:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._event_handlers: list[Callable[[AgentEvent], None]] = []
        self._active_run: Optional[PipelineRun] = None
        self._lock = threading.Lock()

    def on_event(self, handler: Callable[[AgentEvent], None]) -> None:
        self._event_handlers.append(handler)

    def _broadcast(self, event: AgentEvent) -> None:
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as exc:
                self.logger.warning(
                    "Event handler error: %s",
                    _error_text(exc, "Unknown event handler error"),
                )

    def _wire_agent(self, agent: BaseAgent) -> None:
        agent.on_event(self._broadcast)

    def _save_run(self, run: PipelineRun) -> None:
        try:
            run_repo.save(run)
        except Exception as exc:
            self.logger.warning(
                "Run persistence error: %s",
                _error_text(exc, "Unknown run persistence error"),
            )

    def _save_leads(self, run: PipelineRun, leads: list) -> None:
        try:
            lead_repo.save_batch(run.id, leads)
            run_repo.save(run)
        except Exception as exc:
            self.logger.warning(
                "Lead persistence error: %s",
                _error_text(exc, "Unknown lead persistence error"),
            )

    def start_pipeline(self, filters: dict) -> PipelineRun:
        with self._lock:
            if self._active_run and self._active_run.status == RunStatus.RUNNING:
                raise RuntimeError("A pipeline run is already in progress")
            run = PipelineRun(
                filters=filters,
                enrichment_mode=settings.enrichment_mode,
            )
            self._active_run = run
            self._save_run(run)

        def _run() -> None:
            run.status = RunStatus.RUNNING
            self._save_run(run)
            self._broadcast(
                AgentEvent(EventType.PIPELINE_STARTED, "Orchestrator", run.id)
            )
            try:
                scraper = ScraperAgent(run, filters)
                self._wire_agent(scraper)
                leads = scraper.execute()
                self._save_leads(run, leads)
                run.total_enriched = 0
                self._save_leads(run, leads)

                segmenter = SegmentAgent(run, leads)
                self._wire_agent(segmenter)
                leads = segmenter.execute()
                self._save_leads(run, leads)

                exporter = ExportAgent(run, leads)
                self._wire_agent(exporter)
                output_files = exporter.execute()
                self._save_leads(run, leads)

                run.status = RunStatus.COMPLETED
                run.completed_at = datetime.utcnow()
                self._save_run(run)
                self._broadcast(
                    AgentEvent(
                        EventType.PIPELINE_COMPLETED,
                        "Orchestrator",
                        run.id,
                        payload={"files": output_files, **run.summary()},
                    )
                )
            except Exception as exc:
                error_message = _error_text(exc, "Unknown pipeline error")
                run.status = RunStatus.FAILED
                run.error = error_message
                run.completed_at = datetime.utcnow()
                self._save_run(run)
                self._broadcast(
                    AgentEvent(
                        EventType.PIPELINE_FAILED,
                        "Orchestrator",
                        run.id,
                        error=error_message,
                    )
                )
                self.logger.exception("Pipeline failed")

        thread = threading.Thread(
            target=_run,
            daemon=True,
            name=f"pipeline-{run.id[:8]}",
        )
        thread.start()
        return run


    def resume_pipeline(self, run_id: str) -> PipelineRun:
        existing = run_repo.get(run_id)
        if existing is None:
            raise RuntimeError("Run not found")

        with self._lock:
            if self._active_run and self._active_run.status == RunStatus.RUNNING:
                raise RuntimeError("A pipeline run is already in progress")

            existing.status = RunStatus.RUNNING
            existing.error = ""
            existing.completed_at = None
            filters = {
                **(existing.filters or {}),
                "resume_from_checkpoint": True,
            }
            existing.filters = filters
            self._active_run = existing
            self._save_run(existing)

        def _run() -> None:
            self._broadcast(
                AgentEvent(EventType.PIPELINE_STARTED, "Orchestrator", existing.id)
            )

            try:
                scraper = ScraperAgent(existing, filters)
                self._wire_agent(scraper)
                leads = scraper.execute()
                self._save_leads(existing, leads)

                segmenter = SegmentAgent(existing, leads)
                self._wire_agent(segmenter)
                leads = segmenter.execute()
                self._save_leads(existing, leads)

                exporter = ExportAgent(existing, leads)
                self._wire_agent(exporter)
                output_files = exporter.execute()
                self._save_leads(existing, leads)

                existing.status = RunStatus.COMPLETED
                existing.completed_at = datetime.utcnow()
                self._save_run(existing)
                self._broadcast(
                    AgentEvent(
                        EventType.PIPELINE_COMPLETED,
                        "Orchestrator",
                        existing.id,
                        payload={"files": output_files, **existing.summary()},
                    )
                )
            except Exception as exc:
                error_message = _error_text(exc, "Unknown pipeline error")
                existing.status = RunStatus.FAILED
                existing.error = error_message
                existing.completed_at = datetime.utcnow()
                self._save_run(existing)
                self._broadcast(
                    AgentEvent(
                        EventType.PIPELINE_FAILED,
                        "Orchestrator",
                        existing.id,
                        error=error_message,
                    )
                )
                self.logger.exception("Pipeline resume failed")

        thread = threading.Thread(
            target=_run,
            daemon=True,
            name=f"pipeline-resume-{existing.id[:8]}",
        )
        thread.start()
        return existing


    def get_active_run(self) -> Optional[PipelineRun]:
        return self._active_run

    def get_status(self) -> dict:
        if not self._active_run:
            return {"status": "idle"}
        return self._active_run.summary()
