"""Model-profile router for the ID8 LLM layer.

Maps orchestrator node names to model profiles, and profiles to concrete
Gemini model IDs.  The routing table is the single source of truth for
which model each generation step uses.
"""
from __future__ import annotations

from app.models.enums import ModelProfile

# ---------------------------------------------------------------------------
# Profile → Gemini model ID
# ---------------------------------------------------------------------------

MODEL_MAP: dict[ModelProfile, str] = {
    ModelProfile.PRIMARY: "gemini-3.1-pro-preview",
    ModelProfile.CUSTOMTOOLS: "gemini-3.1-pro-preview-customtools",
    ModelProfile.FALLBACK: "gemini-2.5-pro",
}

# ---------------------------------------------------------------------------
# Orchestrator node → default model profile
# ---------------------------------------------------------------------------

NODE_PROFILE_MAP: dict[str, ModelProfile] = {
    # Non-design generation nodes default to Gemini 2.5 Pro for now.
    "GeneratePRD": ModelProfile.FALLBACK,
    "GenerateTechPlan": ModelProfile.FALLBACK,
    "WriteCode": ModelProfile.FALLBACK,
    # Keep design on customtools profile.
    "GenerateDesign": ModelProfile.CUSTOMTOOLS,
}

_DEFAULT_PROFILE = ModelProfile.FALLBACK


def resolve_model(profile: ModelProfile) -> str:
    """Return the concrete Gemini model ID for *profile*.

    Raises ``KeyError`` if the profile is not in the routing table.
    """
    return MODEL_MAP[profile]


def resolve_profile(node_name: str) -> ModelProfile:
    """Return the ``ModelProfile`` that *node_name* should use.

    Falls back to ``fallback`` for nodes not explicitly mapped.
    """
    return NODE_PROFILE_MAP.get(node_name, _DEFAULT_PROFILE)
