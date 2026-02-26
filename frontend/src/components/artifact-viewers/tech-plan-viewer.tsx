"use client";

import type { ProjectArtifact } from "@/types/domain";
import { isRecord, safeString, safeArray, safeRecord } from "@/lib/artifact-guards";
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

function FolderTree({ tree }: { tree: unknown }) {
  if (typeof tree === "string") {
    return <pre className="text-xs">{tree}</pre>;
  }
  return <pre className="text-xs">{JSON.stringify(tree, null, 2)}</pre>;
}

interface ApiRoute {
  method?: string;
  path?: string;
  description?: string;
  handler?: string;
}

interface Component {
  name?: string;
  path?: string;
  children?: Component[];
  description?: string;
}

interface Dependency {
  name?: string;
  version?: string;
  purpose?: string;
}

function toComponent(raw: unknown): Component | null {
  if (!isRecord(raw)) return null;
  const children = safeArray(raw.children).map(toComponent).filter((c): c is Component => c !== null);
  return {
    name: safeString(raw.name),
    path: safeString(raw.path),
    children: children.length > 0 ? children : undefined,
    description: safeString(raw.description),
  };
}

export function TechPlanViewer({ artifact }: { artifact: ProjectArtifact }) {
  const c = safeRecord(artifact.content);
  if (!c) {
    return <RawJsonInspector data={artifact.content} warning="Artifact content is not a valid object." />;
  }

  const folderTree = c.folder_structure ?? c.folder_tree ?? c.folderTree ?? undefined;
  const dbSchema = c.database_schema ?? c.db_schema ?? undefined;
  const rawApiRoutes = safeArray(c.api_routes ?? c.apiRoutes);
  const apiRoutes: ApiRoute[] = rawApiRoutes.filter(isRecord).map((r) => ({
    method: safeString(r.method),
    path: safeString(r.path),
    description: safeString(r.description),
    handler: safeString(r.handler),
  }));
  const componentHierarchy = c.component_hierarchy ?? c.components ?? undefined;
  const components = Array.isArray(componentHierarchy)
    ? componentHierarchy.map(toComponent).filter((c): c is Component => c !== null)
    : [];
  const hasObjectHierarchy = Boolean(componentHierarchy) && !Array.isArray(componentHierarchy);
  const rawDeps = safeArray(c.dependencies);
  const dependencies: Dependency[] = rawDeps.filter(isRecord).map((d) => ({
    name: safeString(d.name),
    version: safeString(d.version),
    purpose: safeString(d.purpose),
  }));
  const deployConfig = safeRecord(c.deployment_config) ?? safeRecord(c.deploy_config);

  function renderComponentTree(items: Component[], depth = 0): React.ReactNode {
    return items.map((item, i) => (
      <div key={i} style={{ paddingLeft: `${depth * 16}px` }} className="py-1.5 border-b border-border-0/30 last:border-0">
        <div className="flex items-center gap-2">
          <span className="font-mono-display text-xs text-accent">{item.name ?? "—"}</span>
          {item.path && <span className="text-[10px] text-text-3 font-mono-display">{item.path}</span>}
        </div>
        {item.description && <p className="text-xs text-text-2 mt-0.5">{item.description}</p>}
        {Array.isArray(item.children) && item.children.length > 0 && renderComponentTree(item.children, depth + 1)}
      </div>
    ));
  }

  const hasStructuredContent = folderTree || apiRoutes.length > 0 || components.length > 0 || hasObjectHierarchy;

  return (
    <div className="space-y-2 animate-fade-in min-w-0">
      {folderTree && (
        <Section title="Folder Structure">
          <div className="glass-raised p-4 overflow-x-auto">
            <FolderTree tree={folderTree} />
          </div>
        </Section>
      )}

      {dbSchema && (
        <Section title="Database Schema">
          <pre className="text-xs overflow-auto max-w-full whitespace-pre-wrap break-words">
            {typeof dbSchema === "string" ? dbSchema : JSON.stringify(dbSchema, null, 2)}
          </pre>
        </Section>
      )}

      {apiRoutes.length > 0 && (
        <Section title="API Routes">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-0">
                  <th className="text-left py-2 pr-4 text-text-3 font-medium text-xs">Method</th>
                  <th className="text-left py-2 pr-4 text-text-3 font-medium text-xs">Path</th>
                  <th className="text-left py-2 pr-4 text-text-3 font-medium text-xs">Handler</th>
                  <th className="text-left py-2 text-text-3 font-medium text-xs">Description</th>
                </tr>
              </thead>
              <tbody>
                {apiRoutes.map((route, i) => (
                  <tr key={i} className="border-b border-border-0/50">
                    <td className="py-2.5 pr-4">
                      <span className="font-mono-display text-xs text-accent font-semibold uppercase">
                        {route.method ?? "GET"}
                      </span>
                    </td>
                    <td className="py-2.5 pr-4 font-mono-display text-xs text-text-1">{route.path ?? "—"}</td>
                    <td className="py-2.5 pr-4 font-mono-display text-xs text-text-2">{route.handler ?? "—"}</td>
                    <td className="py-2.5 text-xs text-text-2">{route.description ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {components.length > 0 && (
        <Section title="Component Hierarchy">
          <div className="glass-raised p-4">
            {renderComponentTree(components)}
          </div>
        </Section>
      )}

      {hasObjectHierarchy && (
        <Section title="Component Hierarchy">
          <pre className="text-xs overflow-auto max-w-full whitespace-pre-wrap break-words">
            {JSON.stringify(componentHierarchy, null, 2)}
          </pre>
        </Section>
      )}

      {dependencies.length > 0 && (
        <Section title="Dependencies">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {dependencies.map((dep, i) => (
              <div key={i} className="glass-raised p-3">
                <div className="flex items-baseline gap-2 mb-0.5">
                  <span className="font-mono-display text-xs text-accent">{dep.name ?? "—"}</span>
                  {dep.version && <span className="text-[10px] text-text-3">{dep.version}</span>}
                </div>
                {dep.purpose && <p className="text-xs text-text-2">{dep.purpose}</p>}
              </div>
            ))}
          </div>
        </Section>
      )}

      {deployConfig && (
        <Section title="Deployment Config">
          <pre className="text-xs overflow-auto max-w-full whitespace-pre-wrap break-words">
            {JSON.stringify(deployConfig, null, 2)}
          </pre>
        </Section>
      )}

      {!hasStructuredContent && (
        <RawJsonInspector data={artifact.content} warning="No recognized tech plan fields found. Showing raw content." />
      )}
    </div>
  );
}
