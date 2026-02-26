import type { ArtifactType, ApprovalStage, ProjectStatus } from "@/types/domain";

/** Canonical 14-node pipeline in execution order. */
export const PIPELINE_NODES = [
  "IngestPrompt",
  "GeneratePRD",
  "WaitPRDApproval",
  "GenerateDesign",
  "WaitDesignApproval",
  "WriteCode",
  "SecurityGate",
  "PreparePR",
  "WaitDeployApproval",
  "DeployProduction",
  "EndSuccess",
  "EndFailed",
] as const;

export const LEGACY_TECH_PLAN_NODES = ["GenerateTechPlan", "WaitTechPlanApproval"] as const;

export type NodeName = (typeof PIPELINE_NODES)[number];

export const NODE_LABELS: Record<string, string> = {
  IngestPrompt: "Ingest Prompt",
  GeneratePRD: "Generate PRD",
  WaitPRDApproval: "PRD Approval",
  GenerateDesign: "Generate Design",
  WaitDesignApproval: "Design Approval",
  GenerateTechPlan: "Legacy Tech Plan",
  WaitTechPlanApproval: "Legacy Tech Plan Approval",
  WriteCode: "Write Code",
  SecurityGate: "Security Gate",
  PreparePR: "Prepare PR",
  WaitDeployApproval: "Deploy Approval",
  DeployProduction: "Deploy Production",
  EndSuccess: "Deployed",
  EndFailed: "Failed",
};

export const STATUS_CONFIG: Record<ProjectStatus, { label: string; color: string; bg: string }> = {
  ideation: { label: "Ideation", color: "var(--color-text-2)", bg: "var(--color-surface-3)" },
  prd_draft: { label: "PRD Draft", color: "var(--color-info)", bg: "var(--color-info-bg)" },
  prd_approved: { label: "PRD Approved", color: "var(--color-success)", bg: "var(--color-success-bg)" },
  design_draft: { label: "Design Draft", color: "var(--color-info)", bg: "var(--color-info-bg)" },
  design_approved: { label: "Design OK", color: "var(--color-success)", bg: "var(--color-success-bg)" },
  tech_plan_draft: { label: "Legacy Tech Plan", color: "var(--color-info)", bg: "var(--color-info-bg)" },
  tech_plan_approved: { label: "Legacy Plan OK", color: "var(--color-success)", bg: "var(--color-success-bg)" },
  codegen: { label: "Codegen", color: "var(--color-accent)", bg: "var(--color-accent-bg)" },
  security_gate: { label: "Security", color: "var(--color-warning)", bg: "var(--color-warning-bg)" },
  deploy_ready: { label: "Deploy Ready", color: "var(--color-accent)", bg: "var(--color-accent-bg)" },
  deploying: { label: "Deploying", color: "var(--color-warning)", bg: "var(--color-warning-bg)" },
  deployed: { label: "Live", color: "var(--color-success)", bg: "var(--color-success-bg)" },
  failed: { label: "Failed", color: "var(--color-error)", bg: "var(--color-error-bg)" },
};

export const ARTIFACT_LABELS: Record<ArtifactType, string> = {
  prd: "PRD",
  design_spec: "Design Spec",
  tech_plan: "Legacy Tech Plan",
  code_snapshot: "Code Snapshot",
  security_report: "Security Report",
  deploy_report: "Deploy Report",
};

export const APPROVAL_STAGE_LABELS: Record<ApprovalStage, string> = {
  prd: "PRD Review",
  design: "Design Review",
  tech_plan: "Legacy Tech Plan Review",
  deploy: "Deploy Approval",
};
