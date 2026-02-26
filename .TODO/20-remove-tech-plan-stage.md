# Task 20: Remove Tech Plan Stage From Active Flow

## Goal
Remove Tech Plan from the active generation/approval path for new runs while preserving legacy read compatibility.

## Scope
- Route design approval directly to code generation.
- Remove tech-plan stage from active timeline/approval UX.
- Keep legacy artifacts/types readable.

## Implementation Steps
- [ ] Update orchestrator transition from design approval to WriteCode.
- [ ] Remove tech-plan stage from active frontend timeline/navigation mappings.
- [ ] Adjust approval flow wiring for active runs.
- [ ] Keep legacy tech-plan rendering paths intact.
- [ ] Update tests/contracts for new active flow semantics.

## Acceptance Criteria
- [ ] New runs do not enter GenerateTechPlan/WaitTechPlanApproval.
- [ ] Existing historical tech-plan artifacts remain viewable.
- [ ] Approval UX no longer prompts for tech-plan review in active flows.

