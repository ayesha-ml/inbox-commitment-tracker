import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "data" / "tracker.db"))
SCHEMA_PATH = BASE_DIR / "schema.sql"

# Reminder limit per commitment (enforced in code, never by the LLM)
MAX_REMINDERS_PER_COMMITMENT = int(os.getenv("MAX_REMINDERS", "2"))

# Working-state checkpoints must stay bounded
CHECKPOINT_MAX_CHARS = 20_000

# The user's own address (used to tell "I owe this" from "they owe me")
USER_EMAIL = os.getenv("USER_EMAIL", "alice@example.com")

# Only these addresses may ever receive a reminder (enforced in code)
ALLOWED_RECIPIENTS = {
    a.strip().lower()
    for a in os.getenv(
        "ALLOWED_RECIPIENTS",
        "sam@example.com,priya@example.com,taylor@example.com",
    ).split(",")
    if a.strip()
}

DUE_SOON_DAYS = int(os.getenv("DUE_SOON_DAYS", "1"))