"use client";

import { useState } from "react";
import type { StitchAuthPayload, StitchAuthMethod } from "@/types/domain";

export function StitchAuthPanel({
  onAuth,
}: {
  onAuth: (payload: StitchAuthPayload) => void;
}) {
  const [method, setMethod] = useState<StitchAuthMethod>("api_key");
  const [apiKey, setApiKey] = useState("");
  const [oauthToken, setOauthToken] = useState("");
  const [googProject, setGoogProject] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (method === "api_key" && apiKey.trim()) {
      onAuth({ authMethod: "api_key", apiKey: apiKey.trim() });
    } else if (method === "oauth_access_token" && oauthToken.trim() && googProject.trim()) {
      onAuth({
        authMethod: "oauth_access_token",
        oauthToken: oauthToken.trim(),
        googUserProject: googProject.trim(),
      });
    }
  }

  return (
    <div className="glass p-6 space-y-5">
      <div>
        <h3 className="text-base font-semibold text-text-0 mb-1 flex items-center gap-2">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--color-warning)" strokeWidth="1.5">
            <rect x="3" y="11" width="18" height="11" rx="2" />
            <path d="M7 11V7a5 5 0 0110 0v4" />
          </svg>
          Stitch Credentials Required
        </h3>
        <p className="text-sm text-text-2">
          Authenticate with Stitch MCP to generate designs.
        </p>
      </div>

      {/* Method toggle */}
      <div className="flex gap-2">
        <button
          onClick={() => setMethod("api_key")}
          className={`btn text-xs flex-1 ${method === "api_key" ? "btn-primary" : "btn-ghost"}`}
        >
          API Key
          <span className="text-[10px] opacity-60 ml-1">(Recommended)</span>
        </button>
        <button
          onClick={() => setMethod("oauth_access_token")}
          className={`btn text-xs flex-1 ${method === "oauth_access_token" ? "btn-primary" : "btn-ghost"}`}
        >
          OAuth Token
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {method === "api_key" ? (
          <div>
            <label className="block text-sm font-medium text-text-1 mb-2">
              API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-stitch-..."
              autoComplete="off"
            />
            <p className="text-xs text-text-3 mt-2">
              Create a key in <span className="text-accent">Stitch Settings &rarr; API Keys &rarr; Create API Key</span>
            </p>
          </div>
        ) : (
          <>
            <div>
              <label className="block text-sm font-medium text-text-1 mb-2">
                OAuth Access Token
              </label>
              <input
                type="password"
                value={oauthToken}
                onChange={(e) => setOauthToken(e.target.value)}
                placeholder="ya29.a0..."
                autoComplete="off"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-1 mb-2">
                Google User Project
              </label>
              <input
                type="text"
                value={googProject}
                onChange={(e) => setGoogProject(e.target.value)}
                placeholder="my-gcp-project-id"
                autoComplete="off"
              />
            </div>
          </>
        )}

        <button type="submit" className="btn btn-primary w-full">
          Authenticate &amp; Continue
        </button>
      </form>

      <p className="text-[11px] text-text-3 leading-relaxed">
        Credentials are used for this session only and never stored in the browser.
      </p>
    </div>
  );
}
