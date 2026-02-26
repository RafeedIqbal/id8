"use client";

import type { ProjectArtifact } from "@/types/domain";
import { isString, safeString, safeRecord } from "@/lib/artifact-guards";
import { RawJsonInspector } from "./raw-json-inspector";

export function DeployViewer({ artifact }: { artifact: ProjectArtifact }) {
  const c = safeRecord(artifact.content);
  if (!c) {
    return <RawJsonInspector data={artifact.content} warning="Artifact content is not a valid object." />;
  }

  const status = safeString(c.status) ?? (safeString(c.live_url) ? "success" : undefined);
  const environment = safeString(c.environment);
  const url = safeString(c.live_url) ?? safeString(c.url);
  const provider = safeString(c.provider) ?? (c.vercel ? "vercel" : undefined);

  // Build provider payload safely, checking each field is a record or string
  let providerPayload: Record<string, unknown> | undefined;
  const rawPayload = c.provider_payload ?? c.provider_details;
  if (rawPayload && typeof rawPayload === "object" && !Array.isArray(rawPayload)) {
    providerPayload = rawPayload as Record<string, unknown>;
  } else if (c.vercel) {
    const composed: Record<string, unknown> = {};
    if (c.vercel) composed.vercel = c.vercel;
    if (c.health_check) composed.health_check = c.health_check;
    if (c.github_repo) composed.github_repo = c.github_repo;
    providerPayload = composed;
  }

  const isLive = status === "success" || status === "deployed" || status === "live";
  const hasContent = status || url;

  return (
    <div className="animate-fade-in space-y-6 min-w-0">
      {/* Status banner */}
      {status && (
        <div className={`glass p-6 ${isLive ? "glow-success" : ""}`}>
          <div className="flex items-center gap-4">
            <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
              isLive ? "bg-success-bg" : "bg-warning-bg"
            }`}>
              {isLive ? (
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--color-success)" strokeWidth="2">
                  <path d="M22 12A10 10 0 1112 2" strokeLinecap="round" />
                  <path d="M22 2L12 12M22 2h-6M22 2v6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--color-warning)" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M12 6v6l4 2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </div>
            <div>
              <div className="font-mono-display text-xs text-text-3 tracking-widest uppercase mb-1">
                Deployment Status
              </div>
              <div className={`text-lg font-semibold ${isLive ? "text-success" : "text-warning"}`}>
                {status}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Details grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 min-w-0">
        {environment && (
          <div className="glass p-5">
            <div className="font-mono-display text-[10px] text-text-3 tracking-widest uppercase mb-2">Environment</div>
            <div className="text-sm text-text-0 font-medium">{environment}</div>
          </div>
        )}
        {provider && isString(provider) && (
          <div className="glass p-5">
            <div className="font-mono-display text-[10px] text-text-3 tracking-widest uppercase mb-2">Provider</div>
            <div className="text-sm text-text-0 font-medium">{provider}</div>
          </div>
        )}
      </div>

      {/* Deployment URL */}
      {url && (
        <div className="glass p-5 glow-accent">
          <div className="font-mono-display text-[10px] text-text-3 tracking-widest uppercase mb-2">Live URL</div>
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent hover:underline font-mono-display text-sm inline-flex items-center gap-2 break-all"
          >
            {url}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </a>
        </div>
      )}

      {/* Provider payload */}
      {providerPayload && (
        <details className="glass p-4">
          <summary className="text-xs font-mono-display text-text-3 cursor-pointer hover:text-text-2 tracking-widest uppercase">
            Provider Payload
          </summary>
          <pre className="text-xs mt-3 overflow-auto max-w-full whitespace-pre-wrap break-words">
            {JSON.stringify(providerPayload, null, 2)}
          </pre>
        </details>
      )}

      {/* Fallback if no structured data */}
      {!hasContent && (
        <RawJsonInspector data={artifact.content} warning="No recognized deployment fields found. Showing raw content." />
      )}
    </div>
  );
}
