"use client";

import { useState } from "react";
import type { ProjectArtifact } from "@/types/domain";
import { cn } from "@/lib/utils";

interface Screen {
  id?: string;
  name?: string;
  description?: string;
  components?: Array<{
    id?: string;
    name?: string;
    type?: string;
    properties?: Record<string, unknown>;
    props?: Record<string, unknown>;
  }>;
  assets?: string[];
}

export function DesignViewer({ artifact }: { artifact: ProjectArtifact }) {
  const c = artifact.content as Record<string, unknown>;
  const screens = (c.screens ?? c.screen_list ?? []) as Screen[];
  const designMeta = (c.__design_metadata ?? c.metadata ?? c.provider_metadata ?? {}) as Record<string, unknown>;
  const provider = (designMeta.provider_used ?? designMeta.provider ?? c.provider) as string | undefined;
  const providerMeta = designMeta;

  const [selectedIdx, setSelectedIdx] = useState(0);
  const selected = screens[selectedIdx];

  return (
    <div className="animate-fade-in">
      {/* Provider badge */}
      {provider && (
        <div className="mb-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-md bg-surface-2 border border-border-1 text-xs font-mono-display text-text-2">
          Provider: <span className="text-accent">{provider}</span>
        </div>
      )}

      {screens.length === 0 ? (
        <div className="glass-raised p-6 text-center">
          <p className="text-sm text-text-2">No screens defined yet.</p>
          <pre className="text-xs mt-4 text-left">{JSON.stringify(artifact.content, null, 2)}</pre>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-4">
          {/* Screen list */}
          <div className="glass p-3 space-y-1 lg:max-h-[600px] overflow-y-auto">
            <div className="text-[10px] font-mono-display text-text-3 tracking-widest uppercase px-3 py-1.5">
              Screens ({screens.length})
            </div>
            {screens.map((screen, i) => (
              <button
                key={screen.id ?? i}
                onClick={() => setSelectedIdx(i)}
                className={cn(
                  "w-full text-left px-3 py-2.5 rounded-lg text-sm transition-all",
                  i === selectedIdx
                    ? "bg-accent-bg text-accent border border-accent/20"
                    : "text-text-2 hover:text-text-1 hover:bg-surface-2"
                )}
              >
                {screen.name ?? `Screen ${i + 1}`}
              </button>
            ))}
          </div>

          {/* Screen detail */}
          <div className="glass p-6 space-y-6">
            <div>
              <h3 className="text-lg font-semibold text-text-0 mb-1">
                {selected?.name ?? `Screen ${selectedIdx + 1}`}
              </h3>
              {selected?.description && (
                <p className="text-sm text-text-2 leading-relaxed">{selected.description}</p>
              )}
            </div>

            {/* Components */}
            {selected?.components && selected.components.length > 0 && (
              <div>
                <h4 className="text-xs font-mono-display text-text-2 tracking-widest uppercase mb-3">
                  Components ({selected.components.length})
                </h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border-0">
                        <th className="text-left py-2 pr-4 text-text-3 font-medium text-xs">Name</th>
                        <th className="text-left py-2 pr-4 text-text-3 font-medium text-xs">Type</th>
                        <th className="text-left py-2 text-text-3 font-medium text-xs">Props</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selected.components.map((comp, i) => (
                        <tr key={i} className="border-b border-border-0/50">
                          <td className="py-2.5 pr-4 font-mono-display text-xs text-accent">
                            {comp.name ?? comp.id}
                          </td>
                          <td className="py-2.5 pr-4 text-text-2 text-xs">{comp.type}</td>
                          <td className="py-2.5 text-text-3 text-xs font-mono-display">
                            {(comp.properties ?? comp.props)
                              ? Object.entries(comp.properties ?? comp.props ?? {})
                                  .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                                  .join(", ")
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Assets */}
            {selected?.assets && selected.assets.length > 0 && (
              <div>
                <h4 className="text-xs font-mono-display text-text-2 tracking-widest uppercase mb-3">
                  Assets
                </h4>
                <div className="flex flex-wrap gap-2">
                  {selected.assets.map((asset, i) => (
                    <span key={i} className="inline-flex px-3 py-1.5 rounded-md bg-surface-2 border border-border-1 text-xs text-text-1 font-mono-display">
                      {asset}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Provider metadata */}
      {providerMeta && Object.keys(providerMeta).length > 0 && (
        <details className="mt-4 glass p-4">
          <summary className="text-xs font-mono-display text-text-3 cursor-pointer hover:text-text-2 tracking-widest uppercase">
            Provider Metadata
          </summary>
          <pre className="text-xs mt-3">{JSON.stringify(providerMeta, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}
