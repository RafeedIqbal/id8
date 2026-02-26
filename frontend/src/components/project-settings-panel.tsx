"use client";

import { useState, useEffect } from "react";
import { useUpdateProject, useRestartProject } from "@/lib/hooks";
import type { Project } from "@/types/domain";
import { DEFAULT_STACK, STACK_OPTIONS, validateStackHostability } from "@/types/stack";
import type { StackJson } from "@/types/stack";

export function ProjectSettingsPanel({
  project,
  onClose,
}: {
  project: Project;
  onClose: () => void;
}) {
  const [prompt, setPrompt] = useState(project.initialPrompt);
  const [stack, setStack] = useState<StackJson>(
    (project.stackJson as unknown as StackJson) ?? DEFAULT_STACK
  );
  const [hostError, setHostError] = useState<string | null>(null);
  const [showRestartConfirm, setShowRestartConfirm] = useState(false);

  const updateProject = useUpdateProject(project.id);
  const restartProject = useRestartProject(project.id);

  useEffect(() => {
    setHostError(validateStackHostability(stack));
  }, [stack]);

  function updateStack<K extends keyof StackJson>(key: K, value: StackJson[K]) {
    setStack((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    const changes: { initial_prompt?: string; stack_json?: StackJson } = {};
    if (prompt.trim() !== project.initialPrompt) {
      changes.initial_prompt = prompt.trim();
    }
    const currentStack = (project.stackJson as unknown as StackJson) ?? DEFAULT_STACK;
    if (JSON.stringify(stack) !== JSON.stringify(currentStack)) {
      changes.stack_json = stack;
    }
    if (!changes.initial_prompt && !changes.stack_json) return;
    await updateProject.mutateAsync(changes);
    onClose();
  }

  async function handleSaveAndRestart() {
    await handleSave();
    await restartProject.mutateAsync();
    onClose();
  }

  const isPending = updateProject.isPending || restartProject.isPending;

  return (
    <div className="glass p-5 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-mono-display text-text-2 tracking-widest uppercase">
          Project Settings
        </h2>
        <button onClick={onClose} className="text-text-3 hover:text-text-1 text-sm">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      {/* Prompt */}
      <div>
        <label className="block text-sm font-medium text-text-1 mb-2">
          Initial Prompt
        </label>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          className="resize-y min-h-[100px] w-full"
        />
      </div>

      {/* Stack config */}
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

      {/* Errors */}
      {updateProject.isError && (
        <div className="text-xs text-error bg-error-bg border border-error-dim rounded-lg p-2.5">
          {(updateProject.error as Error).message}
        </div>
      )}
      {restartProject.isError && (
        <div className="text-xs text-error bg-error-bg border border-error-dim rounded-lg p-2.5">
          {(restartProject.error as Error).message}
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-wrap gap-2 pt-2">
        <button
          onClick={handleSave}
          disabled={isPending || !!hostError}
          className="btn btn-primary"
        >
          {updateProject.isPending ? "Saving\u2026" : "Save"}
        </button>
        {showRestartConfirm ? (
          <button
            onClick={handleSaveAndRestart}
            disabled={isPending || !!hostError}
            className="btn bg-warning text-surface-0 hover:bg-warning/90"
          >
            {restartProject.isPending ? "Restarting\u2026" : "Confirm Save & Restart"}
          </button>
        ) : (
          <button
            onClick={() => setShowRestartConfirm(true)}
            disabled={isPending || !!hostError}
            className="btn btn-ghost"
          >
            Save &amp; Restart
          </button>
        )}
        <button onClick={onClose} className="btn btn-ghost">
          Cancel
        </button>
      </div>
    </div>
  );
}
