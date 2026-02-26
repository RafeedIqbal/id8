"use client";

import { useDesignTools } from "@/lib/hooks";

export function DesignToolsPanel() {
  const { data, isLoading } = useDesignTools();

  if (isLoading) {
    return (
      <div className="glass p-5 space-y-3">
        <div className="skeleton h-4 w-32" />
        <div className="skeleton h-3 w-full" />
        <div className="skeleton h-3 w-3/4" />
        <div className="skeleton h-3 w-5/6" />
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="glass p-5">
      <h3 className="text-xs font-mono-display text-text-2 tracking-widest uppercase mb-4 flex items-center gap-2">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
        </svg>
        Stitch Tools
        <span className="text-text-3 font-normal normal-case tracking-normal">
          ({data.provider})
        </span>
      </h3>

      <div className="space-y-2">
        {data.usableTools.map((tool) => (
          <div key={tool.name} className="glass-raised p-3">
            <div className="font-mono-display text-xs text-accent mb-1">
              {tool.name}
              <span className="text-text-3">
                ({tool.params.join(", ")})
              </span>
            </div>
            <p className="text-xs text-text-2 leading-relaxed">
              {tool.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
