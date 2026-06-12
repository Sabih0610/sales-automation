import os
import random
from datetime import datetime, time as dt_time, timedelta

from src.storage import send_log_repo


FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "icloud.com",
    "live.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _parse_hhmm(value: str, fallback: str) -> dt_time:
    raw = (value or fallback).strip()
    try:
        hour_text, minute_text = raw.split(":", 1)
        return dt_time(hour=int(hour_text), minute=int(minute_text))
    except Exception:
        fallback_hour, fallback_minute = fallback.split(":", 1)
        return dt_time(hour=int(fallback_hour), minute=int(fallback_minute))


def _karachi_now() -> datetime:
    # Asia/Karachi is UTC+05:00 and does not currently use DST.
    return datetime.utcnow() + timedelta(hours=5)


def _domain_for_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    if "@" not in normalized:
        return ""
    return normalized.rsplit("@", 1)[-1].strip().lower()


def next_send_delay_seconds() -> float:
    minimum = _env_float("SEND_JITTER_MIN", 25.0)
    maximum = _env_float("SEND_JITTER_MAX", 75.0)

    if maximum < minimum:
        maximum = minimum

    return random.uniform(minimum, maximum)


class SendPolicy:
    def account_age_days(self) -> int:
        first_send = send_log_repo.first_send_date()
        if not first_send:
            return 0

        today_karachi = _karachi_now().date()
        return max((today_karachi - first_send).days, 0)

    def todays_cap(self) -> int:
        override = os.getenv("SEND_RAMP_OVERRIDE", "").strip()
        if override:
            try:
                return max(int(override), 0)
            except ValueError:
                pass

        age = self.account_age_days()

        if age <= 2:
            return 20
        if age <= 6:
            return 40
        if age <= 13:
            return 75
        if age <= 29:
            return 150

        return _env_int("MAX_EMAILS_PER_DAY", 300)

    def per_domain_cap(self) -> int:
        return _env_int("PER_DOMAIN_DAILY_CAP", 4)

    def send_window(self) -> dict:
        start_raw = os.getenv("SEND_WINDOW_START", "09:00")
        end_raw = os.getenv("SEND_WINDOW_END", "17:30")

        start_time = _parse_hhmm(start_raw, "09:00")
        end_time = _parse_hhmm(end_raw, "17:30")

        now = _karachi_now()
        skip_weekends = os.getenv("SKIP_WEEKENDS", "true").lower() != "false"

        is_weekend = now.weekday() >= 5
        in_time_window = start_time <= now.time() <= end_time

        open_now = in_time_window and not (skip_weekends and is_weekend)

        return {
            "start": start_raw,
            "end": end_raw,
            "open_now": open_now,
            "timezone": "Asia/Karachi",
            "skip_weekends": skip_weekends,
            "is_weekend": is_weekend,
        }

    def status(self) -> dict:
        cap = self.todays_cap()
        sent_today = send_log_repo.count_today()

        window = self.send_window()

        return {
            "account_age_days": self.account_age_days(),
            "todays_cap": cap,
            "sent_today": sent_today,
            "remaining_today": max(cap - sent_today, 0),
            "window": window,
            "per_domain_cap": self.per_domain_cap(),
        }

    def check(
        self,
        to_email: str,
        campaign_filename: str = "",
    ) -> tuple[bool, str]:
        normalized_email = (to_email or "").strip().lower()
        current_campaign = (campaign_filename or "").strip()
        domain = _domain_for_email(normalized_email)

        if not normalized_email or "@" not in normalized_email:
            return False, "Invalid email"

        todays_cap = self.todays_cap()
        sent_today = send_log_repo.count_today()

        if sent_today >= todays_cap:
            return False, f"Daily cap reached ({todays_cap})"

        if domain and domain not in FREE_EMAIL_DOMAINS:
            domain_count = send_log_repo.count_today_for_domain(domain)
            domain_cap = self.per_domain_cap()

            if domain_count >= domain_cap:
                return False, f"Per-domain cap for {domain}"

        window = self.send_window()
        if not window["open_now"]:
            return False, "Outside send window"

        cooldown_days = _env_int("GLOBAL_CONTACT_COOLDOWN_DAYS", 30)
        if cooldown_days > 0 and current_campaign:
            previous = send_log_repo.last_send_for_email(normalized_email)
            if previous:
                other_campaign = previous.get("campaign_filename", "") or ""
                sent_at = previous.get("sent_at", "") or ""
                if other_campaign and other_campaign != current_campaign and sent_at:
                    try:
                        sent_dt = datetime.fromisoformat(sent_at)
                    except ValueError:
                        sent_dt = None
                    if sent_dt:
                        days_ago = max((datetime.utcnow() - sent_dt).days, 0)
                        if datetime.utcnow() - sent_dt < timedelta(days=cooldown_days):
                            return (
                                False,
                                (
                                    f"Contacted by {other_campaign} {days_ago}d ago "
                                    "— global cooldown"
                                ),
                            )

        return True, ""
