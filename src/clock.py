"""Simulated clock so review cycles can be advanced manually (allowed by the brief)."""
from datetime import date, timedelta

from src.db import NotFoundError


def get_today(conn, user_id: str) -> date:
    row = conn.execute("SELECT today FROM clock WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"no clock for user {user_id}")
    return date.fromisoformat(row["today"])


def set_today(conn, user_id: str, iso_date: str) -> None:
    date.fromisoformat(iso_date)  # validates format, raises ValueError if bad
    with conn:
        cur = conn.execute("UPDATE clock SET today=? WHERE user_id=?", (iso_date, user_id))
        if cur.rowcount == 0:
            raise NotFoundError(f"no clock for user {user_id}")


def advance_days(conn, user_id: str, days: int) -> date:
    new_day = get_today(conn, user_id) + timedelta(days=days)
    set_today(conn, user_id, new_day.isoformat())
    return new_day