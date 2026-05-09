from dataclasses import dataclass
from datetime import datetime, timedelta
import re


REMINDER_COMMANDS = ("remind", "reminder")

IN_PATTERN = re.compile(
    r"^in\s+(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\s+(.+)$",
    re.IGNORECASE,
)
DATE_TIME_PATTERNS = (
    ("%Y-%m-%d", re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(.+)$")),
    ("%d.%m.%Y", re.compile(r"^(\d{1,2}\.\d{1,2}\.\d{4})\s+(.+)$")),
    ("%m/%d", re.compile(r"^(\d{1,2}/\d{1,2})\s+(.+)$")),
)
TIME_PATTERN = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+(.+)$", re.IGNORECASE)


@dataclass
class ReminderDetails:
    due_at: datetime | None
    note_text: str
    error: str
    title_due_text: str = ""
    subtitle_due_text: str = ""


def _plural(value, unit):
    return f"{value} {unit}" if value == 1 else f"{value} {unit}s"


def _format_time(due_at):
    return due_at.strftime("%H:%M")


def _format_date(due_at):
    return due_at.strftime("%Y-%m-%d")


def _relative_due_text(amount, unit):
    if unit.startswith("s"):
        return f"in {_plural(amount, 'second')}"
    if unit.startswith("m"):
        return f"in {_plural(amount, 'minute')}"
    if unit.startswith("h"):
        return f"in {_plural(amount, 'hour')}"
    if unit.startswith("d"):
        return f"in {_plural(amount, 'day')}"
    return "with reminder"


def _calendar_due_text(due_at, now):
    today = now.date()
    due_date = due_at.date()
    time_text = _format_time(due_at)
    if due_date == today:
        return f"today at {time_text}"
    if due_date == today + timedelta(days=1):
        return f"tomorrow at {time_text}"
    return f"on {_format_date(due_at)} at {time_text}"


def _subtitle_due_text(due_at, now):
    calendar_text = _calendar_due_text(due_at, now)
    seconds = int((due_at - now).total_seconds())
    if seconds <= 0:
        return calendar_text
    if seconds < 60:
        return f"{calendar_text} ({_relative_due_text(seconds, 's')})"

    minutes = (seconds + 30) // 60
    if minutes < 60:
        return f"{calendar_text} ({_relative_due_text(minutes, 'm')})"

    hours = minutes // 60
    remaining_minutes = minutes % 60
    if hours < 24:
        relative = _relative_due_text(hours, "h")
        if remaining_minutes:
            relative += f" {_plural(remaining_minutes, 'minute')}"
        return f"{calendar_text} ({relative})"

    days = hours // 24
    remaining_hours = hours % 24
    relative = _relative_due_text(days, "d")
    if remaining_hours:
        relative += f" {_plural(remaining_hours, 'hour')}"
    return f"{calendar_text} ({relative})"


def _details(due_at, note_text, now, title_due_text):
    return ReminderDetails(
        due_at=due_at,
        note_text=note_text,
        error="",
        title_due_text=title_due_text,
        subtitle_due_text=_subtitle_due_text(due_at, now),
    )


def _error(message):
    return ReminderDetails(None, "", message)


def _parse_time(value):
    match = TIME_PATTERN.match(str(value or "").strip())
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = (match.group(3) or "").lower()
    rest = match.group(4).strip()

    if minute > 59:
        return None
    if meridiem:
        if hour < 1 or hour > 12:
            return None
        if meridiem == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
    elif hour > 23:
        return None

    if not rest:
        return None
    return hour, minute, rest


def _with_time(base_date, time_and_text):
    parsed = _parse_time(time_and_text)
    if not parsed:
        return None, ""
    hour, minute, note_text = parsed
    return base_date.replace(hour=hour, minute=minute, second=0, microsecond=0), note_text


def _parse_absolute_request(raw, now):
    lowered = raw.lower()
    for keyword, delta_days in (("today ", 0), ("tomorrow ", 1)):
        if lowered.startswith(keyword):
            due_at, note_text = _with_time(now + timedelta(days=delta_days), raw[len(keyword):].strip())
            if due_at is None:
                return _error("Use time like 09:00, 21:00, 9am, or 9:30pm")
            if due_at <= now:
                return _error("Reminder time must be in the future")
            return _details(due_at, note_text, now, _calendar_due_text(due_at, now))

    for date_format, pattern in DATE_TIME_PATTERNS:
        match = pattern.match(raw)
        if not match:
            continue
        date_text = match.group(1)
        try:
            parsed_date = datetime.strptime(date_text, date_format)
        except ValueError:
            return _error("Invalid reminder date")

        year = parsed_date.year if "%Y" in date_format else now.year
        try:
            base_date = now.replace(year=year, month=parsed_date.month, day=parsed_date.day)
        except ValueError:
            return _error("Invalid reminder date")
        due_at, note_text = _with_time(base_date, match.group(2).strip())
        if due_at is None:
            return _error("Use time like 09:00, 21:00, 9am, or 9:30pm")
        if "%Y" not in date_format and due_at <= now:
            try:
                due_at = due_at.replace(year=due_at.year + 1)
            except ValueError:
                return _error("Invalid reminder date")
        if due_at <= now:
            return _error("Reminder time must be in the future")
        return _details(due_at, note_text, now, _calendar_due_text(due_at, now))

    due_at, note_text = _with_time(now, raw)
    if due_at is not None:
        if due_at <= now:
            due_at = due_at + timedelta(days=1)
        return _details(due_at, note_text, now, _calendar_due_text(due_at, now))

    return _error("Use: in 10m [text], today 09:00 [text], tomorrow 9am [text], or 01.05.2026 21:00 [text]")


def parse_reminder_details(text, now=None):
    now = now or datetime.now().astimezone()
    raw = str(text or "").strip()
    match = IN_PATTERN.match(raw)
    if not match:
        return _parse_absolute_request(raw, now)

    amount = int(match.group(1))
    unit = match.group(2).lower()
    note_text = match.group(3).strip()
    if not note_text:
        return _error("Reminder text is required")
    if amount <= 0:
        return _error("Reminder time must be in the future")

    if unit.startswith("s"):
        delta = timedelta(seconds=amount)
    elif unit.startswith("m"):
        delta = timedelta(minutes=amount)
    elif unit.startswith("h"):
        delta = timedelta(hours=amount)
    elif unit.startswith("d"):
        delta = timedelta(days=amount)
    else:
        return _error("Unsupported reminder unit")

    due_at = now + delta
    return _details(due_at, note_text, now, _relative_due_text(amount, unit))


def parse_reminder_request(text, now=None):
    details = parse_reminder_details(text, now)
    return details.due_at, details.note_text, details.error
