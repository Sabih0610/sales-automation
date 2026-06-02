import json
import logging
import os

from openai import OpenAI

from src.models import Lead
from src.personalisation.models import (
    CampaignConfig,
    PersonalisedMessage,
    RelevantContext,
    ResearchResult,
)


class WriterAgent:
    """
    Single OpenAI call per lead.
    Combines lead data + research + KB context into personalised messages.
    """

    def __init__(self, campaign: CampaignConfig):
        self.campaign = campaign
        self.logger = logging.getLogger(self.__class__.__name__)
        self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        self._model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _build_prompt(
        self,
        lead: Lead,
        research: ResearchResult,
        context: RelevantContext,
    ) -> str:
        kb_block = ""
        if context.chunks:
            kb_block = "\n\n".join(
                f"[From {c.source_file}]\n{c.content}"
                for c in context.chunks
            )

        lead_block_parts = []
        if lead.full_name:
            lead_block_parts.append(f"Name: {lead.full_name}")
        if lead.title:
            lead_block_parts.append(f"Title: {lead.title}")
        if lead.company:
            lead_block_parts.append(f"Company: {lead.company}")
        if lead.location:
            lead_block_parts.append(f"Location: {lead.location}")
        lead_block = "\n".join(lead_block_parts)

        research_block = ""
        if research.website_text:
            research_block = (
                f"Company website content:\n{research.website_text[:1500]}"
            )
        elif research.person_context:
            research_block = (
                f"Lead context (inferred from role):\n{research.person_context}"
            )

        tone_instruction = (
            "Write in a professional, concise B2B style."
            if self.campaign.tone == "professional"
            else "Write in a friendly, conversational tone - like one professional to another."
        )

        return f"""
You are an expert B2B sales copywriter for Royal Cyber, a Microsoft Gold Partner.

CAMPAIGN: {self.campaign.name}
GOAL: {self.campaign.email_goal}
TONE: {tone_instruction}

ROYAL CYBER KNOWLEDGE BASE (use this to ground your message):
{kb_block}

LEAD INFORMATION:
{lead_block}

RESEARCH ABOUT THEIR BUSINESS:
{research_block if research_block else "No website data available. Use role and company name to infer context."}

CAMPAIGN PAIN POINTS TO ADDRESS:
{chr(10).join("- " + p for p in self.campaign.key_pain_points)}

TASK:
Write personalised outreach for this specific lead.
Connect Royal Cyber's capabilities to THEIR specific business context.
Do not write generic messages. Reference something specific about them.

Return ONLY valid JSON with this exact structure:
{{
  "email_subject": "subject line under 10 words",
  "email_body": "3 short paragraphs, max {self.campaign.max_email_words} words total. Paragraph 1: specific hook about them. Paragraph 2: how Royal Cyber solves their specific challenge. Paragraph 3: clear CTA.",
  "linkedin_message": "under {self.campaign.max_linkedin_chars} characters. Conversational. Reference something specific about them.",
  "research_summary": "1 sentence: what you found about this lead that shaped the message"
}}

No markdown. No explanation. Only the JSON object.
"""

    def write(
        self,
        lead: Lead,
        research: ResearchResult,
        context: RelevantContext,
    ) -> PersonalisedMessage:
        prompt = self._build_prompt(lead, research, context)

        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=800,
            )
            content = (
                resp.choices[0].message.content
                .strip()
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )
            data = json.loads(content)

            return PersonalisedMessage(
                lead_id=lead.id,
                email_subject=data.get("email_subject", ""),
                email_body=data.get("email_body", ""),
                linkedin_message=data.get("linkedin_message", ""),
                research_summary=data.get("research_summary", ""),
                kb_files_used=[c.source_file for c in context.chunks],
                campaign_name=self.campaign.name,
            )

        except json.JSONDecodeError as e:
            self.logger.warning(f"JSON parse error for {lead.full_name}: {e}")
            return PersonalisedMessage(
                lead_id=lead.id,
                campaign_name=self.campaign.name,
                error=f"JSON parse error: {e}",
            )
        except Exception as e:
            self.logger.warning(f"OpenAI error for {lead.full_name}: {e}")
            return PersonalisedMessage(
                lead_id=lead.id,
                campaign_name=self.campaign.name,
                error=str(e),
            )
