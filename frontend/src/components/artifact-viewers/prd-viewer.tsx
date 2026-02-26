"use client";

import type { ProjectArtifact } from "@/types/domain";
import { isRecord, isString, safeString, safeArray, safeRecord } from "@/lib/artifact-guards";
import { RawJsonInspector } from "./raw-json-inspector";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h3 className="text-sm font-mono-display text-accent tracking-widest uppercase mb-3 pb-2 border-b border-border-0">
        {title}
      </h3>
      {children}
    </section>
  );
}

export function PrdViewer({ artifact }: { artifact: ProjectArtifact }) {
  const c = safeRecord(artifact.content);
  if (!c) {
    return <RawJsonInspector data={artifact.content} warning="Artifact content is not a valid object." />;
  }

  const summary = safeString(c.executive_summary);
  const rawStories = safeArray(c.user_stories);
  const userStories = rawStories.filter(isRecord);
  const scopeBoundaries = safeRecord(c.scope_boundaries);
  const scopeIn = safeArray(scopeBoundaries?.in_scope).filter(isString);
  const scopeOut = safeArray(scopeBoundaries?.out_of_scope).filter(isString);
  const rawEntities = safeArray(c.entity_list);
  const entities = rawEntities.filter(isRecord);
  const nonGoals = safeArray(c.non_goals).filter(isString);

  const hasStructuredContent = summary || userStories.length > 0 || entities.length > 0;

  return (
    <div className="space-y-2 animate-fade-in">
      {summary && (
        <Section title="Executive Summary">
          <p className="text-sm text-text-1 leading-relaxed whitespace-pre-wrap">{summary}</p>
        </Section>
      )}

      {userStories.length > 0 && (
        <Section title="User Stories">
          <div className="space-y-3">
            {userStories.map((story, i) => (
              <div key={i} className="glass-raised p-4">
                <div className="text-sm text-text-0 mb-1">
                  <span className="text-accent font-medium">As</span> {safeString(story.persona) ?? "a user"},{" "}
                  <span className="text-accent font-medium">I want to</span> {safeString(story.action) ?? "—"},{" "}
                  <span className="text-accent font-medium">so that</span> {safeString(story.benefit) ?? "—"}.
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {(scopeIn.length > 0 || scopeOut.length > 0) && (
        <Section title="Scope Boundaries">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {scopeIn.length > 0 && (
              <div className="glass-raised p-4">
                <h4 className="text-xs font-mono-display text-success tracking-wide uppercase mb-2">In Scope</h4>
                <ul className="space-y-1.5">
                  {scopeIn.map((item, i) => (
                    <li key={i} className="text-sm text-text-1 flex items-start gap-2">
                      <span className="text-success mt-0.5">+</span> {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {scopeOut.length > 0 && (
              <div className="glass-raised p-4">
                <h4 className="text-xs font-mono-display text-error tracking-wide uppercase mb-2">Out of Scope</h4>
                <ul className="space-y-1.5">
                  {scopeOut.map((item, i) => (
                    <li key={i} className="text-sm text-text-1 flex items-start gap-2">
                      <span className="text-error mt-0.5">&minus;</span> {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Section>
      )}

      {entities.length > 0 && (
        <Section title="Entities">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {entities.map((entity, i) => (
              <div key={i} className="glass-raised p-4">
                <div className="font-mono-display text-sm text-accent mb-1">{safeString(entity.name) ?? "—"}</div>
                <p className="text-xs text-text-2">{safeString(entity.description) ?? ""}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {nonGoals.length > 0 && (
        <Section title="Non-Goals">
          <ul className="space-y-1.5">
            {nonGoals.map((item, i) => (
              <li key={i} className="text-sm text-text-2 flex items-start gap-2">
                <span className="text-text-3 mt-0.5">&times;</span> {item}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {!hasStructuredContent && (
        <RawJsonInspector data={artifact.content} warning="No recognized PRD fields found. Showing raw content." />
      )}
    </div>
  );
}
