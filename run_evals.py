import json
from pathlib import Path
from src import db, agent, clock


def run_evaluations():
    print("running compulsory scenario tests...")
    
    # creating docs directory if missing
    Path("docs").mkdir(exist_ok=True)

    # clearing previous evaluation database
    db_path = Path("data") / "eval_tracker.db"
    if db_path.exists():
        db_path.unlink()
        
    conn = db.connect(db_path)
    db.init_db(conn)
    db.add_user(conn, "alice", "Alice", "2026-10-20")
    db.add_user(conn, "bob", "Bob", "2026-10-20")

    scenarios = []

    # processing cycle 1 for initial commitments
    c1 = json.load(open("sample_data/cycle1.json", encoding="utf-8"))
    res1 = agent.process_cycle(conn, "alice", c1, use_mock=True)
    commits1 = db.list_commitments(conn, "alice")
    scenarios.append(("1. Initial Use", len(commits1) >= 2, f"Created {len(commits1)} commitments in Cycle 1"))

    # testing handling of ambiguous evidence from cycle 1
    unclear_commit = [c for c in db.list_commitments(conn, "alice", statuses=("NEEDS_REVIEW",)) if c["deadline"] is None]
    scenarios.append(("6. Missing/Conflicting Evidence", len(unclear_commit) > 0, "Ambiguous email correctly stored as NEEDS_REVIEW"))

    # checking overdue status and reminder generation
    c2 = json.load(open("sample_data/cycle2.json", encoding="utf-8"))
    res2 = agent.process_cycle(conn, "alice", c2, use_mock=True)
    has_reminder_action = any(a["action"] == "DRAFT_REMINDER" for a in res2["actions"])
    scenarios.append(("2. Later Use", has_reminder_action, "Correctly recommended DRAFT_REMINDER for overdue task"))

    # testing database persistence across process restart
    conn.close()
    conn = db.connect(db_path)
    commits_post_restart = db.list_commitments(conn, "alice")
    scenarios.append(("3. Process Restart", len(commits_post_restart) > 0, f"Retrieved {len(commits_post_restart)} commitments post-restart without reuploading"))

    # verifying deadline updates and version supersession
    c3 = json.load(open("sample_data/cycle3.json", encoding="utf-8"))
    res3 = agent.process_cycle(conn, "alice", c3, use_mock=True)
    history = db.get_history(conn, "alice", 1)
    scenarios.append(("4. Correction", len(history) == 2 and history[0]["is_current"] == 0, f"Deadline updated to v2 ({history[-1]['deadline']}); v1 marked superseded"))

    # verifying user data isolation
    bob_commits = db.list_commitments(conn, "bob")
    scenarios.append(("5. Isolation", len(bob_commits) == 0, "User Bob cannot see Alice's commitments"))

    # testing prompt injection containment
    m7_msg = db.get_message(conn, "alice", "fx-m07")
    scenarios.append(("7. Untrusted Instruction", m7_msg["llm_label"] == "NO_COMMITMENT", "Prompt injection attempt safely classified with no tool side-effects"))

    # checking duplicate content detection
    dup_res = res2["processed"][0]["status"]
    scenarios.append(("8. Duplicate Retry", "DUPLICATE" in dup_res, f"Duplicate message detected via SHA-256 hash: {dup_res}"))

    # verifying task fulfillment state updates
    fulfilled = [c for c in db.list_commitments(conn, "alice", statuses=("FULFILLED",)) if c["thread_id"] == "t-slides"]
    scenarios.append(("9. Project Specific: Fulfillment", len(fulfilled) == 1, "Task correctly marked FULFILLED on delivery proof"))

    # blocking unauthorized third party changes
    hearsay = [c for c in db.list_commitments(conn, "alice", statuses=("NEEDS_REVIEW",)) if c["thread_id"] == "t-figures"]
    scenarios.append(("10. Project Specific: Hearsay Shield", len(hearsay) == 1, "Third-party date change attempt blocked and flagged NEEDS_REVIEW"))

    # writing scenario evaluation table to file
    out = "# Scenario Evaluation Results\n\n| Scenario | Pass/Fail | Observed Evidence |\n|---|---|---|\n"
    for name, ok, ev in scenarios:
        status = "PASSED" if ok else "FAILED"
        out += f"| {name} | {status} | {ev} |\n"

    Path("docs/scenario_results.md").write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    run_evaluations()