import type { RunTimelineEvent } from "@/types/domain";

export const TERMINAL_NODES = new Set(["EndSuccess", "EndFailed"]);

const ATTEMPT_START_EVENTS = new Set([
  "orchestrator.run_started",
  "orchestrator.run_resumed",
  "orchestrator.run_replayed",
  "orchestrator.run_requeued",
]);

function isFailureOutcome(outcome: string | undefined): boolean {
  if (!outcome) return false;
  const normalized = outcome.trim().toLowerCase();
  return normalized === "failure" || normalized === "failed";
}

function isNonTerminal(node: string | undefined): node is string {
  return Boolean(node && !TERMINAL_NODES.has(node));
}

export function getLatestAttemptTimeline(
  timeline: RunTimelineEvent[] | undefined
): RunTimelineEvent[] {
  const events = timeline ?? [];
  if (events.length <= 1) return events;

  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i];
    if (ATTEMPT_START_EVENTS.has(event.eventType)) {
      return events.slice(i);
    }
  }
  return events;
}

export function inferFailureNode(
  currentNode: string | undefined,
  timeline: RunTimelineEvent[] | undefined,
  isFailed: boolean
): string | undefined {
  if (!isFailed) return undefined;
  if (isNonTerminal(currentNode)) return currentNode;

  const events = getLatestAttemptTimeline(timeline);

  // Prefer the newest concrete transition into EndFailed.
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i];
    if (
      event.eventType === "orchestrator.node_transition" &&
      event.toNode === "EndFailed" &&
      isNonTerminal(event.fromNode) &&
      isFailureOutcome(event.outcome)
    ) {
      return event.fromNode;
    }
  }

  // Fallback for explicit run_failed events that still carry a real source node.
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i];
    if (
      event.eventType === "orchestrator.run_failed" &&
      isNonTerminal(event.fromNode)
    ) {
      return event.fromNode;
    }
  }

  // Last resort: latest non-terminal node observed in timeline.
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i];
    if (isNonTerminal(event.fromNode)) return event.fromNode;
    if (isNonTerminal(event.toNode)) return event.toNode;
  }

  return undefined;
}

export function resolveResumeNode(
  currentNode: string | undefined,
  timeline: RunTimelineEvent[] | undefined,
  isFailed: boolean
): string {
  if (isNonTerminal(currentNode)) return currentNode;
  return inferFailureNode(currentNode, timeline, isFailed) ?? "IngestPrompt";
}

