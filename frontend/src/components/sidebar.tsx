"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

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

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const projectMatch = pathname.match(/^\/projects\/([^/]+)/);
  const projectId =
    projectMatch && projectMatch[1] && projectMatch[1] !== "new"
      ? projectMatch[1]
      : null;
  const artifactType = pathname.match(/^\/projects\/[^/]+\/artifacts\/([^/]+)/)?.[1] ?? "prd";
  const approvalStage = pathname.match(/^\/projects\/[^/]+\/approve\/([^/]+)/)?.[1] ?? "prd";

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
              <NavLink
                href={`/projects/${projectId}/artifacts/${artifactType}`}
                label="Artifacts"
                onNavigate={() => setOpen(false)}
                icon={
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M4 4h16v16H4z" />
                    <path d="M4 10h16M10 4v16" />
                  </svg>
                }
              />
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
