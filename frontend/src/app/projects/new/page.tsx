"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useCreateProject } from "@/lib/hooks";
import { Breadcrumbs } from "@/components/breadcrumbs";
export default function NewProjectPage() {
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const create = useCreateProject();
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !prompt.trim()) return;

    const project = await create.mutateAsync({
      title: title.trim(),
      prompt: prompt.trim(),
    });
    router.push(`/projects/${project.id}`);
  }

  return (
    <div className="animate-fade-in flex flex-col min-h-[calc(100vh-8rem)]">
      <div>
        <Breadcrumbs items={[{ label: "Projects", href: "/" }, { label: "New Project" }]} />
      </div>

      <div className="flex-1 flex flex-col items-center justify-center pb-20">
        <div className="w-full max-w-2xl px-4">
          <h1 className="text-2xl font-semibold text-text-0 mb-2">New Project</h1>
          <p className="text-sm text-text-2 mb-8">
            Describe what you want to build. Be specific about features, target users, and any technical requirements.
          </p>

          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Title */}
            <div>
              <label className="block text-sm font-medium text-text-1 mb-2">
                Project Title
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g., Team Task Board"
                className="w-full"
                required
              />
            </div>

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
                disabled={!title.trim() || !prompt.trim() || create.isPending}
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
    </div>
  );
}
