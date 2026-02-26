# Task 19: Design Image Context to Code Generation

## Goal
Maximize design fidelity by enriching and forwarding Stitch visual context into code generation.

## Scope
- Enrich Stitch outputs using additional MCP tool reads (`list_screens`, targeted `get_screen`).
- Persist normalized visual context in design metadata.
- Inject a bounded design context block into WriteCode prompts.

## Implementation Steps
- [ ] Add Stitch enrichment helpers with safe limits and fallbacks.
- [ ] Normalize screenshots/assets/component region metadata.
- [ ] Persist `design_codegen_context` under design metadata.
- [ ] Include condensed visual context in code-generation prompt templates.
- [ ] Add tests for context inclusion and graceful degradation on partial Stitch failures.

## Acceptance Criteria
- [ ] Codegen prompt includes structured visual context beyond plain screen names.
- [ ] Context size remains bounded and deterministic.
- [ ] Failures in enrichment do not fail design generation.

