"""Agent Decision Engine driving review cycles and action execution."""
from datetime import date
from typing import Dict, Any, List
from src import db, clock, policy, tools, config
from src.llm import classify_message
from src.utils import body_hash


def process_cycle(conn, user_id: str, cycle_data: Dict[str, Any], *,
                  use_mock: bool = False, memory_enabled: bool = True) -> Dict[str, Any]:
    """Executes one complete review cycle for a batch of emails."""
    cycle_id = cycle_data["cycle_id"]
    clock_date = date.fromisoformat(cycle_data["clock_date"])
    
    # Set simulated clock date
    clock.set_today(conn, user_id, cycle_data["clock_date"])
    
    results = []
    
    for msg in cycle_data["messages"]:
        mid = msg["message_id"]
        b_hash = body_hash(msg["body"])
        
        # Step 1: Deterministic Content Deduplication Check
        save_status = db.save_message(
            conn, user_id, mid, b_hash,
            source="fixture_export",
            thread_id=msg.get("thread_id"),
            sender=msg.get("from"),
            subject=msg.get("subject"),
            body=msg.get("body"),
            cycle_id=cycle_id,
            received_at=msg.get("date")
        )
        
        if save_status in ("DUPLICATE_ID", "DUPLICATE_CONTENT"):
            db.log_action(conn, user_id, "MEMORY_READ", tool="dedup", input_data={"mid": mid}, output_data=save_status, cycle_id=cycle_id)
            results.append({"message_id": mid, "status": save_status, "action": "SKIP"})
            continue
        
        # Step 2: LLM Intent Classification
        llm_out, latency, t_in, t_out = classify_message(msg, use_mock=use_mock)
        label = llm_out.get("label", "NO_COMMITMENT")
        db.set_message_label(conn, user_id, mid, label)
        
        db.log_action(
            conn, user_id, "LLM_CALL", tool="classifier",
            input_data={"message_id": mid}, output_data=llm_out,
            cycle_id=cycle_id, latency_ms=latency, tokens_in=t_in, tokens_out=t_out
        )
        
        # Step 3: Date Resolution via Deterministic Tool
        deadline_iso = tools.resolve_deadline(llm_out.get("deadline_phrase"), clock_date)
        
        # Step 4: Apply State Changes (If Memory Enabled)
        if memory_enabled:
            _apply_state_change(conn, user_id, msg, llm_out, deadline_iso, mid)
            
        results.append({"message_id": mid, "label": label, "deadline_iso": deadline_iso})

    # Step 5: Evaluate Next Actions for All Open Commitments
    open_commitments = db.list_commitments(conn, user_id, statuses=("OPEN", "NEEDS_REVIEW"))
    actions = []
    
    for c in open_commitments:
        dec = policy.next_action(
            conn, user_id, c, clock_date,
            user_email=config.USER_EMAIL,
            allowlist=config.ALLOWED_RECIPIENTS,
            max_reminders=config.MAX_REMINDERS_PER_COMMITMENT
        )
        actions.append({"commitment_id": c["commitment_id"], "description": c["description"], "action": dec.action, "reason": dec.reason})

    # Save bounded working checkpoint
    checkpoint_state = {"cycle_id": cycle_id, "processed_count": len(results), "open_count": len(open_commitments)}
    db.save_checkpoint(conn, user_id, cycle_id, checkpoint_state)
    
    return {"cycle_id": cycle_id, "processed": results, "actions": actions}


def _apply_state_change(conn, user_id: str, msg: Dict[str, Any], llm_out: Dict[str, Any],
                        deadline_iso: str, message_id: str) -> None:
    """Applies LLM findings to SQLite commitment tables deterministically."""
    label = llm_out.get("label")
    thread_id = msg.get("thread_id")
    sender = policy.norm_addr(msg.get("from", ""))
    
    if label in ("NEW_COMMITMENT", "UNCLEAR"):
        owner = llm_out.get("owner") or sender
        status = "OPEN" if deadline_iso else "NEEDS_REVIEW"
        db.create_commitment(
            conn, user_id, owner, llm_out.get("description", "Unspecified task"),
            deadline_iso, message_id, thread_id=thread_id,
            evidence_quote=llm_out.get("evidence_quote"),
            status=status
        )
        
    elif label == "REVISION":
        existing = db.list_commitments(conn, user_id, statuses=("OPEN", "NEEDS_REVIEW"))
        matched = [c for c in existing if c.get("thread_id") == thread_id]
        
        if matched:
            c = matched[0]
            # Hearsay Check: Revision only allowed if sender is owner or user
            if sender in (policy.norm_addr(c["owner"]), policy.norm_addr(config.USER_EMAIL)):
                new_v = db.supersede_deadline(conn, user_id, c["commitment_id"], deadline_iso, message_id, evidence_quote=llm_out.get("evidence_quote"))
                if new_v:
                    db.reject_stale_reminders(conn, user_id, c["commitment_id"], new_v)
            else:
                # Flag hearsay / unauthorized change attempt as NEEDS_REVIEW
                db.set_status(conn, user_id, c["commitment_id"], "NEEDS_REVIEW")
                
    elif label == "FULFILLED":
        existing = db.list_commitments(conn, user_id, statuses=("OPEN", "NEEDS_REVIEW"))
        matched = [c for c in existing if c.get("thread_id") == thread_id]
        if matched:
            db.set_status(conn, user_id, matched[0]["commitment_id"], "FULFILLED")