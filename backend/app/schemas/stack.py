"""Fixed runtime profile for generated projects.

The application now enforces a single deployable stack profile:
Next.js full-stack hosted on Vercel.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class StackJson(BaseModel):
    frontend_framework: Literal["nextjs"] = "nextjs"
    backend_framework: Literal["nextjs"] = "nextjs"
    database: Literal["none"] = "none"
    database_provider: Literal["none"] = "none"
    hosting_frontend: Literal["vercel"] = "vercel"
    hosting_backend: Literal["vercel"] = "vercel"


DEFAULT_STACK = StackJson()

