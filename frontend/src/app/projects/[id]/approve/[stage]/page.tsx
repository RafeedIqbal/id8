"use client";

import { use, useMemo, useState } from "react";
import { useArtifacts, useSubmitDesignFeedback } from "@/lib/hooks";
import { getStitchAuthRequiredDetail } from "@/lib/api";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { ApprovalDecisionPanel } from "@/components/approval-decision-panel";
import { APPROVAL_STAGE_LABELS, ARTIFACT_LABELS } from "@/lib/constants";
import { DesignToolsPanel } from "@/components/design-tools-panel";
import { StitchAuthPanel } from "@/components/stitch-auth-panel";
import { formatDateTime } from "@/lib/utils";
import type { ApprovalStage, ArtifactType, ProjectArtifact, StitchAuthPayload } from "@/types/domain";

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

function extractDesignScreens(artifact?: ProjectArtifact): DesignScreen[] {
  if (!artifact || artifact.artifactType !== "design_spec") return [];
  const rawScreens = artifact.content?.screens;
  if (!Array.isArray(rawScreens)) return [];

  const screens: DesignScreen[] = [];
  for (const screen of rawScreens) {
    if (!screen || typeof screen !== "object") continue;
    const record = screen as Record<string, unknown>;
    const screenId = typeof record.id === "string" ? record.id : "";
    const screenName = typeof record.name === "string" ? record.name : screenId || "Screen";
    const rawComponents = Array.isArray(record.components) ? record.components : [];

    const components: Array<{ id: string; name: string }> = [];
    for (const comp of rawComponents) {
      if (!comp || typeof comp !== "object") continue;
      const compRecord = comp as Record<string, unknown>;
      const compId = typeof compRecord.id === "string" ? compRecord.id : "";
      const compName = typeof compRecord.name === "string" ? compRecord.name : compId || "Component";
      if (compId) components.push({ id: compId, name: compName });
    }

    if (screenId) {
      screens.push({
        id: screenId,
        name: screenName,
        components,
      });
    }
  }
  return screens;
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
  const [submitted, setSubmitted] = useState(false);
  const [stitchAuth, setStitchAuth] = useState<StitchAuthPayload | undefined>(undefined);

  const screens = useMemo(() => extractDesignScreens(artifact), [artifact]);
  const selectedScreen = screens.find((screen) => screen.id === selectedScreenId);
  const components = selectedScreen?.components ?? [];

  const stitchAuthDetail = getStitchAuthRequiredDetail(feedback.error);
  const errorText = feedback.isError ? (feedback.error as Error).message : "";
  const needsStitchAuth =
    Boolean(stitchAuthDetail) ||
    errorText.toLowerCase().includes("stitch_auth_required") ||
    errorText.toLowerCase().includes("stitch mcp credentials");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!feedbackText.trim()) return;
    await feedback.mutateAsync({
      feedbackText: feedbackText.trim(),
      targetScreenId: selectedScreenId || undefined,
      targetComponentId: selectedComponentId || undefined,
      stitchAuth,
    });
    setSubmitted(true);
    setFeedbackText("");
    setSelectedComponentId("");
  }

  return (
    <div className="glass p-6 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-text-0">Request Changes</h3>
        <p className="text-xs text-text-2 mt-1">
          Regenerate design with targeted feedback before approval.
        </p>
      </div>

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
          Feedback submitted. A new design artifact version was generated.
        </div>
      )}

      {feedback.isError && (
        <div className="text-xs text-error bg-error-bg border border-error-dim rounded-lg p-2.5">
          {stitchAuthDetail?.message ?? errorText}
        </div>
      )}

      {needsStitchAuth && (
        <div className="space-y-3">
          {stitchAuthDetail?.instructions && stitchAuthDetail.instructions.length > 0 && (
            <div className="text-xs text-text-2 bg-surface-2 border border-border-1 rounded-lg p-3">
              <div className="font-medium text-text-1 mb-1.5">Setup Steps</div>
              <ul className="list-disc pl-4 space-y-1">
                {stitchAuthDetail.instructions.map((instruction) => (
                  <li key={instruction}>{instruction}</li>
                ))}
              </ul>
              {stitchAuthDetail.fallback_note && (
                <p className="mt-2 text-text-3">{stitchAuthDetail.fallback_note}</p>
              )}
            </div>
          )}
          <StitchAuthPanel
            onAuth={(payload) => {
              setStitchAuth(payload);
            }}
          />
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

  // Get latest version of the relevant artifact
  const relevantArtifacts = (artifactsData?.items ?? [])
    .filter((a) => a.artifactType === artifactType)
    .sort((a, b) => b.version - a.version);
  const artifact = relevantArtifacts[0];

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
            <ApprovalDecisionPanel projectId={id} stage={approvalStage} />

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
