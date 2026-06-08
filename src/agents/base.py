## src\agents\base.py
from abc import ABC, abstractmethod
import logging
from typing import Any, Callable

from src.models import AgentEvent, EventType, PipelineRun


class BaseAgent(ABC):
    def __init__(self, run: PipelineRun):
        self.run = run
        self.logger = logging.getLogger(self.__class__.__name__)
        self._event_handlers: list[Callable[[AgentEvent], None]] = []

    def on_event(self, handler: Callable[[AgentEvent], None]) -> None:
        self._event_handlers.append(handler)

    def emit(
        self,
        event_type: EventType,
        payload: dict | None = None,
        error: str = "",
    ) -> None:
        event = AgentEvent(
            event_type=event_type,
            agent_name=self.__class__.__name__,
            run_id=self.run.id,
            payload=payload or {},
            error=error,
        )
        for handler in self._event_handlers:
            handler(event)
        self.logger.info(f"[{event_type.value}] {payload}")

    @abstractmethod
    def run_agent(self) -> Any:
        pass

    def execute(self) -> Any:
        self.emit(EventType.AGENT_STARTED)
        try:
            result = self.run_agent()
            result_count = len(result) if hasattr(result, "__len__") else 1
            self.emit(
                EventType.AGENT_COMPLETED,
                payload={"result_count": result_count},
            )
            return result
        except Exception as exc:
            self.emit(EventType.AGENT_FAILED, error=str(exc))
            self.logger.exception("Agent failed")
            raise
