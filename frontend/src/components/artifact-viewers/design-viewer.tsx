"use client";

import { useState } from "react";
import Image from "next/image";
import type { ProjectArtifact } from "@/types/domain";
import { cn } from "@/lib/utils";
import { isRecord, isString, safeString, safeArray, safeRecord } from "@/lib/artifact-guards";
import { RawJsonInspector } from "./raw-json-inspector";

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

function isHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

function isImageAsset(value: string): boolean {
  const normalized = value.toLowerCase();
  return (
    normalized.includes("image") ||
    normalized.includes(".png") ||
    normalized.includes(".jpg") ||
    normalized.includes(".jpeg") ||
    normalized.includes(".webp") ||
    normalized.includes(".gif")
  );
}

function extractStitchProjectUrl(meta: Record<string, unknown>): string | null {
  const direct = safeString(meta.stitch_project_url) ?? safeString(meta.stitch_url) ?? safeString(meta.project_url);
  if (direct && direct.trim()) return direct.trim();
  const projectId = safeString(meta.stitch_project_id);
  if (projectId && projectId.trim()) {
    return `https://stitch.withgoogle.com/project/${encodeURIComponent(projectId.trim())}`;
  }
  return null;
}

function extractSuggestions(meta: Record<string, unknown>): string[] {
  const raw = safeArray(meta.stitch_suggestions).filter(isString).map((s) => s.trim()).filter(Boolean);
  if (raw.length > 0) return raw;
  const nested = safeRecord(meta.provider_metadata);
  return safeArray(nested?.stitch_suggestions).filter(isString).map((s) => s.trim()).filter(Boolean);
}

function toScreen(raw: unknown): Screen | null {
  if (!isRecord(raw)) return null;
  const components = safeArray(raw.components).filter(isRecord).map((comp) => ({
    id: safeString(comp.id),
    name: safeString(comp.name),
    type: safeString(comp.type),
    properties: safeRecord(comp.properties),
    props: safeRecord(comp.props),
  }));
  return {
    id: safeString(raw.id),
    name: safeString(raw.name),
    description: safeString(raw.description),
    components: components.length > 0 ? components : undefined,
    assets: safeArray(raw.assets).filter(isString),
  };
}

function dedupeScreens(screens: Screen[]): Screen[] {
  const seen = new Set<string>();
  return screens.filter((screen) => {
    const id = screen.id?.trim();
    if (!id) return true;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

export function DesignViewer({ artifact }: { artifact: ProjectArtifact }) {
  const c = safeRecord(artifact.content);
  const rawScreens = c ? safeArray(c.screens ?? c.screen_list) : [];
  const screens = dedupeScreens(rawScreens.map(toScreen).filter((s): s is Screen => s !== null));
  const designMeta = c ? (safeRecord(c.__design_metadata) ?? safeRecord(c.metadata) ?? safeRecord(c.provider_metadata) ?? {}) : {};
  const provider = c ? (safeString(designMeta.provider_used) ?? safeString(designMeta.provider) ?? safeString(c.provider)) : undefined;
  const providerMeta = designMeta;
  const stitchProjectUrl = extractStitchProjectUrl(designMeta);
  const suggestions = extractSuggestions(designMeta);

  const [selectedIdx, setSelectedIdx] = useState(0);
  const selected = screens[selectedIdx];
  const selectedAssets = safeArray(selected?.assets, isString);
  const imageAssets = selectedAssets.filter((asset) => isHttpUrl(asset) && isImageAsset(asset));

  if (!c) {
    return <RawJsonInspector data={artifact.content} warning="Artifact content is not a valid object." />;
  }

  return (
    <div className="animate-fade-in">
      {/* Provider badge */}
      {provider && (
        <div className="mb-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-md bg-surface-2 border border-border-1 text-xs font-mono-display text-text-2">
          Provider: <span className="text-accent">{provider}</span>
        </div>
      )}
      {(stitchProjectUrl || suggestions.length > 0) && (
        <div className="mb-4 flex flex-wrap items-center gap-3 text-xs">
          {stitchProjectUrl && (
            <a
              href={stitchProjectUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-accent hover:underline"
            >
              Open in Stitch
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M7 17L17 7M9 7h8v8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </a>
          )}
          {suggestions.length > 0 && (
            <span className="text-text-2 bg-surface-2 border border-border-1 rounded-md px-2 py-1">
              Stitch suggestions: {suggestions.length}
            </span>
          )}
        </div>
      )}

      {screens.length === 0 ? (
        <RawJsonInspector data={artifact.content} warning="No screens defined. Showing raw content." />
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
                            {comp.name ?? comp.id ?? "—"}
                          </td>
                          <td className="py-2.5 pr-4 text-text-2 text-xs">{comp.type ?? "—"}</td>
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

            {imageAssets.length > 0 && (
              <div>
                <h4 className="text-xs font-mono-display text-text-2 tracking-widest uppercase mb-3">
                  Preview
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {imageAssets.map((asset, i) => (
                    <a
                      key={`${asset}-${i}`}
                      href={asset}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block rounded-lg border border-border-1 overflow-hidden bg-surface-2"
                    >
                      <Image
                        src={asset}
                        alt={`${selected?.name ?? "Screen"} preview ${i + 1}`}
                        width={1024}
                        height={704}
                        unoptimized
                        className="w-full h-44 object-cover"
                      />
                    </a>
                  ))}
                </div>
              </div>
            )}

            {/* Assets */}
            {selectedAssets.length > 0 && (
              <div>
                <h4 className="text-xs font-mono-display text-text-2 tracking-widest uppercase mb-3">
                  Assets
                </h4>
                <div className="flex flex-wrap gap-2">
                  {selectedAssets.map((asset, i) => (
                    isHttpUrl(asset) ? (
                      <a
                        key={i}
                        href={asset}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex px-3 py-1.5 rounded-md bg-surface-2 border border-border-1 text-xs text-accent font-mono-display hover:underline"
                      >
                        {asset}
                      </a>
                    ) : (
                      <span key={i} className="inline-flex px-3 py-1.5 rounded-md bg-surface-2 border border-border-1 text-xs text-text-1 font-mono-display">
                        {asset}
                      </span>
                    )
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
