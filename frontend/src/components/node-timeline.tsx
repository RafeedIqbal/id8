"use client";

import { useEffect, useState } from "react";
import { PIPELINE_NODES, NODE_LABELS } from "@/lib/constants";
import type { RunTimelineEvent } from "@/types/domain";
import { formatTime } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { inferFailureNode } from "@/lib/run-failure";

type NodeState = "completed" | "current" | "pending" | "failed";

function getNodeStates(
  currentNode: string | undefined,
  timeline: RunTimelineEvent[],
  isFailed: boolean,
  failedNode: string | undefined
): Map<string, { state: NodeState; timestamp?: string }> {
  const states = new Map<string, { state: NodeState; timestamp?: string }>();

  // Build set of nodes actually entered (toNode), plus best-effort timestamps.
  const visited = new Set<string>();
  const timestamps = new Map<string, string>();
  for (const event of timeline) {
    visited.add(event.toNode);
    timestamps.set(event.toNode, event.createdAt);
    if (event.fromNode && !timestamps.has(event.fromNode)) {
      timestamps.set(event.fromNode, event.createdAt);
    }
  }

  const currentIdx = !isFailed && currentNode
    ? PIPELINE_NODES.indexOf(currentNode as (typeof PIPELINE_NODES)[number])
    : -1;

  for (const node of PIPELINE_NODES) {
    const idx = PIPELINE_NODES.indexOf(node);
    let state: NodeState = "pending";

    if (isFailed && failedNode) {
      if (node === failedNode) {
        state = "failed";
      } else if (node !== "EndFailed" && visited.has(node)) {
        state = "completed";
      }
    } else {
      if (node === currentNode) {
        state = isFailed ? "failed" : "current";
      } else if (visited.has(node) || (currentIdx >= 0 && idx < currentIdx)) {
        state = "completed";
      }
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
  onReplay,
  isActionPending = false,
}: {
  currentNode?: string;
  timeline?: RunTimelineEvent[];
  status?: string;
  onReplay?: (node: string, mode: "retry_failed" | "replay_from_node") => void;
  isActionPending?: boolean;
}) {
  const isFailed = status === "failed";
  const isTerminal = status === "failed" || status === "deployed";
  const failedNode = inferFailureNode(currentNode, timeline, isFailed);
  const nodeStates = getNodeStates(currentNode, timeline, isFailed, failedNode);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  useEffect(() => {
    setSelectedNode(null);
  }, [currentNode, status, timeline.length]);

  const defaultReplayMode: "retry_failed" | "replay_from_node" = isFailed
    ? "retry_failed"
    : "replay_from_node";

  // Hide EndFailed when we can map failure to a concrete pipeline node.
  const visibleNodes = PIPELINE_NODES.filter(
    (n) => n !== "EndFailed" || (isFailed && !failedNode)
  );

  return (
    <div className="relative py-2">
      <div className="timeline-trace" />

      {visibleNodes.map((node) => {
        const info = nodeStates.get(node) ?? { state: "pending" as NodeState };
        const label = NODE_LABELS[node] ?? node;
        const canOpenMenu = Boolean(onReplay) && isTerminal && node !== "EndSuccess" && node !== "EndFailed";
        const canRestartFromNode = canOpenMenu && info.state !== "pending";
        const menuOpen = selectedNode === node && canOpenMenu;

        return (
          <div key={node} className="timeline-node">
            <NodeDot state={info.state} />
            <button
              type="button"
              onClick={() => {
                if (!canOpenMenu || isActionPending) return;
                setSelectedNode((prev) => (prev === node ? null : node));
              }}
              disabled={!canOpenMenu || isActionPending}
              className={cn(
                "w-full flex items-baseline justify-between gap-2 min-h-[32px] pt-[6px] -ml-1 pl-1 rounded-md text-left transition-colors",
                canOpenMenu && !isActionPending && "hover:bg-surface-2 cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent/40",
                (!canOpenMenu || isActionPending) && "cursor-default"
              )}
            >
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
              <div className="flex items-center gap-2">
                {canOpenMenu && (
                  <span className="text-[10px] font-mono-display text-text-3">
                    {menuOpen ? "Options" : "Press to restart"}
                  </span>
                )}
                {info.timestamp && (
                  <span className="font-mono-display text-[11px] text-text-3 tabular-nums">
                    {formatTime(info.timestamp)}
                  </span>
                )}
                {info.state === "current" && !isFailed && (
                  <span className="font-mono-display text-[11px] text-accent animate-pulse">
                    Processing&hellip;
                  </span>
                )}
                {info.state === "failed" && !canOpenMenu && (
                  <span className="font-mono-display text-[11px] text-error">
                    Error
                  </span>
                )}
              </div>
            </button>
            {menuOpen && (
              <div className="mt-1 pl-1">
                {canRestartFromNode ? (
                  <button
                    type="button"
                    onClick={() => {
                      if (!onReplay || isActionPending) return;
                      onReplay(node, defaultReplayMode);
                      setSelectedNode(null);
                    }}
                    disabled={isActionPending}
                    className={cn(
                      "text-[11px] font-mono-display rounded-md px-2 py-1 border transition-colors",
                      isFailed
                        ? "text-error border-error/30 hover:bg-error-bg"
                        : "text-accent border-accent/30 hover:bg-accent-bg",
                      isActionPending && "opacity-60 cursor-not-allowed"
                    )}
                  >
                    {isActionPending
                      ? "Restarting\u2026"
                      : isFailed
                        ? "Retry From This Step"
                        : "Replay From This Step"}
                  </button>
                ) : (
                  <div className="text-[11px] font-mono-display text-text-3">
                    This step was not reached in the latest run.
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
