# Task 17: Vercel-Only Stack and Prompt Flow

## Goal
Lock generated projects to a single zero-touch Vercel-hostable stack and remove Supabase/stack-choice UX.

## Scope
- Enforce a fixed stack profile in backend schema/defaults.
- Remove stack selectors in frontend create/settings forms.
- Update code-generation prompts/validators for Vercel-only output.
- Remove Supabase branches from deployment UX and pipeline output.

## Implementation Steps
- [ ] Replace variable stack schema with fixed Vercel profile.
- [ ] Remove stack options UI; display read-only runtime profile.
- [ ] Adjust generation prompts to require Next.js full-stack + Vercel compatibility.
- [ ] Remove Supabase provisioning/env injection from deploy handler.
- [ ] Remove Supabase UI affordances in sidebar and deploy viewer.
- [ ] Update contracts and tests.

## Acceptance Criteria
- [ ] New/updated projects always store the fixed stack profile.
- [ ] No Supabase setup is required for successful deploy flow.
- [ ] Generated code constraints explicitly target Vercel deployability.

