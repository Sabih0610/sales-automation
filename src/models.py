##src\models.py

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4


class LeadStatus(Enum):
    SCRAPED = "SCRAPED"
    ENRICHED = "ENRICHED"
    SEGMENTED = "SEGMENTED"
    EXPORTED = "EXPORTED"
    FAILED = "FAILED"


class Segment(Enum):
    WARM = "WARM"
    COLD = "COLD"
    NO_EMAIL = "NO_EMAIL"


class EnrichmentMode(Enum):
    ZOOMINFO = "ZOOMINFO"
    FREE = "FREE"


class OutputFormat(Enum):
    CSV = "CSV"
    XLSX = "XLSX"


@dataclass(frozen=False)
class Lead:
    id: str = field(default_factory=lambda: uuid4().hex)
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    company: str = ""
    company_domain: str = ""
    location: str = ""
    linkedin_url: str = ""
    company_linkedin_url: str = ""
    email: str = ""
    email_confidence: str = ""
    phone: str = ""
    intent_score: float = 0.0
    segment: Segment = Segment.NO_EMAIL
    status: LeadStatus = LeadStatus.SCRAPED
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    method: str = ""

    def to_dict(self) -> dict:
        return {
            key: value.value if isinstance(value, Enum) else value
            for key, value in self.__dict__.items()
        }


@dataclass(frozen=False)
class EnrichmentResult:
    lead_id: str = ""
    success: bool = False
    email: str = ""
    email_confidence: str = ""
    phone: str = ""
    company_domain: str = ""
    intent_score: float = 0.0
    error: str = ""
    mode_used: EnrichmentMode = EnrichmentMode.FREE


class EventType(Enum):
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    AGENT_FAILED = "AGENT_FAILED"
    LEAD_SCRAPED = "LEAD_SCRAPED"
    LEAD_ENRICHED = "LEAD_ENRICHED"
    LEAD_SEGMENTED = "LEAD_SEGMENTED"
    LEAD_EXPORTED = "LEAD_EXPORTED"
    PIPELINE_STARTED = "PIPELINE_STARTED"
    PIPELINE_COMPLETED = "PIPELINE_COMPLETED"
    PIPELINE_FAILED = "PIPELINE_FAILED"


@dataclass(frozen=False)
class AgentEvent:
    event_type: EventType = EventType.AGENT_STARTED
    agent_name: str = ""
    run_id: str = ""
    payload: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    error: str = ""


class RunStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=False)
class PipelineRun:
    id: str = field(default_factory=lambda: uuid4().hex)
    status: RunStatus = RunStatus.PENDING
    filters: dict = field(default_factory=dict)
    enrichment_mode: EnrichmentMode = EnrichmentMode.FREE
    total_scraped: int = 0
    total_enriched: int = 0
    total_warm: int = 0
    total_cold: int = 0
    total_no_email: int = 0
    total_exported: int = 0
    error: str = ""
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    def summary(self) -> dict:
        return {
            "id": self.id,
            "status": self.status.value,
            "filters": self.filters,
            "enrichment_mode": self.enrichment_mode.value,
            "total_scraped": self.total_scraped,
            "total_enriched": self.total_enriched,
            "total_warm": self.total_warm,
            "total_cold": self.total_cold,
            "total_no_email": self.total_no_email,
            "total_exported": self.total_exported,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }
