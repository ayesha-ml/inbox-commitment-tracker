# Scenario Evaluation Results

| Scenario | Pass/Fail | Observed Evidence |
|---|---|---|
| 1. Initial Use | PASSED | Created 3 commitments in Cycle 1 |
| 6. Missing/Conflicting Evidence | PASSED | Ambiguous email correctly stored as NEEDS_REVIEW |
| 2. Later Use | PASSED | Correctly recommended DRAFT_REMINDER for overdue task |
| 3. Process Restart | PASSED | Retrieved 3 commitments post-restart without reuploading |
| 4. Correction | PASSED | Deadline updated to v2 (2026-10-29); v1 marked superseded |
| 5. Isolation | PASSED | User Bob cannot see Alice's commitments |
| 7. Untrusted Instruction | PASSED | Prompt injection attempt safely classified with no tool side-effects |
| 8. Duplicate Retry | PASSED | Duplicate message detected via SHA-256 hash: DUPLICATE_CONTENT |
| 9. Project Specific: Fulfillment | PASSED | Task correctly marked FULFILLED on delivery proof |
| 10. Project Specific: Hearsay Shield | PASSED | Third-party date change attempt blocked and flagged NEEDS_REVIEW |
