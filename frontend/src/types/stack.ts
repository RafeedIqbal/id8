export interface StackJson {
  frontend_framework: "nextjs";
  backend_framework: "nextjs";
  database: "none";
  database_provider: "none";
  hosting_frontend: "vercel";
  hosting_backend: "vercel";
}

export const DEFAULT_STACK: StackJson = {
  frontend_framework: "nextjs",
  backend_framework: "nextjs",
  database: "none",
  database_provider: "none",
  hosting_frontend: "vercel",
  hosting_backend: "vercel",
};

export const FIXED_STACK_LABELS: Array<{ key: keyof StackJson; label: string }> = [
  { key: "frontend_framework", label: "Frontend" },
  { key: "backend_framework", label: "Backend" },
  { key: "database", label: "Database" },
  { key: "database_provider", label: "Database Provider" },
  { key: "hosting_frontend", label: "Frontend Hosting" },
  { key: "hosting_backend", label: "Backend Hosting" },
];

export function validateStackHostability(stack: StackJson): string | null {
  const mismatches = Object.entries(DEFAULT_STACK).filter(
    ([key, expected]) => stack[key as keyof StackJson] !== expected
  );
  if (mismatches.length > 0) {
    return "Stack profile is fixed to Next.js full-stack on Vercel";
  }
  return null;
}

