# Task 21: Timeline State Fixes (In-Process/Failed)

## Goal
Fix timeline rendering bugs by deriving state from the latest run attempt segment.

## Scope
- Derive a latest-segment timeline view after the last replay/resume/start marker.
- Recompute node states from that segment only.
- Align failure-node inference with backend event semantics.

## Implementation Steps
- [ ] Add timeline segmentation helper utilities.
- [ ] Update timeline node state calculations to use segmented events.
- [ ] Update failure-node inference to use latest segment.
- [ ] Validate terminal and in-flight transitions against sample timelines.

## Acceptance Criteria
- [ ] Stale history from prior attempts does not affect current timeline state.
- [ ] Failed/current/completed markers match the latest attempt behavior.
- [ ] Timeline remains stable for replayed and resumed runs.

