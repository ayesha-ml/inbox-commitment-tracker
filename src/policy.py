"""Deterministic policy: who may be emailed, reminder limits, next action.
The LLM never decides recipients, limits or permissions."""
from dataclasses import dataclass
from datetime import date
from email.utils import parseaddr
from typing import Optional

from src import db
from src.tools import deadline_status


@dataclass
class Decision:
    action: str            # WAIT, CLARIFY, SELF_ALERT, DRAFT_REMINDER, AWAIT_APPROVAL,
                           # SEND_APPROVED, RETRY_SEND, ESCALATE, BLOCKED_RECIPIENT
    reason: str
    recipient: Optional[str] = None


def norm_addr(value: str) -> str:
    """'Sam <SAM@Example.com>' -> 'sam@example.com'"""
    return parseaddr(value or "")[1].strip().lower()


def recipient_allowed(recipient: str, allowlist: set) -> bool:
    return norm_addr(recipient) in {norm_addr(a) for a in allowlist}


def next_action(conn, user_id: str, c: dict, today: date, *,
                user_email: str, allowlist: set, max_reminders: int,
                due_soon_days: int = 1) -> Decision:
    if c["status"] == "NEEDS_REVIEW" or not c["deadline"]:
        return Decision("CLARIFY", "deadline missing or evidence conflicts")

    status = deadline_status(c["deadline"], today, due_soon_days)
    if status != "OVERDUE":
        return Decision("WAIT", f"deadline {status.lower().replace('_', ' ')}")

    owner = norm_addr(c["owner"])
    if owner == norm_addr(user_email):
        return Decision("SELF_ALERT", "you owe this and it is overdue (no email sent)")

    mine = [r for r in db.get_reminders(conn, user_id, c["commitment_id"])
            if r["deadline_version"] == c["version"]]

    if any(r["approval_state"] == "PENDING" for r in mine):
        return Decision("AWAIT_APPROVAL", "a draft is waiting for your approval")
    if any(r["approval_state"] == "APPROVED" and r["send_state"] == "NOT_SENT" for r in mine):
        return Decision("SEND_APPROVED", "approved reminder not yet sent")
    if any(r["approval_state"] == "APPROVED" and r["send_state"] == "FAILED" for r in mine):
        return Decision("RETRY_SEND", "last send failed; retry the same reminder")

    active = [r for r in mine if r["approval_state"] != "REJECTED"]
    if len(active) >= max_reminders:
        return Decision("ESCALATE", f"reminder limit ({max_reminders}) reached; decide yourself")

    if not recipient_allowed(owner, allowlist):
        return Decision("BLOCKED_RECIPIENT", f"{owner} is not on the allowlist")

    return Decision("DRAFT_REMINDER", "overdue and within limits", recipient=owner)