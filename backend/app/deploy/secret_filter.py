"""Secret filter — allowlist-based guard for environment variables.

Before any env-var dict is injected into Vercel (or any external runtime),
it MUST pass through ``filter_env_vars``.  The filter:

* Accepts only keys that match an explicit allowlist pattern.
* Rejects any key whose name contains a blocked keyword regardless of prefix.
* Logs the accepted key names (never values) to the audit trail.

The only variables that belong in a frontend runtime are publishable ones —
those prefixed with ``NEXT_PUBLIC_`` or ``PUBLIC_``.  Everything else is
backend-only and must never be injected.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("id8.deploy.secret_filter")

# A key must match at least one of these patterns to be accepted.
_ALLOWLIST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^NEXT_PUBLIC_"),
    re.compile(r"^PUBLIC_"),
)

# A key that matches any of these words anywhere in its name is always
# rejected — even if it matches the allowlist above.
_BLOCKED_KEYWORDS: frozenset[str] = frozenset(
    {
        "SERVICE_ROLE",
        "SECRET",
        "PRIVATE_KEY",
        "PRIVATE",
        "INTERNAL",
        "ADMIN",
    }
)


def filter_env_vars(vars: dict[str, str]) -> dict[str, str]:
    """Return a copy of *vars* containing only publishable keys.

    Raises nothing — rejected keys are silently dropped (but logged at
    WARNING level so the caller can audit what was stripped).
    """
    accepted: dict[str, str] = {}
    rejected_names: list[str] = []

    for key, value in vars.items():
        upper = key.upper()

        # Hard block: key contains a forbidden keyword.
        if any(kw in upper for kw in _BLOCKED_KEYWORDS):
            rejected_names.append(key)
            continue

        # Must match at least one allowlist pattern.
        if not any(pat.search(upper) for pat in _ALLOWLIST_PATTERNS):
            rejected_names.append(key)
            continue

        accepted[key] = value

    if rejected_names:
        logger.warning(
            "secret_filter: rejected %d env var(s) as non-publishable: %s",
            len(rejected_names),
            ", ".join(sorted(rejected_names)),
        )

    if accepted:
        logger.info(
            "secret_filter: injecting %d publishable env var(s): %s",
            len(accepted),
            ", ".join(sorted(accepted)),
        )

    return accepted


def assert_no_secrets(vars: dict[str, str]) -> None:
    """Raise ``ValueError`` if *vars* contains any non-publishable key.

    Use this as a final gate before actually sending vars to an external
    service — it provides an explicit, auditable assertion point.
    """
    leaked = [
        k
        for k in vars
        if any(kw in k.upper() for kw in _BLOCKED_KEYWORDS)
    ]
    if leaked:
        raise ValueError(
            f"Secret safety violation: the following keys must not be "
            f"injected into the frontend runtime: {', '.join(sorted(leaked))}"
        )
