import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from src.runtime_paths import configure_runtime_environment


def main() -> None:
    runtime_paths = configure_runtime_environment()

    db_path = Path(os.getenv("DB_PATH", str(runtime_paths.db_path)))
    backup_dir = Path(os.getenv("DB_BACKUP_DIR", "./backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}_{timestamp}.sqlite3"

    source = sqlite3.connect(str(db_path), timeout=30)
    try:
        target = sqlite3.connect(str(backup_path), timeout=30)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    print(f"Backup created: {backup_path}")


if __name__ == "__main__":
    main()
