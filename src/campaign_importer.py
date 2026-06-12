import json
import logging
from pathlib import Path

from src.models import CampaignSequenceStep
from src.storage import campaign_repo, campaign_sequence_repo, kv_repo


logger = logging.getLogger(__name__)
IMPORT_KEY = "campaigns_imported_v1"


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


def import_campaign_seed_files_once() -> None:
    if kv_repo.get(IMPORT_KEY):
        return

    campaigns_dir = Path("campaigns")
    if not campaigns_dir.exists():
        kv_repo.set(IMPORT_KEY, "1")
        return

    for path in sorted(campaigns_dir.glob("*.json")):
        if path.name == "sequences.json":
            continue
        _import_campaign_file(path)

    _import_sequences_file(campaigns_dir / "sequences.json")
    kv_repo.set(IMPORT_KEY, "1")
    logger.info("Campaign seed import complete")
