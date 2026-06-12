import json
import logging
from pathlib import Path

from src.models import CampaignSequenceStep
from src.storage import campaign_repo, campaign_sequence_repo, kv_repo


logger = logging.getLogger(__name__)
IMPORT_KEY = "campaigns_imported_v1"

DEFAULT_SEQUENCE_STEPS = [
    {
        "number": 1,
        "name": "Email 1",
        "delay_days": 0,
        "delay_value": 0,
        "delay_unit": "days",
        "delay_type": "calendar_days",
        "send_time_mode": "same_as_previous",
        "fixed_send_time": "",
        "subject_template": "",
        "email_body_template": "",
        "linkedin_message_template": "",
        "is_active": True,
    },
    {
        "number": 2,
        "name": "Follow-up 1",
        "delay_days": 3,
        "delay_value": 3,
        "delay_unit": "days",
        "delay_type": "calendar_days",
        "send_time_mode": "same_as_previous",
        "fixed_send_time": "",
        "subject_template": "",
        "email_body_template": "",
        "linkedin_message_template": "",
        "is_active": True,
    },
    {
        "number": 3,
        "name": "Follow-up 2",
        "delay_days": 7,
        "delay_value": 7,
        "delay_unit": "days",
        "delay_type": "calendar_days",
        "send_time_mode": "same_as_previous",
        "fixed_send_time": "",
        "subject_template": "",
        "email_body_template": "",
        "linkedin_message_template": "",
        "is_active": True,
    },
]


def _campaign_filename(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return value if value.endswith(".json") else f"{value}.json"


def _touch_number(touch: dict) -> int:
    try:
        return int(touch.get("touch_number") or touch.get("number") or 0)
    except (TypeError, ValueError):
        return 0


def _import_campaign_file(path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        campaign_repo.upsert_from_file(path.stem, data)
        logger.info("Imported campaign seed %s", path.name)
    except Exception:
        logger.exception("Failed importing campaign seed %s", path)


def _import_sequences_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        all_settings = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed reading campaign sequence seed %s", path)
        return

    for campaign_key, settings in (all_settings or {}).items():
        campaign_filename = _campaign_filename(campaign_key)
        if not campaign_filename:
            continue
        for touch in (settings or {}).get("touches", []):
            number = _touch_number(touch)
            if number <= 0:
                continue
            try:
                existing = campaign_sequence_repo.get_step(
                    campaign_filename,
                    number,
                    active_only=False,
                )
                if existing:
                    continue
                delay_days = int(touch.get("delay_days") or 0)
                delay_value = int(touch.get("delay_value") or delay_days or 0)
                campaign_sequence_repo.save_step(CampaignSequenceStep(
                    campaign_filename=campaign_filename,
                    touch_number=number,
                    touch_name=touch.get("touch_name") or touch.get("name") or "",
                    delay_days=delay_days,
                    delay_value=delay_value,
                    delay_unit=touch.get("delay_unit") or "days",
                    delay_type=touch.get("delay_type") or "calendar_days",
                    send_time_mode=touch.get("send_time_mode") or "same_as_previous",
                    fixed_send_time=touch.get("fixed_send_time") or "",
                    subject_template=touch.get("subject_template", "") or "",
                    email_body_template=touch.get("email_body_template", "") or "",
                    linkedin_message_template=touch.get(
                        "linkedin_message_template",
                        "",
                    ) or "",
                    is_active=bool(touch.get("is_active", True)),
                ))
            except Exception:
                logger.exception(
                    "Failed importing sequence seed %s touch %s",
                    campaign_filename,
                    number,
                )


def _ensure_default_sequences_for_imported_campaigns() -> None:
    for campaign in campaign_repo.list_all():
        campaign_filename = campaign.get("filename") or ""
        if not campaign_filename:
            continue

        try:
            campaign_sequence_repo.ensure_defaults(
                campaign_filename,
                DEFAULT_SEQUENCE_STEPS,
            )
        except Exception:
            logger.exception(
                "Failed ensuring default sequence settings for %s",
                campaign_filename,
            )


def import_campaign_seed_files_once() -> None:
    if kv_repo.get(IMPORT_KEY):
        _ensure_default_sequences_for_imported_campaigns()
        return

    campaigns_dir = Path("campaigns")
    if not campaigns_dir.exists():
        _ensure_default_sequences_for_imported_campaigns()
        kv_repo.set(IMPORT_KEY, "1")
        return

    for path in sorted(campaigns_dir.glob("*.json")):
        if path.name == "sequences.json":
            continue
        _import_campaign_file(path)

    _import_sequences_file(campaigns_dir / "sequences.json")
    _ensure_default_sequences_for_imported_campaigns()
    kv_repo.set(IMPORT_KEY, "1")
    logger.info("Campaign seed import complete")
