"""Internal spec design provider (LLM fallback).

Generates a text-based design specification using the LLM router when
Stitch MCP is unavailable.  Produces the same ``DesignOutput`` format so
downstream consumers are provider-agnostic.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from .base import (
    DesignFeedback,
    DesignOutput,
    DesignProvider,
    DesignProviderError,
    Screen,
    ScreenComponent,
    StitchAuthContext,
)

logger = logging.getLogger("id8.design.internal_spec")

_MAX_PARSE_RETRIES = 1


async def _generate_with_fallback(*args: Any, **kwargs: Any) -> Any:
    """Late-bound wrapper to avoid circular imports."""
    from app.llm.client import generate_with_fallback

    return await generate_with_fallback(*args, **kwargs)


class InternalSpecProvider(DesignProvider):
    """LLM-based design spec generator (fallback provider)."""

    async def generate(
        self,
        prd_content: dict[str, Any],
        constraints: dict[str, Any],
        auth: StitchAuthContext | None = None,
    ) -> DesignOutput:
        from app.llm.prompts.design_generation import build_prompts
        from app.llm.router import resolve_profile

        profile = resolve_profile("GenerateDesign")
        system_prompt, user_prompt = build_prompts(
            prd_content=prd_content,
            constraints=constraints,
        )

        start = time.monotonic()
        output, llm_meta = await self._call_llm(profile, system_prompt, user_prompt)
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)

        output.metadata.update({
            "provider": "internal_spec",
            "generation_time_ms": elapsed_ms,
            **llm_meta,
        })
        return output

    async def regenerate(
        self,
        previous: DesignOutput,
        feedback: DesignFeedback,
        auth: StitchAuthContext | None = None,
    ) -> DesignOutput:
        from app.llm.prompts.design_generation import build_prompts
        from app.llm.router import resolve_profile

        profile = resolve_profile("GenerateDesign")

        # Strip internal metadata from previous design before passing to LLM
        prev_dict = previous.to_dict()
        prev_clean = {k: v for k, v in prev_dict.items() if not k.startswith("__")}

        system_prompt, user_prompt = build_prompts(
            prd_content={},  # PRD context is embedded in the feedback prompt
            constraints={},
            feedback=feedback.feedback_text,
            target_screen_id=feedback.target_screen_id,
            target_component_id=feedback.target_component_id,
            previous_design=prev_clean,
        )

        start = time.monotonic()
        output, llm_meta = await self._call_llm(profile, system_prompt, user_prompt)
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)

        output.metadata.update({
            "provider": "internal_spec",
            "generation_time_ms": elapsed_ms,
            "feedback_text": feedback.feedback_text,
            **llm_meta,
        })
        return output

    # -- internals ---------------------------------------------------------

    async def _call_llm(
        self,
        profile: Any,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[DesignOutput, dict[str, Any]]:
        """Call the LLM with retry on parse failure."""
        last_error: str | None = None

        for attempt in range(_MAX_PARSE_RETRIES + 1):
            effective_system = system_prompt
            if attempt > 0 and last_error:
                effective_system += (
                    "\n\nIMPORTANT: Your previous response was not valid JSON. "
                    f"Error: {last_error}\n"
                    "You MUST return ONLY a valid JSON object, no markdown fences or extra text."
                )

            llm_response = await _generate_with_fallback(
                profile=profile,
                node_name="GenerateDesign",
                prompt=user_prompt,
                system_prompt=effective_system,
            )

            output, parse_error = _parse_llm_response(llm_response.content)
            if output is not None:
                meta = {
                    "model_id": llm_response.model_id,
                    "profile_used": str(llm_response.profile_used),
                    "prompt_tokens": llm_response.token_usage.prompt_tokens,
                    "completion_tokens": llm_response.token_usage.completion_tokens,
                }
                return output, meta

            last_error = parse_error
            logger.warning(
                "Design spec parse failed (attempt %d/%d): %s",
                attempt + 1,
                _MAX_PARSE_RETRIES + 1,
                parse_error,
            )

        raise DesignProviderError(
            f"Internal spec generation failed after retries: {last_error}"
        )


def _parse_llm_response(content: str) -> tuple[DesignOutput | None, str | None]:
    """Parse LLM response into DesignOutput. Returns (output, None) or (None, error)."""
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"

    if not isinstance(raw, dict):
        return None, "Response is not a JSON object"

    raw_screens = raw.get("screens", [])
    if not isinstance(raw_screens, list):
        return None, "'screens' must be a list"

    screens: list[Screen] = []
    for i, rs in enumerate(raw_screens):
        if not isinstance(rs, dict):
            continue
        components = []
        for j, rc in enumerate(rs.get("components", [])):
            if not isinstance(rc, dict):
                continue
            components.append(ScreenComponent(
                id=rc.get("id", f"comp-{j}"),
                name=rc.get("name", f"Component {j}"),
                type=rc.get("type", "unknown"),
                properties=rc.get("properties", {}),
            ))
        screens.append(Screen(
            id=rs.get("id", f"screen-{i}"),
            name=rs.get("name", f"Screen {i}"),
            description=rs.get("description", ""),
            components=components,
            assets=rs.get("assets", []),
        ))

    return DesignOutput(screens=screens), None
