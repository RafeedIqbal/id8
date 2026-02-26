# Task 22: Timeline Step Replay Semantics

## Goal
Fix rollback behavior so replay and retry use correct modes and backend guardrails.

## Scope
- Distinguish retrying failed node from replaying prior nodes.
- Default failed-run non-failed node actions to `replay_from_node`.
- Enforce backend `retry_failed` guardrails to failed-node-only behavior.

## Implementation Steps
- [ ] Update timeline action labeling and replay mode selection.
- [ ] Add backend validation for `retry_failed` requests.
- [ ] Ensure replay continues creating new runs with artifact copy-forward.
- [ ] Add route-level tests for invalid/valid combinations.

## Acceptance Criteria
- [ ] “Retry failed step” only applies to the actual failed node.
- [ ] “Replay from this step” creates a new run for prior-step rollback.
- [ ] User-visible timeline controls match backend behavior.

