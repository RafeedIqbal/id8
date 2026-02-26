"""Stack JSON schema with hostability constraints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


class StackJson(BaseModel):
    frontend_framework: Literal["nextjs", "react", "vue", "svelte"] = "nextjs"
    backend_framework: Literal["fastapi", "express", "nestjs", "django"] = "fastapi"
    database: Literal["postgresql", "mysql", "sqlite"] = "postgresql"
    database_provider: Literal["supabase", "neon", "planetscale", "local"] = "supabase"
    hosting_frontend: Literal["vercel"] = "vercel"
    hosting_backend: Literal["supabase", "vercel"] = "supabase"

    @field_validator("hosting_frontend")
    @classmethod
    def frontend_must_be_vercel(cls, v: str) -> str:
        if v != "vercel":
            raise ValueError("Frontend hosting is locked to 'vercel' in MVP")
        return v

    @field_validator("hosting_backend")
    @classmethod
    def backend_hosting_constraint(cls, v: str) -> str:
        if v not in ("supabase", "vercel"):
            raise ValueError("Backend hosting must be 'supabase' or 'vercel'")
        return v

    @model_validator(mode="after")
    def validate_hostability(self) -> StackJson:
        if self.database_provider == "local":
            raise ValueError("Local database providers are not hostable in MVP")

        if self.database_provider == "supabase" and self.database != "postgresql":
            raise ValueError("Supabase provider requires PostgreSQL")
        if self.database_provider == "neon" and self.database != "postgresql":
            raise ValueError("Neon provider requires PostgreSQL")
        if self.database_provider == "planetscale" and self.database != "mysql":
            raise ValueError("PlanetScale provider requires MySQL")

        if self.database == "sqlite":
            raise ValueError("SQLite is not supported for hosted MVP deployments")

        if self.hosting_backend == "supabase" and self.database_provider != "supabase":
            raise ValueError("Supabase backend hosting requires Supabase database provider")

        return self


DEFAULT_STACK = StackJson()
