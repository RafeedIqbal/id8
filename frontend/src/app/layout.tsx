import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ID8 — Operator Console",
  description: "Prompt to production with HITL approval gates",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 antialiased">{children}</body>
    </html>
  );
}
