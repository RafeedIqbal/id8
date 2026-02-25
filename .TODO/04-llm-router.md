# Task 04: LLM Router & Gemini Integration

## Goal
Implement model-profile-based routing so each orchestrator node uses the correct Gemini model. Record token usage and cost per artifact.

## Dependencies
- Task 03 (orchestrator — node handlers call the LLM router)

## Source of Truth
- `TECH-PLAN.MD` §1 — Model Routing table
- `contracts/domain-types.ts` — `LlmRoutingPolicy`, `ModelProfile`

## Steps

### 1. Gemini SDK client
- [ ] Add `google-genai` (or `google-generativeai`) to `pyproject.toml`
- [ ] `backend/app/llm/client.py`
  - Initialize Gemini client with `GEMINI_API_KEY` from config
  - Wrapper function: `async def generate(model_id: str, prompt: str, system_prompt: str, tools: list | None) -> LlmResponse`
  - `LlmResponse` dataclass: content (str), token_usage (prompt_tokens, completion_tokens), model_id, latency_ms

### 2. Model profile router
- [ ] `backend/app/llm/router.py`
  - Mapping from `ModelProfile` to model ID:
    ```python
    MODEL_MAP = {
        "primary": "gemini-3.1-pro-preview",
        "customtools": "gemini-3.1-pro-preview-customtools",
        "fallback": "gemini-2.5-pro",
    }
    ```
  - `resolve_model(profile: ModelProfile) -> str`
  - Node-to-profile mapping:
    - Planning/reasoning nodes (`GeneratePRD`, `GenerateTechPlan`): `primary`
    - Tool-heavy nodes (`WriteCode`, `GenerateDesign`): `customtools`
    - Fallback: only on retry after primary/customtools failure

### 3. Fallback logic
- [ ] On `generate()` failure with retryable error:
  1. First retry: same model
  2. Second retry: switch to `fallback` profile
  3. Third retry: `fallback` profile with reduced prompt
- [ ] Log model switch events to audit trail

### 4. Token and cost telemetry
- [ ] After each LLM call, persist to `project_artifacts.content` metadata:
  - `model_profile` used
  - `model_id` resolved
  - `prompt_tokens`, `completion_tokens`
  - `latency_ms`
- [ ] Set `project_artifacts.model_profile` column

### 5. Prompt templates
- [ ] `backend/app/llm/prompts/`
  - `prd_generation.py` — system prompt and user prompt template for PRD
  - `tech_plan_generation.py` — system prompt and user prompt template for tech plan
  - `code_generation.py` — system prompt and user prompt template for code
  - Each template accepts structured input (approved artifacts) and returns formatted prompt string

### 6. Rate limit handling
- [ ] Detect 429 responses from Gemini API
- [ ] Extract `retry-after` header if present
- [ ] Feed into orchestrator retry logic with budget-aware delay

## Definition of Done
- [ ] `generate()` correctly routes to the right Gemini model based on profile
- [ ] Fallback from `primary` → `fallback` on simulated failures works
- [ ] Token usage is recorded on every artifact
- [ ] Rate limit errors produce retry jobs with appropriate delays
- [ ] Unit tests with mocked Gemini client cover all three profiles
