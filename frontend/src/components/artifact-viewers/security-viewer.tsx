"use client";

import type { ProjectArtifact } from "@/types/domain";

type Severity = "critical" | "high" | "medium" | "low";

interface Finding {
  severity?: Severity;
  rule_id?: string;
  rule?: string;
  file_path?: string;
  file?: string;
  line_number?: number;
  line?: number;
  message?: string;
  remediation?: string;
  resolved?: boolean;
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
  const c = artifact.content as Record<string, unknown>;
  const findings = ((c.findings ?? []) as Finding[]).sort(
    (a, b) => (SEVERITY_ORDER[a.severity ?? "low"] ?? 4) - (SEVERITY_ORDER[b.severity ?? "low"] ?? 4)
  );
  const summary = (c.summary ?? {}) as Partial<Record<Severity | "total", number>>;

  const counts = {
    critical: summary.critical ?? 0,
    high: summary.high ?? 0,
    medium: summary.medium ?? 0,
    low: summary.low ?? 0,
    total: summary.total ?? findings.length,
  };
  if (!summary.total) {
    for (const f of findings) {
      if (f.severity && f.severity in counts) counts[f.severity as Severity]++;
    }
    counts.total = findings.length;
  }
  const unresolvedCount = findings.filter((f) => !f.resolved).length;

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
                      <SeverityBadge severity={f.severity ?? "low"} />
                    </td>
                    <td className="py-3 px-4 font-mono-display text-xs text-text-1">{f.rule_id ?? f.rule ?? "—"}</td>
                    <td className="py-3 px-4 font-mono-display text-xs text-accent">
                      {f.file_path ?? f.file}
                      {(f.line_number ?? f.line) != null && <span className="text-text-3">:{f.line_number ?? f.line}</span>}
                    </td>
                    <td className="py-3 px-4 text-xs text-text-2 max-w-[300px]">
                      <div>{f.message}</div>
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
      ) : (
        <div className="glass p-8 text-center">
          <div className="text-success text-4xl mb-2">&#10003;</div>
          <p className="text-sm text-text-1">No security findings.</p>
        </div>
      )}
    </div>
  );
}
