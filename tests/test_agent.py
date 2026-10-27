"""Integration tests for the full Agent process cycle and memory diagnostic switch."""
import json
from pathlib import Path
import pytest
from src import db, agent

BASE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def cycle1_data():
    with open(BASE_DIR / "sample_data" / "cycle1.json") as f:
        return json.load(f)


@pytest.fixture
def cycle2_data():
    with open(BASE_DIR / "sample_data" / "cycle2.json") as f:
        return json.load(f)


def test_agent_cycle1_mock(conn, cycle1_data):
    res = agent.process_cycle(conn, "alice", cycle1_data, use_mock=True)
    assert res["cycle_id"] == 1
    assert len(res["processed"]) == 4
    
    commitments = db.list_commitments(conn, "alice")
    assert len(commitments) == 3


def test_agent_cycle2_dedup_and_revision(conn, cycle1_data, cycle2_data):
    agent.process_cycle(conn, "alice", cycle1_data, use_mock=True)
    res2 = agent.process_cycle(conn, "alice", cycle2_data, use_mock=True)
    
    # Check duplicate detection on repeated content or IDs
    statuses = [p["status"] for p in res2["processed"] if "status" in p]
    assert any("DUPLICATE" in s for s in statuses)


def test_memory_off_diagnostic(conn, cycle1_data):
    # With memory_enabled=False, messages are classified but SQLite state isn't updated
    res = agent.process_cycle(conn, "alice", cycle1_data, use_mock=True, memory_enabled=False)
    commitments = db.list_commitments(conn, "alice")
    assert len(commitments) == 0  # No commitments persisted