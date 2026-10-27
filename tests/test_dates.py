from datetime import date

import pytest

from src.tools import (days_overdue, deadline_status, draft_reminder_text,
                       resolve_deadline)

TUE = date(2026, 10, 20)   # a Tuesday
WED = date(2026, 10, 28)   # a Wednesday


@pytest.mark.parametrize("phrase,ref,expected", [
    ("Friday", TUE, "2026-10-23"),
    ("by Friday.", TUE, "2026-10-23"),
    ("Thursday", TUE, "2026-10-22"),
    ("Thursday", WED, "2026-10-29"),
    ("Tuesday", TUE, "2026-10-20"),          # today counts
    ("tomorrow", TUE, "2026-10-21"),
    ("2026-11-02", TUE, "2026-11-02"),
    ("Oct 30", TUE, "2026-10-30"),
    ("30 October", TUE, "2026-10-30"),
    ("Nov 3", WED, "2026-11-03"),
])
def test_resolves(phrase, ref, expected):
    assert resolve_deadline(phrase, ref) == expected


@pytest.mark.parametrize("phrase", [
    None, "", "next week", "next Friday", "soon", "sometime", "Oct 10", "Feb 30",
])
def test_ambiguous_returns_none(phrase):
    assert resolve_deadline(phrase, TUE) is None


def test_deadline_status():
    t = date(2026, 10, 26)
    assert deadline_status(None, t) == "NO_DEADLINE"
    assert deadline_status("2026-10-23", t) == "OVERDUE"
    assert deadline_status("2026-10-26", t) == "DUE_SOON"
    assert deadline_status("2026-10-27", t) == "DUE_SOON"
    assert deadline_status("2026-10-30", t) == "UPCOMING"
    assert days_overdue("2026-10-23", t) == 3


def test_draft_is_labelled_unsent():
    c = {"description": "send budget report", "deadline": "2026-10-23"}
    text = draft_reminder_text(c, date(2026, 10, 26))
    assert text.startswith("[UNSENT DRAFT]") and "3 day(s) ago" in text