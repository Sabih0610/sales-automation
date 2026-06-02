from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ResearchResult:
    lead_id: str
    company_name: str = ""
    website_text: str = ""
    person_context: str = ""
    research_source: str = ""
    error: str = ""


@dataclass
class KBChunk:
    source_file: str
    content: str
    relevance_score: float = 0.0


@dataclass
class RelevantContext:
    lead_id: str
    campaign_name: str
    chunks: list[KBChunk] = field(default_factory=list)
    total_kb_files_searched: int = 0


@dataclass
class PersonalisedMessage:
    lead_id: str
    email_subject: str = ""
    email_body: str = ""
    linkedin_message: str = ""
    research_summary: str = ""
    kb_files_used: list[str] = field(default_factory=list)
    campaign_name: str = ""
    personalised_at: datetime = field(default_factory=datetime.utcnow)
    error: str = ""


@dataclass
class CampaignConfig:
    name: str
    description: str = ""
    knowledge_bases: list[str] = field(default_factory=list)
    target_personas: list[str] = field(default_factory=list)
    target_industries: list[str] = field(default_factory=list)
    tone: str = "professional"
    max_email_words: int = 150
    max_linkedin_chars: int = 280
    email_goal: str = "book a 20-minute discovery call"
    key_pain_points: list[str] = field(default_factory=list)
