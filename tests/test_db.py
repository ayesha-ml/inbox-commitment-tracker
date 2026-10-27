import pytest

from src import clock, db
from src.utils import body_hash


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    db.add_user(c, "alice", "Alice", "2026-10-20")
    db.add_user(c, "bob", "Bob", "2026-10-20")
    yield c
    c.close()


def test_tables_exist(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ["users", "clock", "messages", "commitments",
              "commitment_versions", "reminders", "action_log", "checkpoints"]:
        assert t in names


def test_add_user_is_idempotent(conn):
    clock.advance_days(conn, "alice", 3)
    db.add_user(conn, "alice", "Alice", "2026-10-20")  # must NOT reset the clock
    assert clock.get_today(conn, "alice").isoformat() == "2026-10-23"


def test_supersede_keeps_history_and_one_current(conn):
    cid = db.create_commitment(conn, "alice", "Sam", "send report", "2026-10-23", "m1")
    v = db.supersede_deadline(conn, "alice", cid, "2026-10-26", "m2", "make that Monday")
    assert v == 2
    current = db.get_commitment(conn, "alice", cid)
    assert current["deadline"] == "2026-10-26" and current["version"] == 2
    history = db.get_history(conn, "alice", cid)
    assert [h["deadline"] for h in history] == ["2026-10-23", "2026-10-26"]
    assert [h["is_current"] for h in history] == [0, 1]
    assert history[0]["superseded_at"] is not None


def test_same_revision_twice_is_noop(conn):
    cid = db.create_commitment(conn, "alice", "Sam", "send report", "2026-10-23", "m1")
    assert db.supersede_deadline(conn, "alice", cid, "2026-10-26", "m2") == 2
    assert db.supersede_deadline(conn, "alice", cid, "2026-10-26", "m2") is None
    assert len(db.get_history(conn, "alice", cid)) == 2


def test_state_survives_restart(tmp_path):
    path = tmp_path / "r.db"
    c1 = db.connect(path)
    db.init_db(c1)
    db.add_user(c1, "alice", "Alice", "2026-10-20")
    cid = db.create_commitment(c1, "alice", "Sam", "send report", "2026-10-23", "m1")
    db.supersede_deadline(c1, "alice", cid, "2026-10-26", "m2")
    db.save_checkpoint(c1, "alice", 1, {"step": "done", "pending": ["q1"]})
    c1.close()  # "process exits"

    c2 = db.connect(path)  # "process restarts"
    got = db.get_commitment(c2, "alice", cid)
    assert got["deadline"] == "2026-10-26"
    assert len(db.get_history(c2, "alice", cid)) == 2
    assert db.latest_checkpoint(c2, "alice") == (1, {"step": "done", "pending": ["q1"]})
    c2.close()


def test_isolation_between_users(conn):
    cid = db.create_commitment(conn, "alice", "Sam", "secret thing", "2026-10-23", "m1")
    assert db.get_commitment(conn, "bob", cid) is None
    assert db.list_commitments(conn, "bob") == []
    assert db.get_history(conn, "bob", cid) == []
    with pytest.raises(db.NotFoundError):
        db.supersede_deadline(conn, "bob", cid, "2026-12-01", "evil")
    with pytest.raises(db.NotFoundError):
        db.set_status(conn, "bob", cid, "CANCELLED")
    # Alice's data is untouched
    assert db.get_commitment(conn, "alice", cid)["deadline"] == "2026-10-23"


def test_duplicate_messages_detected_by_code(conn):
    h = body_hash("I'll send the report by Friday.")
    kw = dict(source="fixture_export")
    assert db.save_message(conn, "alice", "msg1", h, **kw) == "NEW"
    assert db.save_message(conn, "alice", "msg1", h, **kw) == "DUPLICATE_ID"
    # same text, different Message-ID, extra whitespace/case -> still a duplicate
    h2 = body_hash("  I'll send the report   by FRIDAY. ")
    assert db.save_message(conn, "alice", "msg2", h2, **kw) == "DUPLICATE_CONTENT"
    # a different user may legitimately receive the same text
    assert db.save_message(conn, "bob", "msg1", h, **kw) == "NEW"


def test_checkpoint_roundtrip_and_bound(conn):
    db.save_checkpoint(conn, "alice", 2, {"step": "classify", "i": 3})
    db.save_checkpoint(conn, "alice", 2, {"step": "draft", "i": 5})  # update, not duplicate
    assert db.load_checkpoint(conn, "alice", 2) == {"step": "draft", "i": 5}
    assert db.load_checkpoint(conn, "bob", 2) is None
    with pytest.raises(ValueError):
        db.save_checkpoint(conn, "alice", 3, {"blob": "x" * 30_000})


def test_clock(conn):
    clock.advance_days(conn, "alice", 7)
    assert clock.get_today(conn, "alice").isoformat() == "2026-10-27"
    assert clock.get_today(conn, "bob").isoformat() == "2026-10-20"  # independent
    with pytest.raises(ValueError):
        clock.set_today(conn, "alice", "not-a-date")