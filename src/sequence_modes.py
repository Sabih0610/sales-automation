def normalize_sequence_mode(value: str | None) -> str:
    mode = (value or "manual").strip().lower()
    if mode in {"auto", "autopilot"}:
        return "auto"
    if mode in {"manual", "review"}:
        return "manual"
    return mode
