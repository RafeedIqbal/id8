"use client";

import type { ProjectArtifact } from "@/types/domain";

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
  const c = artifact.content as Record<string, unknown>;
  const summary = c.executive_summary as string | undefined;
  const userStories = c.user_stories as Array<{ persona?: string; action?: string; benefit?: string }> | undefined;
  const scopeBoundaries = c.scope_boundaries as { in_scope?: string[]; out_of_scope?: string[] } | undefined;
  const scopeIn = scopeBoundaries?.in_scope;
  const scopeOut = scopeBoundaries?.out_of_scope;
  const entities = c.entity_list as Array<{ name?: string; description?: string }> | undefined;
  const nonGoals = c.non_goals as string[] | undefined;

  return (
    <div className="space-y-2 animate-fade-in">
      {summary && (
        <Section title="Executive Summary">
          <p className="text-sm text-text-1 leading-relaxed whitespace-pre-wrap">{summary}</p>
        </Section>
      )}

      {userStories && userStories.length > 0 && (
        <Section title="User Stories">
          <div className="space-y-3">
            {userStories.map((story, i) => (
              <div key={i} className="glass-raised p-4">
                <div className="text-sm text-text-0 mb-1">
                  <span className="text-accent font-medium">As</span> {story.persona ?? "a user"},{" "}
                  <span className="text-accent font-medium">I want to</span> {story.action ?? "—"},{" "}
                  <span className="text-accent font-medium">so that</span> {story.benefit ?? "—"}.
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {(scopeIn || scopeOut) && (
        <Section title="Scope Boundaries">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {scopeIn && (
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
            {scopeOut && (
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

      {entities && entities.length > 0 && (
        <Section title="Entities">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {entities.map((entity, i) => (
              <div key={i} className="glass-raised p-4">
                <div className="font-mono-display text-sm text-accent mb-1">{entity.name}</div>
                <p className="text-xs text-text-2">{entity.description}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {nonGoals && nonGoals.length > 0 && (
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

      {/* Fallback: show raw JSON if content doesn't match expected structure */}
      {!summary && !userStories && !entities && (
        <Section title="Raw Content">
          <pre className="text-xs">{JSON.stringify(artifact.content, null, 2)}</pre>
        </Section>
      )}
    </div>
  );
}
