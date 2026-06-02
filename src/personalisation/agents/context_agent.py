import logging

from src.models import Lead
from src.personalisation.knowledge_base import ContextRetriever
from src.personalisation.models import (
    CampaignConfig,
    RelevantContext,
    ResearchResult,
)


class ContextAgent:
    """
    Retrieves relevant KB chunks for a lead.
    Uses TF-IDF scoring - no OpenAI calls here.
    """

    def __init__(self, campaign: CampaignConfig):
        self.campaign = campaign
        self.retriever = ContextRetriever(campaign)
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_context(
        self,
        lead: Lead,
        research: ResearchResult,
    ) -> RelevantContext:
        """
        Build a query from lead + research data,
        retrieve most relevant KB chunks.
        """
        query_parts = []

        if lead.title:
            query_parts.append(lead.title)
        if lead.company:
            query_parts.append(lead.company)
        if research.website_text:
            query_parts.append(research.website_text[:500])
        if research.person_context:
            query_parts.append(research.person_context)

        query_parts.extend(self.campaign.key_pain_points)

        query = " ".join(query_parts)

        context = self.retriever.retrieve(
            lead_id=lead.id,
            query=query,
        )

        self.logger.info(
            f"Context for {lead.full_name}: "
            f"{len(context.chunks)} chunks from "
            f"{set(c.source_file for c in context.chunks)}"
        )
        return context
