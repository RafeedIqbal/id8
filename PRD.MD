# Product Requirements Document (PRD): ID8

## 1. Executive Summary
**Product Name:** ID8
**Vision:** To democratize software creation by providing a frictionless, end-to-end AI system that transforms a user's natural language web app idea into a fully implemented, secure, and deployed Minimum Viable Product (MVP) in minutes.
**Core Value Proposition:** ID8 acts as an autonomous product manager, designer, software engineer, security auditor, and DevOps engineer, governed by a Human-In-The-Loop (HITL) approval process to ensure accuracy and alignment with the user's vision.

---

## 2. Target Audience
* **Non-Technical Founders/Entrepreneurs:** Looking to rapidly validate ideas without hiring an entire engineering team.
* **Product Managers & Designers:** Prototyping realistic, functional applications for user testing and stakeholder buy-in.
* **Software Engineers:** Accelerating boilerplate creation, MVP scaffolding, and CI/CD setup to focus on complex business logic later.

---



## 3. User Flow & Journey
The system relies on a sequential, state-machine-like flow with distinct approval gates.

1.  **Ideation:** User inputs a natural language prompt describing their web app idea.
2.  **Product Definition:** AI generates a structured PRD for the MVP.
3.  **Gate 1 (PRD Approval):** User reviews, edits, and approves the PRD.
4.  **Design Generation:** AI leverages Google Stitch MCP to generate UI/UX designs based on the approved PRD.
5.  **Gate 2 (Design Approval):** User reviews, edits, and approves the proposed screens.
6.  **Planning:** AI generates a technical implementation plan (architecture, database schema, component tree).
7.  **Implementation:** AI writes Frontend and Backend code.
8.  **Security Audit:** AI runs a static code analysis and security check.
9.  **Version Control:** AI commits and pushes the codebase to a repository using GitHub MCP.
10. **Deployment:** AI provisions infrastructure and deploys using Vercel MCP (Frontend) and Supabase MCP (Backend/Database).

---

## 4. Functional Requirements

### Module 1: Input & Product Definition Engine
* **FR1.1 Prompt Ingestion:** The UI must accept multi-paragraph text, file uploads (e.g., rough sketches), and clarifying constraints (e.g., "Must be mobile-first").
* **FR1.2 PRD Generation:** The LLM must output a structured PRD containing:
    * Core User Stories
    * Out of Scope (MVP constraints)
    * Data Models/Entities
* **FR1.3 Interactive Editor:** The UI must allow users to accept, reject, or manually edit sections of the generated PRD before proceeding.

### Module 2: Design Engine (Google Stitch MCP Integration)
* **FR2.1 Context Handoff:** System must translate the approved PRD into prompt constraints optimized for the Google Stitch MCP.
* **FR2.2 Screen Generation:** Generate distinct mockups/wireframes for all key user flows identified in the PRD.
* **FR2.3 Visual Editor:** User must be able to leave comments on specific UI elements to trigger iterative AI regenerations ("Make this button blue", "Move this form to a modal").

### Module 3: Engineering & Planning Engine
* **FR3.1 Tech Stack Selection:** Default to a modern, compatible stack (e.g., Next.js/React for Frontend, Supabase/PostgreSQL for Backend) unless overridden by the user.
* **FR3.2 Implementation Plan Generation:** Output a step-by-step technical plan including:
    * Folder structure
    * Database schema (SQL/Supabase schema)
    * API route definitions
    * Component hierarchy

### Module 4: Code Generation & Security
* **FR4.1 Autonomous Coding:** The AI agent writes functional code file-by-file based on the implementation plan and approved Stitch designs.
* **FR4.2 Security Audit:** Run an automated LLM-based (and optionally rule-based, like ESLint/SonarQube) security pass.
    * *Checks:* SQL injection, XSS vulnerabilities, exposed API keys, insecure authentication flows.
    * *Action:* Auto-remediate found issues and log them for the user.

### Module 5: DevOps & Deployment Engine
* **FR5.1 GitHub MCP Integration:**
    * Authenticate via OAuth.
    * Create a new private/public repository.
    * Commit all generated code with descriptive commit messages.
    * Push to `main`.
* **FR5.2 Supabase MCP Integration:**
    * Provision a new Supabase project.
    * Execute SQL migrations to set up the database schema and Row Level Security (RLS) policies.
    * Retrieve API keys/secrets for frontend environment variables.
* **FR5.3 Vercel MCP Integration:**
    * Provision a new Vercel project linked to the GitHub repository.
    * Inject environment variables (Supabase URL, Anon Key).
    * Trigger initial build and deployment.
    * Return the live staging/production URL to the user.

---

## 5. Non-Functional Requirements (NFRs)

* **Performance:** PRD and Design generation should take < 30 seconds each. Full code generation and deployment should take < 5 minutes.
* **Reliability (Error Handling):** If an MCP fails (e.g., Vercel API timeout), the system must have retry logic and gracefully surface the error to the user without losing the generated codebase.
* **Security:** User prompts and generated code must be siloed. The platform must securely manage OAuth tokens for GitHub, Vercel, and Supabase without storing them in plaintext.
* **Extensibility:** The system architecture must rely on the Model Context Protocol (MCP) to easily swap or add future integrations (e.g., AWS MCP, Figma MCP).

---

## 6. Technical Architecture & Integrations

* **Core Orchestrator:** LangChain / LlamaIndex or a custom state-machine agent framework (e.g., LangGraph) to manage the strict sequential flow.
* **LLM Provider:** High-context models (e.g., Gemini 1.5 Pro) capable of holding the entire PRD, design specs, and codebase in context simultaneously.
* **Integrations (Via Model Context Protocol):**
    * `stitch-mcp`: For UI design generation.
    * `github-mcp`: For repository management and source control.
    * `vercel-mcp`: For frontend hosting and CI/CD pipelines.
    * `supabase-mcp`: For Backend-as-a-Service, database provisioning, and auth setup.

---

## 7. Out of Scope for MVP
* Post-deployment analytics or monitoring.
* Generating mobile applications (iOS/Android native); web apps only for MVP.
* Complex legacy code migrations or importing existing GitHub repositories.
* Custom domain purchasing and routing (uses default `.vercel.app` domains).