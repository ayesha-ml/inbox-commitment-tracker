import argparse
import json
from pathlib import Path

from src import agent, clock, db


def cmd_init(args):
    conn = db.connect()
    db.init_db(conn)
    db.add_user(conn, args.user, args.name or args.user, args.start)
    print(f"Database ready. User '{args.user}' starts on {args.start}.")


def cmd_cycle(args):
    conn = db.connect()
    fixture_path = Path("sample_data") / f"cycle{args.cycle}.json"
    if not fixture_path.exists():
        print(f"Error: Fixture file {fixture_path} does not exist.")
        return

    with open(fixture_path, encoding="utf-8") as f:
        cycle_data = json.load(f)

    print(f"Running Cycle {args.cycle} (Simulated Date: {cycle_data['clock_date']})...")
    res = agent.process_cycle(
        conn,
        args.user,
        cycle_data,
        use_mock=args.mock,
        memory_enabled=not args.no_memory,
    )

    print("\n--- Processed Emails ---")
    for p in res["processed"]:
        status_label = p.get("label") or p.get("status")
        print(
            f"  Message {p['message_id']}: Label={status_label} | Deadline={p.get('deadline_iso')}"
        )

    print("\n--- Recommended Next Actions ---")
    for a in res["actions"]:
        print(
            f"  Commitment #{a['commitment_id']} ({a['description']}): {a['action']} -> {a['reason']}"
        )


def cmd_status(args):
    conn = db.connect()
    today = clock.get_today(conn, args.user)
    print(f"User: {args.user} | Simulated today: {today}")

    statuses = ("OPEN", "NEEDS_REVIEW", "FULFILLED", "CANCELLED")
    rows = db.list_commitments(conn, args.user, statuses=statuses)
    if not rows:
        print("No commitments recorded.")
        return

    for r in rows:
        print(
            f"#{r['commitment_id']} [{r['status']}] {r['owner']}: "
            f"{r['description']} (due {r['deadline']}, v{r['version']})"
        )
        if getattr(args, "history", False):
            history = db.get_history(conn, args.user, r["commitment_id"])
            for h in history:
                curr_flag = (
                    " (CURRENT)"
                    if h["is_current"]
                    else f" (Superseded at {h['superseded_at']})"
                )
                print(
                    f"    └── v{h['version']}: Deadline={h['deadline']}{curr_flag} | Quote: '{h['evidence_quote']}'"
                )


def cmd_reminders(args):
    conn = db.connect()
    reminders = db.get_reminders(conn, args.user)
    if not reminders:
        print("No reminders generated.")
        return

    print("--- Reminder Drafts & Statuses ---")
    for r in reminders:
        print(
            f"\nReminder #{r['reminder_id']} for Commitment #{r['commitment_id']} (v{r['deadline_version']})"
        )
        print(
            f"Recipient: {r['recipient']} | Idempotency Key: {r['idempotency_key']}"
        )
        print(
            f"Approval: [{r['approval_state']}] | Send State: [{r['send_state']}]"
        )
        print(f"Body:\n{r['draft_body']}")


def main():
    p = argparse.ArgumentParser(description="Inbox Commitment Tracker")
    sub = p.add_subparsers(dest="cmd", required=True)

    # init command
    s = sub.add_parser("init", help="create DB and a user")
    s.add_argument("--user", required=True)
    s.add_argument("--name")
    s.add_argument("--start", default="2026-10-20", help="simulated start date")
    s.set_defaults(func=cmd_init)

    # run-cycle command
    s = sub.add_parser("run-cycle", help="run a review cycle batch")
    s.add_argument("--user", required=True)
    s.add_argument(
        "--cycle", type=int, required=True, choices=[1, 2, 3]
    )
    s.add_argument(
        "--mock", action="store_true", help="use mock classifier fallback"
    )
    s.add_argument(
        "--no-memory",
        action="store_true",
        help="disable memory persistence",
    )
    s.set_defaults(func=cmd_cycle)

    # status command
    s = sub.add_parser("status", help="show open commitments")
    s.add_argument("--user", required=True)
    s.add_argument(
        "--history", action="store_true", help="show version history"
    )
    s.set_defaults(func=cmd_status)

    # reminders command
    s = sub.add_parser("reminders", help="view draft reminders")
    s.add_argument("--user", required=True)
    s.set_defaults(func=cmd_reminders)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()