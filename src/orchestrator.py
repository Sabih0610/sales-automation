##src\orchestrator.py

import logging
import threading
from typing import Callable, Optional

from src.agents.base import BaseAgent
from src.agents.enrichment_agent import EnrichmentAgent
from src.agents.export_agent import ExportAgent
from src.agents.scraper_agent import ScraperAgent
from src.agents.segment_agent import SegmentAgent
from src.config import settings
from src.models import AgentEvent, EventType, PipelineRun, RunStatus, datetime
from src.storage import lead_repo, run_repo


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
                self.logger.warning(f"Event handler error: {exc}")

    def _wire_agent(self, agent: BaseAgent) -> None:
        agent.on_event(self._broadcast)

    def _save_run(self, run: PipelineRun) -> None:
        try:
            run_repo.save(run)
        except Exception as exc:
            self.logger.warning(f"Run persistence error: {exc}")

    def _save_leads(self, run: PipelineRun, leads: list) -> None:
        try:
            lead_repo.save_batch(run.id, leads)
            run_repo.save(run)
        except Exception as exc:
            self.logger.warning(f"Lead persistence error: {exc}")

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

                enricher = EnrichmentAgent(run, leads)
                self._wire_agent(enricher)
                leads = enricher.execute()
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
                run.status = RunStatus.FAILED
                run.error = str(exc)
                run.completed_at = datetime.utcnow()
                self._save_run(run)
                self._broadcast(
                    AgentEvent(
                        EventType.PIPELINE_FAILED,
                        "Orchestrator",
                        run.id,
                        error=str(exc),
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

    def get_active_run(self) -> Optional[PipelineRun]:
        return self._active_run

    def get_status(self) -> dict:
        if not self._active_run:
            return {"status": "idle"}
        return self._active_run.summary()
