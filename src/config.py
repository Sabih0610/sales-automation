##src\config.py

import os
from dataclasses import dataclass
from pathlib import Path

from src.models import EnrichmentMode, OutputFormat
from src.runtime_paths import configure_runtime_environment


class ConfigError(Exception):
    pass


@dataclass
class Settings:
    enrichment_mode: EnrichmentMode = EnrichmentMode.FREE
    zoominfo_client_id: str = ""
    zoominfo_private_key: str = ""
    output_format: OutputFormat = OutputFormat.XLSX
    output_dir: Path = Path("./output")
    max_leads: int = 1000
    smtp_timeout: int = 10
    db_path: Path = Path("./pipeline.db")

    def validate_for_zoominfo(self) -> None:
        if self.enrichment_mode == EnrichmentMode.ZOOMINFO:
            if not self.zoominfo_client_id or not self.zoominfo_private_key:
                raise ConfigError(
                    "ZOOMINFO_ENABLED=true but ZOOMINFO_CLIENT_ID or "
                    "ZOOMINFO_PRIVATE_KEY missing in .env"
                )


def load_settings() -> Settings:
    runtime_paths = configure_runtime_environment()

    zoominfo_enabled = os.getenv("ZOOMINFO_ENABLED", "").lower() == "true"
    enrichment_mode = (
        EnrichmentMode.ZOOMINFO if zoominfo_enabled else EnrichmentMode.FREE
    )

    zoominfo_client_id = os.getenv("ZOOMINFO_CLIENT_ID", "").strip()
    zoominfo_private_key = os.getenv("ZOOMINFO_PRIVATE_KEY", "").strip()

    output_format_value = os.getenv("OUTPUT_FORMAT", "xlsx").lower()
    if output_format_value == "csv":
        output_format = OutputFormat.CSV
    elif output_format_value == "xlsx":
        output_format = OutputFormat.XLSX
    else:
        raise ConfigError("OUTPUT_FORMAT must be either 'csv' or 'xlsx'.")

    return Settings(
        enrichment_mode=enrichment_mode,
        zoominfo_client_id=zoominfo_client_id,
        zoominfo_private_key=zoominfo_private_key,
        output_format=output_format,
        output_dir=Path(os.getenv("OUTPUT_DIR", str(runtime_paths.output_dir))),
        max_leads=int(os.getenv("MAX_LEADS", "1000")),
        smtp_timeout=int(os.getenv("SMTP_TIMEOUT", "10")),
        db_path=Path(os.getenv("DB_PATH", str(runtime_paths.db_path))),
    )


settings = load_settings()
