import concurrent.futures
import logging

from src.models import Lead
from src.personalisation.agents.context_agent import ContextAgent
from src.personalisation.agents.web_research_agent import WebResearchAgent
from src.personalisation.agents.writer_agent import WriterAgent
from src.personalisation.knowledge_base import KnowledgeBaseLoader
from src.personalisation.models import (
    PersonalisedMessage,
    ResearchResult,
)
from src.storage import campaign_sequence_repo, lead_repo


def _load_touch_template(campaign_name: str, touch_number: int) -> dict:
    step = campaign_sequence_repo.get_step(
        campaign_name,
        touch_number,
        active_only=False,
    )
    if not step:
        return {}
    return {
        "number": step.touch_number,
        "name": step.touch_name,
        "delay_days": step.delay_days,
        "delay_value": step.delay_value,
        "delay_unit": step.delay_unit,
        "delay_type": step.delay_type,
        "send_time_mode": step.send_time_mode,
        "fixed_send_time": step.fixed_send_time,
        "subject_template": step.subject_template,
        "email_body_template": step.email_body_template,
        "linkedin_message_template": step.linkedin_message_template,
    }


class PersonalisationOrchestrator:
    """
    Phase 2 orchestrator.
    Takes a run_id + campaign_name.
    Personalises all leads from that run.
    Saves results back to DB.
    Completely separate from Phase 1 orchestrator.
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def _save_message(
        self,
        message: PersonalisedMessage,
        run_id: str,
    ) -> None:
        """Save personalised message fields back to leads table."""
        if message.error:
            self.logger.warning(
                f"Skipping save for {message.lead_id}: {message.error}"
            )
            return
        lead_repo.save_personalised_message(
            message.lead_id,
            message.email_subject,
            message.email_body,
            message.linkedin_message,
            message.research_summary,
            message.campaign_name,
        )

    def _personalise_one(
        self,
        lead: Lead,
        research_agent: WebResearchAgent,
        context_agent: ContextAgent,
        writer_agent: WriterAgent,
    ) -> PersonalisedMessage:
        """Process one lead through all 3 agents."""
        try:
            research = research_agent.research(lead)
            context = context_agent.get_context(lead, research)
            message = writer_agent.write(lead, research, context)
            self.logger.info(
                f"Personalised: {lead.full_name} | "
                f"campaign: {message.campaign_name}"
            )
            return message
        except Exception as e:
            self.logger.error(
                f"Failed to personalise {lead.full_name}: {e}"
            )
            from src.personalisation.models import PersonalisedMessage

            return PersonalisedMessage(
                lead_id=lead.id,
                error=str(e),
            )

    def run(
        self,
        run_id: str,
        campaign_name: str,
        max_workers: int = 3,
        lead_ids: list[str] | None = None,
        limit: int | None = None,
        prefer_email: bool = False,
    ) -> dict:
        """
        Main entry point.
        run_id: the Phase 1 run to personalise
        campaign_name: filename of campaign JSON
                       e.g. "fabric_retail_ctos.json"
        Returns summary dict.
        """
        campaign = KnowledgeBaseLoader.load_campaign(campaign_name)
        self.logger.info(
            f"Starting personalisation: campaign={campaign.name}, "
            f"run_id={run_id}"
        )

        all_leads = lead_repo.get_by_run(run_id)
        if not all_leads:
            return {"error": "No leads found for this run", "total": 0}

        selected_ids = set(lead_ids or [])
        if selected_ids:
            leads = [lead for lead in all_leads if lead.id in selected_ids]
        else:
            leads = list(all_leads)
            if prefer_email:
                leads = [lead for lead in leads if lead.email]
            if limit and limit > 0:
                leads = leads[:limit]

        skipped = 0
        if selected_ids:
            skipped += max(0, len(selected_ids) - len(leads))

        if not leads:
            return {
                "run_id": run_id,
                "campaign": campaign.name,
                "total": 0,
                "success": 0,
                "failed": 0,
                "skipped": skipped,
                "results": [],
            }

        self.logger.info(f"Personalising {len(leads)} selected leads...")

        research_agent = WebResearchAgent()
        context_agent = ContextAgent(campaign)
        touch1_template = _load_touch_template(campaign_name, 1)
        writer_agent = WriterAgent(campaign, touch1_template=touch1_template)

        results = []
        success = 0
        failed = 0

        def research_one(lead: Lead) -> ResearchResult:
            try:
                return research_agent.research(lead)
            except Exception as exc:
                self.logger.exception(
                    f"Research failed for {lead.full_name}: {exc}"
                )
                return ResearchResult(
                    lead_id=lead.id,
                    company_name=lead.company,
                    error=str(exc),
                )

        BATCH_SIZE = 5
        for i in range(0, len(leads), BATCH_SIZE):
            batch = leads[i:i + BATCH_SIZE]

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                research_results = list(executor.map(
                    research_one, batch
                ))

            for lead, research in zip(batch, research_results):
                try:
                    context = context_agent.get_context(lead, research)
                    message = writer_agent.write(lead, research, context)
                except Exception as exc:
                    self.logger.exception(
                        f"Failed to personalise {lead.full_name}: {exc}"
                    )
                    message = PersonalisedMessage(
                        lead_id=lead.id,
                        campaign_name=campaign.name,
                        error=str(exc),
                    )
                self._save_message(message, run_id)
                results.append(message)
                if message.error:
                    failed += 1
                else:
                    success += 1

        self.logger.info(
            f"Personalisation complete. "
            f"Success: {success}, Failed: {failed}"
        )

        return {
            "run_id": run_id,
            "campaign": campaign.name,
            "total": len(leads),
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "results": [
                {
                    "lead_id": message.lead_id,
                    "email_subject": message.email_subject,
                    "email_body": message.email_body,
                    "linkedin_message": message.linkedin_message,
                    "research_summary": message.research_summary,
                    "campaign_name": message.campaign_name,
                    "error": message.error,
                }
                for message in results
            ],
        }
