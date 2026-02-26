"use client";

import type { ProjectStatus } from "@/types/domain";
import { STATUS_CONFIG } from "@/lib/constants";

export function ProjectStatusBadge({ status }: { status: ProjectStatus }) {
  const config = STATUS_CONFIG[status];
  return (
    <span
      className="font-mono-display inline-flex items-center px-2.5 py-1 rounded-md text-[11px] font-semibold tracking-wider uppercase"
      style={{ color: config.color, background: config.bg }}
    >
      {config.label}
    </span>
  );
}
