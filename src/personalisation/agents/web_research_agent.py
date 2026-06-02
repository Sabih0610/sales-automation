import logging
import random
import time

from playwright.sync_api import sync_playwright

from src.models import Lead
from src.personalisation.models import ResearchResult


class WebResearchAgent:
    """
    Scrapes company website to extract business context.
    Falls back to role inference if no domain available.
    No browser opened if domain is empty.
    """

    MAX_CHARS = 3000

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def research(self, lead: Lead) -> ResearchResult:
        if lead.company_domain:
            return self._scrape_website(lead)
        elif lead.title or lead.company:
            return self._infer_from_role(lead)
        else:
            return ResearchResult(
                lead_id=lead.id,
                research_source="none",
                error="No domain or title available",
            )

    def _scrape_website(self, lead: Lead) -> ResearchResult:
        """Visit homepage and about page, extract visible text."""
        domain = lead.company_domain
        if not domain.startswith("http"):
            base_url = f"https://{domain}"
        else:
            base_url = domain

        pages_to_try = [
            base_url,
            f"{base_url}/about",
            f"{base_url}/about-us",
            f"{base_url}/company",
        ]

        all_text = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_extra_http_headers({
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
                    )
                })
                for url in pages_to_try[:2]:
                    try:
                        page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=15000,
                        )
                        time.sleep(random.uniform(1, 2))
                        text = page.evaluate(
                            """
                            () => {
                                ['script','style','nav','footer',
                                 'header','noscript'].forEach(t =>
                                    document.querySelectorAll(t)
                                    .forEach(el => el.remove()));
                                return document.body
                                       ? document.body.innerText : '';
                            }
                            """
                        )
                        if text and len(text.strip()) > 100:
                            all_text.append(text.strip()[:self.MAX_CHARS])
                    except Exception as e:
                        self.logger.debug(f"Page {url} failed: {e}")
                        continue
                browser.close()
        except Exception as e:
            return ResearchResult(
                lead_id=lead.id,
                company_name=lead.company,
                research_source="website",
                error=str(e),
            )

        combined = "\n\n".join(all_text)[:self.MAX_CHARS * 2]
        return ResearchResult(
            lead_id=lead.id,
            company_name=lead.company,
            website_text=combined,
            research_source="website" if combined else "none",
        )

    def _infer_from_role(self, lead: Lead) -> ResearchResult:
        """
        Build context from job title + company name alone.
        Used when no domain is available.
        """
        title = lead.title or ""
        company = lead.company or ""
        location = lead.location or ""

        context_parts = []
        if title:
            context_parts.append(f"Job title: {title}")
        if company:
            context_parts.append(f"Company: {company}")
        if location:
            context_parts.append(f"Location: {location}")

        title_lower = title.lower()
        if any(t in title_lower for t in ["cto", "chief technology", "vp engineer"]):
            context_parts.append(
                "Typical concerns: infrastructure costs, tech debt, "
                "engineering velocity, cloud strategy, team productivity."
            )
        elif any(t in title_lower for t in ["cio", "chief information"]):
            context_parts.append(
                "Typical concerns: digital transformation, IT governance, "
                "vendor consolidation, data security, system integration."
            )
        elif any(t in title_lower for t in ["data", "analytics", "bi", "insight"]):
            context_parts.append(
                "Typical concerns: data silos, slow reporting pipelines, "
                "data quality, self-service analytics, real-time insights."
            )
        elif any(t in title_lower for t in ["cxo", "ceo", "chief exec"]):
            context_parts.append(
                "Typical concerns: business growth, operational efficiency, "
                "competitive advantage, digital transformation ROI."
            )

        person_context = "\n".join(context_parts)
        return ResearchResult(
            lead_id=lead.id,
            company_name=company,
            person_context=person_context,
            research_source="role_inference",
        )
