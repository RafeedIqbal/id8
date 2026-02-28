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
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project, i) => {
            const stitchUrl = project.stackJson?.stitch_project_url as string | undefined;

            return (
              <div
                key={project.id}
                className={`glass flex flex-col relative group p-5 hover:border-accent/30 transition-all duration-200 hover:-translate-y-0.5 animate-slide-up${i <= 5 ? ` animate-slide-up-delay-${i}` : ""}`}
              >
                <Link href={`/projects/${project.id}`} className="absolute inset-0 z-0 rounded-xl" />
                <div className="flex-1 relative z-10 pointer-events-none">
                  <div className="flex items-start justify-between mb-3">
                    <h2 className="text-base font-semibold text-text-0 group-hover:text-accent transition-colors pointer-events-auto">
                      <Link href={`/projects/${project.id}`}>{project.title}</Link>
                    </h2>
                    <div className="pointer-events-auto">
                      <ProjectStatusBadge status={project.status} />
                    </div>
                  </div>
                  <p className="text-sm text-text-2 mb-4 line-clamp-2">
                    {project.initialPrompt}
                  </p>

                  <div className="flex items-center gap-2 text-xs text-text-3 font-mono-display mb-4">
                    <span>{formatRelative(project.updatedAt)}</span>
                    {project.latestRun && (
                      <>
                        <span className="text-border-2">&middot;</span>
                        <span className="text-text-2">
                          {NODE_LABELS[project.latestRun.currentNode] ?? project.latestRun.currentNode}
                        </span>
                      </>
                    )}
                  </div>
                </div>

                {/* Bottom external links */}
                <div className="relative z-10 flex items-center justify-between pt-4 border-t border-border-1/50 -mx-1 -mb-1 px-1">
                  <div className="flex items-center gap-2">
                    {stitchUrl && (
                      <a
                        href={stitchUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-2.5 py-1.5 rounded-md text-[11px] font-mono-display font-medium text-accent bg-accent/5 hover:bg-accent/15 border border-accent/20 transition-colors flex items-center gap-1.5"
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M4 4h16v16H4zM4 10h16M10 4v16" />
                        </svg>
                        Stitch
                      </a>
                    )}
                    {project.githubRepoUrl && (
                      <a
                        href={project.githubRepoUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-2.5 py-1.5 rounded-md text-[11px] font-mono-display font-medium text-text-1 hover:text-text-0 bg-surface-2 hover:bg-surface-3 transition-colors flex items-center gap-1.5"
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M12 2C6.477 2 2 6.477 2 12c0 4.42 2.87 8.17 6.84 9.5.5.08.66-.23.66-.5v-1.69c-2.77.6-3.36-1.34-3.36-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .08 1.53 1.04 1.53 1.04.87 1.52 2.34 1.07 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.92 0-1.11.38-2 1.03-2.71-.1-.25-.45-1.29.1-2.64 0 0 .84-.27 2.75 1.02.79-.22 1.65-.33 2.5-.33.85 0 1.71.11 2.5.33 1.91-1.29 2.75-1.02 2.75-1.02.55 1.35.2 2.39.1 2.64.65.71 1.03 1.6 1.03 2.71 0 3.82-2.34 4.66-4.57 4.91.36.31.69.92.69 1.85V21c0 .27.16.59.67.5C19.14 20.16 22 16.42 22 12A10 10 10 0 0 12 2z" />
                        </svg>
                        Repo
                      </a>
                    )}
                  </div>
                  {project.liveDeploymentUrl && (
                    <a
                      href={project.liveDeploymentUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-2.5 py-1.5 rounded-md text-[11px] font-mono-display font-medium text-success bg-success/5 hover:bg-success/15 border border-success/20 transition-colors flex items-center gap-1.5"
                    >
                      Website
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
