"use client";

import { useState } from "react";
import type { ProjectArtifact } from "@/types/domain";
import { cn } from "@/lib/utils";
import { isRecord, safeString, safeArray, safeRecord } from "@/lib/artifact-guards";
import { RawJsonInspector } from "./raw-json-inspector";

interface FileEntry {
  path: string;
  content?: string;
  language?: string;
}

function toFileEntry(raw: unknown): FileEntry | null {
  if (!isRecord(raw)) return null;
  const path = safeString(raw.path) ?? safeString(raw.file_path) ?? safeString(raw.file);
  if (!path) return null;
  return {
    path,
    content: safeString(raw.content),
    language: safeString(raw.language),
  };
}

type TreeMap = Map<string, FileEntry | TreeMap>;

function buildTree(files: FileEntry[]): TreeMap {
  const root: TreeMap = new Map();
  for (const file of files) {
    const parts = file.path.split("/");
    let current: TreeMap = root;
    for (let i = 0; i < parts.length - 1; i++) {
      if (!current.has(parts[i])) current.set(parts[i], new Map() as TreeMap);
      current = current.get(parts[i]) as TreeMap;
    }
    current.set(parts[parts.length - 1], file);
  }
  return root;
}

function TreeNode({
  name,
  value,
  depth,
  selectedPath,
  onSelect,
}: {
  name: string;
  value: unknown;
  depth: number;
  selectedPath: string;
  onSelect: (file: FileEntry) => void;
}) {
  const [expanded, setExpanded] = useState(depth < 2);
  const isDir = value instanceof Map;
  const isFile = !isDir && typeof value === "object" && value !== null;

  if (isDir) {
    const entries = Array.from((value as Map<string, unknown>).entries()).sort(
      ([, a], [, b]) => {
        const aDir = a instanceof Map ? 0 : 1;
        const bDir = b instanceof Map ? 0 : 1;
        return aDir - bDir;
      }
    );

    return (
      <div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 w-full text-left py-1 px-2 rounded hover:bg-surface-2 text-xs text-text-2 hover:text-text-1 transition-colors"
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className={cn("transition-transform", expanded && "rotate-90")}
          >
            <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="var(--color-warning-dim)" stroke="none">
            <path d="M2 6a2 2 0 012-2h5l2 2h9a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
          </svg>
          <span>{name}</span>
        </button>
        {expanded && entries.map(([key, val]) => (
          <TreeNode key={key} name={key} value={val} depth={depth + 1} selectedPath={selectedPath} onSelect={onSelect} />
        ))}
      </div>
    );
  }

  if (isFile) {
    const file = value as FileEntry;
    return (
      <button
        onClick={() => onSelect(file)}
        className={cn(
          "flex items-center gap-1.5 w-full text-left py-1 px-2 rounded text-xs transition-colors",
          selectedPath === file.path
            ? "bg-accent-bg text-accent"
            : "text-text-2 hover:bg-surface-2 hover:text-text-1"
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" />
        </svg>
        <span>{name}</span>
      </button>
    );
  }

  return null;
}

export function CodeViewer({ artifact }: { artifact: ProjectArtifact }) {
  const c = safeRecord(artifact.content);
  const files = c ? safeArray(c.files).map(toFileEntry).filter((f): f is FileEntry => f !== null) : [];
  const buildCmd = c ? safeString(c.build_command) : undefined;
  const testCmd = c ? safeString(c.test_command) : undefined;

  const [selected, setSelected] = useState<FileEntry | null>(files[0] ?? null);

  if (!c) {
    return <RawJsonInspector data={artifact.content} warning="Artifact content is not a valid object." />;
  }

  if (files.length === 0) {
    return <RawJsonInspector data={artifact.content} warning="No files found in code snapshot. Showing raw content." />;
  }

  const tree = buildTree(files);

  return (
    <div className="animate-fade-in space-y-4">
      {/* Build/test commands */}
      {(buildCmd || testCmd) && (
        <div className="flex flex-wrap gap-3 mb-4">
          {buildCmd && (
            <div className="glass-raised px-4 py-2 flex items-center gap-2 text-xs">
              <span className="text-text-3 font-mono-display">build:</span>
              <code className="text-accent">{buildCmd}</code>
            </div>
          )}
          {testCmd && (
            <div className="glass-raised px-4 py-2 flex items-center gap-2 text-xs">
              <span className="text-text-3 font-mono-display">test:</span>
              <code className="text-accent">{testCmd}</code>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-4">
        {/* File tree */}
        <div className="glass p-2 lg:max-h-[600px] overflow-y-auto">
          <div className="text-[10px] font-mono-display text-text-3 tracking-widest uppercase px-3 py-2">
            Files ({files.length})
          </div>
          {Array.from(tree.entries()).map(([key, val]) => (
            <TreeNode
              key={key}
              name={key}
              value={val}
              depth={0}
              selectedPath={selected?.path ?? ""}
              onSelect={setSelected}
            />
          ))}
        </div>

        {/* Code panel */}
        <div className="glass p-0 overflow-hidden">
          {selected ? (
            <>
              <div className="px-4 py-2.5 border-b border-border-0 flex items-center gap-2">
                <span className="font-mono-display text-xs text-accent">{selected.path}</span>
                {selected.language && (
                  <span className="text-[10px] text-text-3 bg-surface-2 px-2 py-0.5 rounded">
                    {selected.language}
                  </span>
                )}
              </div>
              <pre className="p-4 overflow-auto max-h-[560px] text-xs leading-relaxed rounded-none border-none m-0">
                <code>{selected.content ?? "// No content"}</code>
              </pre>
            </>
          ) : (
            <div className="p-8 text-center text-sm text-text-3">Select a file to view</div>
          )}
        </div>
      </div>
    </div>
  );
}
