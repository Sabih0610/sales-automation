##src\agents\scraper_agent.py

import time, random, re, json, os, subprocess, threading, traceback, math

from openai import OpenAI
from playwright.sync_api import sync_playwright, Page, BrowserContext

from src.agents.base import BaseAgent
from src.config import settings
from src.models import EventType, Lead, LeadStatus, PipelineRun, Segment
from src.runtime_paths import configure_runtime_environment
from src.storage import run_repo, lead_repo


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



_PLACEHOLDER_DETAIL_VALUES = {
    "",
    "-",
    "--",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "no details",
    "no detail",
    "details unavailable",
    "profile unavailable",
    "private profile",
    "linkedin member",
    "linkedin user",
    "view profile",
    "name unavailable",
}


def _is_placeholder_detail(value) -> bool:
    text = safe_str(value).strip().lower()
    return text in _PLACEHOLDER_DETAIL_VALUES


def _has_sales_nav_useful_details(
    name: str,
    title: str,
    company: str,
    location: str,
    href: str,
    company_url: str,
) -> bool:
    if _is_placeholder_detail(name):
        return False

    return any(
        safe_str(value) and not _is_placeholder_detail(value)
        for value in (title, company, location, href, company_url)
    )

def _error_text(exc: Exception, fallback: str = "Unknown scraper error") -> str:
    return str(exc) or repr(exc) or fallback


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
                self.logger.warning(
                    "OpenAI error: %s",
                    _error_text(e, "Unknown OpenAI extraction error"),
                )

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

    def mark_saved_duplicates(
        self,
        run: PipelineRun,
        leads: list[Lead],
    ) -> None:
        from src.storage import lead_repo

        campaign_filename = (
            (run.filters or {}).get("campaign_key")
            or (run.filters or {}).get("campaign")
            or ""
        )
        for lead in leads:
            try:
                lead_repo.mark_duplicate_if_any(lead.id, campaign_filename)
            except Exception as exc:
                self.logger.warning(
                    "Duplicate detection failed for lead %s: %s",
                    lead.id,
                    _error_text(exc, "Unknown duplicate detection error"),
                )


class ScraperAgent(BaseAgent):
    """
    Orchestrates the 5 inner agents.
    Handles pagination and CAPTCHA loop.
    """

    KNOWN_COMPANY_SUFFIXES = [
        "Amazon Web Services (AWS)",
        "Amazon Web Services",
        "Google Cloud",
        "The Mosaic Company",
        "Magenta Mobility",
        "Visory Health",
        "Sendora AI",
        "JPMorganChase",
        "Maryland Department of Health",
        "Write On, LLC International",
        "Impact Creative Branding",
        "Amazon",
        "Slashy (YC S25)",
        "Salesforce",
        "Indeed.com",
        "BioTechUSA",
        "Microsoft",
        "Oracle",
        "Philips",
        "Google",
        "Meta",
        "Sony",
        "Ring",
        "Harkla",
        "BizClik",
        "SAP",
        "IBM",
        "AWS",
        "SWARM",
    ]

    def __init__(self, run: PipelineRun, filters: dict):
        super().__init__(run)
        self.filters = filters
        self._leads: list[Lead] = []
        self._seen_names: set[str] = set()
        self._seen_hashes: set[str] = set()
        self._consecutive_empty: int = 0
        self._raw_pages: list[str] = []
        self._sales_nav_stop_reason = "unknown"
        self._sales_nav_last_next_failure = "unknown"
        self._runtime_paths = configure_runtime_environment()
        self._debug_dir = os.path.join(
            str(self._runtime_paths.debug_dir),
            "runs",
            self.run.id[:8],
        )
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
            self.logger.warning(
                "Debug write failed for %s: %s",
                filename,
                _error_text(exc, "Unknown debug write error"),
            )

    def _write_page_error(self, page_num: int, raw_text: str, exc: Exception) -> None:
        raw_response = getattr(self._extractor, "last_raw_response", "")
        self._write_debug(
            f"page_{page_num:03d}_error.txt",
            "\n".join([
                "EXCEPTION:",
                _error_text(exc, "Unknown page processing error"),
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
        return "linkedin.com/sales/search/people" in (url or "").lower()

    def _clean_sales_nav_name(self, raw_name: str) -> str:
        def clean_candidate(value: str) -> str:
            value = safe_str(value)
            match = re.match(
                r"^\s*add\s+(.+?)\s+to\s+selection\s*$",
                value,
                flags=re.IGNORECASE,
            )
            if match:
                value = match.group(1)
            value = re.sub(
                r"\bis reachable\b",
                "",
                value,
                flags=re.IGNORECASE,
            )
            value = re.sub(
                r"\bdegree connection\b",
                "",
                value,
                flags=re.IGNORECASE,
            )
            value = re.sub(
                r"\bpremium member\b",
                "",
                value,
                flags=re.IGNORECASE,
            )
            value = re.sub(
                r"\blinkedin\b",
                "",
                value,
                flags=re.IGNORECASE,
            )
            value = re.sub(
                r"\b(1st|2nd|3rd)\b",
                "",
                value,
                flags=re.IGNORECASE,
            )
            return re.sub(
                r"\s+",
                " ",
                value,
            ).strip(" -|." + "\u00b7\u2022")

        lines = [clean_candidate(line) for line in safe_str(raw_name).splitlines()]
        skip = {
            "1st", "2nd", "3rd", "out of network",
            "view profile", "open profile", "select all",
            "save", "message", "reactivate subscription",
        }
        name = next(
            (
                line for line in lines
                if line
                and line.lower() not in skip
                and not self._is_dirty_sales_nav_name(line)
            ),
            clean_candidate(raw_name),
        )
        name = re.sub(
            r"^view\s+(.+?)'?s?\s+profile$",
            r"\1",
            name,
            flags=re.IGNORECASE,
        )
        return clean_candidate(name)

    def _is_dirty_sales_nav_name(self, value: str) -> bool:
        text = safe_str(value).strip().lower()
        if not text:
            return True
        if re.match(r"^add\s+.+?\s+to\s+selection$", text):
            return False
        dirty_fragments = [
            " to selection",
            "select all",
            "reactivate subscription",
            "view profile",
            "open profile",
            "show more",
            "recent posts",
            "mutual connection",
            "degree connection",
            "premium member",
        ]
        dirty_exact = {
            "save", "message", "connect", "lead", "account", "linkedin",
            "1st", "2nd", "3rd", "out of network",
        }
        return (
            text in dirty_exact
            or text.startswith("select ")
            or any(fragment in text for fragment in dirty_fragments)
        )

    def _ignore_sales_nav_line(self, line: str) -> bool:
        text = safe_str(line).lower()
        if not text:
            return True
        if re.match(r"^add\s+.+?\s+to\s+selection$", text):
            return True
        ignored_fragments = [
            "is reachable",
            "reactivate subscription",
            " to selection",
            "years in role",
            "year in role",
            "months in role",
            "month in role",
            "years in company",
            "year in company",
            "months in company",
            "month in company",
            "years at company",
            "year at company",
            "months at company",
            "month at company",
            "experience:",
            "about:",
            "mutual connection",
            "mutual connections",
            "degree connection",
            "recent posts",
            "recent post",
            "show more",
            "select all",
            "save",
            "message",
            "connect",
            "view profile",
            "open profile",
            "sales navigator",
            "linkedin",
            "premium",
            "premium member",
            "shared connection",
            "shared connections",
            "recently posted",
            "posted on linkedin",
        ]
        if text in {
            "1st", "2nd", "3rd", "out of network",
            "lead", "account", "linkedin",
        }:
            return True
        return any(fragment in text for fragment in ignored_fragments)

    def _clean_sales_nav_line(self, line: str) -> str:
        value = safe_str(line)
        value = re.sub(
            r"^\s*add\s+(.+?)\s+to\s+selection\s*$",
            r"\1",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"\bis reachable\b", "", value, flags=re.IGNORECASE)
        value = re.sub(
            r"\bdegree connection\b",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bpremium member\b",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"\b(1st|2nd|3rd)\b", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\blinkedin\b", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip(" -|." + "\u00b7\u2022")
        return value

    def _known_sales_nav_company_suffixes(self) -> list[str]:
        return sorted(
            self.KNOWN_COMPANY_SUFFIXES,
            key=lambda value: len(value),
            reverse=True,
        )

    def _strip_sales_nav_trailing_punctuation(self, value: str) -> str:
        return re.sub(r"\s+", " ", safe_str(value)).strip(
            " \t\r\n-_|,;:." + "\u00b7\u2022"
        )

    def _contains_known_sales_nav_company(self, line: str) -> bool:
        text = safe_str(line).lower()
        return any(
            re.search(rf"\b{re.escape(company.lower())}\b", text)
            for company in self._known_sales_nav_company_suffixes()
        )

    def _strip_sales_nav_experience_prefix(self, line: str) -> str:
        value = self._clean_sales_nav_line(line)
        dash = r"[\-\u2013\u2014]"
        value = re.sub(
            rf"^\s*\d{{4}}\s*{dash}\s*(?:\d{{4}}|present|current)\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"^\s*\(\s*\d+\s*(?:yrs?|years?)"
            r"(?:\s*\d+\s*(?:mos?|months?))?\s*\)\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"^\s*\(\s*\d+\s*(?:mos?|months?)\s*\)\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        return self._strip_sales_nav_trailing_punctuation(value)

    def _remove_experience_prefix(self, value: str) -> str:
        return self._strip_sales_nav_experience_prefix(value)

    def _is_sales_nav_experience_noise(self, line: str) -> bool:
        text = safe_str(line).lower()
        if not text:
            return True
        starts = ("experience:", "about:")
        if text.startswith(starts):
            return True
        noise_fragments = [
            "recently promoted",
            "recently hired",
            "mutual connection",
            "mutual connections",
            "recent posts",
            "recent post",
            "message",
            "save",
            "show more",
        ]
        if any(fragment in text for fragment in noise_fragments):
            return True
        if re.fullmatch(
            r"\d{4}\s*[\-\u2013\u2014]\s*(?:\d{4}|present|current)?",
            text,
            flags=re.IGNORECASE,
        ):
            return True
        if re.fullmatch(
            r"\(?\s*\d+\s*(?:yrs?|years?|mos?|months?)"
            r"(?:\s*\d+\s*(?:mos?|months?))?\s*\)?",
            text,
            flags=re.IGNORECASE,
        ):
            return True
        return False

    def _sales_nav_title_needs_repair(self, title: str) -> bool:
        value = safe_str(title)
        if not value:
            return True
        if self._looks_like_location(value):
            return True
        if self._is_sales_nav_experience_noise(value):
            return True
        if re.match(
            r"^\s*\d{4}\s*[\-\u2013\u2014]\s*"
            r"(?:\d{4}|present|current)",
            value,
            flags=re.IGNORECASE,
        ):
            return True
        if re.search(
            r"\(\s*\d+\s*(?:yrs?|years?|mos?|months?)",
            value,
            flags=re.IGNORECASE,
        ):
            return True
        return False

    def _sales_nav_parse_confidence(self, parsed: dict, linkedin_url: str) -> int:
        score = 0
        name = safe_str(parsed.get("full_name"))
        title = safe_str(parsed.get("title"))
        company = safe_str(parsed.get("company"))
        location = safe_str(parsed.get("location"))
        if name and not self._is_dirty_sales_nav_name(name):
            score += 1
        if title and not self._sales_nav_title_needs_repair(title):
            score += 1
        if company:
            score += 1
        if location and self._looks_like_location(location):
            score += 1
        if safe_str(linkedin_url):
            score += 1
        return score

    def _repair_sales_nav_parse_with_openai(
        self,
        parsed: dict,
        card_lines: list[str],
    ) -> dict:
        if os.getenv("SALES_NAV_REPAIR_WITH_OPENAI", "").lower() != "true":
            return parsed
        if not card_lines:
            return parsed
        if not os.getenv("OPENAI_API_KEY", ""):
            self.logger.warning(
                "SalesNav OpenAI repair requested but OPENAI_API_KEY is missing."
            )
            return parsed

        try:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            prompt = (
                "Extract only visible information from this Sales Navigator "
                "card. Do not invent. Return only JSON with keys: "
                'full_name, title, company, location. '
                "Do not invent email or phone. If company/title are not "
                "visible, leave them blank. Separate company from title. "
                "Do not use experience/date prefix as current title. Do not "
                "use Reactivate subscription, Message, Save, or Add to "
                "selection.\n\nCARD LINES:\n"
                + "\n".join(card_lines[:20])
            )
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=500,
            )
            content = (
                safe_str(resp.choices[0].message.content)
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )
            repaired = json.loads(content)
            if not isinstance(repaired, dict):
                return parsed
            merged = dict(parsed)
            for key in ("full_name", "title", "company", "location"):
                value = self._clean_sales_nav_line(repaired.get(key))
                if value:
                    merged[key] = value
            title, company = self._finalize_sales_nav_title_company(
                safe_str(merged.get("title")),
                safe_str(merged.get("company")),
            )
            merged["title"] = title
            merged["company"] = company
            return merged
        except Exception as exc:
            self.logger.warning(
                "SalesNav OpenAI repair failed: %s",
                _error_text(exc, "Unknown SalesNav repair error"),
            )
            return parsed

    def _write_sales_nav_debug_jsonl(
        self,
        lead: Lead,
        raw_name: str,
        parsed: dict,
        confidence: int,
        card_lines: list[str],
    ) -> None:
        try:
            output_dir = "output"
            os.makedirs(output_dir, exist_ok=True)
            path = os.path.join(
                output_dir,
                f"salesnav_debug_{self.run.id}.jsonl",
            )
            row = {
                "lead_id": lead.id,
                "raw_name": safe_str(raw_name),
                "parsed": parsed,
                "confidence": confidence,
                "card_lines": card_lines[:10],
            }
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            self.logger.warning(
                "SalesNav debug JSONL write failed: %s",
                _error_text(exc, "Unknown SalesNav debug write error"),
            )

    def _split_sales_nav_title_company(self, value: str) -> tuple[str, str]:
        value = self._strip_sales_nav_experience_prefix(value)
        if not value:
            return "", ""
        if self._looks_like_location(value):
            return value, ""

        separators = ["\u00b7", "\u00c2\u00b7", "\u2022", " - "]
        for sep in separators:
            if sep in value:
                parts = [
                    self._clean_sales_nav_line(part)
                    for part in value.split(sep)
                    if self._clean_sales_nav_line(part)
                ]
                if len(parts) >= 2:
                    return (
                        self._strip_sales_nav_trailing_punctuation(parts[0]),
                        self._strip_sales_nav_trailing_punctuation(parts[-1]),
                    )

        for company in self._known_sales_nav_company_suffixes():
            pattern = rf"^(?P<title>.+?)\s+{re.escape(company)}$"
            match = re.match(pattern, value, flags=re.IGNORECASE)
            if match:
                title = self._strip_sales_nav_trailing_punctuation(
                    match.group("title")
                )
                if title:
                    return title, company

        prefix_title, prefix_company = self._split_sales_nav_company_prefix(value)
        if prefix_company:
            return prefix_title, prefix_company

        match = re.match(
            r"(.+?)\s+(?:at|@)\s+(.+)$",
            value,
            flags=re.IGNORECASE,
        )
        if match:
            return (
                self._strip_sales_nav_trailing_punctuation(match.group(1)),
                self._strip_sales_nav_trailing_punctuation(match.group(2)),
            )
        return value, ""

    def _split_sales_nav_company_prefix(self, value: str) -> tuple[str, str]:
        value = self._strip_sales_nav_trailing_punctuation(value)
        for company in self._known_sales_nav_company_suffixes():
            pattern = rf"^{re.escape(company)}\s+(?P<title>.+)$"
            match = re.match(pattern, value, flags=re.IGNORECASE)
            if not match:
                continue
            title = self._strip_sales_nav_trailing_punctuation(
                match.group("title")
            )
            if title and self._has_sales_nav_title_marker(title):
                return title, company
        return value, ""

    def _has_sales_nav_title_marker(self, line: str) -> bool:
        text = safe_str(line).lower()
        title_markers = [
            "account", "administrator", "architect", "consultant",
            "cto", "ceo", "cio", "chief", "director", "engineer",
            "executive", "field", "founder", "global", "head",
            "ai", "cloud", "data", "marketing", "product", "technical",
            "lead", "manager", "officer", "owner", "president",
            "principal", "retail", "sales", "specialist", "startups",
            "strategist", "technology", "vp", "vice president",
        ]
        return any(
            re.search(rf"\b{re.escape(word)}\b", text)
            for word in title_markers
        )

    def _has_sales_nav_degree_suffix(self, line: str) -> bool:
        return bool(re.search(
            r"\b(MBA|PhD|CPA|PMP|MD|JD|Esq|MSc|BSc|MA|MS)\b",
            safe_str(line),
            flags=re.IGNORECASE,
        ))

    def _looks_like_location(self, line: str) -> bool:
        text = safe_str(line).lower()
        if self._ignore_sales_nav_line(line):
            return False
        if self._has_sales_nav_degree_suffix(line):
            return False
        bad = ["year", "month", "role", "company", "experience", "about"]
        if any(word in text for word in bad):
            return False
        if self._contains_known_sales_nav_company(line):
            return False
        if self._has_sales_nav_title_marker(line):
            return False
        location_markers = [
            " area",
            "bay area",
            "united states",
            "united kingdom",
            "saudi arabia",
            "singapore",
            "germany",
            "france",
            "australia",
            "canada",
            "pakistan",
            "india",
            "uae",
            "dubai",
            "metropolitan area",
            "greater ",
        ]
        return "," in line or any(marker in text for marker in location_markers)

    def _looks_like_sales_nav_title_line(self, line: str) -> bool:
        text = safe_str(line).lower()
        if (
            not text
            or self._ignore_sales_nav_line(line)
            or self._is_sales_nav_experience_noise(line)
        ):
            return False
        if self._looks_like_location(line):
            return False
        if self._split_sales_nav_title_company(line)[1]:
            return True
        return self._has_sales_nav_title_marker(text)

    def _looks_like_sales_nav_person_name(self, line: str) -> bool:
        value = self._clean_sales_nav_name(line)
        if not value or self._is_dirty_sales_nav_name(value):
            return False
        if self._looks_like_location(value):
            return False
        if self._split_sales_nav_title_company(value)[1]:
            return False
        org_markers = ["microsoft", " mfg ", " ou ", " inc", " llc", " corp"]
        padded_lower = f" {value.lower()} "
        if any(marker in padded_lower for marker in org_markers):
            return False
        words = value.split()
        if len(words) > 8:
            return False
        lower = value.lower()
        title_words = [
            "account", "architect", "consultant", "director", "engineer",
            "executive", "founder", "manager", "officer", "president",
            "specialist", "strategist", "technology", "global", "retail",
        ]
        return bool(re.search(r"[A-Za-z]", value)) and not any(
            word in lower for word in title_words
        )

    def _clean_sales_nav_location(self, line: str, name: str = "") -> str:
        value = self._strip_sales_nav_trailing_punctuation(line)
        clean_name = self._clean_sales_nav_name(name)
        if clean_name and value.lower().startswith(clean_name.lower()):
            value = value[len(clean_name):].strip(" ,-|")
        return self._strip_sales_nav_trailing_punctuation(value)

    def _append_sales_nav_title_context(
        self,
        title: str,
        context: str,
    ) -> str:
        title = self._strip_sales_nav_trailing_punctuation(title)
        context = self._strip_sales_nav_trailing_punctuation(context)
        if not context:
            return title
        if not title:
            return context
        if context.lower() in title.lower():
            return title
        return f"{title}, {context}"

    def _finalize_sales_nav_title_company(
        self,
        title: str,
        company: str,
    ) -> tuple[str, str]:
        title = self._strip_sales_nav_experience_prefix(title)
        company = self._strip_sales_nav_trailing_punctuation(company)

        if company and company.lower() == title.lower():
            company = ""

        if title and not company:
            parsed_title, parsed_company = self._split_sales_nav_title_company(
                title
            )
            if parsed_company:
                title = parsed_title
                company = parsed_company

        if title and not company:
            parsed_title, parsed_company = self._split_sales_nav_company_prefix(
                title
            )
            if parsed_company:
                title = parsed_title
                company = parsed_company

        if company:
            context_title, real_company = self._split_sales_nav_title_company(
                company
            )
            if real_company:
                title = self._append_sales_nav_title_context(
                    title,
                    context_title,
                )
                company = real_company

        if company and company.lower() == title.lower():
            company = ""

        return (
            self._strip_sales_nav_trailing_punctuation(title),
            self._strip_sales_nav_trailing_punctuation(company),
        )

    def _parse_sales_nav_card(
        self,
        raw_name: str,
        text: str,
        company_anchor_text: str = "",
    ) -> dict:
        name = self._clean_sales_nav_name(raw_name)
        anchor_company = self._strip_sales_nav_trailing_punctuation(
            company_anchor_text
        )
        if anchor_company and self._ignore_sales_nav_line(anchor_company):
            anchor_company = ""
        lines = []
        for raw_line in safe_str(text).splitlines():
            if re.match(
                r"^\s*add\s+.+?\s+to\s+selection\s*$",
                safe_str(raw_line),
                flags=re.IGNORECASE,
            ):
                continue
            line = self._clean_sales_nav_line(raw_line)
            if line.lower().startswith(("experience:", "about:")):
                continue
            line = self._strip_sales_nav_experience_prefix(line)
            if (
                line
                and not self._ignore_sales_nav_line(line)
                and not self._is_sales_nav_experience_noise(line)
            ):
                lines.append(line)

        if not name or not self._looks_like_sales_nav_person_name(name):
            for line in lines:
                cleaned = self._clean_sales_nav_name(line)
                if self._looks_like_sales_nav_person_name(cleaned):
                    name = cleaned
                    break

        name_idx = -1
        normalized_name = name.lower()
        for idx, line in enumerate(lines):
            cleaned = self._clean_sales_nav_name(line)
            if normalized_name and (
                normalized_name == cleaned.lower()
                or normalized_name in cleaned.lower()
                or cleaned.lower() in normalized_name
            ):
                name_idx = idx
                name = cleaned or name
                break

        if name_idx < 0 and lines:
            for idx, line in enumerate(lines):
                if self._looks_like_sales_nav_person_name(line):
                    name_idx = idx
                    name = self._clean_sales_nav_name(line)
                    break

        useful = [
            line for idx, line in enumerate(lines)
            if idx != name_idx
        ]

        title = ""
        company = ""
        location = ""

        title_line_idx = -1
        for idx, line in enumerate(useful):
            if self._looks_like_location(line):
                continue
            parsed_title, parsed_company = self._split_sales_nav_title_company(line)
            if parsed_title and parsed_company:
                title = parsed_title
                company = parsed_company
                title_line_idx = idx
                break
            if self._looks_like_sales_nav_title_line(line):
                title = line
                title_line_idx = idx
                break

        if title and not company:
            for idx, line in enumerate(useful):
                if idx <= title_line_idx or self._looks_like_location(line):
                    continue
                context_title, real_company = self._split_sales_nav_title_company(
                    line
                )
                if context_title and real_company:
                    title = self._append_sales_nav_title_context(
                        title,
                        context_title,
                    )
                    company = real_company
                    break

        if anchor_company:
            if company and company.lower() != anchor_company.lower():
                if company.lower().endswith(anchor_company.lower()):
                    context = company[: -len(anchor_company)]
                    title = self._append_sales_nav_title_context(
                        title,
                        context,
                    )
                company = anchor_company
            elif not company:
                company = anchor_company

        title, company = self._finalize_sales_nav_title_company(title, company)

        for idx, line in enumerate(useful):
            if idx <= title_line_idx:
                continue
            if line.lower() in {title.lower(), company.lower()}:
                continue
            if self._looks_like_location(line):
                location = self._clean_sales_nav_location(line, name)
                break

        if not location:
            for idx, line in enumerate(useful):
                if idx <= title_line_idx:
                    continue
                if (
                    line.lower() not in {title.lower(), company.lower()}
                    and not self._ignore_sales_nav_line(line)
                    and not self._split_sales_nav_title_company(line)[1]
                    and not self._looks_like_sales_nav_title_line(line)
                ):
                    location = self._clean_sales_nav_location(line, name)
                    break

        parts = name.split()
        return {
            "full_name": name,
            "first_name": parts[0] if parts else "",
            "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
            "title": title.strip(" -|"),
            "company": company.strip(" -|"),
            "location": location.strip(" -|"),
        }

    def _visible_sales_nav_cards(self, page: Page) -> list[dict]:
        try:
            return page.evaluate(
                """
() => {
    const leadLinks = Array.from(document.querySelectorAll(
        'a[href*="/sales/lead/"]'
    ));

    const cleanLine = (value) => (value || '')
        .replace(/\\s+/g, ' ')
        .replace(/\\bis reachable\\b/gi, '')
        .trim();

    const cleanName = (value) => cleanLine(value)
        .replace(/^add\\s+(.+?)\\s+to\\s+selection$/i, '$1')
        .replace(/\\bdegree connection\\b/gi, '')
        .replace(/\\bpremium member\\b/gi, '')
        .replace(/\\b(1st|2nd|3rd)\\b/gi, '')
        .replace(/\\blinkedin\\b/gi, '')
        .replace(/^[\\s\\-|.\\u00b7\\u2022]+/g, '')
        .replace(/[\\s\\-|.\\u00b7\\u2022]+$/g, '')
        .replace(/\\s+/g, ' ')
        .trim();

    const isJunkLine = (value) => {
        const text = cleanLine(value).toLowerCase();
        if (!text) return true;
        if (/^add\\s+.+?\\s+to\\s+selection$/.test(text)) return true;
        if (/^select\\s+/.test(text)) return true;
        const exactJunk = [
            'save', 'message', 'connect', 'select all',
            'view profile', 'open profile', 'lead', 'account', 'linkedin'
        ];
        const junkFragments = [
            'reactivate subscription',
            'show more',
            'recent posts',
            'recent post',
            'mutual connection',
            'mutual connections',
            'degree connection',
            'premium member',
            'about:',
            'experience:',
            'years in role',
            'year in role',
            'months in role',
            'month in role',
            'years in company',
            'year in company',
            'months in company',
            'month in company'
        ];
        return exactJunk.includes(text) ||
            junkFragments.some(item => text.includes(item));
    };

    const isDirtyName = (value) => {
        const text = cleanLine(value).toLowerCase();
        if (!text) return true;
        if (/^add\\s+.+?\\s+to\\s+selection$/.test(text)) return false;
        if (/^select\\s+/.test(text)) return true;
        const dirtyFragments = [
            ' to selection',
            'reactivate subscription',
            'view profile',
            'open profile',
            'show more',
            'recent posts',
            'mutual connection',
            'degree connection',
            'premium member'
        ];
        const dirtyExact = [
            'save', 'message', 'connect', 'select all',
            'lead', 'account', 'linkedin'
        ];
        return dirtyExact.includes(text) ||
            dirtyFragments.some(item => text.includes(item));
    };

    const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 &&
            rect.height > 0 &&
            style.visibility !== 'hidden' &&
            style.display !== 'none';
    };

    const findLeadCard = (el) => {
        let current = el;
        for (let i = 0; i < 8 && current; i += 1) {
            const text = current.innerText || '';
            const hasLeadUrl = current.querySelectorAll(
                'a[href*="/sales/lead/"]'
            ).length;
            const hasMessageOrSave = /Message|Save/.test(text);
            const textLen = text.length;

            if (
                textLen > 80 &&
                textLen < 2500 &&
                hasLeadUrl >= 1 &&
                hasMessageOrSave
            ) {
                return current;
            }
            current = current.parentElement;
        }

        const fallback = el.closest('li') ||
            el.closest('[role="listitem"]') ||
            el.parentElement ||
            el;
        const fallbackLen = (fallback.innerText || '').length;
        return fallbackLen < 2500 ? fallback : el;
    };

    return leadLinks
        .filter(visible)
        .map(anchor => {
            const href = anchor.href || anchor.getAttribute('href') || '';
            if (!href) return null;

            const card = findLeadCard(anchor);
            const cardLines = (card.innerText || '')
                .split('\\n')
                .map(cleanLine)
                .filter(Boolean)
                .filter(line => !isJunkLine(line));
            const companyLink = Array.from(card.querySelectorAll(
                'a[href*="/sales/company/"], ' +
                'a[href*="/company/"], ' +
                'a[href*="/sales/accounts/"]'
            )).find(visible);
            const companyUrl = companyLink
                ? (companyLink.href || companyLink.getAttribute('href') || '')
                : '';
            const companyAnchorText = companyLink
                ? cleanLine(
                    companyLink.innerText ||
                    companyLink.textContent ||
                    companyLink.getAttribute('aria-label')
                )
                : '';

            let rawName = cleanName(anchor.innerText || anchor.textContent);
            if (isDirtyName(rawName) || rawName.length > 140) {
                rawName = '';
            }
            if (!rawName) {
                rawName = cardLines.find(line => !isDirtyName(line)) || '';
                rawName = cleanName(rawName);
            }
            if (!rawName || rawName.length < 2) return null;

            return {
                raw_name: rawName,
                href,
                company_linkedin_url: companyUrl,
                company_anchor_text: companyAnchorText,
                card_text: cardLines.join('\\n'),
                card_lines: cardLines,
            };
        })
        .filter(Boolean);
}
                """
            ) or []
        except Exception as exc:
            self.logger.warning(
                "Sales Navigator DOM evaluate failed: %s",
                _error_text(exc, "Unknown Sales Navigator DOM error"),
            )
            return []

    def _scroll_sales_nav_results(self, page: Page) -> None:
        try:
            page.evaluate(
                """
() => {
    const containers = Array.from(document.querySelectorAll('div'))
        .filter(el => el.scrollHeight > el.clientHeight + 300)
        .sort((a, b) => b.scrollHeight - a.scrollHeight);
    const target = containers[0] || document.scrollingElement || document.body;
    target.scrollBy({ top: 1200, behavior: 'smooth' });
}
                """
            )
        except Exception:
            pass
        try:
            page.mouse.wheel(0, 1200)
        except Exception:
            pass

    def _sales_nav_page_signature(self, page: Page) -> str:
        try:
            return safe_str(page.evaluate(
                """
() => Array.from(document.querySelectorAll('a[href*="/sales/lead/"]'))
    .slice(0, 12)
    .map(a => (a.href || a.getAttribute('href') || '').split('?')[0])
    .filter(Boolean)
    .join('|')
                """
            ))
        except Exception:
            return ""

    def _reset_sales_nav_scroll(self, page: Page) -> None:
        try:
            page.evaluate(
                """
() => {
    const containers = Array.from(document.querySelectorAll('div'))
        .filter(el => el.scrollHeight > el.clientHeight + 300)
        .sort((a, b) => b.scrollHeight - a.scrollHeight);
    const target = containers[0] || document.scrollingElement || document.body;
    if (target) target.scrollTo({ top: 0, behavior: 'instant' });
    window.scrollTo({ top: 0, behavior: 'instant' });
}
                """
            )
        except Exception:
            pass

    def _click_sales_nav_next_page(self, page: Page) -> bool:
        self._sales_nav_last_next_failure = "unknown"
        selectors = [
            'button[aria-label*="Next"]',
            'button[aria-label*="next"]',
            "button.artdeco-pagination__button--next",
            "li.artdeco-pagination__indicator + button",
            "button:has-text('Next')",
            "a:has-text('Next')",
            "xpath=//*[self::button or self::a][contains(normalize-space(.), 'Next')]",
        ]
        saw_disabled_next = False

        for selector in selectors:
            try:
                handles = page.query_selector_all(selector)
                if not handles:
                    continue
                for handle in handles:
                    disabled = handle.evaluate(
                        """
el => Boolean(
    el.disabled ||
    el.getAttribute('aria-disabled') === 'true' ||
    el.classList.contains('disabled')
)
                        """
                    )
                    visible = handle.is_visible()
                    if disabled:
                        saw_disabled_next = True
                        continue
                    if not visible:
                        continue
                    self.logger.info("Clicking Sales Navigator next page...")
                    handle.evaluate(
                        "el => el.scrollIntoView({ behavior: 'instant', block: 'center' })"
                    )
                    handle.click(timeout=5000)
                    time.sleep(random.uniform(4, 6))
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    self._reset_sales_nav_scroll(page)
                    return True
            except Exception:
                continue

        try:
            clicked = bool(page.evaluate(
                """
() => {
  const candidates = Array.from(document.querySelectorAll("button, a"));
  const next = candidates.find(el => {
    const text = (el.innerText || "").trim().toLowerCase();
    const aria = (el.getAttribute("aria-label") || "").toLowerCase();
    const disabled =
      el.disabled ||
      el.getAttribute("aria-disabled") === "true" ||
      el.classList.contains("disabled");

    return !disabled && (
      aria.includes("next") ||
      text === "next" ||
      text.includes("next")
    );
  });

  if (next) {
    next.scrollIntoView({ behavior: "instant", block: "center" });
    next.click();
    return true;
  }

  return false;
}
                """
            ))
            if clicked:
                self.logger.info("Clicking Sales Navigator next page...")
                time.sleep(random.uniform(4, 6))
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                self._reset_sales_nav_scroll(page)
                return True
        except Exception as exc:
            self.logger.warning(
                "Sales Navigator next page JS fallback failed: %s",
                _error_text(exc, "Unknown Sales Navigator pagination error"),
            )

        if saw_disabled_next:
            self._sales_nav_last_next_failure = "no_next_button"
            self.logger.info(
                "Sales Navigator next button disabled. Stopping pagination."
            )
        else:
            self._sales_nav_last_next_failure = "no_next_button"
            self.logger.info(
                "No next page found. Stopping Sales Navigator pagination."
            )
        return False

    def _raise_if_stop_requested(self) -> None:
        try:
            if run_repo.get_control(self.run.id) == "stop":
                self.logger.warning("Stop requested by user. Stopping scraper.")
                raise RuntimeError("Run stopped by user.")
        except RuntimeError:
            raise
        except Exception as exc:
            self.logger.warning(
                "Could not check run control state: %s",
                _error_text(exc, "Unknown run control error"),
            )

    def _sales_nav_rate_limit_message(self, page: Page) -> str:
        try:
            text = safe_str(page.evaluate(
                """() => `${document.title || ""}\n${document.body ? document.body.innerText : ""}`"""
            )).lower()
        except Exception:
            return ""

        markers = (
            "too many requests",
            "you've made too many requests",
            "try again later",
            "rate limit",
        )
        if any(marker in text for marker in markers):
            return (
                "LinkedIn Sales Navigator rate limit detected: Too Many Requests. "
                "Scraping paused to avoid further requests. Retry later."
            )
        return ""

    def _raise_if_sales_nav_rate_limited(self, page: Page) -> None:
        message = self._sales_nav_rate_limit_message(page)
        if not message:
            return
        self._sales_nav_stop_reason = "rate_limited"
        self.emit(EventType.AGENT_FAILED, {
            "status": "rate_limited",
            "message": message,
        })
        raise RuntimeError(message)

    def _sales_nav_scroll_delay(self) -> None:
        minimum = float(os.getenv("SALES_NAV_SCROLL_DELAY_MIN", "4"))
        maximum = float(os.getenv("SALES_NAV_SCROLL_DELAY_MAX", "8"))
        time.sleep(random.uniform(minimum, max(minimum, maximum)))

    def _sales_nav_page_delay(self) -> None:
        minimum = float(os.getenv("SALES_NAV_PAGE_DELAY_MIN", "45"))
        maximum = float(os.getenv("SALES_NAV_PAGE_DELAY_MAX", "90"))
        time.sleep(random.uniform(minimum, max(minimum, maximum)))

    def _scrape_sales_navigator(self, page: Page, max_leads: int) -> list[Lead]:
        self._sales_nav_stop_reason = "unknown"
        self.logger.info(
            "Sales Navigator detected. Using DOM scroll scraper."
        )
        self.emit(EventType.LEAD_SCRAPED, {
            "status": "sales_navigator_dom",
            "message": "Sales Navigator detected. Using DOM scroll scraper.",
        })
        try:
            settings.output_dir.mkdir(parents=True, exist_ok=True)
            debug_path = settings.output_dir / f"salesnav_debug_{self.run.id}.jsonl"
            with open(debug_path, "w", encoding="utf-8"):
                pass
        except Exception as exc:
            self.logger.warning(
                "SalesNav debug JSONL init failed: %s",
                _error_text(exc, "Unknown SalesNav debug init error"),
            )

        try:
            page.wait_for_load_state("domcontentloaded", timeout=60000)
        except Exception:
            pass
        try:
            page.wait_for_selector(
                (
                    'a[href*="/sales/lead/"], '
                    'a[href*="/sales/people/"], '
                    'a[href*="/in/"]'
                ),
                timeout=60000,
            )
        except Exception:
            self.logger.warning(
                "Timed out waiting for Sales Navigator lead anchors. "
                "Confirm the browser is logged in and results are visible."
            )
        self._raise_if_sales_nav_rate_limited(page)

        leads: list[Lead] = []
        seen_urls: set[str] = set()
        seen_name_company: set[str] = set()
        seen_name_title_location: set[str] = set()
        max_empty_rounds = 5
        page_number = 1
        last_saved_count = 0

        resume_from_checkpoint = bool(self.filters.get("resume_from_checkpoint"))
        checkpoint = run_repo.get_checkpoint(self.run.id) if resume_from_checkpoint else None
        start_page = int(self.filters.get("start_page") or 1)

        if checkpoint:
            start_page = max(start_page, int(checkpoint.get("last_page") or 0) + 1)

        batch_page_limit = int(
            self.filters.get("batch_page_limit")
            or os.getenv("SCRAPER_BATCH_PAGE_LIMIT", "0")
            or 0
        )

        max_pages = max(10, math.ceil(max_leads / 20) + 3)
        if batch_page_limit > 0:
            max_pages = min(max_pages, start_page + batch_page_limit - 1)

        no_new_page_count = 0

        if start_page > 1:
            self.logger.info(f"Resuming Sales Navigator scrape from page {start_page}.")
            self.emit(EventType.LEAD_SCRAPED, {
                "status": "resume",
                "page": start_page,
                "message": f"Resuming from checkpoint page {start_page}.",
            })

            while page_number < start_page:
                if not self._click_sales_nav_next_page(page):
                    self._sales_nav_stop_reason = (
                        self._sales_nav_last_next_failure or "resume_next_failed"
                    )
                    self.logger.warning(
                        f"Could not advance to resume page {start_page}. "
                        f"Stopped at page {page_number}."
                    )
                    return leads
                page_number += 1
                time.sleep(random.uniform(0.75, 1.5))

        while len(leads) < max_leads and page_number <= max_pages:
            self._raise_if_stop_requested()
            self._raise_if_sales_nav_rate_limited(page)
            self.logger.info(f"Sales Navigator page {page_number} started.")
            page_start_total = len(leads)
            empty_rounds = 0
            scroll_rounds = 0

            try:
                page.wait_for_selector(
                    'a[href*="/sales/lead/"]',
                    timeout=30000,
                )
            except Exception:
                self.logger.warning(
                    f"Sales Navigator page {page_number} has no visible "
                    "lead anchors yet."
                )

            while (
                len(leads) < max_leads
                and empty_rounds < max_empty_rounds
            ):
                self._raise_if_stop_requested()
                scroll_rounds += 1
                visible_cards = self._visible_sales_nav_cards(page)
                new_this_round = 0

                for card in visible_cards:
                    if len(leads) >= max_leads:
                        break

                    href = safe_str(card.get("href"))
                    if href and href.startswith("/"):
                        href = f"https://www.linkedin.com{href}"
                    href = href.split("?")[0].rstrip("/")

                    card_lines = card.get("card_lines")
                    if not isinstance(card_lines, list):
                        card_lines = safe_str(
                            card.get("card_text")
                        ).splitlines()
                    card_lines = [safe_str(line) for line in card_lines]

                    parsed = self._parse_sales_nav_card(
                        safe_str(card.get("raw_name")),
                        safe_str(card.get("card_text")),
                        safe_str(card.get("company_anchor_text")),
                    )
                    confidence = self._sales_nav_parse_confidence(
                        parsed,
                        href,
                    )
                    needs_repair = (
                        not safe_str(parsed.get("company"))
                        or not safe_str(parsed.get("title"))
                        or self._sales_nav_title_needs_repair(
                            safe_str(parsed.get("title"))
                        )
                    )
                    if needs_repair and card_lines:
                        parsed = self._repair_sales_nav_parse_with_openai(
                            parsed,
                            card_lines,
                        )
                        confidence = self._sales_nav_parse_confidence(
                            parsed,
                            href,
                        )
                    name = safe_str(parsed.get("full_name"))
                    company = safe_str(parsed.get("company"))
                    title = safe_str(parsed.get("title"))
                    location = safe_str(parsed.get("location"))
                    company_url = safe_str(card.get("company_linkedin_url"))
                    if company_url and company_url.startswith("/"):
                        company_url = f"https://www.linkedin.com{company_url}"
                    company_url = company_url.split("?")[0].rstrip("/")

                    if _is_placeholder_detail(name):
                        name = ""
                    if _is_placeholder_detail(title):
                        title = ""
                    if _is_placeholder_detail(company):
                        company = ""
                    if _is_placeholder_detail(location):
                        location = ""

                    if not name or len(name) < 2:
                        continue

                    if not _has_sales_nav_useful_details(
                        name,
                        title,
                        company,
                        location,
                        href,
                        company_url,
                    ):
                        self.logger.warning(
                            "Skipping Sales Navigator card with no usable "
                            f"details: name={name!r}, title={title!r}, "
                            f"company={company!r}, location={location!r}, "
                            f"href={href!r}"
                        )
                        continue

                    url_key = href.lower()
                    name_company_key = (
                        f"{name.lower()}|{company.lower()}"
                    )
                    name_title_location_key = (
                        f"{name.lower()}|{title.lower()}|{location.lower()}"
                    )
                    if url_key and url_key in seen_urls:
                        continue
                    if company and name_company_key in seen_name_company:
                        continue
                    if (
                        (title or location)
                        and name_title_location_key
                        in seen_name_title_location
                    ):
                        continue

                    if url_key:
                        seen_urls.add(url_key)
                    if company:
                        seen_name_company.add(name_company_key)
                    if title or location:
                        seen_name_title_location.add(name_title_location_key)

                    lead = Lead(
                        full_name=name[:100],
                        first_name=safe_str(parsed.get("first_name"))[:50],
                        last_name=safe_str(parsed.get("last_name"))[:50],
                        title=title[:100],
                        company=company[:100],
                        location=location[:100],
                        linkedin_url=href[:200],
                        company_linkedin_url=company_url[:200],
                        email="",
                        phone="",
                        email_confidence="",
                        segment=Segment.NO_EMAIL,
                        status=LeadStatus.SCRAPED,
                    )
                    leads.append(lead)
                    self._leads.append(lead)
                    new_this_round += 1

                    self.logger.info(
                        "Sales Navigator lead parsed: "
                        f"name={lead.full_name} | "
                        f"title={lead.title} | "
                        f"company={lead.company} | "
                        f"location={lead.location} | "
                        f"linkedin_url={lead.linkedin_url} | "
                        f"company_linkedin_url={lead.company_linkedin_url}"
                    )
                    if confidence < 3:
                        self.logger.warning(
                            "SalesNav low confidence parse:\n"
                            f"name={lead.full_name}\n"
                            f"score={confidence}\n"
                            f"lines={card_lines[:10]}"
                        )
                    if (
                        not lead.company
                        and self._split_sales_nav_title_company(lead.title)[1]
                    ):
                        self.logger.warning(
                            f"Company split missed for title: {lead.title}"
                        )
                    if not (lead.title and lead.company and lead.location):
                        debug_text = "\n".join(card_lines[:10])
                        self.logger.info(
                            "Sales Navigator debug card lines for "
                            f"{lead.full_name}:\n{debug_text}"
                        )
                    self._write_sales_nav_debug_jsonl(
                        lead=lead,
                        raw_name=safe_str(card.get("raw_name")),
                        parsed={
                            "full_name": lead.full_name,
                            "title": lead.title,
                            "company": lead.company,
                            "location": lead.location,
                        },
                        confidence=confidence,
                        card_lines=card_lines,
                    )
                    self.emit(EventType.LEAD_SCRAPED, {
                        "name": lead.full_name,
                        "company": lead.company,
                        "title": lead.title,
                        "location": lead.location,
                        "linkedin_url": lead.linkedin_url,
                        "company_linkedin_url": lead.company_linkedin_url,
                        "total_so_far": len(leads),
                        "source": "sales_navigator",
                        "page": page_number,
                    })

                # Do not checkpoint inside a scroll round.
                # Checkpoint is saved only after the page's leads are persisted to DB.

                if new_this_round == 0:
                    empty_rounds += 1
                else:
                    empty_rounds = 0

                if len(leads) >= max_leads:
                    break

                self._scroll_sales_nav_results(page)
                self._sales_nav_scroll_delay()

            page_new = len(leads) - page_start_total
            self.logger.info(
                f"Sales Navigator page {page_number} collected "
                f"{page_new} new leads. Total {len(leads)}."
            )

            if len(leads) > last_saved_count:
                new_leads = leads[last_saved_count:]
                lead_repo.save_batch(self.run.id, new_leads)
                last_saved_count = len(leads)
                self.run.total_scraped = len(leads)
                run_repo.save(self.run)
                run_repo.update_checkpoint(
                    run_id=self.run.id,
                    last_page=page_number,
                    leads_collected=len(leads),
                )
                self.logger.info(
                    f"Checkpoint saved: page {page_number}, "
                    f"{len(leads)} leads persisted."
                )
                self.emit(EventType.LEAD_SCRAPED, {
                    "status": "checkpoint_saved",
                    "page": page_number,
                    "total_so_far": len(leads),
                    "message": f"Saved checkpoint at page {page_number}.",
                })

            if len(leads) >= max_leads:
                self._sales_nav_stop_reason = "max_leads_reached"
                break

            if page_new == 0:
                no_new_page_count += 1
                self.logger.warning(
                    f"Sales Navigator page {page_number} produced zero "
                    "new leads after full scroll."
                )
            else:
                no_new_page_count = 0

            if page_number >= max_pages:
                self._sales_nav_stop_reason = "max_pages_reached"
                self.logger.info(
                    f"Sales Navigator safety max pages reached "
                    f"({max_pages}). Stopping pagination."
                )
                break

            before_signature = self._sales_nav_page_signature(page)
            if not self._click_sales_nav_next_page(page):
                self._sales_nav_stop_reason = (
                    self._sales_nav_last_next_failure or "no_next_button"
                )
                break
            self._raise_if_sales_nav_rate_limited(page)
            self._sales_nav_page_delay()

            after_signature = ""
            update_deadline = time.time() + 10
            while time.time() < update_deadline:
                after_signature = self._sales_nav_page_signature(page)
                if (
                    not before_signature
                    or not after_signature
                    or before_signature != after_signature
                ):
                    break
                time.sleep(0.75)

            self._reset_sales_nav_scroll(page)
            if (
                before_signature
                and after_signature
                and before_signature == after_signature
            ):
                no_new_page_count += 1
                self._sales_nav_stop_reason = "page_did_not_change"
                self.logger.warning(
                    "Sales Navigator next page clicked, but visible lead "
                    "signature did not change yet."
                )

            if no_new_page_count >= 2:
                self._sales_nav_stop_reason = "no_new_leads_after_next"
                self.logger.warning(
                    "No new Sales Navigator leads after pagination. "
                    "Stopping to avoid an infinite loop."
                )
                break

            page_number += 1

        if self._sales_nav_stop_reason == "unknown":
            if not leads:
                self._sales_nav_stop_reason = "blocked_or_captcha"
            else:
                self._sales_nav_stop_reason = "unknown"
        self.logger.info(
            f"Sales Navigator DOM scraper collected {len(leads)} leads total."
        )
        self._write_debug(
            "sales_navigator_leads.json",
            [lead.to_dict() for lead in leads],
        )
        return leads

    _SALESNAV_SEARCH_HINTS = (
        "salesapileadsearch",
        "salesapipeoplesearch",
        "leadsearch",
        "peoplesearch",
        "sales-api",
    )

    def _capture_salesnav_payload(self, page, trigger):
        # Attach a response listener, run the trigger (goto / next click), and
        # return the search JSON payload with the most leads, or None.
        bucket = []
        state = {"auth_or_rate": False}
        extract = getattr(self, "_extract_salesnav", None)

        def handler(response):
            try:
                url = safe_str(getattr(response, "url", "")).lower()
                if not any(hint in url for hint in self._SALESNAV_SEARCH_HINTS):
                    return
                try:
                    status = int(response.status)
                except Exception:
                    status = 0
                if status in (401, 403, 429):
                    state["auth_or_rate"] = True
                    return
                ctype = safe_str((response.headers or {}).get("content-type", "")).lower()
                if "json" not in ctype:
                    return
                bucket.append(response.json())
            except Exception:
                pass

        try:
            page.on("response", handler)
        except Exception:
            return None, False, False

        triggered = False
        try:
            result = trigger()
            triggered = True if result is None else bool(result)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            time.sleep(2.0)
        except Exception as exc:
            self.logger.warning(
                "SalesNav capture trigger failed: %s",
                _error_text(exc, "Unknown capture error"),
            )
            triggered = False
        finally:
            try:
                page.remove_listener("response", handler)
            except Exception:
                pass

        best = None
        best_n = -1
        for body in bucket:
            try:
                n = len(extract(body)) if extract else 0
            except Exception:
                n = 0
            if n > best_n:
                best_n = n
                best = body
        if best is not None:
            try:
                self._salesnav_api_dump = getattr(self, "_salesnav_api_dump", 0) + 1
                self._write_debug(f"salesnav_api_{self._salesnav_api_dump:03d}.json", best)
            except Exception:
                pass
        return best, triggered, state["auth_or_rate"]

    def _ingest_salesnav_record(self, rec, leads, seen_urls, seen_name_company, seen_name_title_location):
        name = safe_str(rec.get("full_name"))
        if not name or len(name) < 2:
            return False
        title = safe_str(rec.get("title"))
        company = safe_str(rec.get("company"))
        location = safe_str(rec.get("location"))
        href = safe_str(rec.get("linkedin_url")).split("?")[0].rstrip("/")
        first = safe_str(rec.get("first_name"))
        last = safe_str(rec.get("last_name"))

        url_key = href.lower()
        name_company_key = f"{name.lower()}|{company.lower()}"
        name_title_location_key = f"{name.lower()}|{title.lower()}|{location.lower()}"
        if url_key and url_key in seen_urls:
            return False
        if company and name_company_key in seen_name_company:
            return False
        if (title or location) and name_title_location_key in seen_name_title_location:
            return False
        if url_key:
            seen_urls.add(url_key)
        if company:
            seen_name_company.add(name_company_key)
        if title or location:
            seen_name_title_location.add(name_title_location_key)

        lead = Lead(
            full_name=name[:100],
            first_name=first[:50],
            last_name=last[:50],
            title=title[:100],
            company=company[:100],
            location=location[:100],
            linkedin_url=href[:200],
            company_linkedin_url="",
            email="",
            phone="",
            email_confidence="",
            segment=Segment.NO_EMAIL,
            status=LeadStatus.SCRAPED,
        )
        leads.append(lead)
        self._leads.append(lead)
        self.emit(EventType.LEAD_SCRAPED, {
            "name": lead.full_name,
            "company": lead.company,
            "title": lead.title,
            "location": lead.location,
            "linkedin_url": lead.linkedin_url,
            "total_so_far": len(leads),
            "source": "sales_navigator_api",
        })
        return True

    def _scrape_sales_navigator_fast(self, page, max_leads):
        from src.agents.salesnav_extractor import extract_salesnav_leads
        from src.storage import lead_repo, run_repo

        self._extract_salesnav = extract_salesnav_leads
        self._sales_nav_stop_reason = "unknown"
        self.logger.info("Sales Navigator detected. Using fast search-API capture scraper.")
        self.emit(EventType.LEAD_SCRAPED, {
            "status": "sales_navigator_api",
            "message": "Capturing Sales Navigator results from the page search API.",
        })

        try:
            page.wait_for_load_state("domcontentloaded", timeout=60000)
        except Exception:
            pass
        self._raise_if_sales_nav_rate_limited(page)

        start_url = safe_str(self.filters.get("start_url"))
        leads = []
        seen_urls = set()
        seen_name_company = set()
        seen_name_title_location = set()

        resume_from_checkpoint = bool(self.filters.get("resume_from_checkpoint"))
        checkpoint = run_repo.get_checkpoint(self.run.id) if resume_from_checkpoint else None
        start_page = int(self.filters.get("start_page") or 1)
        if checkpoint:
            start_page = max(start_page, int(checkpoint.get("last_page") or 0) + 1)

        batch_page_limit = int(self.filters.get("batch_page_limit") or os.getenv("SCRAPER_BATCH_PAGE_LIMIT", "0") or 0)
        max_pages = max(10, math.ceil(max_leads / 20) + 3)
        if batch_page_limit > 0:
            max_pages = min(max_pages, start_page + batch_page_limit - 1)

        delay_min = float(os.getenv("SALES_NAV_PAGE_DELAY_MIN", "8"))
        delay_max = float(os.getenv("SALES_NAV_PAGE_DELAY_MAX", "16"))
        chunk_lead_limit = int(os.getenv("SALES_NAV_CHUNK_LEAD_LIMIT", "500") or 500)
        chunk_page_limit = int(os.getenv("SALES_NAV_CHUNK_PAGE_LIMIT", "25") or 25)
        cooldown_minutes = int(os.getenv("SALES_NAV_COOLDOWN_MINUTES", "20") or 20)
        chunk_collected = 0
        chunk_pages = 0

        page_number = 1
        last_saved_count = 0

        if start_page > 1:
            self.logger.info(f"Resuming Sales Navigator scrape from page {start_page}.")
            while page_number < start_page:
                if not self._click_sales_nav_next_page(page):
                    self._sales_nav_stop_reason = self._sales_nav_last_next_failure or "resume_next_failed"
                    return leads
                page_number += 1
                time.sleep(random.uniform(0.75, 1.5))

        consecutive_zero = 0
        first_capture = True

        while len(leads) < max_leads and page_number <= max_pages:
            self._raise_if_stop_requested()
            self._raise_if_sales_nav_rate_limited(page)

            if first_capture:
                # run_agent already navigated, so re-open the search URL with the
                # listener attached to reliably capture this page search response.
                payload, _t, auth_or_rate = self._capture_salesnav_payload(
                    page,
                    lambda: page.goto(start_url, wait_until="domcontentloaded", timeout=60000),
                )
                first_capture = False
            else:
                clicked = {"ok": False}

                def go_next():
                    clicked["ok"] = self._click_sales_nav_next_page(page)
                    return clicked["ok"]

                payload, _t, auth_or_rate = self._capture_salesnav_payload(page, go_next)
                if not clicked["ok"]:
                    self._sales_nav_stop_reason = self._sales_nav_last_next_failure or "no_next_button"
                    break

            if auth_or_rate:
                self._sales_nav_stop_reason = "rate_limited"
                self.emit(EventType.AGENT_FAILED, {
                    "status": "rate_limited",
                    "message": "LinkedIn returned 401/403/429 on the search API. Stopped to keep the account safe.",
                })
                raise RuntimeError("LinkedIn Sales Navigator rate limit detected on the search API. Scraping paused. Retry later.")

            self._raise_if_sales_nav_rate_limited(page)

            if not payload:
                self._sales_nav_stop_reason = "no_results" if page_number == start_page else "no_payload"
                self.logger.warning(f"No Sales Navigator search payload captured on page {page_number}.")
                break

            records = extract_salesnav_leads(payload)
            page_new = 0
            for rec in records:
                if len(leads) >= max_leads:
                    break
                if self._ingest_salesnav_record(rec, leads, seen_urls, seen_name_company, seen_name_title_location):
                    page_new += 1

            self.logger.info(f"Sales Navigator page {page_number} captured {page_new} new leads. Total {len(leads)}.")
            chunk_collected += page_new
            chunk_pages += 1

            if len(leads) > last_saved_count:
                new_leads = leads[last_saved_count:]
                lead_repo.save_batch(self.run.id, new_leads)
                last_saved_count = len(leads)
                self.run.total_scraped = len(leads)
                run_repo.save(self.run)
                run_repo.update_checkpoint(run_id=self.run.id, last_page=page_number, leads_collected=len(leads))
                self.emit(EventType.LEAD_SCRAPED, {
                    "status": "checkpoint_saved",
                    "page": page_number,
                    "total_so_far": len(leads),
                    "message": f"Saved checkpoint at page {page_number}.",
                })

            if len(leads) >= max_leads:
                self._sales_nav_stop_reason = "max_leads_reached"
                break

            if page_new == 0:
                consecutive_zero += 1
                if consecutive_zero >= 2:
                    self._sales_nav_stop_reason = "no_new_leads"
                    break
            else:
                consecutive_zero = 0

            if page_number >= max_pages:
                self._sales_nav_stop_reason = "max_pages_reached"
                break

            if (
                cooldown_minutes > 0
                and len(leads) < max_leads
                and (chunk_collected >= chunk_lead_limit or chunk_pages >= chunk_page_limit)
            ):
                self._salesnav_cooldown(cooldown_minutes, len(leads))
                chunk_collected = 0
                chunk_pages = 0

            page_number += 1
            time.sleep(random.uniform(delay_min, max(delay_min, delay_max)))

        return leads

    def _salesnav_cooldown(self, minutes, total_so_far):
        total_seconds = max(0, int(minutes * 60))
        self.logger.info(
            f"Sales Navigator safe chunk reached. Cooling down {minutes} minute(s) "
            f"with the session open. Collected {total_so_far} so far."
        )
        self.emit(EventType.LEAD_SCRAPED, {
            "status": "cooldown",
            "message": (
                f"Safe chunk collected. Cooling down {minutes} minute(s) to stay "
                f"under the rate limit. Collected {total_so_far} so far."
            ),
            "cooldown_minutes": minutes,
            "total_so_far": total_so_far,
        })
        waited = 0
        while waited < total_seconds:
            self._raise_if_stop_requested()
            step = min(15, total_seconds - waited)
            time.sleep(step)
            waited += step
            remaining = max(0, total_seconds - waited)
            if remaining == 0 or waited % 60 == 0:
                self.emit(EventType.LEAD_SCRAPED, {
                    "status": "cooldown",
                    "message": f"Cooling down. About {math.ceil(remaining / 60)} minute(s) left.",
                    "cooldown_minutes": minutes,
                    "total_so_far": total_so_far,
                })
        self.emit(EventType.LEAD_SCRAPED, {
            "status": "running",
            "message": "Cooldown complete. Continuing the same Sales Navigator session.",
            "total_so_far": total_so_far,
        })

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
                error_message = _error_text(exc, "Unknown extraction error")
                self.logger.exception(
                    "Phase 2 extraction failed for page %s: %s",
                    page_num,
                    error_message,
                )
                self.emit(
                    EventType.AGENT_FAILED,
                    payload={
                        "page": page_num,
                        "stage": "phase2_extract",
                    },
                    error=error_message,
                )
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
            os.getenv("CHROME_PATH", "").strip(),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.join(
                os.getenv("LOCALAPPDATA", ""),
                "Google",
                "Chrome",
                "Application",
                "chrome.exe",
            ),
            os.path.join(
                os.getenv("PROGRAMFILES", ""),
                "Google",
                "Chrome",
                "Application",
                "chrome.exe",
            ),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]

        chrome_exe = next(
            (path for path in chrome_paths if path and os.path.exists(path)),
            None,
        )

        with sync_playwright() as pw:
            chrome_proc = None
            if chrome_exe:
                runtime_paths = configure_runtime_environment()
                debug_profile = str(runtime_paths.chrome_profile_dir)
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

                browser = None
                last_cdp_error = ""

                for attempt in range(5):
                    try:
                        browser = pw.chromium.connect_over_cdp(
                            "http://127.0.0.1:9222",
                            timeout=5000,
                        )
                        break
                    except Exception as cdp_exc:
                        last_cdp_error = _error_text(
                            cdp_exc,
                            "Unknown Chrome CDP connection error",
                        )
                        self.logger.warning(
                            f"CDP connect attempt {attempt + 1}/5 failed: "
                            f"{last_cdp_error}"
                        )
                        time.sleep(2)

                if browser is None:
                    raise RuntimeError(
                        "Could not connect to Chrome on port 9222 after 5 attempts. "
                        f"Last error: {last_cdp_error}. "
                        "Close existing scraper Chrome windows or check CHROME_PATH."
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

            def cleanup_browser() -> None:
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
                "Browser ready. Solve any CAPTCHA that appears."
            )
            self.emit(EventType.LEAD_SCRAPED, {
                "status": "browser_ready",
                "message": "Browser opened. Solve CAPTCHA if shown.",
            })

            page.goto(start_url, wait_until="commit", timeout=60000)

            if is_sales_nav:
                leads = self._scrape_sales_navigator_fast(page, max_leads)
                self.run.total_scraped = len(leads)
                if leads:
                    from src.storage import lead_repo

                    lead_repo.save_batch(self.run.id, leads)
                    self._storer.mark_saved_duplicates(self.run, leads)
                    self.logger.info(
                        f"Saved {len(leads)} Sales Navigator leads to DB."
                    )
                cleanup_browser()
                return leads

            self.logger.info("=" * 55)
            self.logger.info("PHASE 1: Collecting all pages fast.")
            self.logger.info("Solve CAPTCHA when it appears.")
            self.logger.info("OpenAI extraction runs AFTER all pages copied.")
            self.logger.info("=" * 55)

            estimated_pages = max(1, (max_leads // 15) + 1)
            page_num = 1

            first_hash = self._page_hash(page)
            self._seen_hashes.add(first_hash)

            while page_num <= estimated_pages:
                self._raise_if_stop_requested()
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
            cleanup_browser()

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
                error_message = _error_text(exc, "Unknown extraction error")
                self.logger.exception(
                    "Phase 2 extraction failed for page %s: %s",
                    page_num,
                    error_message,
                )
                self.emit(
                    EventType.AGENT_FAILED,
                    payload={
                        "page": page_num,
                        "stage": "phase2_extract",
                    },
                    error=error_message,
                )
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
            self._storer.mark_saved_duplicates(self.run, self._leads)
            self.logger.info(
                f"Saved {len(self._leads)} leads to DB with all fields."
            )

        self.run.total_scraped = len(self._leads)
        self.logger.info(
            f"Done. {len(self._leads)} leads collected."
        )
        return self._leads
