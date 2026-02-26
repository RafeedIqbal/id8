import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Sidebar } from "@/components/sidebar";

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
      <body>
        <Providers>
          <Sidebar />
          <main className="lg:pl-[260px] min-h-dvh">
            <div className="max-w-[1280px] mx-auto px-6 pt-16 lg:pt-8 pb-12">
              {children}
            </div>
          </main>
        </Providers>
      </body>
    </html>
  );
}
