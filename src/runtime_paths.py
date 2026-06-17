from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


APP_NAME = "RoyalCyberLeadPipeline"
DESKTOP_MODE_VALUES = {"built", "desktop", "packaged", "prod", "production"}


@dataclass(frozen=True)
class RuntimePaths:
    use_app_data: bool
    app_data_dir: Path
    db_path: Path
    output_dir: Path
    log_dir: Path
    chrome_profile_dir: Path
    debug_dir: Path
    knowledge_base_dir: Path
    env_file: Path


def project_root() -> Path:
    return Path.cwd()


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", project_root()))


def bundled_knowledge_base_dir() -> Path:
    return resource_root() / "knowledge_base"


def is_app_data_mode() -> bool:
    desktop_mode = os.getenv("RCLP_DESKTOP_MODE", "").strip().lower()
    return bool(os.getenv("APP_DATA_DIR")) or desktop_mode in DESKTOP_MODE_VALUES


def default_app_data_dir() -> Path:
    configured = os.getenv("APP_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / APP_NAME

    if sys.platform.startswith("win"):
        return Path.home() / "AppData" / "Local" / APP_NAME

    xdg_data_home = os.getenv("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home) / APP_NAME

    return Path.home() / ".local" / "share" / APP_NAME


def load_runtime_env(override: bool = False) -> None:
    app_data_env = default_app_data_dir() / ".env"
    root_env = project_root() / ".env"

    if override:
        if root_env.exists():
            load_dotenv(root_env, override=True)
        if is_app_data_mode() and app_data_env.exists():
            load_dotenv(app_data_env, override=True)
        return

    if is_app_data_mode() and app_data_env.exists():
        load_dotenv(app_data_env, override=False)
    if root_env.exists():
        load_dotenv(root_env, override=False)


def _path_from_env(name: str, fallback: Path, base_dir: Path | None = None) -> Path:
    value = os.getenv(name, "").strip()
    if not value:
        return fallback

    path = Path(value).expanduser()
    if base_dir is not None and not path.is_absolute():
        return base_dir / path
    return path


def _default_runtime_paths() -> RuntimePaths:
    load_runtime_env()

    use_app_data = is_app_data_mode()
    app_data_dir = default_app_data_dir() if use_app_data else project_root()
    relative_base = app_data_dir if use_app_data else None

    if use_app_data:
        db_fallback = app_data_dir / "pipeline.db"
        output_fallback = app_data_dir / "output"
        log_fallback = app_data_dir / "logs"
        chrome_fallback = app_data_dir / "chrome-scraper-profile"
        debug_fallback = app_data_dir / "debug"
        kb_fallback = app_data_dir / "knowledge_base"
    else:
        db_fallback = Path("./pipeline.db")
        output_fallback = Path("./output")
        log_fallback = Path("./logs")
        chrome_fallback = Path.home() / "chrome-scraper-profile"
        debug_fallback = Path("./debug")
        kb_fallback = Path("./knowledge_base")

    return RuntimePaths(
        use_app_data=use_app_data,
        app_data_dir=app_data_dir,
        db_path=_path_from_env("DB_PATH", db_fallback, relative_base),
        output_dir=_path_from_env("OUTPUT_DIR", output_fallback, relative_base),
        log_dir=_path_from_env("LOG_DIR", log_fallback, relative_base),
        chrome_profile_dir=_path_from_env(
            "CHROME_PROFILE_DIR",
            chrome_fallback,
            relative_base,
        ),
        debug_dir=_path_from_env("DEBUG_DIR", debug_fallback, relative_base),
        knowledge_base_dir=_path_from_env(
            "KNOWLEDGE_BASE_DIR",
            kb_fallback,
            relative_base,
        ),
        env_file=app_data_dir / ".env" if use_app_data else Path(".env"),
    )


def _copy_if_missing(source: Path, target: Path) -> None:
    if not source.exists() or target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_legacy_database_once(paths: RuntimePaths) -> None:
    if not paths.use_app_data:
        return

    legacy_db = project_root() / "pipeline.db"
    target_db = paths.db_path
    if target_db.exists() or not legacy_db.exists():
        return

    try:
        _copy_if_missing(legacy_db, target_db)
        for suffix in ("-wal", "-shm"):
            _copy_if_missing(
                Path(f"{legacy_db}{suffix}"),
                Path(f"{target_db}{suffix}"),
            )
    except OSError as exc:
        raise RuntimeError(
            f"Could not copy existing database to app data: {exc}"
        ) from exc


def configure_runtime_environment(create_dirs: bool = True) -> RuntimePaths:
    paths = _default_runtime_paths()

    os.environ["DB_PATH"] = str(paths.db_path)
    os.environ["OUTPUT_DIR"] = str(paths.output_dir)

    if paths.use_app_data:
        os.environ["APP_DATA_DIR"] = str(paths.app_data_dir)
        os.environ["LOG_DIR"] = str(paths.log_dir)
        os.environ["CHROME_PROFILE_DIR"] = str(paths.chrome_profile_dir)
        os.environ["DEBUG_DIR"] = str(paths.debug_dir)
        os.environ["KNOWLEDGE_BASE_DIR"] = str(paths.knowledge_base_dir)

    if create_dirs:
        paths.db_path.parent.mkdir(parents=True, exist_ok=True)
        if paths.use_app_data:
            for directory in (
                paths.app_data_dir,
                paths.output_dir,
                paths.log_dir,
                paths.chrome_profile_dir,
                paths.debug_dir,
                paths.knowledge_base_dir,
            ):
                directory.mkdir(parents=True, exist_ok=True)
            _copy_legacy_database_once(paths)

    return paths


def user_env_path() -> Path:
    paths = configure_runtime_environment()
    return paths.env_file
