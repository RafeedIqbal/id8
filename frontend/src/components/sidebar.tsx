"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { useArtifacts, useProject } from "@/lib/hooks";

const NAV_ITEMS = [
  {
    label: "Dashboard",
    href: "/",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </svg>
    ),
  },
  {
    label: "New Project",
    href: "/projects/new",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v8M8 12h8" strokeLinecap="round" />
      </svg>
    ),
  },
];

const ARTIFACT_SUB_ITEMS = [
  { label: "PRD", type: "prd" },
  { label: "Screens", type: "design_spec" },
  { label: "Code Base", type: "code_snapshot" },
] as const;

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-3 px-2 py-1 group">
      <div className="w-9 h-9 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center group-hover:bg-accent/15 transition-colors">
        <span className="font-mono-display text-accent text-sm font-bold tracking-tighter">i8</span>
      </div>
      <div>
        <div className="font-mono-display text-text-0 text-sm font-semibold tracking-tight">ID8</div>
        <div className="text-[10px] text-text-3 tracking-widest uppercase">Operator</div>
      </div>
    </Link>
  );
}

function NavLink({
  href,
  icon,
  label,
  onNavigate,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const isActive = href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <Link
      href={href}
      onClick={onNavigate}
      className={cn("sidebar-link", isActive && "sidebar-link-active")}
      aria-current={isActive ? "page" : undefined}
    >
      {icon}
      <span>{label}</span>
    </Link>
  );
}

function ExternalNavLink({
  href,
  label,
  icon,
  onNavigate,
}: {
  href?: string;
  label: string;
  icon: React.ReactNode;
  onNavigate?: () => void;
}) {
  if (!href) {
    return (
      <span className="sidebar-link opacity-40 cursor-default">
        {icon}
        <span className="text-text-3">{label}</span>
        <span className="text-[9px] text-text-3 ml-auto">N/A</span>
      </span>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={onNavigate}
      className="sidebar-link hover:text-accent"
    >
      {icon}
      <span>{label}</span>
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="ml-auto opacity-50">
        <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </a>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const projectMatch = pathname.match(/^\/projects\/([^/]+)/);
  const projectId =
    projectMatch && projectMatch[1] && projectMatch[1] !== "new"
      ? projectMatch[1]
      : null;
  const approvalStage = pathname.match(/^\/projects\/[^/]+\/approve\/([^/]+)/)?.[1] ?? "prd";
  const isOnArtifactsRoute = pathname.includes("/artifacts/");

  const [artifactsExpanded, setArtifactsExpanded] = useState(isOnArtifactsRoute);

  // Expand artifacts when navigating to an artifact route
  useEffect(() => {
    if (isOnArtifactsRoute) setArtifactsExpanded(true);
  }, [isOnArtifactsRoute]);

  // Fetch project data for external links
  const { data: project } = useProject(projectId ?? "", {
    refetchInterval: undefined,
  });
  const { data: artifactsData } = useArtifacts(projectId ?? "", {
    refetchInterval: undefined,
  });

  const latestDesignArtifact = artifactsData?.items
    ?.filter((a) => a.artifactType === "design_spec")
    ?.sort((a, b) => b.version - a.version)?.[0];

  const designMetadata = (() => {
    const content = latestDesignArtifact?.content;
    if (!content || typeof content !== "object") return {};
    const record = content as Record<string, unknown>;
    const meta = record.__design_metadata ?? record.metadata ?? record.provider_metadata;
    if (!meta || typeof meta !== "object" || Array.isArray(meta)) return {};
    return meta as Record<string, unknown>;
  })();

  const stitchProjectUrl = (() => {
    const direct =
      (designMetadata.stitch_project_url as string | undefined) ??
      (designMetadata.stitch_url as string | undefined) ??
      (designMetadata.project_url as string | undefined);
    if (direct) return direct;
    const projectId = designMetadata.stitch_project_id;
    if (typeof projectId === "string" && projectId.trim()) {
      return `https://stitch.withgoogle.com/project/${encodeURIComponent(projectId)}`;
    }
    return undefined;
  })();

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return (
    <>
      {/* Mobile hamburger */}
      <button
        onClick={() => setOpen(true)}
        className="lg:hidden fixed top-4 left-4 z-50 w-10 h-10 rounded-lg bg-surface-2 border border-border-1 flex items-center justify-center text-text-1 hover:text-accent transition-colors"
        aria-label="Open navigation"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
        </svg>
      </button>

      {/* Drawer overlay */}
      {open && (
        <button
          type="button"
          className="drawer-overlay lg:hidden border-0"
          onClick={() => setOpen(false)}
          aria-label="Close navigation"
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={cn(
          "fixed top-0 left-0 h-dvh w-[260px] bg-surface-1 border-r border-border-0 z-50 flex flex-col",
          "transition-transform duration-200",
          "lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="p-5 pb-4 border-b border-border-0">
          <Logo />
        </div>

        <nav className="flex-1 overflow-y-auto p-3 space-y-1">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.href} {...item} onNavigate={() => setOpen(false)} />
          ))}

          {projectId && (
            <div className="pt-3 mt-3 border-t border-border-0 space-y-1">
              <div className="text-[10px] font-mono-display text-text-3 tracking-widest uppercase px-3 py-1.5">
                Project
              </div>

              <NavLink
                href={`/projects/${projectId}`}
                label="Overview"
                onNavigate={() => setOpen(false)}
                icon={
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <circle cx="12" cy="12" r="8" />
                    <path d="M12 8v4l2.5 2.5" strokeLinecap="round" />
                  </svg>
                }
              />

              {/* Collapsible Artifacts group */}
              <div>
                <button
                  onClick={() => setArtifactsExpanded(!artifactsExpanded)}
                  className={cn(
                    "sidebar-link w-full justify-between",
                    isOnArtifactsRoute && "sidebar-link-active"
                  )}
                  aria-expanded={artifactsExpanded}
                >
                  <div className="flex items-center gap-2">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M4 4h16v16H4z" />
                      <path d="M4 10h16M10 4v16" />
                    </svg>
                    <span>Artifacts</span>
                  </div>
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    className={cn("transition-transform", artifactsExpanded && "rotate-90")}
                  >
                    <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>

                {artifactsExpanded && (
                  <div role="group" className="pl-4 space-y-0.5 mt-0.5">
                    {ARTIFACT_SUB_ITEMS.map(({ label, type }) => {
                      const href = `/projects/${projectId}/artifacts/${type}`;
                      const isActive = pathname === href;
                      const externalHref =
                        type === "design_spec"
                          ? stitchProjectUrl
                          : type === "code_snapshot"
                            ? project?.githubRepoUrl
                            : undefined;
                      const externalLabel =
                        type === "design_spec"
                          ? "Stitch"
                          : type === "code_snapshot"
                            ? "GitHub"
                            : undefined;
                      return (
                        <div key={type} className="flex items-center gap-1">
                          <Link
                            href={href}
                            onClick={() => setOpen(false)}
                            className={cn(
                              "flex-1 block px-3 py-1.5 rounded-lg text-xs transition-colors",
                              isActive
                                ? "text-accent bg-accent-bg"
                                : "text-text-2 hover:text-text-1 hover:bg-surface-2"
                            )}
                          >
                            {label}
                          </Link>
                          {externalLabel && (
                            externalHref ? (
                              <a
                                href={externalHref}
                                target="_blank"
                                rel="noopener noreferrer"
                                onClick={() => setOpen(false)}
                                className="px-2 py-1 rounded-md text-[10px] font-mono-display text-accent hover:bg-accent-bg"
                                title={`Open ${externalLabel}`}
                              >
                                {externalLabel}
                              </a>
                            ) : (
                              <span className="px-2 py-1 rounded-md text-[9px] font-mono-display text-text-3">
                                N/A
                              </span>
                            )
                          )}
                        </div>
                      );
                    })}

                    {/* External destinations */}
                    <div className="pt-1.5 mt-1.5 border-t border-border-0/50 space-y-0.5">
                      <ExternalNavLink
                        href={project?.liveDeploymentUrl}
                        label="Vercel Site"
                        onNavigate={() => setOpen(false)}
                        icon={
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M12 1L1 22h22L12 1z" />
                          </svg>
                        }
                      />
                    </div>
                  </div>
                )}
              </div>

              <NavLink
                href={`/projects/${projectId}/approve/${approvalStage}`}
                label="Approvals"
                onNavigate={() => setOpen(false)}
                icon={
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
                    <circle cx="12" cy="12" r="9" />
                  </svg>
                }
              />
            </div>
          )}
        </nav>

        <div className="p-4 border-t border-border-0">
          <div className="text-[10px] font-mono-display text-text-3 tracking-widest uppercase">
            v0.1.0 <span className="text-accent/40">MVP</span>
          </div>
        </div>
      </aside>
    </>
  );
}
