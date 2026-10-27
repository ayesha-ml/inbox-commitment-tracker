import argparse
from src import clock, db


def cmd_init(args):
    conn = db.connect()
    db.init_db(conn)
    db.add_user(conn, args.user, args.name or args.user, args.start)
    print(f"Database ready. User '{args.user}' starts on {args.start}.")


def cmd_status(args):
    conn = db.connect()
    today = clock.get_today(conn, args.user)
    print(f"User: {args.user} | Simulated today: {today}")
    rows = db.list_commitments(conn, args.user)
    if not rows:
        print("No open commitments.")
        return
    for r in rows:
        print(f"#{r['commitment_id']} [{r['status']}] {r['owner']}: "
              f"{r['description']} (due {r['deadline']}, v{r['version']})")


def main():
    p = argparse.ArgumentParser(description="Inbox Commitment Tracker")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create DB and a user")
    s.add_argument("--user", required=True)
    s.add_argument("--name")
    s.add_argument("--start", default="2026-10-20", help="simulated start date")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("status", help="show open commitments")
    s.add_argument("--user", required=True)
    s.set_defaults(func=cmd_status)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()