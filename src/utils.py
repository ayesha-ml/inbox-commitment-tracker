import hashlib
import re
from datetime import datetime, timezone


def now_iso() -> str:
    """Real wall-clock time, used for audit timestamps."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalise_body(text: str) -> str:
    """Collapse whitespace and lowercase so trivially different copies hash equal."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def body_hash(text: str) -> str:
    return hashlib.sha256(normalise_body(text).encode("utf-8")).hexdigest()


def idempotency_key(user_id: str, commitment_id: int,
                    deadline_version: int, reminder_n: int) -> str:
    """Same reminder for the same deadline version always gets the same key."""
    return f"{user_id}:{commitment_id}:v{deadline_version}:r{reminder_n}"