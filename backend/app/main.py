from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import approvals, artifacts, deploy, design, projects, runs


def create_app() -> FastAPI:
    app = FastAPI(
        title="ID8 Operator API",
        version="0.1.0",
        description="MVP API for orchestrating prompt-to-production runs with HITL gates.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(projects.router, prefix="/v1")
    app.include_router(runs.router, prefix="/v1")
    app.include_router(design.router, prefix="/v1")
    app.include_router(approvals.router, prefix="/v1")
    app.include_router(artifacts.router, prefix="/v1")
    app.include_router(deploy.router, prefix="/v1")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
