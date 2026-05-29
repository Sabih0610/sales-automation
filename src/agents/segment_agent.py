from src.agents.base import BaseAgent
from src.config import settings
from src.models import (
    EnrichmentMode,
    EventType,
    Lead,
    LeadStatus,
    PipelineRun,
    Segment,
)


class SegmentAgent(BaseAgent):
    def __init__(self, run: PipelineRun, leads: list[Lead]):
        super().__init__(run)
        self.leads = leads

    def _assign(self, lead: Lead) -> Segment:
        if not lead.email:
            return Segment.NO_EMAIL
        if settings.enrichment_mode == EnrichmentMode.ZOOMINFO:
            return Segment.WARM if lead.intent_score > 0 else Segment.COLD
        return Segment.WARM if lead.email_confidence == "verified" else Segment.COLD

    def run_agent(self) -> list[Lead]:
        for lead in self.leads:
            lead.segment = self._assign(lead)
            lead.status = LeadStatus.SEGMENTED
            self.emit(
                EventType.LEAD_SEGMENTED,
                {"lead_id": lead.id, "segment": lead.segment.value},
            )
        warm = [lead for lead in self.leads if lead.segment == Segment.WARM]
        warm.sort(key=lambda lead: lead.intent_score, reverse=True)
        cold = [lead for lead in self.leads if lead.segment == Segment.COLD]
        no_email = [lead for lead in self.leads if lead.segment == Segment.NO_EMAIL]
        self.run.total_warm = len(warm)
        self.run.total_cold = len(cold)
        self.run.total_no_email = len(no_email)
        return warm + cold + no_email
