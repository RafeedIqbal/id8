# Task 16: Artifact Pages Viewport Fit

## Goal
Ensure artifact pages and viewers never overflow the viewport on desktop or mobile.

## Scope
- Add `min-w-0` and overflow guards to artifact route layout and viewer containers.
- Normalize table/code/raw JSON wrappers to scroll within panels, not the page.
- Clamp long URLs/paths/labels in headers and metadata rows.

## Implementation Steps
- [ ] Update artifact page grid/container sizing constraints.
- [ ] Add shared utility classes for safe horizontal overflow behavior.
- [ ] Patch viewers (PRD, design, tech plan, code, security, deploy, raw JSON) to avoid layout expansion.
- [ ] Verify project artifact route behavior at narrow/mobile widths.

## Acceptance Criteria
- [ ] No horizontal page scroll on artifact routes in normal usage.
- [ ] Long content scrolls/wraps inside viewer panels.
- [ ] Version rail + main content remain usable at mobile widths.

