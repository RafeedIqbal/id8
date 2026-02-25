import type {
  ApprovalEvent,
  ApprovalStage,
  ArtifactType,
  DesignProvider,
  ModelProfile,
  Project,
  ProjectArtifact,
  ProjectRun,
  ProjectStatus,
} from "@/types/domain";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type ProjectWire = {
  id: string;
  owner_user_id: string;
  initial_prompt: string;
  status: ProjectStatus;
  github_repo_url?: string;
  live_deployment_url?: string;
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

type DeploymentRecord = {
  id: string;
  project_id: string;
  environment: string;
  status: string;
  url?: string;
};

function toProject(data: ProjectWire): Project {
  return {
    id: data.id,
    ownerUserId: data.owner_user_id,
    initialPrompt: data.initial_prompt,
    status: data.status,
    githubRepoUrl: data.github_repo_url,
    liveDeploymentUrl: data.live_deployment_url,
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
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `API error ${res.status}`);
  }
  return res.json();
}

// Projects
export async function createProject(
  initial_prompt: string,
  constraints?: Record<string, unknown>
): Promise<Project> {
  const data = await request<ProjectWire>("/v1/projects", {
    method: "POST",
    body: JSON.stringify({ initial_prompt, constraints }),
  });
  return toProject(data);
}

export async function getProject(id: string): Promise<Project> {
  const data = await request<ProjectWire>(`/v1/projects/${id}`);
  return toProject(data);
}

// Runs
export async function createRun(
  projectId: string,
  opts?: { resume_from_node?: string; model_profile?: ModelProfile; idempotency_key?: string }
): Promise<ProjectRun> {
  const headers: Record<string, string> = {};
  if (opts?.idempotency_key) headers["Idempotency-Key"] = opts.idempotency_key;
  const data = await request<ProjectRunWire>(`/v1/projects/${projectId}/runs`, {
    method: "POST",
    headers,
    body: JSON.stringify({ resume_from_node: opts?.resume_from_node, model_profile: opts?.model_profile }),
  });
  return toProjectRun(data);
}

// Design
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
      body: JSON.stringify({ provider, model_profile, prompt_constraints }),
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
      body: JSON.stringify({ feedback_text, target_screen_id, target_component_id }),
    }
  );
  return { artifact: toProjectArtifact(data.artifact) };
}

// Approvals
export async function submitApproval(
  projectId: string,
  stage: ApprovalStage,
  decision: "approved" | "rejected",
  notes?: string
): Promise<ApprovalEvent> {
  const data = await request<ApprovalEventWire>(`/v1/projects/${projectId}/approvals`, {
    method: "POST",
    body: JSON.stringify({ stage, decision, notes }),
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
