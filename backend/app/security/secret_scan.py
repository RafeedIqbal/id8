"""Secret scanner — regex-based detection of hardcoded credentials.

Scans all generated files for common secret patterns: API keys, passwords,
tokens, and private keys.  Any match is reported as a ``critical`` finding.

False-positive reduction: matches inside example/placeholder strings (e.g.
``your-api-key``, ``<SECRET>``, ``${ENV_VAR}``) are discarded, as are
well-known documentation files (``.env.example``, ``README.md``).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.schemas.security_report import SecurityFinding

logger = logging.getLogger("id8.security.secret_scan")

# (rule_id, human-readable description, compiled pattern)
_SECRET_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "SECRET_OPENAI_KEY",
        "OpenAI API key",
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
    ),
    (
        "SECRET_AWS_ACCESS_KEY",
        "AWS access key ID",
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ),
    (
        "SECRET_AWS_SECRET",
        "AWS secret access key",
        re.compile(r'(?i)aws.{0,20}secret.{0,20}["\'][A-Za-z0-9/+=]{40}["\']'),
    ),
    (
        "SECRET_PRIVATE_KEY",
        "Private key material",
        re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    (
        "SECRET_GITHUB_TOKEN",
        "GitHub personal access token",
        re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    ),
    (
        "SECRET_STRIPE_LIVE_KEY",
        "Stripe live secret key",
        re.compile(r"sk_live_[A-Za-z0-9]{24,}"),
    ),
    (
        "SECRET_GENERIC_API_KEY",
        "Hardcoded API key",
        re.compile(r'(?i)(api_key|apikey)\s*[=:]\s*["\'][A-Za-z0-9_\-\.]{8,}["\']'),
    ),
    (
        "SECRET_HARDCODED_PASSWORD",
        "Hardcoded password",
        re.compile(r'(?i)(password|passwd|pwd)\s*[=:]\s*["\'][^"\']{4,}["\']'),
    ),
    (
        "SECRET_HARDCODED_TOKEN",
        "Hardcoded token or secret",
        re.compile(r'(?i)(token|secret)\s*[=:]\s*["\'][A-Za-z0-9_\-\.]{10,}["\']'),
    ),
]

# Files that commonly contain placeholder/example values — skip scanning them.
_SKIP_BASENAMES: frozenset[str] = frozenset(
    {
        ".env.example",
        ".env.sample",
        "README.md",
        "readme.md",
        "CHANGELOG.md",
        "LICENSE",
    }
)

# Substrings that indicate a value is a placeholder rather than a real secret.
_PLACEHOLDER_RE = re.compile(
    r"""(?ix)
    your[-_]?api[-_]?key
    | your[-_]?secret
    | your[-_]?token
    | <[A-Z_]+>
    | \$\{[A-Z_][A-Z0-9_]*\}
    | %\([A-Z_][A-Z0-9_]*\)s
    | \bxxxx\b
    | \b1234\b
    | \bplaceholder\b
    | \bexample\b
    | \bchangeme\b
    | \btodo\b
    | replace.?me
    | test.?secret
    | dummy
    | fake
    """,
)


async def run_secret_scan(files: list[dict[str, Any]]) -> list[SecurityFinding]:
    """Scan generated files for hardcoded secrets.

    Parameters
    ----------
    files:
        List of ``{"path": str, "content": str, "language": str}`` dicts.

    Returns
    -------
    list[SecurityFinding]
        Critical-severity findings; empty when no secrets are detected.
    """
    findings: list[SecurityFinding] = []

    for f in files:
        path = str(f.get("path", ""))
        content = str(f.get("content", ""))
        basename = path.split("/")[-1] if "/" in path else path

        if basename in _SKIP_BASENAMES:
            continue

        findings.extend(_scan_file(path, content))

    return findings


def _scan_file(file_path: str, content: str) -> list[SecurityFinding]:
    """Scan a single file's content and return any secret findings."""
    findings: list[SecurityFinding] = []
    lines = content.splitlines()

    for rule_id, description, pattern in _SECRET_PATTERNS:
        for line_num, line in enumerate(lines, start=1):
            match = pattern.search(line)
            if match is None:
                continue

            matched_text = match.group(0)
            if _PLACEHOLDER_RE.search(matched_text):
                continue

            findings.append(
                SecurityFinding(
                    rule_id=rule_id,
                    severity="critical",
                    file_path=file_path,
                    line_number=line_num,
                    message=f"{description} detected",
                    remediation=(
                        "Remove the hardcoded secret and load it from an "
                        "environment variable or secrets manager instead"
                    ),
                    resolved=False,
                )
            )

    return findings
