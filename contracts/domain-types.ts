export type DesignProvider = "stitch_mcp" | "internal_spec" | "manual_upload";

export type ModelProfile = "primary" | "customtools" | "fallback";

export type ProjectStatus =
  | "ideation"
  | "prd_draft"
  | "prd_approved"
  | "design_draft"
  | "design_approved"
  | "tech_plan_draft"
  | "tech_plan_approved"
  | "codegen"
  | "security_gate"
  | "deploy_ready"
  | "deploying"
  | "deployed"
  | "failed";

export type ApprovalStage = "prd" | "design" | "tech_plan" | "deploy";
export type StitchAuthMethod = "api_key" | "oauth_access_token";

export type ArtifactType =
  | "prd"
  | "design_spec"
  | "tech_plan"
  | "code_snapshot"
  | "security_report"
  | "deploy_report";

export interface Project {
  id: string;
  ownerUserId: string;
  initialPrompt: string;
  status: ProjectStatus;
  githubRepoUrl?: string;
  liveDeploymentUrl?: string;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectRun {
  id: string;
  projectId: string;
  status: ProjectStatus;
  currentNode: string;
  idempotencyKey?: string;
  lastErrorCode?: string;
  lastErrorMessage?: string;
  createdAt: string;
  updatedAt: string;
}

export interface RunTimelineEvent {
  eventType: string;
  fromNode?: string;
  toNode: string;
  outcome?: string;
  createdAt: string;
}

export interface ProjectRunDetail extends ProjectRun {
  timeline: RunTimelineEvent[];
}

export interface ProjectRunSummary {
  id: string;
  status: ProjectStatus;
  currentNode: string;
  updatedAt: string;
}

export interface ProjectListItem extends Project {
  latestRun?: ProjectRunSummary;
}

export interface ProjectArtifact {
  id: string;
  projectId: string;
  runId: string;
  artifactType: ArtifactType;
  version: number;
  content: Record<string, unknown>;
  modelProfile?: ModelProfile;
  createdAt: string;
}

export interface ApprovalEvent {
  id: string;
  projectId: string;
  runId: string;
  stage: ApprovalStage;
  decision: "approved" | "rejected";
  notes?: string;
  createdBy: string;
  createdAt: string;
}

export interface StitchAuthPayload {
  authMethod: StitchAuthMethod;
  apiKey?: string;
  oauthToken?: string;
  googUserProject?: string;
}

export interface DesignTool {
  name: string;
  params: string[];
  description: string;
}

export interface GenerateDesignRequest {
  provider: DesignProvider;
  modelProfile: ModelProfile;
  promptConstraints: Record<string, unknown>;
  stitchAuth?: StitchAuthPayload;
}

export interface DesignFeedbackRequest {
  targetScreenId?: string;
  targetComponentId?: string;
  feedbackText: string;
  stitchAuth?: StitchAuthPayload;
}

export interface ApprovalRequest {
  stage: ApprovalStage;
  decision: "approved" | "rejected";
  notes?: string;
  artifactId?: string;
}

export interface LlmRoutingPolicy {
  planningReasoning: "gemini-2.5-pro";
  toolHeavyOrchestration: "gemini-2.5-pro";
  fallback: "gemini-2.5-pro";
}

export const DEFAULT_LLM_ROUTING_POLICY: LlmRoutingPolicy = {
  planningReasoning: "gemini-2.5-pro",
  toolHeavyOrchestration: "gemini-2.5-pro",
  fallback: "gemini-2.5-pro",
};
