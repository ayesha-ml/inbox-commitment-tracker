import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from src.config import CHECKPOINT_MAX_CHARS, DB_PATH, SCHEMA_PATH
from src.utils import idempotency_key, now_iso


class NotFoundError(LookupError):
    """Record does not exist FOR THIS USER (also used for cross-user access)."""


#  connection / setup 

def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def add_user(conn, user_id: str, display_name: str, start_date: str) -> None:
    """Idempotent: calling twice does not create a second user or reset the clock."""
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, display_name, created_at) VALUES (?,?,?)",
            (user_id, display_name, now_iso()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO clock (user_id, today) VALUES (?,?)",
            (user_id, start_date),
        )


#  action log 

def log_action(conn, user_id: str, kind: str, tool: Optional[str] = None,
               input_data: Any = None, output_data: Any = None,
               outcome: str = "ok", cycle_id: Optional[int] = None,
               latency_ms: Optional[int] = None,
               tokens_in: Optional[int] = None,
               tokens_out: Optional[int] = None) -> None:
    """kind: TOOL_CALL / MEMORY_READ / MEMORY_WRITE / LLM_CALL / ERROR"""
    with conn:
        conn.execute(
            """INSERT INTO action_log
               (user_id, cycle_id, ts, kind, tool, input_json, output_json,
                outcome, latency_ms, tokens_in, tokens_out)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, cycle_id, now_iso(), kind, tool,
             json.dumps(input_data, default=str),
             json.dumps(output_data, default=str),
             outcome, latency_ms, tokens_in, tokens_out),
        )


def get_log(conn, user_id: str, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM action_log WHERE user_id=? ORDER BY log_id DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(r) for r in rows]


#  messages (dedup + evidence source) 

def save_message(conn, user_id: str, message_id: str, body_hash: str, *,
                 source: str, thread_id: Optional[str] = None,
                 sender: Optional[str] = None, subject: Optional[str] = None,
                 body: Optional[str] = None, cycle_id: Optional[int] = None,
                 received_at: Optional[str] = None) -> str:
    """Returns 'NEW', 'DUPLICATE_ID' or 'DUPLICATE_CONTENT'.
    Duplicate detection is done HERE (deterministic), never by the LLM."""
    if conn.execute("SELECT 1 FROM messages WHERE user_id=? AND message_id=?",
                    (user_id, message_id)).fetchone():
        return "DUPLICATE_ID"
    if conn.execute("SELECT 1 FROM messages WHERE user_id=? AND body_hash=?",
                    (user_id, body_hash)).fetchone():
        return "DUPLICATE_CONTENT"
    with conn:
        conn.execute(
            """INSERT INTO messages
               (message_id, user_id, thread_id, sender, subject, body, body_hash,
                source, cycle_id, received_at, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (message_id, user_id, thread_id, sender, subject, body, body_hash,
             source, cycle_id, received_at, now_iso()),
        )
    return "NEW"


def set_message_label(conn, user_id: str, message_id: str, label: str) -> None:
    with conn:
        conn.execute(
            "UPDATE messages SET llm_label=? WHERE user_id=? AND message_id=?",
            (label, user_id, message_id),
        )


def get_message(conn, user_id: str, message_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM messages WHERE user_id=? AND message_id=?",
        (user_id, message_id),
    ).fetchone()
    return dict(row) if row else None


#  commitments + versions 

def create_commitment(conn, user_id: str, owner: str, description: str,
                      deadline: Optional[str], source_message_id: str, *,
                      counterparty: Optional[str] = None,
                      thread_id: Optional[str] = None,
                      evidence_quote: Optional[str] = None,
                      status: str = "OPEN") -> int:
    ts = now_iso()
    with conn:
        cur = conn.execute(
            """INSERT INTO commitments
               (user_id, thread_id, owner, counterparty, description, status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, thread_id, owner, counterparty, description, status, ts),
        )
        cid = cur.lastrowid
        conn.execute(
            """INSERT INTO commitment_versions
               (commitment_id, version, deadline, is_current,
                source_message_id, evidence_quote, recorded_at)
               VALUES (?,?,?,?,?,?,?)""",
            (cid, 1, deadline, 1, source_message_id, evidence_quote, ts),
        )
    return cid


def supersede_deadline(conn, user_id: str, commitment_id: int,
                       new_deadline: Optional[str], source_message_id: str,
                       evidence_quote: Optional[str] = None) -> Optional[int]:
    """Add a new current version; old one is kept as history.
    Returns the new version number, or None if the deadline did not change
    (so replaying the same revision email twice is harmless)."""
    ts = now_iso()
    with conn:  # rolls back everything if anything below raises
        owned = conn.execute(
            "SELECT 1 FROM commitments WHERE commitment_id=? AND user_id=?",
            (commitment_id, user_id),
        ).fetchone()
        if owned is None:
            raise NotFoundError(f"commitment {commitment_id} not found for {user_id}")

        cur = conn.execute(
            """SELECT version, deadline FROM commitment_versions
               WHERE commitment_id=? AND is_current=1""",
            (commitment_id,),
        ).fetchone()
        if cur is not None and cur["deadline"] == new_deadline:
            return None

        new_version = (cur["version"] + 1) if cur else 1
        if cur is not None:
            conn.execute(
                """UPDATE commitment_versions SET is_current=0, superseded_at=?
                   WHERE commitment_id=? AND version=?""",
                (ts, commitment_id, cur["version"]),
            )
        conn.execute(
            """INSERT INTO commitment_versions
               (commitment_id, version, deadline, is_current,
                source_message_id, evidence_quote, recorded_at)
               VALUES (?,?,?,?,?,?,?)""",
            (commitment_id, new_version, new_deadline, 1,
             source_message_id, evidence_quote, ts),
        )
    return new_version


def set_status(conn, user_id: str, commitment_id: int, status: str) -> None:
    with conn:
        cur = conn.execute(
            "UPDATE commitments SET status=? WHERE commitment_id=? AND user_id=?",
            (status, commitment_id, user_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"commitment {commitment_id} not found for {user_id}")


_CURRENT_SQL = """
SELECT c.commitment_id, c.user_id, c.thread_id, c.owner, c.counterparty,
       c.description, c.status, c.created_at,
       v.version, v.deadline, v.source_message_id, v.evidence_quote
FROM commitments c
JOIN commitment_versions v
  ON v.commitment_id = c.commitment_id AND v.is_current = 1
"""


def get_commitment(conn, user_id: str, commitment_id: int) -> Optional[dict]:
    row = conn.execute(
        _CURRENT_SQL + " WHERE c.user_id=? AND c.commitment_id=?",
        (user_id, commitment_id),
    ).fetchone()
    return dict(row) if row else None


def list_commitments(conn, user_id: str,
                     statuses: tuple = ("OPEN", "NEEDS_REVIEW")) -> list[dict]:
    marks = ",".join("?" for _ in statuses)
    rows = conn.execute(
        _CURRENT_SQL + f""" WHERE c.user_id=? AND c.status IN ({marks})
                            ORDER BY v.deadline IS NULL, v.deadline, c.commitment_id""",
        (user_id, *statuses),
    )
    return [dict(r) for r in rows]


def get_history(conn, user_id: str, commitment_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT v.* FROM commitment_versions v
           JOIN commitments c ON c.commitment_id = v.commitment_id
           WHERE c.user_id=? AND v.commitment_id=?
           ORDER BY v.version""",
        (user_id, commitment_id),
    )
    return [dict(r) for r in rows]


#  working-state checkpoints (bounded) 

def save_checkpoint(conn, user_id: str, cycle_id: int, state: dict) -> None:
    text = json.dumps(state, default=str)
    if len(text) > CHECKPOINT_MAX_CHARS:
        raise ValueError("checkpoint too large: working state must stay bounded")
    with conn:
        conn.execute(
            """INSERT INTO checkpoints (user_id, cycle_id, state_json, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(user_id, cycle_id)
               DO UPDATE SET state_json=excluded.state_json,
                             updated_at=excluded.updated_at""",
            (user_id, cycle_id, text, now_iso()),
        )


def load_checkpoint(conn, user_id: str, cycle_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT state_json FROM checkpoints WHERE user_id=? AND cycle_id=?",
        (user_id, cycle_id),
    ).fetchone()
    return json.loads(row["state_json"]) if row else None


def latest_checkpoint(conn, user_id: str) -> Optional[tuple[int, dict]]:
    row = conn.execute(
        """SELECT cycle_id, state_json FROM checkpoints
           WHERE user_id=? ORDER BY cycle_id DESC LIMIT 1""",
        (user_id,),
    ).fetchone()
    return (row["cycle_id"], json.loads(row["state_json"])) if row else None

# reminders (draft / approval / send tracked separately)

def get_reminders(conn, user_id: str, commitment_id: Optional[int] = None) -> list[dict]:
    sql, params = "SELECT * FROM reminders WHERE user_id=?", [user_id]
    if commitment_id is not None:
        sql += " AND commitment_id=?"
        params.append(commitment_id)
    return [dict(r) for r in conn.execute(sql + " ORDER BY reminder_id", params)]


def create_reminder(conn, user_id: str, commitment_id: int, deadline_version: int,
                    recipient: str, draft_body: str) -> tuple[dict, bool]:
    """Returns (reminder, created). Retry-safe: if a PENDING draft already exists for
    this commitment+deadline version, it is returned instead of making a second one.
    The UNIQUE idempotency_key is a second line of defence."""
    with conn:
        if not conn.execute(
                "SELECT 1 FROM commitments WHERE commitment_id=? AND user_id=?",
                (commitment_id, user_id)).fetchone():
            raise NotFoundError(f"commitment {commitment_id} not found for {user_id}")

        pending = conn.execute(
            """SELECT * FROM reminders WHERE user_id=? AND commitment_id=?
               AND deadline_version=? AND approval_state='PENDING'""",
            (user_id, commitment_id, deadline_version)).fetchone()
        if pending:
            return dict(pending), False

        n = conn.execute(
            """SELECT COALESCE(MAX(reminder_n),0)+1 FROM reminders
               WHERE user_id=? AND commitment_id=? AND deadline_version=?""",
            (user_id, commitment_id, deadline_version)).fetchone()[0]
        key = idempotency_key(user_id, commitment_id, deadline_version, n)
        ts = now_iso()
        cur = conn.execute(
            """INSERT OR IGNORE INTO reminders
               (user_id, commitment_id, deadline_version, reminder_n, recipient,
                draft_body, idempotency_key, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, commitment_id, deadline_version, n, recipient,
             draft_body, key, ts, ts))
        row = conn.execute("SELECT * FROM reminders WHERE idempotency_key=?", (key,)).fetchone()
        return dict(row), cur.rowcount == 1


def set_approval(conn, user_id: str, reminder_id: int, state: str) -> None:
    if state not in ("APPROVED", "REJECTED"):
        raise ValueError("state must be APPROVED or REJECTED")
    with conn:
        cur = conn.execute(
            """UPDATE reminders SET approval_state=?, updated_at=?
               WHERE reminder_id=? AND user_id=? AND approval_state='PENDING'""",
            (state, now_iso(), reminder_id, user_id))
        if cur.rowcount == 0:
            raise NotFoundError(f"no pending reminder {reminder_id} for {user_id}")


def mark_send_result(conn, user_id: str, reminder_id: int, ok: bool,
                     error: Optional[str] = None) -> bool:
    """Record the outcome of a real send. Returns False if already SENT
    (a retry after success is a no-op, so no duplicate side effects)."""
    with conn:
        row = conn.execute(
            "SELECT approval_state, send_state FROM reminders WHERE reminder_id=? AND user_id=?",
            (reminder_id, user_id)).fetchone()
        if row is None:
            raise NotFoundError(f"reminder {reminder_id} not found for {user_id}")
        if row["approval_state"] != "APPROVED":
            raise PermissionError("reminder was not approved")
        if row["send_state"] == "SENT":
            return False
        conn.execute(
            "UPDATE reminders SET send_state=?, send_error=?, updated_at=? WHERE reminder_id=?",
            ("SENT" if ok else "FAILED", None if ok else error, now_iso(), reminder_id))
        return True


def reject_stale_reminders(conn, user_id: str, commitment_id: int,
                           current_version: int) -> int:
    """After a deadline correction, unsent drafts for older versions are void."""
    with conn:
        cur = conn.execute(
            """UPDATE reminders SET approval_state='REJECTED',
                      send_error='superseded by newer deadline', updated_at=?
               WHERE user_id=? AND commitment_id=? AND deadline_version<?
                 AND approval_state IN ('PENDING','APPROVED') AND send_state!='SENT'""",
            (now_iso(), user_id, commitment_id, current_version))
        return cur.rowcount