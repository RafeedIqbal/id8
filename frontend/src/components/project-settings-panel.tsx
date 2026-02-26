"use client";

import { useState } from "react";
import { useUpdateProject, useRestartProject } from "@/lib/hooks";
import type { Project } from "@/types/domain";
import { DEFAULT_STACK, FIXED_STACK_LABELS } from "@/types/stack";

export function ProjectSettingsPanel({
  project,
  onClose,
}: {
  project: Project;
  onClose: () => void;
}) {
  const [title, setTitle] = useState(project.title);
  const [prompt, setPrompt] = useState(project.initialPrompt);
  const [showRestartConfirm, setShowRestartConfirm] = useState(false);

  const updateProject = useUpdateProject(project.id);
  const restartProject = useRestartProject(project.id);

  async function handleSave() {
    const changes: { title?: string; initial_prompt?: string } = {};
    if (title.trim() !== project.title) {
      changes.title = title.trim();
    }
    if (prompt.trim() !== project.initialPrompt) {
      changes.initial_prompt = prompt.trim();
    }
    if (!changes.title && !changes.initial_prompt) return;
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
          Project Title
        </label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="w-full"
        />
      </div>

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
          Runtime Profile
        </label>
        <div className="grid grid-cols-2 gap-3">
          {FIXED_STACK_LABELS.map(({ key, label }) => (
            <div key={key}>
              <label className="block text-[10px] font-mono-display text-text-3 tracking-widest uppercase mb-1">
                {label}
              </label>
              <div className="w-full text-xs bg-surface-2 border border-border-1 rounded-lg px-3 py-2">
                {DEFAULT_STACK[key]}
              </div>
            </div>
          ))}
        </div>
        <p className="text-xs text-text-3 mt-2">
          Stack selection is locked to ensure zero-config Vercel deployments.
        </p>
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
          disabled={isPending || !title.trim() || !prompt.trim()}
          className="btn btn-primary"
        >
          {updateProject.isPending ? "Saving\u2026" : "Save"}
        </button>
        {showRestartConfirm ? (
          <button
            onClick={handleSaveAndRestart}
            disabled={isPending || !title.trim() || !prompt.trim()}
            className="btn bg-warning text-surface-0 hover:bg-warning/90"
          >
            {restartProject.isPending ? "Restarting\u2026" : "Confirm Save & Restart"}
          </button>
        ) : (
          <button
            onClick={() => setShowRestartConfirm(true)}
            disabled={isPending || !title.trim() || !prompt.trim()}
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
