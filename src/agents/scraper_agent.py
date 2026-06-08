##src\agents\scraper_agent.py

import time, random, re, json, os, subprocess, threading, traceback

from openai import OpenAI
from playwright.sync_api import sync_playwright, Page, BrowserContext

from src.agents.base import BaseAgent
from src.config import settings
from src.models import EventType, Lead, LeadStatus, PipelineRun
from src.storage import run_repo


def safe_str(value) -> str:
    """Convert any AI-returned value into a clean string safely."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value).strip()
    if isinstance(value, list):
        return " ".join(safe_str(v) for v in value if safe_str(v)).strip()
    if isinstance(value, dict):
        return " ".join(
            safe_str(v) for v in value.values() if safe_str(v)
        ).strip()
    return str(value).strip()


class _BrowserAgent:
    """
    Handles all browser interaction.
    Opens URL, detects and waits for CAPTCHA to clear,
    returns raw page text when content is ready.
    """

    CAPTCHA_TITLES = [
        "just a moment",
        "checking your browser",
        "please wait",
        "ddos-guard",
        "attention required",
        "verifying you are human",
    ]

    def __init__(self, logger):
        self.logger = logger

    def wait_for_content(self, page: Page, timeout: int = 120) -> str:
        """
        Polls until real content appears.
        Returns raw page text or empty string on timeout.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                title = page.title().lower()
                if any(c in title for c in self.CAPTCHA_TITLES):
                    self.logger.info(
                        "CAPTCHA detected - waiting for you to "
                        "solve it in the browser..."
                    )
                    time.sleep(3)
                    continue

                text = page.evaluate("""
() => {
    const clone = document.body.cloneNode(true);

    const remove = [
        'script', 'style', 'nav', 'footer',
        'header', 'noscript', 'iframe'
    ];

    remove.forEach(tag => {
        clone.querySelectorAll(tag).forEach(el => el.remove());
    });

    const visibleText = clone.innerText || '';

    const linkLines = Array.from(document.querySelectorAll('a[href]'))
        .map(a => {
            const label = (a.innerText || '')
                .trim()
                .replace(/\\s+/g, ' ');
            const href = (a.href || '').trim();

            if (!href) return '';

            if (
                href.startsWith('mailto:') ||
                href.startsWith('tel:') ||
                href.startsWith('http')
            ) {
                return `${label} ${href}`.trim();
            }

            return '';
        })
        .filter(Boolean)
        .join('\\n');

    return visibleText + '\\n\\nLINKS FOUND:\\n' + linkLines;
}
""")

                if text and len(text.strip()) > 300:
                    self.logger.info(
                        f"Content ready. "
                        f"{len(text)} chars. "
                        f"Preview: {text.strip()[:120]}"
                    )
                    return text.strip()

                time.sleep(2)

            except Exception:
                time.sleep(2)
                continue

        self.logger.warning("Timeout waiting for content.")
        return ""

    def scroll(self, page: Page) -> None:
        try:
            page.evaluate(
                """
                () => new Promise(resolve => {
                    let y = 0;
                    const step = () => {
                        window.scrollBy(0,
                            Math.floor(Math.random()*200)+100);
                        y += 200;
                        if (y < document.body.scrollHeight * 0.7)
                            setTimeout(step,
                                Math.random()*300+100);
                        else setTimeout(resolve, 400);
                    };
                    step();
                })
                """
            )
        except Exception:
            pass


class _ExtractorAgent:
    """
    Sends raw page text to OpenAI.
    Returns a list of raw dicts (unvalidated).
    """

    PROMPT = """
You are a lead extraction expert. You will receive raw text copied from a browser page.

Your job is to extract real business/person leads into structured JSON.

IMPORTANT CONTEXT:
The text may come from any website:
- business directories
- company listing pages
- Sales Navigator/search result pages
- Yellow Pages style pages
- B2B directories

The browser text may be flattened, so you must infer listing boundaries carefully.

FIELDS TO RETURN FOR EACH LEAD:
  full_name      : person name if the listing is a person; otherwise business/company name
  first_name     : first name only if full_name is a person
  last_name      : last name only if full_name is a person
  title          : job title, role, business category, or service type
  company        : company/business name
  phone          : phone number associated with that listing
  email          : email address associated with that listing
  location       : full visible address/city/country if available
  company_domain : website domain only, without https:// or www.
  linkedin_url   : profile/listing/source URL if visible

STRICT EXTRACTION RULES:
1. One lead should represent one real lead/listing, not random text.

2. For business directories:
   - A lead should normally represent one company/business card.
   - If a person/contact name appears inside or near a company listing, attach that person to that company.
   - Do NOT create a separate person-only lead if the person is just a contact under a company.
   - Example:
     EFROTECH
     Information technology, software development
     Nadir Khan Feroz
     should become:
     full_name = "Nadir Khan Feroz"
     company = "EFROTECH"
     title = "Information technology, software development"

3. If only a company is visible and no contact person is visible:
   full_name = company name
   company = company name

4. For Sales Navigator or people search pages:
   - A person profile can be a lead.
   - But it must have at least company, title, location, profile URL, email, or phone.

5. Do not create standalone person rows unless that person has clear business context:
   company, title, email, phone, location, domain, or profile/listing URL.

6. Extract emails from:
   - visible email text
   - mailto: links in LINKS FOUND

7. Extract phones from:
   - visible phone text
   - tel: links in LINKS FOUND

8. Extract website domains from:
   - visible website text
   - http/https links in LINKS FOUND

9. If a visible line says Email, Website, Call, Contact, or Visit Website and LINKS FOUND contains the actual href, use the href value.

10. Skip:
    - navigation
    - footer links
    - login/sign-up prompts
    - pagination controls
    - cookie banners
    - ads
    - headings like Premium, Basic, Business Details, Person Details

11. Do not invent missing data.

12. Return ONLY a valid JSON array. No explanation. No markdown. No code fences.

13. If truly no leads are found, return: []

PAGE TEXT:
{text}
"""

    def __init__(self, logger):
        self.logger = logger
        self._client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "")
        )
        self._model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._local = threading.local()

    @property
    def last_raw_response(self) -> str:
        return getattr(self._local, "last_raw_response", "")

    def extract(self, text: str) -> list[dict]:
        if not text or len(text) < 100:
            return []

        chunk_size = 4000
        chunks = [
            text[i:i + chunk_size]
            for i in range(0, min(len(text), 12000), chunk_size)
        ]

        all_items = []
        raw_responses = []
        self._local.last_raw_response = ""
        for chunk in chunks:
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{
                        "role": "user",
                        "content": self.PROMPT.format(text=chunk),
                    }],
                    temperature=0,
                    max_tokens=2000,
                )
                content = (
                    safe_str(resp.choices[0].message.content)
                    .replace("```json", "")
                    .replace("```", "")
                    .strip()
                )
                raw_responses.append(content)
                self._local.last_raw_response = (
                    "\n\n--- CHUNK ---\n\n".join(raw_responses)
                )
                parsed = json.loads(content)

                if isinstance(parsed, dict):
                    if isinstance(parsed.get("leads"), list):
                        parsed = parsed["leads"]
                    else:
                        parsed = []

                if not isinstance(parsed, list):
                    parsed = []

                all_items.extend(
                    item for item in parsed if isinstance(item, dict)
                )
            except json.JSONDecodeError as e:
                self.logger.warning(
                    f"JSON parse error in chunk: {e}"
                )
            except Exception as e:
                self.logger.warning(f"OpenAI error: {e}")

        self.logger.info(
            f"ExtractorAgent: {len(all_items)} raw items extracted"
        )
        if all_items:
            self.logger.info(
                f"Sample raw item from OpenAI: {json.dumps(all_items[0], indent=2)}"
            )
        return all_items


class _VerifierAgent:
    """
    Validates each raw dict.
    Returns (valid_items, junk_count).
    A lead is valid if it has a name and business context.
    """

    JUNK_NAMES = {
        "premium", "basic", "business details", "person details",
        "contact details", "advertisement", "sponsored", "featured",
        "sign in", "sign up", "register", "login", "home", "back",
        "next", "previous", "more details", "read more", "view all",
        "show more", "load more", "filter", "sort by",
    }

    def __init__(self, logger):
        self.logger = logger

    def verify(self, items: list[dict]) -> tuple[list[dict], int]:
        """
        Keep listings that have a usable name/company and at least
        one business context field.
        """
        JUNK_NAMES = {
            "next", "previous", "prev", "back", "forward",
            "sign in", "sign up", "log in", "login", "logout",
            "register", "subscribe", "home", "menu", "search",
            "filter", "sort by", "load more", "show more",
            "read more", "view all", "see all", "more info",
            "contact us", "about us", "terms", "privacy",
            "cookie", "advertisement", "sponsored", "ad",
            "navigation", "pagination", "footer", "header",
            "close", "open", "expand", "collapse",
            "premium", "basic", "business details", "person details",
            "contact details", "details", "call", "email", "website",
            "visit website", "more", "less",
        }

        valid = []
        junk = 0

        for item in items:
            if not isinstance(item, dict):
                junk += 1
                continue

            name = safe_str(item.get("full_name")) or safe_str(
                item.get("company")
            )

            if not name or len(name) < 2:
                junk += 1
                continue

            if name.lower() in JUNK_NAMES:
                junk += 1
                continue

            if len(name.split()) == 1 and len(name) < 4:
                junk += 1
                continue

            company = safe_str(item.get("company"))
            title = safe_str(item.get("title"))
            email = safe_str(item.get("email"))
            phone = safe_str(item.get("phone"))
            location = safe_str(item.get("location"))
            domain = safe_str(item.get("company_domain"))
            url = safe_str(item.get("linkedin_url"))

            has_business_context = any([
                company,
                title,
                email,
                phone,
                location,
                domain,
                url,
            ])

            if not has_business_context:
                junk += 1
                continue

            valid.append(item)

        self.logger.info(
            f"VerifierAgent: {len(valid)} valid, {junk} junk"
        )
        return valid, junk


class _FormatterAgent:
    """
    Maps a verified raw dict to a Lead dataclass.
    Cleans and normalises all fields.
    """

    def __init__(self, logger):
        self.logger = logger

    def _clean_phone(self, phone: str) -> str:
        phone = safe_str(phone)
        if not phone or phone in ("None", "null", ""):
            return ""
        cleaned = re.sub(r"[^\d\s\+\(\)\-]", "", phone).strip()
        digits = re.sub(r"[^\d]", "", cleaned)
        if len(digits) < 6:
            return ""
        return cleaned[:30]

    def _clean_domain(self, domain: str) -> str:
        domain = safe_str(domain)
        domain = re.sub(r"https?://(www\.)?", "", domain)
        domain = domain.rstrip("/").strip()
        return domain[:100]

    def _clean_email(self, email: str) -> str:
        email = safe_str(email).lower()
        if "@" not in email or "." not in email:
            return ""
        return email[:100]

    def format(self, item: dict) -> Lead:
        full_name = safe_str(item.get("full_name"))
        company = safe_str(item.get("company"))
        name = (full_name or company)[:100]
        name_parts = name.split()

        first_name = safe_str(item.get("first_name"))
        first = (first_name or (name_parts[0] if name_parts else name))[:50]

        last_name = safe_str(item.get("last_name"))
        last = (
            last_name
            or (" ".join(name_parts[1:]) if len(name_parts) > 1 else "")
        )[:50]

        title = safe_str(item.get("title"))
        email = self._clean_email(item.get("email"))
        raw_phone = (
            safe_str(item.get("phone"))
            or safe_str(item.get("telephone"))
            or safe_str(item.get("mobile"))
        )
        phone = self._clean_phone(raw_phone)
        location = safe_str(item.get("location"))
        company_domain = safe_str(item.get("company_domain"))
        linkedin_url = safe_str(item.get("linkedin_url"))

        if self.logger:
            self.logger.debug(
                f"Formatting: {full_name} | "
                f"raw_phone={raw_phone} | "
                f"cleaned={phone}"
            )

        lead = Lead(
            full_name=name,
            first_name=first,
            last_name=last,
            title=title[:100],
            company=company[:100],
            phone=phone,
            email=email,
            email_confidence="scraped" if email else "",
            location=location[:100],
            company_domain=self._clean_domain(
                company_domain
            ),
            linkedin_url=linkedin_url[:200],
            status=LeadStatus.SCRAPED,
        )
        return lead


class _StorageAgent:
    """
    Deduplicates leads against already-seen names.
    Appends new unique leads to the output list.
    Returns count of new leads added.
    """

    def __init__(self, logger):
        self.logger = logger

    def store(
        self,
        leads: list[Lead],
        seen_names: set[str],
        output: list[Lead],
    ) -> int:
        added = 0
        for lead in leads:
            key = lead.full_name.lower().strip()
            if key in seen_names:
                continue
            seen_names.add(key)
            output.append(lead)
            added += 1
        return added


class ScraperAgent(BaseAgent):
    """
    Orchestrates the 5 inner agents.
    Handles pagination and CAPTCHA loop.
    """

    def __init__(self, run: PipelineRun, filters: dict):
        super().__init__(run)
        self.filters = filters
        self._leads: list[Lead] = []
        self._seen_names: set[str] = set()
        self._seen_hashes: set[str] = set()
        self._consecutive_empty: int = 0
        self._raw_pages: list[str] = []
        self._debug_dir = os.path.join("debug", "runs", self.run.id[:8])
        os.makedirs(self._debug_dir, exist_ok=True)

        self._browser_agent = _BrowserAgent(self.logger)
        self._extractor = _ExtractorAgent(self.logger)
        self._verifier = _VerifierAgent(self.logger)
        self._formatter = _FormatterAgent(self.logger)
        self._storer = _StorageAgent(self.logger)

    def _write_debug(self, filename: str, data) -> None:
        try:
            path = os.path.join(self._debug_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                if isinstance(data, str):
                    f.write(data)
                else:
                    json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        except Exception as exc:
            self.logger.warning(f"Debug write failed for {filename}: {exc}")

    def _write_page_error(self, page_num: int, raw_text: str, exc: Exception) -> None:
        raw_response = getattr(self._extractor, "last_raw_response", "")
        self._write_debug(
            f"page_{page_num:03d}_error.txt",
            "\n".join([
                "EXCEPTION:",
                str(exc),
                "",
                "TRACEBACK:",
                traceback.format_exc(),
                "",
                "RAW_TEXT_FIRST_5000_CHARS:",
                safe_str(raw_text)[:5000],
                "",
                "OPENAI_RAW_RESPONSE:",
                safe_str(raw_response),
            ]),
        )

    def _is_sales_navigator(self, url: str) -> bool:
        return "linkedin.com/sales" in url

    def _page_hash(self, page: Page) -> str:
        import hashlib

        try:
            body = page.query_selector("body")
            text = (body.inner_text() or "")[:2000] if body else ""
            return hashlib.md5(text.encode()).hexdigest()
        except Exception:
            return str(random.random())

    def _go_to_next_page(
        self, page: Page, current_url: str, page_num: int
    ) -> bool:
        import urllib.parse

        if self._is_sales_navigator(current_url):
            for sel in [
                "button[aria-label='Next']",
                "[data-test-pagination-page-btn='next']",
                "button:has-text('Next')",
            ]:
                try:
                    btn = page.query_selector(sel)
                    if btn and not btn.is_disabled() and btn.is_visible():
                        time.sleep(random.uniform(12, 16))
                        btn.click()
                        time.sleep(3)
                        return True
                except Exception:
                    continue
            return False

        parsed = urllib.parse.urlparse(current_url)
        params = urllib.parse.parse_qs(parsed.query)
        page_key = next(
            (key for key in params if key.lower() in ("page", "p", "pg")),
            "page",
        )
        params[page_key] = [str(page_num + 1)]
        next_url = urllib.parse.urlunparse(
            parsed._replace(
                query=urllib.parse.urlencode(params, doseq=True)
            )
        )
        try:
            page.goto(next_url, wait_until="commit", timeout=30000)
            return True
        except Exception:
            pass

        for sel in [
            "a[aria-label='Next']", "button[aria-label='Next']",
            "a:has-text('Next')", "button:has-text('Next')",
            "a.next", "[rel='next']",
            "a:has-text('\u203a')", "a:has-text('\u00bb')",
        ]:
            try:
                btn = page.query_selector(sel)
                if not btn or not btn.is_visible():
                    continue
                href = btn.get_attribute("href") or ""
                if href and href not in ("#", "javascript:void(0)"):
                    next_url = (
                        href if href.startswith("http")
                        else f"{parsed.scheme}://{parsed.netloc}{href}"
                    )
                    page.goto(
                        next_url, wait_until="commit", timeout=30000
                    )
                    return True
                btn.click(timeout=5000)
                time.sleep(2)
                return True
            except Exception:
                continue

        return False

    def _phase2_extract(self) -> list[Lead]:
        """
        Process all collected raw page texts through
        Extractor -> Verifier -> Formatter -> Storage.
        Runs after all pages have been scraped.
        """
        import concurrent.futures

        self.logger.info(
            f"Phase 2: Processing {len(self._raw_pages)} "
            f"pages through OpenAI..."
        )

        def process_page(args):
            page_num, raw_text = args
            try:
                self.logger.info(
                    f"Extracting page {page_num}..."
                )
                raw_items = self._extractor.extract(raw_text)
                self._write_debug(
                    f"page_{page_num:03d}_openai_raw.json",
                    raw_items,
                )
                valid_items, junk = self._verifier.verify(raw_items)
                self._write_debug(
                    f"page_{page_num:03d}_verified.json",
                    valid_items,
                )
                formatted = [
                    self._formatter.format(item)
                    for item in valid_items
                ]
                self._write_debug(
                    f"page_{page_num:03d}_final_leads.json",
                    [lead.to_dict() for lead in formatted],
                )
                self.logger.info(
                    f"Page {page_num}: {len(formatted)} leads "
                    f"({junk} junk)"
                )
                return formatted
            except Exception as exc:
                self.logger.exception(
                    f"Phase 2 extraction failed for page {page_num}: {exc}"
                )
                self.emit(EventType.AGENT_FAILED, {
                    "page": page_num,
                    "error": str(exc),
                    "stage": "phase2_extract",
                })
                self._write_page_error(page_num, raw_text, exc)
                return []

        all_leads = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=3
        ) as executor:
            results = executor.map(
                process_page,
                enumerate(self._raw_pages, start=1)
            )
            for leads in results:
                added = self._storer.store(
                    leads, self._seen_names, self._leads
                )
                all_leads.extend(self._leads[-added:] if added else [])

        for lead in self._leads:
            self.emit(EventType.LEAD_SCRAPED, {
                "name": lead.full_name,
                "company": lead.company,
                "total_so_far": len(self._leads),
            })

        return self._leads

    def run_agent(self) -> list[Lead]:
        start_url = self.filters.get("start_url", "")
        if not start_url:
            raise ValueError("No URL provided.")

        max_leads = settings.max_leads or 100
        is_sales_nav = self._is_sales_navigator(start_url)
        page_num = 1

        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome",
        ]
        chrome_exe = next(
            (path for path in chrome_paths if os.path.exists(path)), None
        )

        with sync_playwright() as pw:
            chrome_proc = None
            if chrome_exe:
                debug_profile = os.path.join(
                    os.path.expanduser("~"), "chrome-scraper-profile"
                )
                os.makedirs(debug_profile, exist_ok=True)
                chrome_proc = subprocess.Popen([
                    chrome_exe,
                    "--remote-debugging-port=9222",
                    f"--user-data-dir={debug_profile}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--start-maximized",
                ])
                time.sleep(3)
                browser = pw.chromium.connect_over_cdp(
                    "http://localhost:9222"
                )
                context = (
                    browser.contexts[0]
                    if browser.contexts
                    else browser.new_context()
                )
                page = (
                    context.pages[0]
                    if context.pages
                    else context.new_page()
                )
                self.logger.info("Connected to real Chrome via CDP")
            else:
                self.logger.warning(
                    "Chrome not found. Using Playwright Chromium."
                )
                browser = pw.chromium.launch(
                    headless=False,
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                )
                page = context.new_page()

            try:
                context.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',"
                    "{get:()=>undefined});"
                )
            except Exception:
                pass

            self.logger.info(
                "Browser ready. Solve any CAPTCHA that appears."
            )
            self.emit(EventType.LEAD_SCRAPED, {
                "status": "browser_ready",
                "message": "Browser opened. Solve CAPTCHA if shown.",
            })

            self.logger.info("=" * 55)
            self.logger.info("PHASE 1: Collecting all pages fast.")
            self.logger.info("Solve CAPTCHA when it appears.")
            self.logger.info("OpenAI extraction runs AFTER all pages copied.")
            self.logger.info("=" * 55)

            estimated_pages = max(1, (max_leads // 15) + 1)
            page_num = 1

            page.goto(start_url, wait_until="commit", timeout=60000)
            first_hash = self._page_hash(page)
            self._seen_hashes.add(first_hash)

            while page_num <= estimated_pages:
                raw_text = self._browser_agent.wait_for_content(page)
                if raw_text:
                    self._raw_pages.append(raw_text)
                    self._write_debug(f"page_{page_num:03d}_raw.txt", raw_text)
                    self.logger.info(
                        f"Page {page_num} copied ({len(raw_text)} chars). "
                        f"Total pages: {len(self._raw_pages)}"
                    )
                    self.emit(EventType.LEAD_SCRAPED, {
                        "status": "copying",
                        "page": page_num,
                        "message": f"Page {page_num} copied. Moving to next...",
                    })
                else:
                    self.logger.warning(f"Page {page_num} returned no content.")

                run_repo.update_checkpoint(
                    run_id=self.run.id,
                    last_page=page_num,
                    leads_collected=len(self._leads),
                )

                current_url = page.url
                navigated = self._go_to_next_page(page, current_url, page_num)
                if not navigated:
                    self.logger.info("No more pages to copy.")
                    break

                new_hash = self._page_hash(page)
                if new_hash in self._seen_hashes:
                    self.logger.info("Same page content. Stopping copy phase.")
                    break
                self._seen_hashes.add(new_hash)
                page_num += 1
                if not is_sales_nav:
                    time.sleep(random.uniform(1, 2))

            self.logger.info(
                f"Phase 1 complete. {len(self._raw_pages)} pages copied."
            )
            try:
                browser.close()
            except Exception:
                pass
            if chrome_proc:
                try:
                    chrome_proc.terminate()
                except Exception:
                    pass

        self.logger.info(
            f"Phase 2: Processing {len(self._raw_pages)} pages..."
        )

        import concurrent.futures

        def process_page(args):
            page_num, raw_text = args
            try:
                self.logger.info(f"Extracting page {page_num}...")
                raw_items = self._extractor.extract(raw_text)
                self._write_debug(
                    f"page_{page_num:03d}_openai_raw.json",
                    raw_items,
                )
                valid_items, junk = self._verifier.verify(raw_items)
                self._write_debug(
                    f"page_{page_num:03d}_verified.json",
                    valid_items,
                )
                formatted = [
                    self._formatter.format(item) for item in valid_items
                ]
                self._write_debug(
                    f"page_{page_num:03d}_final_leads.json",
                    [lead.to_dict() for lead in formatted],
                )
                self.logger.info(
                    f"Page {page_num}: {len(formatted)} leads ({junk} junk)"
                )
                return formatted
            except Exception as exc:
                self.logger.exception(
                    f"Phase 2 extraction failed for page {page_num}: {exc}"
                )
                self.emit(EventType.AGENT_FAILED, {
                    "page": page_num,
                    "error": str(exc),
                    "stage": "phase2_extract",
                })
                self._write_page_error(page_num, raw_text, exc)
                return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(
                process_page,
                enumerate(self._raw_pages, start=1)
            ))

        for formatted_leads in results:
            added = self._storer.store(
                formatted_leads, self._seen_names, self._leads
            )
            for lead in self._leads[-added:] if added else []:
                self.emit(EventType.LEAD_SCRAPED, {
                    "name": lead.full_name,
                    "company": lead.company,
                    "total_so_far": len(self._leads),
                })

        if self._leads:
            from src.storage import lead_repo

            lead_repo.save_batch(self.run.id, self._leads)
            self.logger.info(
                f"Saved {len(self._leads)} leads to DB with all fields."
            )

        self.run.total_scraped = len(self._leads)
        self.logger.info(
            f"Done. {len(self._leads)} leads collected."
        )
        return self._leads
