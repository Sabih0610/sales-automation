from dataclasses import fields
import math
import pathlib
import re

from src.personalisation.models import CampaignConfig, KBChunk, RelevantContext


KB_DIR = pathlib.Path("knowledge_base")
CHUNK_SIZE = 400
CHUNK_OVERLAP = 50
TOP_K = 4


class KnowledgeBaseLoader:
    @staticmethod
    def load_campaign(campaign_file: str) -> CampaignConfig:
        """Load campaign config by legacy filename or display name."""
        from src.storage import campaign_repo

        campaign = campaign_repo.get_by_filename(campaign_file)
        if not campaign:
            for item in campaign_repo.list_all():
                if item.get("name") == campaign_file:
                    campaign = item
                    break
        if not campaign:
            raise FileNotFoundError(f"Campaign not found: {campaign_file}")
        raw_data = {
            "name": campaign.get("name", ""),
            "description": campaign.get("description", ""),
            **(campaign.get("config") or {}),
        }

        allowed_fields = {field.name for field in fields(CampaignConfig)}
        data = {
            key: value
            for key, value in raw_data.items()
            if key in allowed_fields
        }

        return CampaignConfig(**data)

    @staticmethod
    def list_campaigns() -> list[dict]:
        """Return list of all campaign configs as dicts."""
        from src.storage import campaign_repo

        return campaign_repo.list_all()

    @staticmethod
    def list_kb_files() -> list[str]:
        """Return all .txt filenames in knowledge_base/ folder."""
        if not KB_DIR.exists():
            return []
        return sorted(f.name for f in KB_DIR.glob("*.txt"))

    @staticmethod
    def load_kb_file(filename: str) -> str:
        """Load raw text from a KB file."""
        path = KB_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"KB file not found: {filename}")
        return path.read_text(encoding="utf-8")


class KBChunker:
    @staticmethod
    def chunk_text(text: str, source_file: str) -> list[KBChunk]:
        """
        Split text into overlapping word chunks.
        Returns list of KBChunk objects.
        """
        words = text.split()
        chunks = []
        start = 0
        while start < len(words):
            end = min(start + CHUNK_SIZE, len(words))
            chunk_text = " ".join(words[start:end])
            chunks.append(KBChunk(
                source_file=source_file,
                content=chunk_text,
            ))
            if end >= len(words):
                break
            start += CHUNK_SIZE - CHUNK_OVERLAP
        return chunks


class TFIDFRetriever:
    """
    Simple TF-IDF keyword retrieval.
    No external dependencies - pure Python.
    Scores chunks by relevance to a query string.
    """

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z]+", text.lower())

    @staticmethod
    def _tf(tokens: list[str]) -> dict[str, float]:
        count = {}
        for t in tokens:
            count[t] = count.get(t, 0) + 1
        total = len(tokens) or 1
        return {t: c / total for t, c in count.items()}

    @staticmethod
    def _idf(term: str, all_docs: list[list[str]]) -> float:
        containing = sum(1 for doc in all_docs if term in doc)
        if containing == 0:
            return 0.0
        return math.log(len(all_docs) / containing)

    @classmethod
    def score(
        cls,
        query: str,
        chunks: list[KBChunk],
    ) -> list[KBChunk]:
        """
        Score chunks by TF-IDF relevance to query.
        Returns chunks sorted by score descending.
        """
        query_tokens = set(cls._tokenize(query))
        all_tokens = [cls._tokenize(c.content) for c in chunks]

        scored = []
        for i, chunk in enumerate(chunks):
            chunk_tokens = all_tokens[i]
            tf = cls._tf(chunk_tokens)
            score = 0.0
            for term in query_tokens:
                if term in tf:
                    idf = cls._idf(term, all_tokens)
                    score += tf[term] * idf
            chunk.relevance_score = score
            scored.append(chunk)

        return sorted(scored, key=lambda c: c.relevance_score, reverse=True)


class ContextRetriever:
    """
    Main RAG retrieval class.
    Loads KB files for a campaign, chunks them,
    scores against lead context, returns top K chunks.
    """

    def __init__(self, campaign: CampaignConfig):
        self.campaign = campaign
        self._chunks: list[KBChunk] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        for kb_file in self.campaign.knowledge_bases:
            try:
                text = KnowledgeBaseLoader.load_kb_file(kb_file)
                self._chunks.extend(
                    KBChunker.chunk_text(text, kb_file)
                )
            except FileNotFoundError:
                continue
        self._loaded = True

    def retrieve(
        self,
        lead_id: str,
        query: str,
        top_k: int = TOP_K,
    ) -> RelevantContext:
        """
        Retrieve most relevant KB chunks for a lead query.
        Query = combination of lead title + company + research text.
        """
        self._ensure_loaded()

        if not self._chunks:
            return RelevantContext(
                lead_id=lead_id,
                campaign_name=self.campaign.name,
                total_kb_files_searched=0,
            )

        scored = TFIDFRetriever.score(query, list(self._chunks))
        top_chunks = [c for c in scored[:top_k] if c.relevance_score > 0]

        if not top_chunks:
            seen_files = set()
            for chunk in self._chunks:
                if chunk.source_file not in seen_files:
                    top_chunks.append(chunk)
                    seen_files.add(chunk.source_file)
                    if len(top_chunks) >= top_k:
                        break

        return RelevantContext(
            lead_id=lead_id,
            campaign_name=self.campaign.name,
            chunks=top_chunks,
            total_kb_files_searched=len(self.campaign.knowledge_bases),
        )
