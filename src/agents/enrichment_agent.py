###src\agents\enrichment_agent.py
import hashlib
import hmac
import json
import re
import smtplib
import socket
import time

import dns.resolver
import requests
from tqdm import tqdm

from src.agents.base import BaseAgent
from src.config import settings
from src.models import (
    EnrichmentMode,
    EnrichmentResult,
    EventType,
    Lead,
    LeadStatus,
    PipelineRun,
    datetime,
)


class EnrichmentAgent(BaseAgent):
    def __init__(self, run: PipelineRun, leads: list[Lead]):
        super().__init__(run)
        self.leads = leads
        self._zi_token: str = ""
        self._zi_token_expiry: float = 0.0

    def _clean(self, s: str) -> str:
        return re.sub(r"[^a-z]", "", s.lower().strip())

    def _email_candidates(self, first: str, last: str, domain: str) -> list[str]:
        f = self._clean(first)
        l = self._clean(last)
        if not f or not l or not domain:
            return []
        fi = f[0]
        li = l[0]
        patterns = [
            f"{f}.{l}",
            f"{fi}{l}",
            f"{f}{l}",
            f"{f}_{l}",
            f"{f}",
            f"{fi}.{l}",
            f"{l}.{f}",
            f"{l}{fi}",
            f"{f}-{l}",
        ]
        seen = set()
        out = []
        for pattern in patterns:
            email = f"{pattern}@{domain}"
            if email not in seen:
                seen.add(email)
                out.append(email)
        return out

    def _clearbit_domain(self, company: str) -> str:
        if not company:
            return ""
        try:
            response = requests.get(
                "https://autocomplete.clearbit.com/v1/companies/suggest",
                params={"query": company},
                timeout=8,
            )
            if response.status_code == 200 and response.json():
                return response.json()[0].get("domain", "")
        except Exception:
            pass
        return ""

    def _smtp_verify(self, email: str, domain: str) -> tuple[bool, str]:
        try:
            mx_records = sorted(
                dns.resolver.resolve(domain, "MX"),
                key=lambda record: record.preference,
            )
            mx_host = str(mx_records[0].exchange).rstrip(".")
        except Exception:
            return False, "error"
        try:
            with smtplib.SMTP(timeout=settings.smtp_timeout) as smtp:
                smtp.connect(mx_host, 25)
                smtp.helo("verify-check.com")
                smtp.mail("verify@example-check.com")
                code, _ = smtp.rcpt(email)
                if code != 250:
                    return False, "invalid"
                code2, _ = smtp.rcpt(f"zzz_fake_9999@{domain}")
                return True, "catch_all" if code2 == 250 else "verified"
        except Exception:
            return False, "error"

    def _enrich_free(self, lead: Lead) -> EnrichmentResult:
        """
        Free enrichment - domain discovery only.
        No SMTP, no email guessing, no waiting.
        ZoomInfo handles email enrichment separately.
        """
        domain = lead.company_domain

        if not domain and lead.company:
            domain = self._clearbit_domain(lead.company)

        return EnrichmentResult(
            lead_id=lead.id,
            success=bool(domain),
            company_domain=domain,
            mode_used=EnrichmentMode.FREE,
        )

    def _zi_get_token(self) -> str:
        if self._zi_token and time.time() < self._zi_token_expiry - 60:
            return self._zi_token
        import time as t

        ts = int(t.time())
        msg = json.dumps(
            {"client_id": settings.zoominfo_client_id, "timestamp": ts},
            separators=(",", ":"),
        ).encode()
        sig = hmac.new(
            settings.zoominfo_private_key.encode(),
            msg,
            hashlib.sha256,
        ).hexdigest()
        response = requests.post(
            "https://api.zoominfo.com/authenticate",
            json={
                "client_id": settings.zoominfo_client_id,
                "timestamp": ts,
                "signature": sig,
            },
            timeout=15,
        )
        response.raise_for_status()
        self._zi_token = response.json()["jwt"]
        self._zi_token_expiry = time.time() + 3600
        return self._zi_token

    def _enrich_zoominfo(self, lead: Lead) -> EnrichmentResult:
        headers = {
            "Authorization": f"Bearer {self._zi_get_token()}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            "https://api.zoominfo.com/search/contact",
            headers=headers,
            json={
                "matchPersonInput": [
                    {
                        "firstName": lead.first_name,
                        "lastName": lead.last_name,
                        "companyName": lead.company,
                    }
                ],
                "outputFields": ["email", "phone", "companyWebsite"],
            },
            timeout=15,
        )
        if not response.ok:
            return EnrichmentResult(
                lead_id=lead.id,
                success=False,
                error=f"ZI HTTP {response.status_code}",
                mode_used=EnrichmentMode.ZOOMINFO,
            )
        rows = response.json().get("data", {}).get("outputFields", [])
        if not rows:
            return EnrichmentResult(
                lead_id=lead.id,
                success=False,
                error="no_match",
                mode_used=EnrichmentMode.ZOOMINFO,
            )
        match = rows[0]
        domain = (
            match.get("companyWebsite", "")
            .replace("https://", "")
            .replace("http://", "")
            .rstrip("/")
        )
        intent = 0.0
        if domain:
            try:
                intent_response = requests.post(
                    "https://api.zoominfo.com/enrich/company",
                    headers=headers,
                    json={
                        "matchCompanyInput": [{"website": domain}],
                        "outputFields": ["intentScore"],
                    },
                    timeout=15,
                )
                if intent_response.ok:
                    intent_rows = intent_response.json().get("data", {}).get(
                        "outputFields",
                        [{}],
                    )
                    intent = float(intent_rows[0].get("intentScore", 0) or 0)
            except Exception:
                pass
        return EnrichmentResult(
            lead_id=lead.id,
            success=bool(match.get("email")),
            email=match.get("email", ""),
            phone=match.get("phone", ""),
            email_confidence=(
                "zoominfo_verified" if match.get("email") else "zi_no_email"
            ),
            company_domain=domain,
            intent_score=intent,
            mode_used=EnrichmentMode.ZOOMINFO,
        )

    def _apply(self, lead: Lead, result: EnrichmentResult) -> None:
        lead.email = result.email
        lead.email_confidence = result.email_confidence
        lead.phone = result.phone
        lead.company_domain = result.company_domain
        lead.intent_score = result.intent_score
        lead.status = LeadStatus.ENRICHED
        lead.updated_at = datetime.utcnow()

    def run_agent(self) -> list[Lead]:
        settings.validate_for_zoominfo()
        for lead in tqdm(self.leads, desc="Enriching", unit="lead"):
            try:
                result = (
                    self._enrich_zoominfo(lead)
                    if settings.enrichment_mode == EnrichmentMode.ZOOMINFO
                    else self._enrich_free(lead)
                )
                self._apply(lead, result)
                self.emit(
                    EventType.LEAD_ENRICHED,
                    {
                        "lead_id": lead.id,
                        "email": lead.email,
                        "confidence": lead.email_confidence,
                    },
                )
            except Exception as exc:
                lead.status = LeadStatus.FAILED
                self.emit(EventType.LEAD_ENRICHED, {"lead_id": lead.id}, error=str(exc))
            time.sleep(0.2)
        self.run.total_enriched = sum(1 for lead in self.leads if lead.email)
        return self.leads
