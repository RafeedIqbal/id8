"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useDeleteProject } from "@/lib/hooks";

export function DeleteProjectModal({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const [confirmation, setConfirmation] = useState("");
  const deleteProject = useDeleteProject(projectId);
  const router = useRouter();

  const shortId = projectId.slice(0, 8);
  const isConfirmed = confirmation === shortId;

  async function handleDelete() {
    if (!isConfirmed) return;
    await deleteProject.mutateAsync();
    router.push("/");
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <button
        type="button"
        className="absolute inset-0 bg-surface-0/80 backdrop-blur-sm border-0"
        onClick={onClose}
        aria-label="Close"
      />
      <div className="relative glass p-6 max-w-md w-full mx-4 space-y-4">
        <h2 className="text-lg font-semibold text-error">Delete Project</h2>
        <p className="text-sm text-text-2">
          This action will soft-delete the project. It will no longer appear in the project list.
        </p>
        <div>
          <label className="block text-xs text-text-3 mb-1.5 font-mono-display">
            Type <span className="text-error font-semibold">{shortId}</span> to confirm
          </label>
          <input
            type="text"
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
            placeholder={shortId}
            className="w-full font-mono-display text-sm"
            autoFocus
          />
        </div>

        {deleteProject.isError && (
          <div className="text-xs text-error bg-error-bg border border-error-dim rounded-lg p-2.5">
            {(deleteProject.error as Error).message}
          </div>
        )}

        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={handleDelete}
            disabled={!isConfirmed || deleteProject.isPending}
            className="btn bg-error text-surface-0 hover:bg-error/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {deleteProject.isPending ? "Deleting\u2026" : "Delete Project"}
          </button>
          <button onClick={onClose} className="btn btn-ghost">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
