"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useCreateProject } from "@/lib/hooks";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { DEFAULT_STACK, STACK_OPTIONS, validateStackHostability } from "@/types/stack";
import type { StackJson } from "@/types/stack";

export default function NewProjectPage() {
  const [prompt, setPrompt] = useState("");
  const [constraints, setConstraints] = useState("");
  const [constraintsError, setConstraintsError] = useState("");
  const [stack, setStack] = useState<StackJson>({ ...DEFAULT_STACK });
  const [hostError, setHostError] = useState<string | null>(null);
  const create = useCreateProject();
  const router = useRouter();

  useEffect(() => {
    setHostError(validateStackHostability(stack));
  }, [stack]);

  function parseConstraints(): Record<string, unknown> | undefined {
    if (!constraints.trim()) return undefined;
    try {
      const parsed = JSON.parse(constraints);
      setConstraintsError("");
      return parsed;
    } catch {
      setConstraintsError("Invalid JSON");
      return undefined;
    }
  }

  function updateStack<K extends keyof StackJson>(key: K, value: StackJson[K]) {
    setStack((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!prompt.trim() || hostError) return;

    const parsedConstraints = constraints.trim() ? parseConstraints() : undefined;
    if (constraints.trim() && !parsedConstraints) return;

    const project = await create.mutateAsync({
      prompt: prompt.trim(),
      constraints: parsedConstraints,
      stackJson: stack,
    });
    router.push(`/projects/${project.id}`);
  }

  return (
    <div className="animate-fade-in">
      <Breadcrumbs items={[{ label: "Projects", href: "/" }, { label: "New Project" }]} />

      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold text-text-0 mb-2">New Project</h1>
        <p className="text-sm text-text-2 mb-8">
          Describe what you want to build. Be specific about features, target users, and any technical requirements.
        </p>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Prompt */}
          <div>
            <label className="block text-sm font-medium text-text-1 mb-2">
              Project Description
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={8}
              placeholder="Describe the application you want to build&#10;&#10;e.g., A task management app with real-time collaboration, drag-and-drop kanban boards, and team workspaces. Users should be able to assign tasks, set deadlines, and track progress with burndown charts."
              className="resize-y min-h-[160px]"
              autoFocus
            />
            <div className="flex justify-end mt-1.5">
              <span className="text-[11px] font-mono-display text-text-3 tabular-nums">
                {prompt.length} chars
              </span>
            </div>
          </div>

          {/* Stack Configuration */}
          <div>
            <label className="block text-sm font-medium text-text-1 mb-2">
              Stack Configuration
            </label>
            <div className="grid grid-cols-2 gap-3">
              {(Object.keys(STACK_OPTIONS) as Array<keyof typeof STACK_OPTIONS>).map((key) => (
                <div key={key}>
                  <label className="block text-[10px] font-mono-display text-text-3 tracking-widest uppercase mb-1">
                    {key.replace(/_/g, " ")}
                  </label>
                  <select
                    value={stack[key]}
                    onChange={(e) => updateStack(key, e.target.value as never)}
                    className="w-full text-xs"
                    disabled={key === "hosting_frontend"}
                  >
                    {STACK_OPTIONS[key].map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
            {hostError && (
              <p className="text-xs text-error mt-2">{hostError}</p>
            )}
          </div>

          {/* Constraints */}
          <div>
            <label className="block text-sm font-medium text-text-1 mb-2">
              Constraints
              <span className="text-text-3 font-normal ml-1">(optional, JSON)</span>
            </label>
            <textarea
              value={constraints}
              onChange={(e) => {
                setConstraints(e.target.value);
                setConstraintsError("");
              }}
              rows={4}
              placeholder='{"auth": "supabase", "styling": "tailwind"}'
              className="resize-y font-mono-display text-xs"
            />
            {constraintsError && (
              <p className="text-xs text-error mt-1.5">{constraintsError}</p>
            )}
          </div>

          {/* Error */}
          {create.isError && (
            <div className="text-sm text-error bg-error-bg border border-error-dim rounded-lg p-3">
              {(create.error as Error).message}
            </div>
          )}

          {/* Submit */}
          <div className="flex items-center gap-4 pt-2">
            <button
              type="submit"
              disabled={!prompt.trim() || create.isPending || !!hostError}
              className="btn btn-primary"
            >
              {create.isPending ? (
                <>
                  <span className="w-4 h-4 border-2 border-surface-0 border-t-transparent rounded-full animate-spin" />
                  Creating&hellip;
                </>
              ) : (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Create Project
                </>
              )}
            </button>
            <button
              type="button"
              onClick={() => router.push("/")}
              className="btn btn-ghost"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
