"use client";

import { useState } from "react";

function JsonNode({ data, depth = 0 }: { data: unknown; depth?: number }) {
  const [expanded, setExpanded] = useState(depth < 2);

  if (data === null || data === undefined) {
    return <span className="text-text-3 italic">null</span>;
  }

  if (typeof data === "string") {
    return <span className="text-success">&quot;{data.length > 200 ? data.slice(0, 200) + "…" : data}&quot;</span>;
  }

  if (typeof data === "number" || typeof data === "boolean") {
    return <span className="text-accent">{String(data)}</span>;
  }

  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="text-text-3">[]</span>;
    return (
      <span>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-text-2 hover:text-text-1 font-mono-display"
        >
          {expanded ? "▼" : "▶"} [{data.length}]
        </button>
        {expanded && (
          <div style={{ paddingLeft: 16 }}>
            {data.map((item, i) => (
              <div key={i} className="py-0.5">
                <span className="text-text-3 text-[10px] mr-1">{i}:</span>
                <JsonNode data={item} depth={depth + 1} />
              </div>
            ))}
          </div>
        )}
      </span>
    );
  }

  if (typeof data === "object") {
    const entries = Object.entries(data as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-text-3">{"{}"}</span>;
    return (
      <span>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-text-2 hover:text-text-1 font-mono-display"
        >
          {expanded ? "▼" : "▶"} {"{"}
          {entries.length}
          {"}"}
        </button>
        {expanded && (
          <div style={{ paddingLeft: 16 }}>
            {entries.map(([key, val]) => (
              <div key={key} className="py-0.5">
                <span className="text-warning text-xs">{key}</span>
                <span className="text-text-3 mx-1">:</span>
                <JsonNode data={val} depth={depth + 1} />
              </div>
            ))}
          </div>
        )}
      </span>
    );
  }

  return <span className="text-text-3">{String(data)}</span>;
}

export function RawJsonInspector({
  data,
  warning,
}: {
  data: unknown;
  warning?: string;
}) {
  return (
    <div className="animate-fade-in min-w-0">
      {warning && (
        <div className="mb-4 px-4 py-3 rounded-lg bg-warning-bg border border-warning-dim text-warning text-xs font-mono-display">
          {warning}
        </div>
      )}
      <div className="glass p-4 overflow-auto max-h-[600px] max-w-full text-xs font-mono-display leading-relaxed break-words">
        <JsonNode data={data} />
      </div>
    </div>
  );
}
