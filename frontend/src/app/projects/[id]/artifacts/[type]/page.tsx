"use client";

import { use, useState } from "react";
import { useArtifacts } from "@/lib/hooks";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { ARTIFACT_LABELS } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { ArtifactType, ProjectArtifact } from "@/types/domain";

import { PrdViewer } from "@/components/artifact-viewers/prd-viewer";
import { DesignViewer } from "@/components/artifact-viewers/design-viewer";
import { TechPlanViewer } from "@/components/artifact-viewers/tech-plan-viewer";
import { CodeViewer } from "@/components/artifact-viewers/code-viewer";
import { SecurityViewer } from "@/components/artifact-viewers/security-viewer";
import { DeployViewer } from "@/components/artifact-viewers/deploy-viewer";

const VIEWERS: Record<ArtifactType, React.ComponentType<{ artifact: ProjectArtifact }>> = {
  prd: PrdViewer,
  design_spec: DesignViewer,
  tech_plan: TechPlanViewer,
  code_snapshot: CodeViewer,
  security_report: SecurityViewer,
  deploy_report: DeployViewer,
};

export default function ArtifactViewerPage({
  params,
}: {
  params: Promise<{ id: string; type: string }>;
}) {
  const { id, type } = use(params);
  const artifactType = type as ArtifactType;
  const { data, isLoading } = useArtifacts(id);

  const versions = (data?.items ?? [])
    .filter((a) => a.artifactType === artifactType)
    .sort((a, b) => b.version - a.version);

  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const current =
    versions.find((v) => v.version === selectedVersion) ?? versions[0] ?? null;

  const Viewer = VIEWERS[artifactType];
  const label = ARTIFACT_LABELS[artifactType] ?? type;

  return (
    <div className="animate-fade-in">
      <Breadcrumbs
        items={[
          { label: "Projects", href: "/" },
          { label: id, href: `/projects/${id}` },
          { label: label },
        ]}
      />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-semibold text-text-0">{label}</h1>
          {current && (
            <div className="flex items-center gap-3 mt-1 text-xs text-text-3 font-mono-display">
              <span>Version {current.version}</span>
              <span className="text-border-2">&middot;</span>
              <span>{formatDateTime(current.createdAt)}</span>
              {current.modelProfile && (
                <>
                  <span className="text-border-2">&middot;</span>
                  <span>{current.modelProfile}</span>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="glass p-6 space-y-4">
          <div className="skeleton h-5 w-48" />
          <div className="skeleton h-4 w-full" />
          <div className="skeleton h-4 w-3/4" />
          <div className="skeleton h-4 w-5/6" />
        </div>
      ) : !current ? (
        <div className="glass p-8 text-center">
          <p className="text-sm text-text-2">No {label.toLowerCase()} artifact found.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-[180px_1fr] gap-4">
          {/* Version rail */}
          {versions.length > 1 && (
            <div className="glass p-3 xl:max-h-[600px] overflow-y-auto">
              <div className="text-[10px] font-mono-display text-text-3 tracking-widest uppercase px-3 py-1.5 mb-1">
                Versions
              </div>
              {versions.map((v) => (
                <button
                  key={v.id}
                  onClick={() => setSelectedVersion(v.version)}
                  className={cn(
                    "w-full text-left px-3 py-2 rounded-lg text-xs transition-all",
                    v.id === current.id
                      ? "bg-accent-bg text-accent border border-accent/20"
                      : "text-text-2 hover:text-text-1 hover:bg-surface-2"
                  )}
                >
                  <div className="font-mono-display">v{v.version}</div>
                  <div className="text-[10px] text-text-3 mt-0.5">
                    {formatDateTime(v.createdAt)}
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Main viewer */}
          <div className={versions.length <= 1 ? "xl:col-span-2" : ""}>
            {Viewer ? (
              <Viewer artifact={current} />
            ) : (
              <div className="glass p-6">
                <pre className="text-xs">{JSON.stringify(current.content, null, 2)}</pre>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
