# Technical Implementation Plan: ID8

## 1. System Architecture

The system will utilize a centralized orchestration backend that manages the state of each project and communicates with external services via the Model Context Protocol (MCP).



* **Frontend Client:** Next.js (React) web app where users input ideas and approve AI outputs (Human-in-the-Loop gates).
* **API & Orchestration Backend:** Python (FastAPI). Python is highly recommended if using LangGraph for complex state machine orchestration.
* **State Management Database:** PostgreSQL (hosted on Supabase) to track user sessions, project metadata, and the current state of the AI agent.
* **LLM Engine:** Gemini
* **External Integrations (MCP Servers):** 
    * Stitch MCP (UI generation)
    * GitHub MCP (Source control)
    * Supabase MCP (BaaS provisioning)
    * Vercel MCP (Frontend hosting)

---

## 2. Internal Database Schema

To make the system frictionless and resumable, ID8 AI needs to track the state of every generated application.

**Table: `users`**
* `id` (UUID, Primary Key)
* `email` (String)
* `MCP/AI Tokens and API keys` (Encrypted String)


**Table: `projects`**
* `id` (UUID, Primary Key)
* `user_id` (UUID, Foreign Key)
* `initial_prompt` (Text)
* `status` (Enum: `ideation`, `design`, `coding`, `deploying`, `completed`, `failed`)
* `github_repo_url` (String, Nullable)
* `live_deployment_url` (String, Nullable)

**Table: `project_artifacts`**
* `id` (UUID, Primary Key)
* `project_id` (UUID, Foreign Key)
* `artifact_type` (Enum: `prd`, `design_spec`, `tech_plan`, `codebase_snapshot`, `MCP_info (Stitch, GitHub, Supabase, Vercel)`)
* `content` (JSONB)
* `approved_by_user` (Boolean, Default: false)

---

## 3. Agent State Machine Flow

Because this system requires Human-in-the-Loop (HITL) interventions, a standard linear script will fail. We must implement a state machine (e.g., using LangGraph or AWS Step Functions).



**The State Nodes & Edges:**

1.  **Node `Ingest_Prompt`** -> Transitions to `Generate_PRD`
2.  **Node `Generate_PRD`** -> Transitions to `Wait_PRD_Approval`
3.  **Gate `Wait_PRD_Approval`**:
    * If User Edits/Rejects -> Loop back to `Generate_PRD` with feedback.
    * If User Approves -> Transition to `Generate_Design`
4.  **Node `Generate_Design`** (Calls Stitch MCP) -> Transitions to `Wait_Design_Approval`
5.  **Gate `Wait_Design_Approval`**:
    * If User Edits/Rejects -> Loop back to `Generate_Design` with UI feedback.
    * If User Approves -> Transition to `Generate_Tech_Plan`
6.  **Node `Generate_Tech_Plan`** -> Transitions to `Write_Code`
7.  **Node `Write_Code`** -> Transitions to `Security_Audit`
    * *Loop:* If `Security_Audit` fails -> Loop back to `Write_Code` with error context.
    * If `Security_Audit` passes -> Transition to `Commit_To_Repo`
8.  **Node `Commit_To_Repo`** (Calls GitHub MCP) -> Transitions to `Deploy_Infrastructure`
9.  **Node `Deploy_Infrastructure`** (Calls Supabase & Vercel MCPs) -> Transitions to `End_Success`

---

## 4. Phased Engineering Execution

To avoid integration hell, the engineering team should build this in four distinct phases:

### Phase 1: The Core Platform & HITL Framework
* Set up the Next.js frontend and the backend API.
* Implement user authentication.
* Build the database schema to track projects and artifacts.
* **Goal:** A user can log in, submit a prompt, and the system saves it to the database, marking the status as "pending".

### Phase 2: Orchestration & AI Content Generation
* Integrate the LLM and build the agent state machine logic.
* Implement the prompt chains for PRD generation and Technical Plan generation.
* Build the interactive UI components that allow users to view, edit, and approve the PRD and Tech Plan (the HITL gates).
* **Goal:** The system can guide a user from a prompt to a finalized, approved technical architecture document.

### Phase 3: The MCP Integration Layer (The Heavy Lifting)
* Implement OAuth flows for Stitch, GitHub, Vercel, and Supabase so Genesis AI has permission to act on the user's behalf.
* Integrate the Stitch MCP for generating UI definitions based on the approved PRD.
* Integrate the GitHub MCP to create repos and push code.
* **Goal:** The system can successfully talk to external tools and manage credentials securely.

### Phase 4: Autonomous Coding & Deployment
* Implement the `Write_Code` node. Give the LLM tools to create files, write boilerplate, and implement components based on the Tech Plan.
* Implement the automated Security Audit prompt chain.
* Connect the final outputs to the Vercel and Supabase MCPs to execute the deployment.
* **Goal:** The fully realized system where approved code is automatically shipped to a live URL.