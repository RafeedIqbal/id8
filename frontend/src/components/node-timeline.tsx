"use client";

import { PIPELINE_NODES, NODE_LABELS } from "@/lib/constants";
import type { RunTimelineEvent } from "@/types/domain";
import { formatTime } from "@/lib/utils";
import { cn } from "@/lib/utils";

type NodeState = "completed" | "current" | "pending" | "failed";

function getNodeStates(
  currentNode: string | undefined,
  timeline: RunTimelineEvent[],
  isFailed: boolean
): Map<string, { state: NodeState; timestamp?: string }> {
  const states = new Map<string, { state: NodeState; timestamp?: string }>();

  // Build set of visited nodes from timeline
  const visited = new Set<string>();
  const timestamps = new Map<string, string>();
  for (const event of timeline) {
    visited.add(event.toNode);
    timestamps.set(event.toNode, event.createdAt);
    if (event.fromNode) visited.add(event.fromNode);
  }

  const currentIdx = currentNode
    ? PIPELINE_NODES.indexOf(currentNode as (typeof PIPELINE_NODES)[number])
    : -1;

  for (const node of PIPELINE_NODES) {
    const idx = PIPELINE_NODES.indexOf(node);
    let state: NodeState = "pending";

    if (node === currentNode) {
      state = isFailed ? "failed" : "current";
    } else if (visited.has(node) || (currentIdx >= 0 && idx < currentIdx)) {
      state = "completed";
    }

    states.set(node, { state, timestamp: timestamps.get(node) });
  }

  return states;
}

function NodeDot({ state }: { state: NodeState }) {
  return (
    <div
      className={cn(
        "timeline-dot",
        state === "completed" && "timeline-dot-completed",
        state === "current" && "timeline-dot-current",
        state === "failed" && "timeline-dot-failed"
      )}
    >
      {state === "completed" && (
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--color-surface-0)"
          strokeWidth="3.5"
          className="absolute top-[1px] left-[1px]"
        >
          <path d="M5 12l5 5L19 7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </div>
  );
}

export function NodeTimeline({
  currentNode,
  timeline = [],
  status,
}: {
  currentNode?: string;
  timeline?: RunTimelineEvent[];
  status?: string;
}) {
  const isFailed = status === "failed";
  const nodeStates = getNodeStates(currentNode, timeline, isFailed);

  // Filter out EndFailed unless we're actually in failed state
  const visibleNodes = PIPELINE_NODES.filter(
    (n) => n !== "EndFailed" || isFailed
  );

  return (
    <div className="relative py-2">
      <div className="timeline-trace" />

      {visibleNodes.map((node) => {
        const info = nodeStates.get(node) ?? { state: "pending" as NodeState };
        const label = NODE_LABELS[node] ?? node;

        return (
          <div key={node} className="timeline-node">
            <NodeDot state={info.state} />
            <div className="flex items-baseline justify-between gap-4 min-h-[32px] pt-[6px]">
              <span
                className={cn(
                  "text-sm font-medium",
                  info.state === "completed" && "text-text-1",
                  info.state === "current" && "text-accent",
                  info.state === "failed" && "text-error",
                  info.state === "pending" && "text-text-3"
                )}
              >
                {label}
              </span>
              {info.timestamp && (
                <span className="font-mono-display text-[11px] text-text-3 tabular-nums">
                  {formatTime(info.timestamp)}
                </span>
              )}
              {info.state === "current" && !isFailed && (
                <span className="font-mono-display text-[11px] text-accent animate-pulse">
                  Processing\u2026
                </span>
              )}
              {info.state === "failed" && (
                <span className="font-mono-display text-[11px] text-error">
                  Error
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
