"use client";

import { useState } from "react";
import type { ApprovalStage } from "@/types/domain";
import { APPROVAL_STAGE_LABELS } from "@/lib/constants";
import { useDesignTools, useSubmitApproval } from "@/lib/hooks";
import { useRouter } from "next/navigation";

export function ApprovalDecisionPanel({
  projectId,
  stage,
}: {
  projectId: string;
  stage: ApprovalStage;
}) {
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);
  const [notes, setNotes] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const approval = useSubmitApproval(projectId);
  const designTools = useDesignTools();
  const router = useRouter();
  const isPrdApproval = stage === "prd" && decision === "approved";
  const stitchAuthConfigured = Boolean(designTools.data?.stitchAuthConfigured);
  const requiresServerStitch =
    isPrdApproval &&
    (designTools.data?.provider ?? "stitch_mcp") === "stitch_mcp";

  const canSubmit =
    decision !== null &&
    (decision === "approved" || notes.trim().length > 0) &&
    (!requiresServerStitch || stitchAuthConfigured);

  async function handleSubmit() {
    if (!decision || !canSubmit) return;
    await approval.mutateAsync({
      stage,
      decision,
      notes: notes.trim() || undefined,
    });
    setSubmitted(true);
    setTimeout(() => router.push(`/projects/${projectId}`), 1200);
  }

  if (submitted) {
    return (
      <div className="glass p-8 text-center animate-fade-in">
        <div className="w-14 h-14 rounded-full bg-success-bg border border-success-dim mx-auto mb-4 flex items-center justify-center">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--color-success)" strokeWidth="2">
            <path d="M5 12l5 5L20 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <h3 className="text-lg font-semibold text-text-0 mb-2">
          {decision === "approved" ? "Approved" : "Rejected"}
        </h3>
        <p className="text-sm text-text-2">Redirecting to project\u2026</p>
      </div>
    );
  }

  return (
    <div className="glass p-6 space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-text-0 mb-1">
          {APPROVAL_STAGE_LABELS[stage]}
        </h2>
        <p className="text-sm text-text-2">
          Review the artifact and make your decision.
        </p>
      </div>

      {/* Decision buttons */}
      <div className="flex gap-3">
        <button
          onClick={() => setDecision("approved")}
          className={`btn flex-1 ${
            decision === "approved"
              ? "btn-success glow-success"
              : "btn-ghost"
          }`}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M5 12l5 5L20 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Approve
        </button>
        <button
          onClick={() => setDecision("rejected")}
          className={`btn flex-1 ${
            decision === "rejected"
              ? "btn-danger glow-error"
              : "btn-ghost"
          }`}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Reject
        </button>
      </div>

      {/* Notes field */}
      <div>
        <label className="block text-sm font-medium text-text-1 mb-2">
          Notes
          {decision === "rejected" && (
            <span className="text-error ml-1">*</span>
          )}
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={4}
          placeholder={
            decision === "rejected"
              ? "Describe what needs to change\u2026"
              : "Optional notes\u2026"
          }
        />
        {decision === "rejected" && notes.trim().length === 0 && (
          <p className="text-xs text-error mt-1.5">Notes are required when rejecting.</p>
        )}
      </div>

      {isPrdApproval && (
        <div className="space-y-2">
          <div className="text-xs font-medium text-text-1">
            Stitch Setup
          </div>
          {stitchAuthConfigured ? (
            <p className="text-xs text-success">
              Server-level Stitch credentials are configured.
            </p>
          ) : (
            <div className="text-xs text-warning bg-warning-bg border border-warning-dim rounded-lg p-2.5">
              Stitch is required for design generation. Set <span className="font-mono-display">STITCH_MCP_API_KEY</span> (or OAuth env vars)
              in backend <span className="font-mono-display">.env</span>, then restart API/worker.
            </div>
          )}
        </div>
      )}

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={!canSubmit || approval.isPending}
        className="btn btn-primary w-full"
      >
        {approval.isPending ? "Submitting\u2026" : "Submit Decision"}
      </button>

      {approval.isError && (
        <div className="text-sm text-error bg-error-bg border border-error-dim rounded-lg p-3">
          {(approval.error as Error).message}
        </div>
      )}
    </div>
  );
}
