# Task 03: Orchestrator & State Machine

## Goal
Implement the persisted state machine from `orchestration/state-machine.md` as the core run engine. This is the backbone of ID8 — it manages node transitions, checkpointing, retries, and resume-from-failure.

## Dependencies
- Task 01 (database models)
- Task 02 (API routes — to wire up run creation)

## Source of Truth
- `orchestration/state-machine.md` — node graph and contracts
- `TECH-PLAN.MD` §5 — state machine nodes and transition rules

## Steps

### 1. Define node registry
- [ ] `backend/app/orchestrator/nodes.py`
  - Enum or registry of all 14 nodes:
    `IngestPrompt, GeneratePRD, WaitPRDApproval, GenerateDesign, WaitDesignApproval, GenerateTechPlan, WaitTechPlanApproval, WriteCode, SecurityGate, PreparePR, WaitDeployApproval, DeployProduction, EndSuccess, EndFailed`
  - Each node has: `name`, `next_on_success`, `next_on_failure`, `is_wait_node`, `is_terminal`

### 2. Define transition table
- [ ] `backend/app/orchestrator/transitions.py`
  - Encode the full Mermaid graph as a transition map:
    ```python
    TRANSITIONS = {
        "IngestPrompt": {"success": "GeneratePRD"},
        "GeneratePRD": {"success": "WaitPRDApproval"},
        "WaitPRDApproval": {"approved": "GenerateDesign", "rejected": "GeneratePRD"},
        "GenerateDesign": {"success": "WaitDesignApproval"},
        "WaitDesignApproval": {"approved": "GenerateTechPlan", "rejected": "GenerateDesign"},
        "GenerateTechPlan": {"success": "WaitTechPlanApproval"},
        "WaitTechPlanApproval": {"approved": "WriteCode", "rejected": "GenerateTechPlan"},
        "WriteCode": {"success": "SecurityGate"},
        "SecurityGate": {"passed": "PreparePR", "failed": "WriteCode"},
        "PreparePR": {"success": "WaitDeployApproval"},
        "WaitDeployApproval": {"approved": "DeployProduction", "rejected": "EndFailed"},
        "DeployProduction": {"passed": "EndSuccess", "failed": "EndFailed"},
    }
    ```

### 3. Node handler interface
- [ ] `backend/app/orchestrator/base.py`
  - Abstract `NodeHandler` class:
    ```python
    class NodeHandler(ABC):
        async def execute(self, context: RunContext) -> NodeResult
    ```
  - `RunContext` dataclass: run_id, project_id, current_node, attempt, previous_artifacts, db_session
  - `NodeResult` dataclass: outcome (success/failed/approved/rejected/passed), artifact_data (optional), error (optional)

### 4. Orchestrator engine
- [ ] `backend/app/orchestrator/engine.py`
  - `async def run_orchestrator(run_id: UUID, db: AsyncSession)`
  - Main loop:
    1. Load run from DB, get `current_node`
    2. Lookup handler for current node
    3. Execute handler → get `NodeResult`
    4. If wait node: persist state and return (resume on next API call)
    5. If terminal: mark run complete/failed, update project status
    6. Otherwise: resolve next node from transition table, update `current_node`, loop
  - On handler exception: increment retry_count, schedule retry job if retryable, else transition to EndFailed

### 5. Checkpoint and idempotency
- [ ] Before executing a node, check if artifact for this (run_id, node_name) already exists
- [ ] If yes and node is idempotent: skip execution, use existing result
- [ ] Update `project_runs.current_node` and `project_runs.updated_at` after each transition
- [ ] Update `projects.status` to match the relevant status for the current node

### 6. Retry logic
- [ ] `backend/app/orchestrator/retry.py`
  - Exponential backoff: 3s, 9s, 27s with jitter
  - Max 3 attempts per node
  - On retry exhaustion: transition to `EndFailed` with resume metadata
  - Model rate-limit errors: switch to fallback profile before retrying
  - Create `RetryJob` row for scheduled retries

### 7. Resume from failure
- [ ] When `createRun` is called with `resume_from_node`:
  - Validate the node exists and was previously reached
  - Set `current_node` to that node
  - Clear error fields
  - Re-enter orchestrator loop

### 8. Worker entrypoint
- [ ] `backend/app/worker.py`
  - Poll for pending runs and retry jobs
  - Execute `run_orchestrator` for each
  - Process scheduled retry jobs whose `scheduled_for` has passed

### 9. Wire into API
- [ ] `POST /v1/projects/{projectId}/runs` → enqueue run for worker
- [ ] `POST /v1/projects/{projectId}/approvals` → if run is at a wait node, trigger orchestrator to transition

## Stub Node Handlers (for now)
- [ ] `IngestPromptHandler` — extract prompt from project, return success
- [ ] `WaitXApprovalHandler` — check for approval event in DB, return approved/rejected or wait
- [ ] `EndSuccessHandler` / `EndFailedHandler` — mark terminal state
- [ ] All generation nodes: return placeholder artifacts (real implementations in Tasks 05-09)

## Definition of Done
- [ ] A run can progress from `IngestPrompt` through all wait nodes to `EndSuccess` with manual approvals
- [ ] Rejection at any gate loops back to the correct generation node
- [ ] Killing the worker mid-run and resuming produces no duplicate artifacts
- [ ] Retry logic fires on simulated transient errors
- [ ] `project_runs.current_node` always reflects the actual state
- [ ] `projects.status` updates match the node progression
