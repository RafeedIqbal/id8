import type {
  ApprovalEvent,
  ApprovalStage,
  ArtifactType,
  DesignTool,
  DesignProvider,
  ModelProfile,
  Project,
  ProjectListItem,
  ProjectArtifact,
  ProjectRunDetail,
  ProjectRun,
  ProjectStatus,
} from "@/types/domain";
import type { StackJson } from "@/types/stack";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type ProjectWire = {
  id: string;
  owner_user_id: string;
  title: string;
  initial_prompt: string;
  status: ProjectStatus;
  github_repo_url?: string;
  live_deployment_url?: string;
  deleted_at?: string;
  stack_json?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

type ProjectRunWire = {
  id: string;
  project_id: string;
  status: ProjectStatus;
  current_node: string;
  idempotency_key?: string;
  last_error_code?: string;
  last_error_message?: string;
  created_at: string;
  updated_at: string;
};

type RunTimelineEventWire = {
  event_type: string;
  from_node?: string;
  to_node: string;
  outcome?: string;
  created_at: string;
};

type ProjectRunDetailWire = ProjectRunWire & {
  timeline: RunTimelineEventWire[];
};

type ProjectRunSummaryWire = {
  id: string;
  status: ProjectStatus;
  current_node: string;
  updated_at: string;
};

type ProjectListItemWire = ProjectWire & {
  latest_run?: ProjectRunSummaryWire;
};

type ProjectArtifactWire = {
  id: string;
  project_id: string;
  run_id: string;
  artifact_type: ArtifactType;
  version: number;
  content: Record<string, unknown>;
  model_profile?: ModelProfile;
  created_at: string;
};

type ApprovalEventWire = {
  id: string;
  project_id: string;
  run_id: string;
  stage: ApprovalStage;
  decision: "approved" | "rejected";
  notes?: string;
  created_by: string;
  created_at: string;
};

type DesignToolWire = {
  name: string;
  params: string[];
  description: string;
};

type DesignToolsWire = {
  provider: DesignProvider;
  usable_tools: DesignToolWire[];
  stitch_auth_configured?: boolean;
};

type DeploymentRecord = {
  id: string;
  project_id: string;
  environment: string;
  status: string;
  url?: string;
};

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type StitchAuthRequiredDetail = {
  error_type?: string;
  message?: string;
  instructions?: string[];
  fallback_note?: string;
};

function extractErrorMessage(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  for (const key of ["message", "detail", "error"]) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return undefined;
}

function asStitchAuthRequiredDetail(value: unknown): StitchAuthRequiredDetail | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const errorType = typeof record.error_type === "string" ? record.error_type : "";
  const message = typeof record.message === "string" ? record.message : "";
  if (
    errorType === "stitch_auth_required" ||
    message.toLowerCase().includes("stitch")
  ) {
    return {
      error_type: errorType || undefined,
      message: message || undefined,
      instructions: Array.isArray(record.instructions)
        ? record.instructions.filter((x): x is string => typeof x === "string")
        : undefined,
      fallback_note:
        typeof record.fallback_note === "string" ? record.fallback_note : undefined,
    };
  }
  return null;
}

export function getStitchAuthRequiredDetail(error: unknown): StitchAuthRequiredDetail | null {
  if (!(error instanceof ApiError)) return null;
  return (
    asStitchAuthRequiredDetail(error.detail) ??
    asStitchAuthRequiredDetail(
      (error.detail as { detail?: unknown } | null | undefined)?.detail
    )
  );
}

function toProject(data: ProjectWire): Project {
  return {
    id: data.id,
    ownerUserId: data.owner_user_id,
    title: data.title,
    initialPrompt: data.initial_prompt,
    status: data.status,
    githubRepoUrl: data.github_repo_url,
    liveDeploymentUrl: data.live_deployment_url,
    deletedAt: data.deleted_at,
    stackJson: data.stack_json,
    createdAt: data.created_at,
    updatedAt: data.updated_at,
  };
}

function toProjectRun(data: ProjectRunWire): ProjectRun {
  return {
    id: data.id,
    projectId: data.project_id,
    status: data.status,
    currentNode: data.current_node,
    idempotencyKey: data.idempotency_key,
    lastErrorCode: data.last_error_code,
    lastErrorMessage: data.last_error_message,
    createdAt: data.created_at,
    updatedAt: data.updated_at,
  };
}

function toProjectListItem(data: ProjectListItemWire): ProjectListItem {
  const project = toProject(data);
  return {
    ...project,
    latestRun: data.latest_run
      ? {
          id: data.latest_run.id,
          status: data.latest_run.status,
          currentNode: data.latest_run.current_node,
          updatedAt: data.latest_run.updated_at,
        }
      : undefined,
  };
}

function toProjectRunDetail(data: ProjectRunDetailWire): ProjectRunDetail {
  return {
    ...toProjectRun(data),
    timeline: data.timeline.map((event) => ({
      eventType: event.event_type,
      fromNode: event.from_node,
      toNode: event.to_node,
      outcome: event.outcome,
      createdAt: event.created_at,
    })),
  };
}

function toProjectArtifact(data: ProjectArtifactWire): ProjectArtifact {
  return {
    id: data.id,
    projectId: data.project_id,
    runId: data.run_id,
    artifactType: data.artifact_type,
    version: data.version,
    content: data.content,
    modelProfile: data.model_profile,
    createdAt: data.created_at,
  };
}

function toApprovalEvent(data: ApprovalEventWire): ApprovalEvent {
  return {
    id: data.id,
    projectId: data.project_id,
    runId: data.run_id,
    stage: data.stage,
    decision: data.decision,
    notes: data.notes,
    createdBy: data.created_by,
    createdAt: data.created_at,
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as Record<string, unknown>));
    const detail = (body as Record<string, unknown>)?.detail ?? body;
    const message =
      extractErrorMessage(detail) ??
      extractErrorMessage((body as Record<string, unknown>)?.error) ??
      `API error ${res.status}`;
    throw new ApiError(res.status, message, detail);
  }
  return res.json();
}

// Projects
export async function listProjects(): Promise<{ items: ProjectListItem[] }> {
  const data = await request<{ items: ProjectListItemWire[] }>("/v1/projects");
  return { items: data.items.map(toProjectListItem) };
}

export async function createProject(
  title: string,
  initial_prompt: string,
  constraints?: Record<string, unknown>,
  stack_json?: StackJson
): Promise<Project> {
  const data = await request<ProjectWire>("/v1/projects", {
    method: "POST",
    body: JSON.stringify({ title, initial_prompt, constraints, stack_json }),
  });
  return toProject(data);
}

export async function getProject(id: string): Promise<Project> {
  const data = await request<ProjectWire>(`/v1/projects/${id}`);
  return toProject(data);
}

export async function deleteProject(id: string): Promise<{ id: string; deleted_at: string }> {
  return request(`/v1/projects/${id}`, { method: "DELETE" });
}

export async function updateProject(
  id: string,
  body: { title?: string; initial_prompt?: string; stack_json?: StackJson }
): Promise<Project> {
  const data = await request<ProjectWire>(`/v1/projects/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  return toProject(data);
}

export async function restartProject(id: string): Promise<Project> {
  const data = await request<ProjectWire>(`/v1/projects/${id}/restart`, {
    method: "POST",
  });
  return toProject(data);
}

// Runs
export async function createRun(
  projectId: string,
  opts?: {
    resume_from_node?: string;
    model_profile?: ModelProfile;
    idempotency_key?: string;
    replay_mode?: "retry_failed" | "replay_from_node";
  }
): Promise<ProjectRun> {
  const headers: Record<string, string> = {};
  if (opts?.idempotency_key) headers["Idempotency-Key"] = opts.idempotency_key;
  const data = await request<ProjectRunWire>(`/v1/projects/${projectId}/runs`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      resume_from_node: opts?.resume_from_node,
      model_profile: opts?.model_profile,
      replay_mode: opts?.replay_mode,
    }),
  });
  return toProjectRun(data);
}

export async function getLatestRun(projectId: string): Promise<ProjectRunDetail> {
  const data = await request<ProjectRunDetailWire>(`/v1/projects/${projectId}/runs/latest`);
  return toProjectRunDetail(data);
}

// Design
export async function listDesignTools(): Promise<{
  provider: DesignProvider;
  usableTools: DesignTool[];
  stitchAuthConfigured: boolean;
}> {
  const data = await request<DesignToolsWire>("/v1/design/tools");
  return {
    provider: data.provider,
    usableTools: data.usable_tools.map((tool) => ({
      name: tool.name,
      params: tool.params,
      description: tool.description,
    })),
    stitchAuthConfigured: Boolean(data.stitch_auth_configured),
  };
}

export async function generateDesign(
  projectId: string,
  provider: DesignProvider,
  model_profile: ModelProfile,
  prompt_constraints?: Record<string, unknown>,
  idempotency_key?: string
): Promise<{ artifact: ProjectArtifact }> {
  const headers: Record<string, string> = {};
  if (idempotency_key) headers["Idempotency-Key"] = idempotency_key;
  const data = await request<{ artifact: ProjectArtifactWire }>(
    `/v1/projects/${projectId}/design/generate`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        provider,
        model_profile,
        prompt_constraints,
      }),
    }
  );
  return { artifact: toProjectArtifact(data.artifact) };
}

export async function submitDesignFeedback(
  projectId: string,
  feedback_text: string,
  target_screen_id?: string,
  target_component_id?: string,
  idempotency_key?: string
): Promise<{ artifact: ProjectArtifact }> {
  const headers: Record<string, string> = {};
  if (idempotency_key) headers["Idempotency-Key"] = idempotency_key;
  const data = await request<{ artifact: ProjectArtifactWire }>(
    `/v1/projects/${projectId}/design/feedback`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        feedback_text,
        target_screen_id,
        target_component_id,
      }),
    }
  );
  return { artifact: toProjectArtifact(data.artifact) };
}

// Approvals
export async function submitApproval(
  projectId: string,
  stage: ApprovalStage,
  decision: "approved" | "rejected",
  notes?: string,
  artifact_id?: string
): Promise<ApprovalEvent> {
  const data = await request<ApprovalEventWire>(`/v1/projects/${projectId}/approvals`, {
    method: "POST",
    body: JSON.stringify({
      stage,
      decision,
      notes,
      artifact_id,
    }),
  });
  return toApprovalEvent(data);
}

// Artifacts
export async function listArtifacts(
  projectId: string
): Promise<{ items: ProjectArtifact[] }> {
  const data = await request<{ items: ProjectArtifactWire[] }>(
    `/v1/projects/${projectId}/artifacts`
  );
  return { items: data.items.map(toProjectArtifact) };
}

// Deploy
export function deployProject(
  projectId: string,
  opts?: { target?: string; artifact_id?: string; idempotency_key?: string }
) {
  const headers: Record<string, string> = {};
  if (opts?.idempotency_key) headers["Idempotency-Key"] = opts.idempotency_key;
  return request<DeploymentRecord>(`/v1/projects/${projectId}/deploy`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      target: opts?.target ?? "production",
      artifact_id: opts?.artifact_id,
    }),
  });
}
