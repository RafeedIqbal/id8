from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Database
    database_url: str = "postgresql+asyncpg://id8:id8@localhost:5432/id8"

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_anon_key: str = ""

    # Google Gemini
    gemini_api_key: str = ""

    # Supabase Management API (for provisioning generated-app projects)
    supabase_access_token: str = ""  # Personal access token for Management API
    supabase_org_id: str = ""  # Organization ID to create projects under

    # GitHub
    github_token: str = ""
    github_app_id: str = ""
    github_app_private_key: str = ""

    # Vercel
    vercel_token: str = ""
    vercel_team_id: str = ""

    # Stitch MCP
    stitch_mcp_endpoint: str = ""


settings = Settings()
