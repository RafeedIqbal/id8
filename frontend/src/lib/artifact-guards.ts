/**
 * Type guard utilities for safely accessing artifact content fields.
 * Artifacts come from LLM-generated JSON — any field may be missing, null,
 * or an unexpected type. These helpers prevent runtime crashes.
 */

export function isString(value: unknown): value is string {
  return typeof value === "string";
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function safeString(value: unknown): string | undefined {
  return isString(value) ? value : undefined;
}

export function safeArray<T>(value: unknown, guard?: (item: unknown) => item is T): T[] {
  if (!Array.isArray(value)) return [];
  if (!guard) return value as T[];
  return value.filter(guard);
}

export function safeRecord(value: unknown): Record<string, unknown> | undefined {
  return isRecord(value) ? value : undefined;
}

export function safeNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function safeBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}
