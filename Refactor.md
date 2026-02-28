# Template-Based Next.js Codegen Refactor

## Summary
- Replace the current “generate a full standalone Next.js app” flow with a template-anchored flow that uses the local template at [exampleApp/example](/Users/rafeediqbal/GitHub/id8/exampleApp/example) as the server-side base project.
- Keep `code_snapshot` as the authoritative, full merged project artifact. The LLM should return only allowed app deltas plus package additions; the backend should merge those deltas into the template before validation, security scanning, artifact persistence, GitHub push, and Vercel deployment.
- Preserve the existing orchestration graph. This refactor is limited to codegen, merge, validation, and GitHub sync behavior. No new workflow stages and no REST contract expansion.

## Agent Context Files
### Must Read First
- Codegen entrypoint: [write_code.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/handlers/write_code.py)
- Codegen prompt contract: [code_generation.py](/Users/rafeediqbal/GitHub/id8/backend/app/llm/prompts/code_generation.py)
- Code artifact schema: [code_snapshot.py](/Users/rafeediqbal/GitHub/id8/backend/app/schemas/code_snapshot.py)
- GitHub upload flow: [prepare_pr.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/handlers/prepare_pr.py)
- GitHub tree commit client: [client.py](/Users/rafeediqbal/GitHub/id8/backend/app/github/client.py)
- Design artifact production and metadata wiring: [generate_design.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/handlers/generate_design.py)
- Stitch design enrichment used for codegen context: [stitch_mcp.py](/Users/rafeediqbal/GitHub/id8/backend/app/design/stitch_mcp.py)
- PRD generation input flow: [generate_prd.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/handlers/generate_prd.py)
- Artifact loading and selected-artifact override behavior: [engine.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/engine.py)
- Runtime settings: [config.py](/Users/rafeediqbal/GitHub/id8/backend/app/config.py)

### Template Source Of Truth
- Template root to inventory recursively: [example](/Users/rafeediqbal/GitHub/id8/exampleApp/example)
- Base manifest to send into codegen and merge server-side: [package.json](/Users/rafeediqbal/GitHub/id8/exampleApp/example/package.json)
- Base layout allowed for controlled override: [layout.tsx](/Users/rafeediqbal/GitHub/id8/exampleApp/example/app/layout.tsx)
- Base homepage allowed for controlled override: [page.tsx](/Users/rafeediqbal/GitHub/id8/exampleApp/example/app/page.tsx)
- Base global styles allowed for controlled override: [globals.css](/Users/rafeediqbal/GitHub/id8/exampleApp/example/app/globals.css)
- Base config preserved as server-owned: [next.config.ts](/Users/rafeediqbal/GitHub/id8/exampleApp/example/next.config.ts)
- Base config preserved as server-owned: [tsconfig.json](/Users/rafeediqbal/GitHub/id8/exampleApp/example/tsconfig.json)
- Base config preserved as server-owned: [postcss.config.mjs](/Users/rafeediqbal/GitHub/id8/exampleApp/example/postcss.config.mjs)
- Base config preserved as server-owned: [eslint.config.mjs](/Users/rafeediqbal/GitHub/id8/exampleApp/example/eslint.config.mjs)

### Downstream Consumers To Verify
- Deploy reads the latest `code_snapshot`: [deploy_production.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/handlers/deploy_production.py)
- Artifact wire schema stays compatible: [artifact.py](/Users/rafeediqbal/GitHub/id8/backend/app/schemas/artifact.py)
- Artifact persistence model: [project_artifact.py](/Users/rafeediqbal/GitHub/id8/backend/app/models/project_artifact.py)
- Code artifact viewer should still work with full merged snapshots: [code-viewer.tsx](/Users/rafeediqbal/GitHub/id8/frontend/src/components/artifact-viewers/code-viewer.tsx)
- Frontend domain typing to confirm no public contract change is needed: [domain.ts](/Users/rafeediqbal/GitHub/id8/frontend/src/types/domain.ts)
- Canonical contract file to verify “no API change”: [domain-types.ts](/Users/rafeediqbal/GitHub/id8/contracts/domain-types.ts)

## Public Interfaces And Defaults
- No REST route shape changes. Do not change [openapi.yaml](/Users/rafeediqbal/GitHub/id8/contracts/openapi.yaml) unless implementation later decides to expose new merge metadata publicly. Default decision: do not expose it.
- Internal LLM chunk schema must change. `CodeChunkContent` in [code_snapshot.py](/Users/rafeediqbal/GitHub/id8/backend/app/schemas/code_snapshot.py) should gain `package_changes` with `dependencies` and `devDependencies` maps.
- `CodeSnapshotContent` should remain externally compatible with `files`, `build_command`, `test_command`, and `entry_point`, but `__code_metadata` should record template and merge provenance.
- Add `codegen_template_dir` to [config.py](/Users/rafeediqbal/GitHub/id8/backend/app/config.py). Default it to repo-relative `exampleApp/example`, with optional env override. Resolve relative paths against the repo root; do not hardcode the user-specific absolute path in runtime logic.

## Implementation
1. Add a new helper module at [template_project.py](/Users/rafeediqbal/GitHub/id8/backend/app/codegen/template_project.py) and package init at [__init__.py](/Users/rafeediqbal/GitHub/id8/backend/app/codegen/__init__.py). This module should load the template tree, ignore non-source/runtime noise (`node_modules`, `.next`, `.git`, OS files), expose the template inventory for prompts, parse and merge `package.json`, apply AI file deltas, and return the full merged file list sorted by path.
2. Refactor [code_generation.py](/Users/rafeediqbal/GitHub/id8/backend/app/llm/prompts/code_generation.py) so the model is no longer asked to create a whole project. The prompt must send four things explicitly: sanitized PRD JSON, sanitized design artifact JSON, `design_codegen_context` from Stitch metadata, and the template context consisting of file inventory plus full contents of `package.json`, `app/layout.tsx`, `app/page.tsx`, and `app/globals.css`.
3. Change the prompt output schema to this exact internal contract: `{"files":[...],"package_changes":{"dependencies":{},"devDependencies":{}}}`. The prompt must instruct the model to return only allowed project deltas and never return a replacement `package.json`.
4. Enforce an allowlist in [write_code.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/handlers/write_code.py). Allowed new or replaced paths are `app/**`, `components/**`, `lib/**`, `types/**`, `data/**`, and `public/**`. Controlled override paths are only `app/page.tsx`, `app/layout.tsx`, and `app/globals.css`. Template-owned config files such as `next.config.ts`, `tsconfig.json`, `postcss.config.mjs`, `eslint.config.mjs`, and root `package.json` must remain server-managed.
5. Replace the current generation phases in [write_code.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/handlers/write_code.py) with two template-aware phases: `shared_foundation` for shared components, data/types/lib, allowed shell overrides, and package additions; `pages` for `app/page.tsx` and additional route pages under `app/**/page.tsx`. Keep the repair pass, but make it operate on the merged tree and the same path restrictions.
6. Merge package additions on the server in [template_project.py](/Users/rafeediqbal/GitHub/id8/backend/app/codegen/template_project.py). Existing template dependency versions win. If the model attempts to modify an already-present package version instead of adding a new package, treat that as validation failure, not silent mutation. Persist the merged manifest as the final root `package.json`.
7. Build the final `code_snapshot` from the full merged project tree, not from the AI delta. This keeps [deploy_production.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/handlers/deploy_production.py), the security gate, and the artifact viewer unchanged in behavior.
8. Update snapshot validation in [write_code.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/handlers/write_code.py) so root-level `app/page.tsx` is a valid entrypoint candidate. Also change inferred defaults to match the template stack: `entry_point` default should become `app/page.tsx`, and `test_command` should become `npx tsc --noEmit && npm run lint` instead of `npm test`.
9. Record merge provenance in `__code_metadata` inside [write_code.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/handlers/write_code.py). Include `template_dir`, `template_file_count`, `ai_delta_file_count`, `merged_file_count`, `allowed_override_paths`, `package_additions`, and a flag indicating the snapshot is an authoritative merged tree.
10. Change GitHub tree writing in [client.py](/Users/rafeediqbal/GitHub/id8/backend/app/github/client.py) to an authoritative full-tree commit. Do not create the new tree on top of `base_tree`; create the commit tree from the full merged snapshot so stale files from earlier runs are removed automatically.
11. Keep [prepare_pr.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/handlers/prepare_pr.py) as the consumer of the merged full snapshot, but update comments and commit semantics to make it clear that it pushes the exact merged template tree for the run.
12. Exclude `package-lock.json` from the final merged output. The template currently contains a lockfile, but without a reliable server-side install/regeneration step it will drift as soon as the model adds packages. The authoritative pushed project should therefore include the merged `package.json` and omit `package-lock.json`.
13. Do not change the orchestrator node graph in [nodes.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/nodes.py) or [transitions.py](/Users/rafeediqbal/GitHub/id8/backend/app/orchestrator/transitions.py). This refactor is intentionally underneath the existing `WriteCode -> SecurityGate -> PreparePR -> DeployProduction` flow.

## Tests And Acceptance
- Create `backend/tests/` if it is still absent, then add [test_template_project.py](/Users/rafeediqbal/GitHub/id8/backend/tests/codegen/test_template_project.py) to cover template resolution, ignored files, package merge behavior, allowlist enforcement, and full merged tree assembly.
- Add [test_code_generation.py](/Users/rafeediqbal/GitHub/id8/backend/tests/llm/prompts/test_code_generation.py) to verify the prompt now includes PRD, design spec, `design_codegen_context`, template file inventory, and the literal template `package.json` contents, while instructing the model to return package additions instead of a full manifest.
- Add [test_write_code_template_merge.py](/Users/rafeediqbal/GitHub/id8/backend/tests/orchestrator/handlers/test_write_code_template_merge.py) to cover successful delta merge, blocked protected-file mutation, blocked package version override, repair-pass behavior on merged snapshots, `app/page.tsx` entrypoint inference, and full-snapshot metadata.
- Add [test_client_push_files.py](/Users/rafeediqbal/GitHub/id8/backend/tests/github/test_client_push_files.py) to verify the GitHub client now produces authoritative full-tree commits rather than additive overlays.
- Acceptance scenario 1: approved PRD plus approved design yields an LLM delta containing new pages and package additions; backend merges them into the template and persists a full `code_snapshot` with template files included.
- Acceptance scenario 2: rerunning the project with fewer routes removes stale files from the branch commit, proving the repo sync is authoritative.
- Acceptance scenario 3: a model response that tries to rewrite `next.config.ts` or change the version of an existing template dependency fails fast with an explicit validation error.
- Acceptance scenario 4: downstream [code-viewer.tsx](/Users/rafeediqbal/GitHub/id8/frontend/src/components/artifact-viewers/code-viewer.tsx) still renders the full merged tree without requiring frontend contract changes.
- Acceptance scenario 5: the final GitHub repo contains the full template-based project, not only the AI-authored page files, and Vercel deployment still uses the same repo/main-branch flow.

## Assumptions And Locked Decisions
- Repo sync mode is authoritative per run.
- Template edit scope is controlled overrides only.
- PRD and design data are both required prompt inputs for codegen; use the existing design artifact plus `design_codegen_context` and do not add a new tech-plan dependency in this refactor.
- The template path defaults to repo-relative `exampleApp/example`; absolute local paths are only a development reference, not the runtime contract.
- `package-lock.json` is intentionally omitted from generated output until the backend can regenerate it deterministically.
