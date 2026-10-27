from datetime import date

import pytest

from src import db, policy

TODAY = date(2026, 10, 26)
KW = dict(user_email="alice@example.com",
          allowlist={"sam@example.com", "priya@example.com"},
          max_reminders=2)


def make(conn, owner="sam@example.com", deadline="2026-10-23"):
    return db.create_commitment(conn, "alice", owner, "send budget report", deadline, "m1")


def act(conn, cid, user="alice"):
    c = db.get_commitment(conn, user, cid)
    return policy.next_action(conn, user, c, TODAY, **KW)


def test_allowlist_parsing():
    assert policy.recipient_allowed("Sam <SAM@Example.com>", {"sam@example.com"})
    assert not policy.recipient_allowed("attacker@evil.example", {"sam@example.com"})


def test_basic_actions(conn):
    assert act(conn, make(conn)).action == "DRAFT_REMINDER"
    assert act(conn, make(conn, deadline="2026-10-30")).action == "WAIT"
    assert act(conn, make(conn, deadline=None)).action == "CLARIFY"
    assert act(conn, make(conn, owner="alice@example.com")).action == "SELF_ALERT"


def test_untrusted_recipient_is_blocked(conn):
    d = act(conn, make(conn, owner="attacker@evil.example"))
    assert d.action == "BLOCKED_RECIPIENT" and d.recipient is None


def test_needs_review_asks_for_clarification(conn):
    cid = make(conn)
    db.set_status(conn, "alice", cid, "NEEDS_REVIEW")
    assert act(conn, cid).action == "CLARIFY"


def test_reminder_lifecycle_and_limit(conn):
    cid = make(conn)
    d = act(conn, cid)
    r, created = db.create_reminder(conn, "alice", cid, 1, d.recipient, "draft")
    assert created and r["idempotency_key"] == f"alice:{cid}:v1:r1"
    assert act(conn, cid).action == "AWAIT_APPROVAL"

    db.set_approval(conn, "alice", r["reminder_id"], "APPROVED")
    assert act(conn, cid).action == "SEND_APPROVED"

    assert db.mark_send_result(conn, "alice", r["reminder_id"], False, "smtp down") is True
    assert act(conn, cid).action == "RETRY_SEND"
    assert db.mark_send_result(conn, "alice", r["reminder_id"], True) is True
    assert db.mark_send_result(conn, "alice", r["reminder_id"], True) is False  # retry no-op

    assert act(conn, cid).action == "DRAFT_REMINDER"          # 1 of 2 used
    r2, _ = db.create_reminder(conn, "alice", cid, 1, "sam@example.com", "draft 2")
    assert r2["reminder_n"] == 2
    db.set_approval(conn, "alice", r2["reminder_id"], "APPROVED")
    db.mark_send_result(conn, "alice", r2["reminder_id"], True)
    assert act(conn, cid).action == "ESCALATE"                # limit reached


def test_create_reminder_is_idempotent(conn):
    cid = make(conn)
    r1, c1 = db.create_reminder(conn, "alice", cid, 1, "sam@example.com", "draft")
    r2, c2 = db.create_reminder(conn, "alice", cid, 1, "sam@example.com", "draft")
    assert c1 is True and c2 is False
    assert r1["reminder_id"] == r2["reminder_id"]
    assert len(db.get_reminders(conn, "alice", cid)) == 1


def test_cannot_send_unapproved(conn):
    cid = make(conn)
    r, _ = db.create_reminder(conn, "alice", cid, 1, "sam@example.com", "draft")
    with pytest.raises(PermissionError):
        db.mark_send_result(conn, "alice", r["reminder_id"], True)


def test_correction_voids_old_draft_and_changes_decision(conn):
    cid = make(conn)
    r, _ = db.create_reminder(conn, "alice", cid, 1, "sam@example.com", "draft")
    assert db.supersede_deadline(conn, "alice", cid, "2026-10-29", "m8") == 2
    assert db.reject_stale_reminders(conn, "alice", cid, 2) == 1
    assert db.get_reminders(conn, "alice", cid)[0]["approval_state"] == "REJECTED"
    assert act(conn, cid).action == "WAIT"        # new deadline drives the decision


def test_reminders_are_isolated(conn):
    cid = make(conn)
    r, _ = db.create_reminder(conn, "alice", cid, 1, "sam@example.com", "draft")
    assert db.get_reminders(conn, "bob") == []
    with pytest.raises(db.NotFoundError):
        db.set_approval(conn, "bob", r["reminder_id"], "APPROVED")
    with pytest.raises(db.NotFoundError):
        db.create_reminder(conn, "bob", cid, 1, "sam@example.com", "evil")