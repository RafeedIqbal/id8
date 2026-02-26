"use client";

import type { ProjectArtifact } from "@/types/domain";
import { isRecord, safeString, safeArray, safeRecord, safeBoolean } from "@/lib/artifact-guards";
import { RawJsonInspector } from "./raw-json-inspector";

type Severity = "critical" | "high" | "medium" | "low";

const VALID_SEVERITIES = new Set<string>(["critical", "high", "medium", "low"]);

interface Finding {
  severity: Severity;
  rule_id?: string;
  file_path?: string;
  line_number?: number;
  message?: string;
  remediation?: string;
  resolved: boolean;
}

function toFinding(raw: unknown): Finding | null {
  if (!isRecord(raw)) return null;
  const sev = safeString(raw.severity)?.toLowerCase() ?? "low";
  return {
    severity: (VALID_SEVERITIES.has(sev) ? sev : "low") as Severity,
    rule_id: safeString(raw.rule_id) ?? safeString(raw.rule),
    file_path: safeString(raw.file_path) ?? safeString(raw.file),
    line_number: typeof raw.line_number === "number" ? raw.line_number : typeof raw.line === "number" ? raw.line : undefined,
    message: safeString(raw.message),
    remediation: safeString(raw.remediation),
    resolved: safeBoolean(raw.resolved) ?? false,
  };
}

const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

function SeverityBadge({ severity }: { severity: string }) {
  const cls = `severity-${severity}`;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono-display font-semibold uppercase tracking-wider ${cls}`}>
      {severity}
    </span>
  );
}

export function SecurityViewer({ artifact }: { artifact: ProjectArtifact }) {
  const c = safeRecord(artifact.content);
  if (!c) {
    return <RawJsonInspector data={artifact.content} warning="Artifact content is not a valid object." />;
  }

  const findings = safeArray(c.findings)
    .map(toFinding)
    .filter((f): f is Finding => f !== null)
    .slice() // clone before sorting to avoid mutating
    .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 4) - (SEVERITY_ORDER[b.severity] ?? 4));

  const summaryRecord = safeRecord(c.summary);

  // Compute counts from findings (avoids double-counting bug from summary + findings)
  const counts = { critical: 0, high: 0, medium: 0, low: 0, total: findings.length };
  for (const f of findings) {
    counts[f.severity]++;
  }

  // Only use summary counts if there are no findings to count from
  if (findings.length === 0 && summaryRecord) {
    for (const sev of ["critical", "high", "medium", "low"] as const) {
      const val = summaryRecord[sev];
      if (typeof val === "number") counts[sev] = val;
    }
    const total = summaryRecord.total;
    counts.total = typeof total === "number" ? total : 0;
  }

  const unresolvedCount = findings.filter((f) => !f.resolved).length;

  const hasContent = findings.length > 0 || (summaryRecord && Object.keys(summaryRecord).length > 0);

  return (
    <div className="animate-fade-in space-y-6">
      {/* Summary badges */}
      <div className="flex flex-wrap gap-3">
        {(["critical", "high", "medium", "low"] as const).map((sev) => (
          <div key={sev} className="glass-raised px-4 py-3 flex items-center gap-3 min-w-[120px]">
            <SeverityBadge severity={sev} />
            <span className="font-mono-display text-lg text-text-0 tabular-nums">{counts[sev]}</span>
          </div>
        ))}
        <div className="glass-raised px-4 py-3 flex items-center gap-3 min-w-[140px]">
          <span className="text-xs font-mono-display text-text-2 uppercase tracking-wider">Unresolved</span>
          <span className="font-mono-display text-lg text-text-0 tabular-nums">{unresolvedCount}</span>
        </div>
      </div>

      {/* Findings table */}
      {findings.length > 0 ? (
        <div className="glass overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-0 bg-surface-2/50">
                  <th className="text-left py-3 px-4 text-text-3 font-medium text-xs">Severity</th>
                  <th className="text-left py-3 px-4 text-text-3 font-medium text-xs">Rule</th>
                  <th className="text-left py-3 px-4 text-text-3 font-medium text-xs">File</th>
                  <th className="text-left py-3 px-4 text-text-3 font-medium text-xs">Message</th>
                  <th className="text-left py-3 px-4 text-text-3 font-medium text-xs">Status</th>
                </tr>
              </thead>
              <tbody>
                {findings.map((f, i) => (
                  <tr key={i} className="border-b border-border-0/50 hover:bg-surface-2/30 transition-colors">
                    <td className="py-3 px-4">
                      <SeverityBadge severity={f.severity} />
                    </td>
                    <td className="py-3 px-4 font-mono-display text-xs text-text-1">{f.rule_id ?? "—"}</td>
                    <td className="py-3 px-4 font-mono-display text-xs text-accent">
                      {f.file_path ?? "—"}
                      {f.line_number != null && <span className="text-text-3">:{f.line_number}</span>}
                    </td>
                    <td className="py-3 px-4 text-xs text-text-2 max-w-[300px]">
                      <div>{f.message ?? "—"}</div>
                      {f.remediation && (
                        <div className="text-success mt-1 text-[11px]">Fix: {f.remediation}</div>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      {f.resolved ? (
                        <span className="inline-flex items-center gap-1 text-xs text-success">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M5 12l5 5L20 7" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                          Resolved
                        </span>
                      ) : (
                        <span className="text-xs text-warning">Open</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : hasContent ? (
        <div className="glass p-8 text-center">
          <div className="text-success text-4xl mb-2">&#10003;</div>
          <p className="text-sm text-text-1">No security findings.</p>
        </div>
      ) : (
        <RawJsonInspector data={artifact.content} warning="No recognized security report fields found. Showing raw content." />
      )}
    </div>
  );
}
