"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import type { ApprovalStage, ModelProfile, DesignProvider, StitchAuthPayload } from "@/types/domain";

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
    mutationFn: (vars: { prompt: string; constraints?: Record<string, unknown> }) =>
      api.createProject(vars.prompt, vars.constraints),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
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
    mutationFn: (vars?: { resumeFromNode?: string; modelProfile?: ModelProfile }) =>
      api.createRun(projectId, { resume_from_node: vars?.resumeFromNode, model_profile: vars?.modelProfile }),
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
    mutationFn: (vars: { stage: ApprovalStage; decision: "approved" | "rejected"; notes?: string; stitchAuth?: StitchAuthPayload }) =>
      api.submitApproval(projectId, vars.stage, vars.decision, vars.notes, vars.stitchAuth),
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
    mutationFn: (vars: { provider: DesignProvider; modelProfile: ModelProfile; constraints?: Record<string, unknown>; stitchAuth?: StitchAuthPayload }) =>
      api.generateDesign(projectId, vars.provider, vars.modelProfile, vars.constraints, undefined, vars.stitchAuth),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["artifacts", projectId] }),
  });
}

export function useSubmitDesignFeedback(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { feedbackText: string; targetScreenId?: string; targetComponentId?: string; stitchAuth?: StitchAuthPayload }) =>
      api.submitDesignFeedback(projectId, vars.feedbackText, vars.targetScreenId, vars.targetComponentId, undefined, vars.stitchAuth),
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
