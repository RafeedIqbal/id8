# Initial Concept\n\nID8 orchestrator API — prompt to production with HITL gates

# Product Definition

## Overview
ID8 is an AI-powered application generation platform designed for **Application Owners**. It streamlines the process of transforming natural language prompts into production-ready web applications through a managed, multi-stage workflow.

## Target Users
The primary users are **Application Owners**, who need a fast, reliable way to build and deploy web applications without deep technical expertise.

## Core Goals
- **Rapid App Generation:** Minimize the time from idea to a functional, deployed application by leveraging advanced AI for PRD, design, and code generation.
- **Efficient Orchestration:** Manage the entire development lifecycle, from initial concept to production deployment.

## Key Features
- **State Machine Pipeline:** A robust, multi-stage orchestration engine that guides the application building process through distinct phases (PRD, Design, Tech Plan, Code Generation).
- **Automated Deployment:** Seamless integration with platforms like Supabase and Vercel to automatically deploy approved application artifacts to production.
- **HITL Approval Gates:** Integrated interfaces for reviewing and approving AI-generated artifacts, ensuring quality and alignment with the user's vision.

## Technical Constraints & Requirements
- **Mandatory HITL Approval:** Every major milestone (PRD, Design, Tech Plan, Deployment) requires explicit user approval before the system can proceed.
- **State Persistence:** The system must track and persist the state of each project run, allowing for resumes from the last successful checkpoint in case of failures or manual rejections.
- **Deployment Targets:** Initial focus on Supabase for backend/database and Vercel for frontend hosting.

## Success Metrics
- Reduction in development time for new application prototypes.
- Percentage of projects successfully reaching production deployment.
- High user satisfaction with the quality of AI-generated artifacts.
