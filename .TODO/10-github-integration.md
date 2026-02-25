# Task 10: GitHub Integration (PreparePR Node)

## Goal
Implement repo creation, branch management, PR creation, check polling, and merge via GitHub API. Enforce branch protection — no direct push to main.

## Dependencies
- Task 09 (security gate — must pass before PR)
- Task 01 (provider_credentials table for GitHub auth)

## Source of Truth
- `orchestration/state-machine.md` — node 10
- `PRD.MD` §5.5 — Module 5: Repository and Merge Workflow
- `IMPLEMENTATION-PLAN-V2.MD` — Agent-GitHub

## Steps

### 1. GitHub client
- [ ] `backend/app/github/client.py`
- [ ] Authenticate via GitHub App (private key + app ID from config) or PAT
- [ ] Wrapper methods:
  - `create_repo(name, org, private) -> RepoInfo`
  - `create_branch(repo, base, branch_name) -> BranchRef`
  - `push_files(repo, branch, files: list[CodeFile]) -> CommitSha`
  - `create_pull_request(repo, head, base, title, body) -> PrInfo`
  - `get_check_runs(repo, ref) -> list[CheckRun]`
  - `merge_pull_request(repo, pr_number, method="squash") -> MergeResult`
- [ ] Use `httpx` async client for GitHub REST API v3

### 2. PreparePR handler
- [ ] `backend/app/orchestrator/handlers/prepare_pr.py`
- [ ] Steps:
  1. Check if GitHub repo exists for this project (check `projects.github_repo_url`)
  2. If not: create repo via `create_repo()`, update project record
  3. Create feature branch: `id8/run-{run_id}`
  4. Push all files from `code_snapshot` artifact to the branch
  5. Create PR: title = project prompt summary, body = artifact references
  6. Poll check runs until all complete (with timeout)
  7. If all checks pass: merge PR
  8. If checks fail: return failure with check details
- [ ] Update `projects.github_repo_url` with repo URL
- [ ] Store PR URL in artifact metadata

### 3. Branch protection enforcement
- [ ] NEVER push directly to `main` — always use branch + PR flow
- [ ] If repo has branch protection rules, respect them
- [ ] If merge is blocked by failing checks: return to caller with details

### 4. Idempotency
- [ ] If branch already exists (resume scenario): don't recreate
- [ ] If PR already exists for this run: don't create duplicate
- [ ] Check by matching branch name pattern `id8/run-{run_id}`

### 5. Error handling
- [ ] GitHub API rate limits: exponential backoff
- [ ] Auth failures: clear error message, don't retry
- [ ] Check timeout: fail with details after configurable max wait (10 min default)

### 6. Artifact output
- [ ] Store in run context / artifact metadata:
  - `github_repo_url`
  - `branch_name`
  - `pr_url`
  - `pr_number`
  - `merge_commit_sha`
  - `check_statuses`

## Definition of Done
- [ ] Repo is created if absent
- [ ] Code is pushed to feature branch (not main)
- [ ] PR is created, checks are polled, merge happens on pass
- [ ] Direct push to protected branch is rejected
- [ ] Resume creates no duplicate PRs or branches
- [ ] Matches acceptance test scenario #6 (Git Policy Enforcement)
