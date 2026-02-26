"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useProject, useLatestRun, useArtifacts, useCreateRun, useGenerateDesign } from "@/lib/hooks";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { ProjectStatusBadge } from "@/components/project-status-badge";
import { NodeTimeline } from "@/components/node-timeline";
import { ArtifactCard } from "@/components/artifact-card";
import { EmptyState } from "@/components/empty-state";
import { StitchAuthPanel } from "@/components/stitch-auth-panel";
import { formatDateTime, truncate } from "@/lib/utils";
import type { ArtifactType, ApprovalStage, ProjectStatus, StitchAuthPayload } from "@/types/domain";

const ACTIVE_STATUSES: ProjectStatus[] = [
  "prd_draft", "design_draft", "tech_plan_draft", "codegen",
  "security_gate", "deploying",
];

const WAITING_STAGES: Record<string, ApprovalStage> = {
  WaitPRDApproval: "prd",
  WaitDesignApproval: "design",
  WaitTechPlanApproval: "tech_plan",
  WaitDeployApproval: "deploy",
};

const TERMINAL_NODES = new Set(["EndSuccess", "EndFailed"]);

function resolveResumeNode(
  currentNode: string | undefined,
  timeline: { toNode: string; fromNode?: string }[] | undefined
): string | undefined {
  if (!currentNode) return undefined;
  if (!TERMINAL_NODES.has(currentNode)) return currentNode;

  const events = timeline ?? [];
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i];
    if (event.fromNode && !TERMINAL_NODES.has(event.fromNode)) {
      return event.fromNode;
    }
    if (event.toNode && !TERMINAL_NODES.has(event.toNode)) {
      return event.toNode;
    }
  }

  return "IngestPrompt";
}

const COST_PER_1K_TOKENS: Record<string, number> = {
  primary: 0.01,
  customtools: 0.015,
  fallback: 0.005,
};

function buildUsageSummary(items: Array<{ content: Record<string, unknown>; modelProfile?: string }>) {
  let promptTokens = 0;
  let completionTokens = 0;
  let estimatedCost = 0;
  const profiles = new Map<string, number>();

  for (const artifact of items) {
    const meta = artifact.content?.__llm_metadata;
    if (!meta || typeof meta !== "object") continue;
    const record = meta as Record<string, unknown>;
    const prompt = Number(record.prompt_tokens ?? 0);
    const completion = Number(record.completion_tokens ?? 0);
    const profile = String(record.model_profile ?? artifact.modelProfile ?? "unknown");
    if (!Number.isFinite(prompt) || !Number.isFinite(completion)) continue;

    promptTokens += prompt;
    completionTokens += completion;
    profiles.set(profile, (profiles.get(profile) ?? 0) + 1);
    const rate = COST_PER_1K_TOKENS[profile] ?? 0;
    estimatedCost += ((prompt + completion) / 1000) * rate;
  }

  return {
    promptTokens,
    completionTokens,
    totalTokens: promptTokens + completionTokens,
    estimatedCost,
    profiles: Array.from(profiles.entries()),
  };
}

function ProjectSkeleton() {
  return (
    <div className="space-y-6">
      <div className="skeleton h-6 w-64 mb-2" />
      <div className="skeleton h-4 w-96" />
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_3fr] gap-6 mt-8">
        <div className="glass p-5 space-y-4">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="skeleton h-4 w-full" />
          ))}
        </div>
        <div className="glass p-5 space-y-4">
          <div className="skeleton h-4 w-40" />
          <div className="grid grid-cols-2 gap-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="skeleton h-24 w-full rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ProjectDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [stitchAuth, setStitchAuth] = useState<StitchAuthPayload | undefined>(undefined);
  const [stitchActionState, setStitchActionState] = useState<"idle" | "success">("idle");
  const { data: project, isLoading: loadingProject, error: projectError } = useProject(id, {
    refetchInterval: 5000,
  });
  const isActive = project && ACTIVE_STATUSES.includes(project.status);
  const { data: runDetail, isLoading: loadingRun } = useLatestRun(id, {
    refetchInterval: isActive ? 5000 : undefined,
  });
  const { data: artifactsData } = useArtifacts(id, {
    refetchInterval: isActive ? 5000 : undefined,
  });
  const createRun = useCreateRun(id);
  const generateDesign = useGenerateDesign(id);

  const artifacts = artifactsData?.items ?? [];
  const usageSummary = buildUsageSummary(artifacts);
  const latestByType = new Map<ArtifactType, (typeof artifacts)[number]>();
  for (const a of artifacts) {
    const existing = latestByType.get(a.artifactType);
    if (!existing || a.version > existing.version) {
      latestByType.set(a.artifactType, a);
    }
  }

  // Determine if we're at a waiting node (approval gate)
  const currentNode = runDetail?.currentNode;
  const waitingStage = currentNode ? WAITING_STAGES[currentNode] : undefined;
  const resumeNode = resolveResumeNode(runDetail?.currentNode, runDetail?.timeline);
  const stitchAuthError =
    runDetail?.lastErrorMessage?.toLowerCase().includes("stitch") ||
    runDetail?.lastErrorMessage?.toLowerCase().includes("credentials");

  async function handleConnectAndResumeDesign() {
    if (!stitchAuth) return;
    setStitchActionState("idle");
    await generateDesign.mutateAsync({
      provider: "stitch_mcp",
      modelProfile: "customtools",
      stitchAuth,
    });
    await createRun.mutateAsync({ resumeFromNode: "GenerateDesign" });
    setStitchActionState("success");
  }

  if (loadingProject) return <ProjectSkeleton />;
  if (projectError) {
    return (
      <div className="text-sm text-error bg-error-bg border border-error-dim rounded-lg p-4">
        {(projectError as Error).message}
      </div>
    );
  }
  if (!project) return null;

  return (
    <div className="animate-fade-in">
      <Breadcrumbs
        items={[
          { label: "Projects", href: "/" },
          { label: project.id },
        ]}
      />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 mb-8">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-2">
            <h1 className="text-xl font-semibold text-text-0 truncate">
              {truncate(project.initialPrompt, 80)}
            </h1>
            <ProjectStatusBadge status={project.status} />
          </div>
          <div className="flex items-center gap-4 text-xs text-text-3 font-mono-display">
            <span>Created {formatDateTime(project.createdAt)}</span>
            {project.githubRepoUrl && (
              <a
                href={project.githubRepoUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline inline-flex items-center gap-1"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
                </svg>
                Repo
              </a>
            )}
            {project.liveDeploymentUrl && (
              <a
                href={project.liveDeploymentUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-success hover:underline inline-flex items-center gap-1"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Live
              </a>
            )}
          </div>
        </div>
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_3fr] gap-6">
        {/* Left: Timeline + Controls */}
        <div className="space-y-4">
          {/* Run controls */}
          <div className="glass p-5">
            <h2 className="text-xs font-mono-display text-text-2 tracking-widest uppercase mb-4">
              Run Controls
            </h2>
            <div className="flex flex-wrap gap-2">
              {project.status === "ideation" && (
                <button
                  onClick={() => createRun.mutate({})}
                  disabled={createRun.isPending}
                  className="btn btn-primary w-full"
                >
                  {createRun.isPending ? "Starting\u2026" : "Start Run"}
                </button>
              )}
              {project.status === "failed" && (
                <button
                  onClick={() => createRun.mutate({ resumeFromNode: resumeNode })}
                  disabled={createRun.isPending}
                  className="btn btn-primary w-full"
                >
                  {createRun.isPending ? "Resuming\u2026" : "Resume from Failure"}
                </button>
              )}
              {waitingStage && (
                <Link
                  href={`/projects/${id}/approve/${waitingStage}`}
                  className="btn btn-primary w-full text-center"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
                    <circle cx="12" cy="12" r="10" />
                  </svg>
                  Review &amp; Approve
                </Link>
              )}
              {!waitingStage && project.status !== "ideation" && project.status !== "failed" && project.status !== "deployed" && (
                <div className="w-full text-center text-xs text-text-3 py-2 font-mono-display">
                  Pipeline running\u2026
                </div>
              )}
              {project.status === "deployed" && (
                <div className="w-full text-center text-sm text-success py-2">
                  Deployment complete
                </div>
              )}
            </div>
            {createRun.isError && (
              <div className="text-xs text-error mt-2">
                {(createRun.error as Error).message}
              </div>
            )}
          </div>

          {/* Timeline */}
          <div className="glass p-5">
            <h2 className="text-xs font-mono-display text-text-2 tracking-widest uppercase mb-4">
              Pipeline Timeline
            </h2>
            {loadingRun ? (
              <div className="space-y-3">
                {[...Array(6)].map((_, i) => (
                  <div key={i} className="skeleton h-4 w-full" />
                ))}
              </div>
            ) : runDetail ? (
              <NodeTimeline
                currentNode={runDetail.currentNode}
                timeline={runDetail.timeline}
                status={runDetail.status}
              />
            ) : (
              <p className="text-sm text-text-3 text-center py-4">
                No runs yet. Start a run to see the timeline.
              </p>
            )}
          </div>

          {/* Error display */}
          {runDetail?.lastErrorMessage && (
            <div className="glass p-5 glow-error">
              <h2 className="text-xs font-mono-display text-error tracking-widest uppercase mb-2">
                Error
              </h2>
              {runDetail.lastErrorCode && (
                <div className="font-mono-display text-xs text-text-3 mb-1">
                  Code: {runDetail.lastErrorCode}
                </div>
              )}
              <p className="text-sm text-error leading-relaxed">
                {runDetail.lastErrorMessage}
              </p>
            </div>
          )}

          {project.status === "failed" && stitchAuthError && (
            <div className="glass p-5 space-y-3">
              <h2 className="text-xs font-mono-display text-warning tracking-widest uppercase">
                Stitch Reconnect
              </h2>
              <p className="text-sm text-text-2">
                This run failed during design generation due to missing Stitch credentials.
                Connect Stitch and resume from <span className="font-mono-display">GenerateDesign</span>.
              </p>
              <StitchAuthPanel onAuth={(payload) => setStitchAuth(payload)} />
              <button
                onClick={handleConnectAndResumeDesign}
                disabled={!stitchAuth || generateDesign.isPending || createRun.isPending}
                className="btn btn-primary w-full"
              >
                {generateDesign.isPending || createRun.isPending
                  ? "Connecting…"
                  : "Connect Stitch & Resume Design"}
              </button>
              {(generateDesign.isError || createRun.isError) && (
                <div className="text-xs text-error bg-error-bg border border-error-dim rounded-lg p-2.5">
                  {((generateDesign.error ?? createRun.error) as Error)?.message}
                </div>
              )}
              {stitchActionState === "success" && (
                <div className="text-xs text-success bg-success-bg border border-success-dim rounded-lg p-2.5">
                  Stitch credentials saved. Resuming design generation.
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: Artifacts */}
        <div className="space-y-4">
          <div className="glass p-5">
            <h2 className="text-xs font-mono-display text-text-2 tracking-widest uppercase mb-4">
              Model Usage
            </h2>
            <div className="grid grid-cols-2 gap-3 mb-3">
              <div className="glass-raised p-3">
                <div className="text-[10px] font-mono-display text-text-3 uppercase mb-1">Total Tokens</div>
                <div className="text-sm text-text-0 font-semibold">{usageSummary.totalTokens.toLocaleString()}</div>
              </div>
              <div className="glass-raised p-3">
                <div className="text-[10px] font-mono-display text-text-3 uppercase mb-1">Estimated Cost</div>
                <div className="text-sm text-text-0 font-semibold">${usageSummary.estimatedCost.toFixed(4)}</div>
              </div>
            </div>
            <div className="space-y-1">
              {usageSummary.profiles.length > 0 ? (
                usageSummary.profiles.map(([profile, count]) => (
                  <div key={profile} className="flex items-center justify-between text-xs">
                    <span className="font-mono-display text-text-2">{profile}</span>
                    <span className="text-text-3">{count} artifact{count !== 1 ? "s" : ""}</span>
                  </div>
                ))
              ) : (
                <div className="text-xs text-text-3">No model telemetry yet.</div>
              )}
            </div>
          </div>

          <div className="glass p-5">
            <h2 className="text-xs font-mono-display text-text-2 tracking-widest uppercase mb-4">
              Artifacts
            </h2>
            {latestByType.size > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {Array.from(latestByType.entries()).map(([type, artifact]) => (
                  <ArtifactCard
                    key={type}
                    type={type}
                    version={artifact.version}
                    createdAt={artifact.createdAt}
                    modelProfile={artifact.modelProfile}
                    projectId={id}
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                title="No artifacts yet"
                description="Artifacts will appear here as the pipeline progresses."
              />
            )}
          </div>

          {/* Project info */}
          <div className="glass p-5">
            <h2 className="text-xs font-mono-display text-text-2 tracking-widest uppercase mb-4">
              Project Details
            </h2>
            <div className="space-y-3">
              <div>
                <div className="text-[10px] font-mono-display text-text-3 tracking-widest uppercase mb-1">
                  Initial Prompt
                </div>
                <p className="text-sm text-text-1 leading-relaxed whitespace-pre-wrap">
                  {project.initialPrompt}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="text-[10px] font-mono-display text-text-3 tracking-widest uppercase mb-1">
                    Project ID
                  </div>
                  <div className="font-mono-display text-xs text-text-2 break-all">{project.id}</div>
                </div>
                <div>
                  <div className="text-[10px] font-mono-display text-text-3 tracking-widest uppercase mb-1">
                    Last Updated
                  </div>
                  <div className="font-mono-display text-xs text-text-2">
                    {formatDateTime(project.updatedAt)}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
