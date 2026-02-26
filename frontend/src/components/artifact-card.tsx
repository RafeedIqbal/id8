"use client";

import Link from "next/link";
import type { ArtifactType, ModelProfile } from "@/types/domain";
import { ARTIFACT_LABELS } from "@/lib/constants";
import { formatRelative } from "@/lib/utils";

const ARTIFACT_ICONS: Record<ArtifactType, React.ReactNode> = {
  prd: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" />
      <path d="M14 2v6h6M8 13h8M8 17h4" strokeLinecap="round" />
    </svg>
  ),
  design_spec: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18M9 9v12" strokeLinecap="round" />
    </svg>
  ),
  tech_plan: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M4 6h16M4 12h16M4 18h8" strokeLinecap="round" />
      <circle cx="18" cy="18" r="3" />
    </svg>
  ),
  code_snapshot: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M16 18l6-6-6-6M8 6l-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  security_report: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M12 2l8 4v6c0 5.25-3.44 9.5-8 11-4.56-1.5-8-5.75-8-11V6l8-4z" />
      <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  deploy_report: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M22 12A10 10 0 1112 2" strokeLinecap="round" />
      <path d="M22 2L12 12M22 2h-6M22 2v6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
};

export function ArtifactCard({
  type,
  version,
  createdAt,
  modelProfile,
  projectId,
}: {
  type: ArtifactType;
  version: number;
  createdAt: string;
  modelProfile?: ModelProfile;
  projectId: string;
}) {
  return (
    <Link
      href={`/projects/${projectId}/artifacts/${type}`}
      className="glass group block p-5 hover:border-accent/30 transition-all duration-200 hover:-translate-y-0.5"
    >
      <div className="flex items-start justify-between mb-4">
        <div className="w-10 h-10 rounded-lg bg-surface-2 border border-border-1 flex items-center justify-center text-text-2 group-hover:text-accent group-hover:border-accent/20 transition-colors">
          {ARTIFACT_ICONS[type]}
        </div>
        <span className="font-mono-display text-[11px] text-text-3 bg-surface-2 px-2 py-0.5 rounded">
          v{version}
        </span>
      </div>
      <h3 className="text-sm font-semibold text-text-0 mb-1 group-hover:text-accent transition-colors">
        {ARTIFACT_LABELS[type]}
      </h3>
      <div className="flex items-center gap-3 text-[11px] text-text-3 font-mono-display">
        <span>{formatRelative(createdAt)}</span>
        {modelProfile && (
          <>
            <span className="text-border-2">&middot;</span>
            <span>{modelProfile}</span>
          </>
        )}
      </div>
    </Link>
  );
}
