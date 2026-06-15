from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def _get_attr(obj, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _parse_clock(value: str, fallback: time) -> time:
    try:
        hour, minute, *_ = (value or "").split(":")
        return time(int(hour), int(minute))
    except Exception:
        return fallback


def _as_campaign_time(value: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name or "Asia/Karachi")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(tz)


def _to_utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _add_business_days(value: datetime, days: int) -> datetime:
    if days <= 0:
        return value
    current = value
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def _next_valid_weekday(value: datetime, preferred: time | None = None) -> datetime:
    current = value
    while current.weekday() >= 5:
        current += timedelta(days=1)
    if preferred:
        current = current.replace(
            hour=preferred.hour,
            minute=preferred.minute,
            second=0,
            microsecond=0,
        )
    return current


def _move_to_next_window_day(value: datetime, window_start: time, skip_weekends: bool) -> datetime:
    current = (value + timedelta(days=1)).replace(
        hour=window_start.hour,
        minute=window_start.minute,
        second=0,
        microsecond=0,
    )
    if skip_weekends:
        current = _next_valid_weekday(current, window_start)
    return current


def calculate_next_touch_due_at(
    previous_sent_at: datetime,
    next_step,
    rules,
) -> datetime:
    tz_name = _get_attr(rules, "timezone", "Asia/Karachi") or "Asia/Karachi"
    due = _as_campaign_time(previous_sent_at, tz_name)

    delay_value = int(
        _get_attr(next_step, "delay_value", None)
        if _get_attr(next_step, "delay_value", None) not in (None, "")
        else _get_attr(next_step, "delay_days", 0)
    )
    delay_unit = (_get_attr(next_step, "delay_unit", "days") or "days").lower()
    delay_type = (_get_attr(next_step, "delay_type", "calendar_days") or "calendar_days").lower()
    send_time_mode = (
        _get_attr(next_step, "send_time_mode", "same_as_previous")
        or "same_as_previous"
    ).lower()
    window_start = _parse_clock(
        _get_attr(rules, "send_window_start", "09:00"),
        time(9, 0),
    )
    window_end = _parse_clock(
        _get_attr(rules, "send_window_end", "17:00"),
        time(17, 0),
    )
    skip_weekends = bool(_get_attr(rules, "skip_weekends", False))

    if delay_unit == "minutes":
        due += timedelta(minutes=delay_value)
    elif delay_unit == "hours":
        due += timedelta(hours=delay_value)
    elif delay_type == "business_days":
        due = _add_business_days(due, delay_value)
    else:
        due += timedelta(days=delay_value)

    previous_time = due.timetz().replace(tzinfo=None)
    if send_time_mode == "fixed_time":
        fixed = _parse_clock(_get_attr(next_step, "fixed_send_time", ""), window_start)
        due = due.replace(hour=fixed.hour, minute=fixed.minute, second=0, microsecond=0)
        preferred_time = fixed
    elif send_time_mode == "next_available_in_window":
        preferred_time = window_start
    else:
        due = due.replace(second=0, microsecond=0)
        preferred_time = previous_time

    if skip_weekends and due.weekday() >= 5:
        due = _next_valid_weekday(due, preferred_time)

    current_time = due.timetz().replace(tzinfo=None)
    if current_time < window_start:
        due = due.replace(
            hour=window_start.hour,
            minute=window_start.minute,
            second=0,
            microsecond=0,
        )
    elif current_time > window_end:
        due = _move_to_next_window_day(due, window_start, skip_weekends)

    if skip_weekends and due.weekday() >= 5:
        due = _next_valid_weekday(due, window_start)

    return _to_utc_naive(due)
