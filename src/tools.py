"""Deterministic tools: date resolution, deadline status, reminder drafting.
No LLM here. The LLM may extract a PHRASE ("Thursday"); code turns it into a date."""
import re
from datetime import date, timedelta
from typing import Optional

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6}
MONTHS = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
          "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
          "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
          "oct": 10, "october": 10, "nov": 11, "november": 11,
          "dec": 12, "december": 12}


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def resolve_deadline(phrase: Optional[str], ref: date) -> Optional[str]:
    """Phrase + reference date -> ISO date, or None when ambiguous.
    None is a feature: it makes the agent ASK instead of guessing.
    Unsupported on purpose: 'next week', 'next Friday', 'soon', past dates."""
    if not phrase:
        return None
    p = phrase.strip().lower().rstrip(".,!;")
    p = re.sub(r"^(by|before|on|until|till)\s+", "", p)

    d: Optional[date] = None
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", p)
    if iso:
        d = _safe_date(*map(int, iso.groups()))
    elif p in ("today", "eod"):
        d = ref
    elif p == "tomorrow":
        d = ref + timedelta(days=1)
    elif p in WEEKDAYS:
        d = ref + timedelta(days=(WEEKDAYS[p] - ref.weekday()) % 7)
    else:
        m1 = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)", p)
        m2 = re.fullmatch(r"([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?", p)
        if m1 and m1.group(2) in MONTHS:
            d = _safe_date(ref.year, MONTHS[m1.group(2)], int(m1.group(1)))
        elif m2 and m2.group(1) in MONTHS:
            d = _safe_date(ref.year, MONTHS[m2.group(1)], int(m2.group(2)))

    if d is None or d < ref:
        return None
    return d.isoformat()


def deadline_status(deadline_iso: Optional[str], today: date,
                    due_soon_days: int = 1) -> str:
    """NO_DEADLINE / OVERDUE / DUE_SOON / UPCOMING"""
    if not deadline_iso:
        return "NO_DEADLINE"
    delta = (date.fromisoformat(deadline_iso) - today).days
    if delta < 0:
        return "OVERDUE"
    if delta <= due_soon_days:
        return "DUE_SOON"
    return "UPCOMING"


def days_overdue(deadline_iso: str, today: date) -> int:
    return max(0, (today - date.fromisoformat(deadline_iso)).days)


def draft_reminder_text(commitment: dict, today: date) -> str:
    """Template-based draft. Always labelled unsent."""
    n = days_overdue(commitment["deadline"], today)
    return (
        "[UNSENT DRAFT]\n"
        f"Subject: Following up: {commitment['description']}\n\n"
        "Hi,\n\n"
        f"A quick follow-up on: {commitment['description']}. "
        f"This was due on {commitment['deadline']} ({n} day(s) ago). "
        "Could you share a status update or a new date?\n\nThanks"
    )