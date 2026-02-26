"use client";

import Link from "next/link";

export interface Crumb {
  label: string;
  href?: string;
}

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-sm mb-6">
      {items.map((crumb, i) => (
        <span key={i} className="flex items-center gap-2">
          {i > 0 && (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-3">
              <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
          {crumb.href ? (
            <Link href={crumb.href} className="text-text-2 hover:text-accent transition-colors">
              {crumb.label}
            </Link>
          ) : (
            <span className="text-text-0 font-medium">{crumb.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
