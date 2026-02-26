"use client";

import { use, useMemo, useState } from "react";
import { useArtifacts, useSubmitDesignFeedback } from "@/lib/hooks";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { ApprovalDecisionPanel } from "@/components/approval-decision-panel";
import { APPROVAL_STAGE_LABELS, ARTIFACT_LABELS } from "@/lib/constants";
import { DesignToolsPanel } from "@/components/design-tools-panel";
import { formatDateTime } from "@/lib/utils";
import type { ApprovalStage, ArtifactType, ProjectArtifact } from "@/types/domain";

import { PrdViewer } from "@/components/artifact-viewers/prd-viewer";
import { DesignViewer } from "@/components/artifact-viewers/design-viewer";
import { TechPlanViewer } from "@/components/artifact-viewers/tech-plan-viewer";
import { DeployViewer } from "@/components/artifact-viewers/deploy-viewer";
import { SecurityViewer } from "@/components/artifact-viewers/security-viewer";
import { CodeViewer } from "@/components/artifact-viewers/code-viewer";

const STAGE_TO_ARTIFACT: Record<ApprovalStage, ArtifactType> = {
  prd: "prd",
  design: "design_spec",
  tech_plan: "tech_plan",
  // Deploy approval happens before DeployProduction generates deploy_report.
  deploy: "code_snapshot",
};

type DesignScreen = {
  id: string;
  name: string;
  components: Array<{ id: string; name: string }>;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function extractDesignScreens(artifact?: ProjectArtifact): DesignScreen[] {
  if (!artifact || artifact.artifactType !== "design_spec") return [];
  const rawScreens = artifact.content?.screens;
  if (!Array.isArray(rawScreens)) return [];

  const screens: DesignScreen[] = [];
  const seenScreenIds = new Set<string>();
  for (const screen of rawScreens) {
    if (!screen || typeof screen !== "object") continue;
    const record = screen as Record<string, unknown>;
    const screenId = typeof record.id === "string" ? record.id : "";
    const screenName = typeof record.name === "string" ? record.name : screenId || "Screen";
    const rawComponents = Array.isArray(record.components) ? record.components : [];

    const components: Array<{ id: string; name: string }> = [];
    const seenComponentIds = new Set<string>();
    for (const comp of rawComponents) {
      if (!comp || typeof comp !== "object") continue;
      const compRecord = comp as Record<string, unknown>;
      const compId = typeof compRecord.id === "string" ? compRecord.id : "";
      const compName = typeof compRecord.name === "string" ? compRecord.name : compId || "Component";
      if (compId && !seenComponentIds.has(compId)) {
        seenComponentIds.add(compId);
        components.push({ id: compId, name: compName });
      }
    }

    if (screenId && !seenScreenIds.has(screenId)) {
      seenScreenIds.add(screenId);
      screens.push({
        id: screenId,
        name: screenName,
        components,
      });
    }
  }
  return screens;
}

function extractDesignMetadata(artifact?: ProjectArtifact): Record<string, unknown> {
  if (!artifact || artifact.artifactType !== "design_spec") return {};
  const content = asRecord(artifact.content);
  if (!content) return {};
  const meta = asRecord(content.__design_metadata) ?? asRecord(content.metadata) ?? asRecord(content.provider_metadata);
  return meta ?? {};
}

function extractStitchProjectUrl(artifact?: ProjectArtifact): string | null {
  const meta = extractDesignMetadata(artifact);
  const direct = meta.stitch_project_url ?? meta.stitch_url ?? meta.project_url;
  if (typeof direct === "string" && direct.trim()) return direct.trim();
  const projectId = meta.stitch_project_id;
  if (typeof projectId === "string" && projectId.trim()) {
    return `https://stitch.withgoogle.com/project/${encodeURIComponent(projectId.trim())}`;
  }
  return null;
}

function extractStitchSuggestions(artifact?: ProjectArtifact): string[] {
  const meta = extractDesignMetadata(artifact);
  const fromMeta = Array.isArray(meta.stitch_suggestions)
    ? meta.stitch_suggestions.filter((x): x is string => typeof x === "string" && x.trim().length > 0)
    : [];
  if (fromMeta.length > 0) return fromMeta;

  // Backward-compatible fallback in case provider metadata is nested.
  const providerMeta = asRecord(meta.provider_metadata);
  const nested = providerMeta?.stitch_suggestions;
  if (!Array.isArray(nested)) return [];
  return nested.filter((x): x is string => typeof x === "string" && x.trim().length > 0);
}

function isTransientStitchError(raw: string): boolean {
  const text = raw.toLowerCase();
  return (
    text.includes("timed out") ||
    text.includes("timeout") ||
    text.includes("connection failed") ||
    text.includes("connection reset") ||
    text.includes("connection closed") ||
    text.includes("service unavailable") ||
    text.includes("http 503")
  );
}

function DesignFeedbackPanel({
  projectId,
  artifact,
}: {
  projectId: string;
  artifact?: ProjectArtifact;
}) {
  const feedback = useSubmitDesignFeedback(projectId);
  const [selectedScreenId, setSelectedScreenId] = useState<string>("");
  const [selectedComponentId, setSelectedComponentId] = useState<string>("");
  const [feedbackText, setFeedbackText] = useState("");
  const [lastSubmittedText, setLastSubmittedText] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const screens = useMemo(() => extractDesignScreens(artifact), [artifact]);
  const stitchSuggestions = useMemo(() => extractStitchSuggestions(artifact), [artifact]);
  const stitchProjectUrl = useMemo(() => extractStitchProjectUrl(artifact), [artifact]);
  const selectedScreen = screens.find((screen) => screen.id === selectedScreenId);
  const components = selectedScreen?.components ?? [];

  const errorText = feedback.isError ? (feedback.error as Error).message : "";
  const transientStitchError = isTransientStitchError(errorText);
  const needsStitchConfig =
    errorText.toLowerCase().includes("stitch") ||
    errorText.toLowerCase().includes("credentials");

  async function submitFeedback(text: string) {
    const normalized = text.trim();
    if (!normalized) return;
    await feedback.mutateAsync({
      feedbackText: normalized,
      targetScreenId: selectedScreenId || undefined,
      targetComponentId: selectedComponentId || undefined,
    });
    setSubmitted(true);
    setLastSubmittedText(normalized);
    setFeedbackText("");
    setSelectedComponentId("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await submitFeedback(feedbackText);
  }

  async function handleSuggestionClick(suggestion: string) {
    setFeedbackText(suggestion);
    await submitFeedback(suggestion);
  }

  return (
    <div className="glass p-6 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-text-0">Request Changes</h3>
        <p className="text-xs text-text-2 mt-1">
          Regenerate design with targeted feedback before approval.
        </p>
      </div>

      <div className="text-xs text-text-2 bg-surface-2 border border-border-1 rounded-lg p-3">
        Stitch MCP generations can take a few minutes. Submit once, then wait for the updated artifact.
        {" "}
        Avoid repeated retries while a request is in progress.
      </div>

      {stitchProjectUrl && (
        <a
          href={stitchProjectUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
        >
          Open current design in Stitch
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M7 17L17 7M9 7h8v8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </a>
      )}

      {stitchSuggestions.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-medium text-text-1">Stitch Suggestions</div>
          <div className="space-y-2">
            {stitchSuggestions.map((suggestion, idx) => (
              <button
                key={`${idx}-${suggestion}`}
                type="button"
                onClick={() => handleSuggestionClick(suggestion)}
                disabled={feedback.isPending}
                className="w-full text-left text-xs text-text-2 bg-surface-2 border border-border-1 rounded-lg px-3 py-2 hover:border-accent/40 hover:text-text-1 disabled:opacity-60"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-text-1 mb-1.5">Target Screen (optional)</label>
          <select
            value={selectedScreenId}
            onChange={(e) => {
              setSelectedScreenId(e.target.value);
              setSelectedComponentId("");
            }}
          >
            <option value="">All screens</option>
            {screens.map((screen) => (
              <option key={screen.id} value={screen.id}>
                {screen.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-text-1 mb-1.5">Target Component (optional)</label>
          <select
            value={selectedComponentId}
            onChange={(e) => setSelectedComponentId(e.target.value)}
            disabled={!selectedScreenId || components.length === 0}
          >
            <option value="">All components</option>
            {components.map((component) => (
              <option key={component.id} value={component.id}>
                {component.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-text-1 mb-1.5">Feedback</label>
          <textarea
            rows={4}
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            placeholder="Describe exactly what to change."
          />
        </div>

        <button
          type="submit"
          disabled={!feedbackText.trim() || feedback.isPending}
          className="btn btn-ghost w-full"
        >
          {feedback.isPending ? "Submitting…" : "Request Changes"}
        </button>
      </form>

      {submitted && !feedback.isError && (
        <div className="text-xs text-success bg-success-bg border border-success-dim rounded-lg p-2.5">
          Change request submitted:
          {" "}
          <span className="font-mono-display text-success">
            {lastSubmittedText || "feedback"}
          </span>
          . The refreshed design artifact will appear once Stitch completes generation.
        </div>
      )}

      {feedback.isError && (
        <div className="text-xs text-error bg-error-bg border border-error-dim rounded-lg p-2.5">
          {errorText}
        </div>
      )}

      {needsStitchConfig && (
        <div className="space-y-3">
          <div className="text-xs text-text-2 bg-surface-2 border border-border-1 rounded-lg p-3">
            <div className="font-medium text-text-1 mb-1.5">Server Stitch setup</div>
            <p>
              Stitch credentials are env-only. Set <span className="font-mono-display">STITCH_MCP_API_KEY</span>
              or OAuth env vars on backend, then restart API/worker.
            </p>
          </div>
        </div>
      )}

      {transientStitchError && (
        <div className="text-xs text-warning bg-warning-bg border border-warning-dim rounded-lg p-3">
          Stitch may still complete this generation even if the connection dropped. Check the Stitch project, wait a few minutes, then refresh artifacts before resubmitting.
        </div>
      )}
    </div>
  );
}

export default function ApprovalPage({
  params,
}: {
  params: Promise<{ id: string; stage: string }>;
}) {
  const { id, stage } = use(params);
  const approvalStage = stage as ApprovalStage;
  const artifactType = STAGE_TO_ARTIFACT[approvalStage];
  const stageLabel = APPROVAL_STAGE_LABELS[approvalStage] ?? stage;

  const { data: artifactsData, isLoading } = useArtifacts(id);

  // Get selectable versions for the relevant artifact type.
  const relevantArtifacts = (artifactsData?.items ?? [])
    .filter((a) => a.artifactType === artifactType)
    .sort((a, b) => b.version - a.version);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string>("");
  const artifact =
    relevantArtifacts.find((candidate) => candidate.id === selectedArtifactId) ??
    relevantArtifacts[0];

  // If deploy approval, also show security report
  const securityArtifact = approvalStage === "deploy"
    ? (artifactsData?.items ?? [])
        .filter((a) => a.artifactType === "security_report")
        .sort((a, b) => b.version - a.version)[0]
    : null;

  return (
    <div className="animate-fade-in">
      <Breadcrumbs
        items={[
          { label: "Projects", href: "/" },
          { label: id, href: `/projects/${id}` },
          { label: stageLabel },
        ]}
      />

      <h1 className="text-xl font-semibold text-text-0 mb-6">{stageLabel}</h1>

      {isLoading ? (
        <div className="glass p-6 space-y-4">
          <div className="skeleton h-5 w-48" />
          <div className="skeleton h-4 w-full" />
          <div className="skeleton h-4 w-3/4" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-6">
          {/* Left: Artifact preview */}
          <div className="space-y-6">
            {artifact ? (
              <div className="glass p-6">
                <div className="flex items-center justify-between mb-4 pb-3 border-b border-border-0">
                  <div>
                    <h2 className="text-sm font-semibold text-text-0">
                      {ARTIFACT_LABELS[artifactType]}
                    </h2>
                    <div className="text-xs text-text-3 font-mono-display mt-0.5">
                      v{artifact.version} &middot; {formatDateTime(artifact.createdAt)}
                    </div>
                  </div>
                  {relevantArtifacts.length > 1 && (
                    <div className="min-w-[210px]">
                      <label className="block text-[10px] font-mono-display text-text-3 tracking-wider uppercase mb-1">
                        Version
                      </label>
                      <select
                        value={artifact.id}
                        onChange={(e) => setSelectedArtifactId(e.target.value)}
                      >
                        {relevantArtifacts.map((candidate) => (
                          <option key={candidate.id} value={candidate.id}>
                            v{candidate.version} · {formatDateTime(candidate.createdAt)}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>

                {artifactType === "prd" && <PrdViewer artifact={artifact} />}
                {artifactType === "design_spec" && <DesignViewer artifact={artifact} />}
                {artifactType === "tech_plan" && <TechPlanViewer artifact={artifact} />}
                {artifactType === "code_snapshot" && <CodeViewer artifact={artifact} />}
                {artifactType === "deploy_report" && <DeployViewer artifact={artifact} />}
              </div>
            ) : (
              <div className="glass p-8 text-center">
                <p className="text-sm text-text-2">
                  No {ARTIFACT_LABELS[artifactType]?.toLowerCase() ?? "artifact"} found to review.
                </p>
              </div>
            )}

            {/* Security report before deploy */}
            {securityArtifact && (
              <div className="glass p-6">
                <h2 className="text-sm font-semibold text-text-0 mb-4 pb-3 border-b border-border-0">
                  Security Report
                  <span className="text-xs text-text-3 font-mono-display ml-2">
                    v{securityArtifact.version}
                  </span>
                </h2>
                <SecurityViewer artifact={securityArtifact} />
              </div>
            )}
          </div>

          {/* Right: Decision panel + extras */}
          <div className="space-y-4">
            <ApprovalDecisionPanel
              projectId={id}
              stage={approvalStage}
              artifactId={artifact?.id}
            />

            {/* Show design tools panel on design approval */}
            {approvalStage === "design" && (
              <>
                <DesignFeedbackPanel projectId={id} artifact={artifact} />
                <DesignToolsPanel />
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
