# Expected outcomes (written BEFORE running the agent)

User: alice (alice@example.com). Allowlist: sam@, priya@, taylor@example.com.
Label set: NEW_COMMITMENT, REVISION, DUPLICATE, FULFILLED, UNCLEAR, NO_COMMITMENT.

| Msg | Cycle | Expected LLM label | Expected code behaviour                              | Expected state               |
| --- | ----- | ------------------ | ---------------------------------------------------- | ---------------------------- |
| m01 | 1     | NEW_COMMITMENT     | "Friday" -> 2026-10-23, owner sam                    | #1 OPEN v1 due 10-23         |
| m02 | 1     | UNCLEAR            | no resolvable date                                   | #2 NEEDS_REVIEW, no deadline |
| m03 | 1     | NEW_COMMITMENT     | "Thursday" -> 2026-10-22, owner alice                | #3 OPEN v1 due 10-22         |
| m04 | 1     | NO_COMMITMENT      | nothing stored except message                        | none                         |
| m05 | 2     | (not reached)      | caught by content hash BEFORE the LLM                | message not stored again     |
| m06 | 2     | REVISION           | "Oct 30" -> 2026-10-30, sender = owner so applied    | #2 OPEN v1 due 10-30         |
| m07 | 2     | NO_COMMITMENT      | injection ignored; attacker not in allowlist         | no state change              |
| m08 | 3     | REVISION           | "Thursday" -> 2026-10-29, sender = owner, supersedes | #1 v2 due 10-29, v1 kept     |
| m09 | 3     | FULFILLED          | closes #2 with m09 as evidence                       | #2 FULFILLED                 |
| m10 | 3     | NEW_COMMITMENT     | "Thursday" -> 2026-10-29, owner taylor               | #4 OPEN v1 due 10-29         |
| m11 | 3     | REVISION (hearsay) | sender is neither owner nor user -> NOT applied      | #4 NEEDS_REVIEW              |

## Expected next actions

- Cycle 1 (10-20): #1 WAIT, #2 CLARIFY, #3 WAIT
- Cycle 2 (10-26): #1 DRAFT_REMINDER to sam (3 days overdue), #2 WAIT, #3 SELF_ALERT (you owe it, never emailed)
- Cycle 3 (10-28): #1 pending v1 draft auto-rejected as stale, new due date -> WAIT/due soon;
  #2 closed; #4 CLARIFY

## Compulsory scenario mapping

initial use = c1 | later use = c2 #1 | restart = before c2 | correction = m08
isolation = bob cannot see alice | conflicting evidence = m11 | tool failure = Phase 5
untrusted instruction = m07 | project-specific: duplicate = m05, fulfilled = m09
