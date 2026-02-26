"use client";

import Link from "next/link";
import { useProjects } from "@/lib/hooks";
import { ProjectStatusBadge } from "@/components/project-status-badge";
import { EmptyState } from "@/components/empty-state";
import { formatRelative, truncate } from "@/lib/utils";
import { NODE_LABELS } from "@/lib/constants";

function DashboardSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <div key={i} className="glass p-5">
          <div className="flex items-start justify-between mb-3">
            <div className="skeleton h-4 w-48" />
            <div className="skeleton h-5 w-20 rounded-md" />
          </div>
          <div className="skeleton h-3 w-3/4 mb-2" />
          <div className="skeleton h-3 w-32" />
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const { data, isLoading, error } = useProjects();
  const projects = data?.items ?? [];

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="flex items-end justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-text-0 mb-1">Projects</h1>
          <p className="text-sm text-text-2">
            {projects.length > 0
              ? `${projects.length} project${projects.length !== 1 ? "s" : ""}`
              : "No projects yet"}
          </p>
        </div>
        <Link href="/projects/new" className="btn btn-primary">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8v8M8 12h8" strokeLinecap="round" />
          </svg>
          New Project
        </Link>
      </div>

      {/* Error state */}
      {error && (
        <div className="text-sm text-error bg-error-bg border border-error-dim rounded-lg p-4 mb-6">
          {(error as Error).message}
        </div>
      )}

      {/* Loading */}
      {isLoading && <DashboardSkeleton />}

      {/* Empty state */}
      {!isLoading && projects.length === 0 && !error && (
        <EmptyState
          title="No projects yet"
          description="Create your first project to start the prompt-to-production pipeline."
          action={
            <Link href="/projects/new" className="btn btn-primary">
              Create First Project
            </Link>
          }
        />
      )}

      {/* Project list */}
      {projects.length > 0 && (
        <div className="space-y-3">
          {projects.map((project, i) => (
            <Link
              key={project.id}
              href={`/projects/${project.id}`}
              className={`glass group block p-5 hover:border-accent/30 transition-all duration-200 hover:-translate-y-0.5 animate-slide-up${i <= 5 ? ` animate-slide-up-delay-${i}` : ""}`}
            >
              <div className="flex items-start justify-between mb-3">
                <h2 className="text-base font-semibold text-text-0 group-hover:text-accent transition-colors">
                  {project.title}
                </h2>
                <ProjectStatusBadge status={project.status} />
              </div>
              <p className="text-sm text-text-2 mb-3">
                {truncate(project.initialPrompt, 120)}
              </p>

              <div className="flex items-center gap-4 text-xs text-text-3 font-mono-display">
                <span>{formatRelative(project.updatedAt)}</span>
                {project.latestRun && (
                  <>
                    <span className="text-border-2">&middot;</span>
                    <span className="text-text-2">
                      {NODE_LABELS[project.latestRun.currentNode] ?? project.latestRun.currentNode}
                    </span>
                  </>
                )}
                {project.liveDeploymentUrl && (
                  <>
                    <span className="text-border-2">&middot;</span>
                    <span className="text-success">Live</span>
                  </>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
