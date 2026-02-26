"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import type { ApprovalStage, ModelProfile, DesignProvider } from "@/types/domain";
import type { StackJson } from "@/types/stack";

// ── Projects ──────────────────────────────────────────────────
export function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: api.listProjects, staleTime: 10_000 });
}

export function useProject(id: string, opts?: { refetchInterval?: number }) {
  return useQuery({
    queryKey: ["project", id],
    queryFn: () => api.getProject(id),
    enabled: !!id,
    refetchInterval: opts?.refetchInterval,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { prompt: string; constraints?: Record<string, unknown>; stackJson?: StackJson }) =>
      api.createProject(vars.prompt, vars.constraints, vars.stackJson),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useDeleteProject(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.deleteProject(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });
}

export function useUpdateProject(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { initial_prompt?: string; stack_json?: StackJson }) =>
      api.updateProject(projectId, vars),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useRestartProject(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.restartProject(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["latestRun", projectId] });
      qc.invalidateQueries({ queryKey: ["artifacts", projectId] });
    },
  });
}

// ── Runs ──────────────────────────────────────────────────────
export function useLatestRun(projectId: string, opts?: { refetchInterval?: number }) {
  return useQuery({
    queryKey: ["latestRun", projectId],
    queryFn: () => api.getLatestRun(projectId),
    enabled: !!projectId,
    refetchInterval: opts?.refetchInterval,
  });
}

export function useCreateRun(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars?: {
      resumeFromNode?: string;
      modelProfile?: ModelProfile;
      replayMode?: "retry_failed" | "replay_from_node";
    }) =>
      api.createRun(projectId, {
        resume_from_node: vars?.resumeFromNode,
        model_profile: vars?.modelProfile,
        replay_mode: vars?.replayMode,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["latestRun", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });
}

// ── Artifacts ─────────────────────────────────────────────────
export function useArtifacts(projectId: string, opts?: { refetchInterval?: number }) {
  return useQuery({
    queryKey: ["artifacts", projectId],
    queryFn: () => api.listArtifacts(projectId),
    enabled: !!projectId,
    refetchInterval: opts?.refetchInterval,
  });
}

// ── Approvals ─────────────────────────────────────────────────
export function useSubmitApproval(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { stage: ApprovalStage; decision: "approved" | "rejected"; notes?: string; artifactId?: string }) =>
      api.submitApproval(projectId, vars.stage, vars.decision, vars.notes, vars.artifactId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["latestRun", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["artifacts", projectId] });
    },
  });
}

// ── Design ────────────────────────────────────────────────────
export function useDesignTools() {
  return useQuery({ queryKey: ["designTools"], queryFn: api.listDesignTools, staleTime: 60_000 });
}

export function useGenerateDesign(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { provider: DesignProvider; modelProfile: ModelProfile; constraints?: Record<string, unknown> }) =>
      api.generateDesign(projectId, vars.provider, vars.modelProfile, vars.constraints),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["artifacts", projectId] }),
  });
}

export function useSubmitDesignFeedback(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { feedbackText: string; targetScreenId?: string; targetComponentId?: string }) =>
      api.submitDesignFeedback(projectId, vars.feedbackText, vars.targetScreenId, vars.targetComponentId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["artifacts", projectId] }),
  });
}

// ── Deploy ────────────────────────────────────────────────────
export function useDeploy(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.deployProject(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["latestRun", projectId] });
    },
  });
}
