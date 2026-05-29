import json
import logging
import random
import time
import urllib.parse

from playwright.sync_api import Page, sync_playwright

from src.agents.base import BaseAgent
from src.config import settings
from src.models import EventType, Lead, LeadStatus, PipelineRun
from src.storage import lead_repo, run_repo


class ScraperAgent(BaseAgent):
    PAGE_SIZE = 25
    SALES_NAV_SEARCH_URL = "https://www.linkedin.com/sales/search/people"
    SALES_NAV_API_URL = "https://www.linkedin.com/sales-api/salesApiLeadSearch"

    def __init__(self, run: PipelineRun, filters: dict):
        super().__init__(run)
        self.filters = filters
        self._intercepted_leads: list[Lead] = []
        self._seen_lead_keys: set[str] = set()
        self._total_available = 0

    def _login_if_needed(self, page: Page) -> None:
        page.goto(
            self.SALES_NAV_SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        if any(x in page.url for x in ["login", "checkpoint", "authwall"]):
            raise RuntimeError(
                "LinkedIn is not logged in on your Chrome profile.\n"
                "Open Chrome manually, log into LinkedIn, then run again."
            )
        page.wait_for_load_state("networkidle", timeout=60000)
        self.logger.info("Sales Navigator loaded using existing Chrome session")

    def _apply_filters(self, page: Page) -> None:
        """
        Apply search filters via URL params. Sales Navigator supports direct
        filter params in the URL; keyword is the minimum supported here.
        """
        params = []
        if self.filters.get("keywords"):
            kw = urllib.parse.quote(self.filters["keywords"])
            params.append(f"keywords={kw}")

        url = self.SALES_NAV_SEARCH_URL
        if params:
            url = url + "?" + "&".join(params)

        page.goto(url, wait_until="networkidle")
        time.sleep(random.uniform(2, 4))

    def _lead_key(self, lead: Lead) -> str:
        return lead.linkedin_url or "|".join(
            [lead.full_name, lead.title, lead.company, lead.location]
        )

    def _setup_interception(self, page: Page) -> None:
        """
        Intercept Sales Navigator API responses and extract lead data from JSON.
        The browser makes the request; this scraper reads the response payload.
        """

        def handle_response(response) -> None:
            if "salesApiLeadSearch" not in response.url:
                return
            try:
                data = response.json()
                elements = data.get("elements", [])
                if not self._total_available:
                    self._total_available = data.get("paging", {}).get("total", 0)
                for raw in elements:
                    lead = self._parse_lead(raw)
                    key = self._lead_key(lead)
                    if key in self._seen_lead_keys:
                        continue
                    self._seen_lead_keys.add(key)
                    self._intercepted_leads.append(lead)
                    self.emit(
                        EventType.LEAD_SCRAPED,
                        {
                            "lead_id": lead.id,
                            "name": lead.full_name,
                            "total_so_far": len(self._intercepted_leads),
                        },
                    )
            except Exception as exc:
                self.logger.warning(f"Failed to parse intercepted response: {exc}")

        page.on("response", handle_response)

    def _navigate_pages(self, page: Page) -> None:
        """
        Navigate through Sales Navigator pages by clicking Next. Each page load
        triggers an API response that _setup_interception reads.
        """
        max_leads = settings.max_leads or 999999

        while len(self._intercepted_leads) < max_leads:
            time.sleep(random.uniform(12, 16))

            total_target = min(self._total_available or max_leads, max_leads)
            self.logger.info(
                "Page complete. Leads so far: "
                f"{len(self._intercepted_leads)}/{total_target}"
            )

            lead_repo.save_batch(self.run.id, self._intercepted_leads)
            current_page = len(self._intercepted_leads) // self.PAGE_SIZE
            run_repo.update_checkpoint(
                run_id=self.run.id,
                last_page=current_page,
                leads_collected=len(self._intercepted_leads),
            )

            if len(self._intercepted_leads) >= max_leads:
                break

            next_btn = page.query_selector(
                'button[aria-label="Next"],'
                '[data-test-pagination-page-btn="next"],'
                'button:has-text("Next")'
            )

            if not next_btn:
                self.logger.info("No Next button found - reached last page")
                break

            if next_btn.is_disabled():
                self.logger.info("Next button disabled - reached last page")
                break

            next_btn.click()
            self.logger.info("Navigated to next page")

    def _parse_lead(self, raw: dict) -> Lead:
        pos = (raw.get("currentPositions") or [{}])[0]
        pub = raw.get("publicIdentifier", "")
        urn = raw.get("entityUrn", "")

        if pub:
            linkedin_url = f"https://www.linkedin.com/in/{pub}"
        elif urn:
            parts = urn.split("(")
            person_id = parts[1].split(",")[0] if len(parts) > 1 else ""
            linkedin_url = (
                f"https://www.linkedin.com/sales/people/{person_id}"
                if person_id
                else ""
            )
        else:
            linkedin_url = ""

        company_urn = pos.get("companyUrn", "")
        company_url = ""
        if company_urn and ":" in company_urn:
            company_id = company_urn.split(":")[-1]
            company_url = f"https://www.linkedin.com/company/{company_id}"

        return Lead(
            full_name=raw.get("fullName", "").strip(),
            first_name=raw.get("firstName", "").strip(),
            last_name=raw.get("lastName", "").strip(),
            title=pos.get("title", "").strip(),
            company=(pos.get("companyName") or raw.get("companyName", "")).strip(),
            location=raw.get("geoRegion", raw.get("location", "")).strip(),
            linkedin_url=linkedin_url,
            company_linkedin_url=company_url,
            status=LeadStatus.SCRAPED,
        )

    def run_agent(self) -> list[Lead]:
        with sync_playwright() as playwright:
            import os

            chrome_user_data = os.path.expanduser(
                r"C:\Users\SabihAamir\AppData\Local\Google\Chrome\User Data"
            )

            context = playwright.chromium.launch_persistent_context(
                user_data_dir=chrome_user_data,
                channel="chrome",
                headless=False,
                slow_mo=300,
                args=[
                    "--start-maximized",
                    "--disable-blink-features=AutomationControlled",
                    "--profile-directory=Default",
                ],
            )
            page = context.new_page()

            self._setup_interception(page)
            self._login_if_needed(page)
            self._apply_filters(page)
            self._navigate_pages(page)

            context.close()

        leads = self._intercepted_leads
        if settings.max_leads:
            leads = leads[: settings.max_leads]

        self.run.total_scraped = len(leads)
        self.logger.info(f"Scraping complete. Total leads: {len(leads)}")
        return leads
