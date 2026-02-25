from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import ArtifactType, ModelProfile


class ProjectArtifact(Base):
    __tablename__ = "project_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_runs.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[ArtifactType] = mapped_column(
        ENUM(ArtifactType, name="artifact_type_enum", create_type=False), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_profile: Mapped[ModelProfile | None] = mapped_column(
        ENUM(ModelProfile, name="model_profile_enum", create_type=False), nullable=True
    )
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))

    __table_args__ = (UniqueConstraint("project_id", "artifact_type", "version"),)
