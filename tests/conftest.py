import pytest

from src import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    db.add_user(c, "alice", "Alice", "2026-10-20")
    db.add_user(c, "bob", "Bob", "2026-10-20")
    yield c
    c.close()