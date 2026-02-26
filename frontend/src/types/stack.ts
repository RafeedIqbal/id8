export type FrontendFramework = "nextjs" | "react" | "vue" | "svelte";
export type BackendFramework = "fastapi" | "express" | "nestjs" | "django";
export type Database = "postgresql" | "mysql" | "sqlite";
export type DatabaseProvider = "supabase" | "neon" | "planetscale" | "local";
export type HostingFrontend = "vercel";
export type HostingBackend = "supabase" | "vercel";

export interface StackJson {
  frontend_framework: FrontendFramework;
  backend_framework: BackendFramework;
  database: Database;
  database_provider: DatabaseProvider;
  hosting_frontend: HostingFrontend;
  hosting_backend: HostingBackend;
}

export const DEFAULT_STACK: StackJson = {
  frontend_framework: "nextjs",
  backend_framework: "fastapi",
  database: "postgresql",
  database_provider: "supabase",
  hosting_frontend: "vercel",
  hosting_backend: "supabase",
};

export const STACK_OPTIONS = {
  frontend_framework: ["nextjs", "react", "vue", "svelte"] as const,
  backend_framework: ["fastapi", "express", "nestjs", "django"] as const,
  database: ["postgresql", "mysql", "sqlite"] as const,
  database_provider: ["supabase", "neon", "planetscale", "local"] as const,
  hosting_frontend: ["vercel"] as const,
  hosting_backend: ["supabase", "vercel"] as const,
} as const;

export function validateStackHostability(stack: StackJson): string | null {
  if (stack.hosting_frontend !== "vercel") {
    return "Frontend hosting is locked to 'vercel' in MVP";
  }
  if (stack.hosting_backend !== "supabase" && stack.hosting_backend !== "vercel") {
    return "Backend hosting must be 'supabase' or 'vercel'";
  }
  if (stack.database_provider === "local") {
    return "Local database providers are not hostable in MVP";
  }
  if (stack.database === "sqlite") {
    return "SQLite is not supported for hosted MVP deployments";
  }
  if (
    (stack.database_provider === "supabase" || stack.database_provider === "neon") &&
    stack.database !== "postgresql"
  ) {
    return `${stack.database_provider} provider requires postgresql`;
  }
  if (stack.database_provider === "planetscale" && stack.database !== "mysql") {
    return "planetscale provider requires mysql";
  }
  if (stack.hosting_backend === "supabase" && stack.database_provider !== "supabase") {
    return "Supabase backend hosting requires supabase database provider";
  }
  return null;
}
