# Task 18: Canonical Project Title

## Goal
Make project title first-class and use it consistently (including Stitch project naming).

## Scope
- Add `title` to project API models and persistence.
- Require `title` on project creation and allow editing.
- Render title across dashboard/project pages.
- Use title as primary Stitch project naming input.

## Implementation Steps
- [ ] Add `title` field in project model/schema/routes/contracts.
- [ ] Update frontend create/settings forms and domain/api mappings.
- [ ] Update page headers/list cards to prefer title.
- [ ] Pass title into design generation naming path.
- [ ] Align PR title generation fallback with project title.

## Acceptance Criteria
- [ ] Projects have stable, explicit titles.
- [ ] Stitch project creation/matching uses canonical title.
- [ ] UI no longer relies on awkward prompt truncation as the project name.

