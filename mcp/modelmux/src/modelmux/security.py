"""Security scanning layer for modelmux dispatch pipeline.

Detects prompt injection, credential leaks, and data exfiltration attempts
before sending tasks to model adapters. Inspired by IronClaw's security model.

Threat levels:
  - BLOCK: reject the request entirely
  - WARN: allow but log a warning
  - LOG_ONLY: silent logging only
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ThreatLevel(str, Enum):
    BLOCK = "block"
    WARN = "warn"
    LOG_ONLY = "log"


@dataclass
class SecurityFinding:
    """A single security finding from a scan."""

    category: str  # "prompt_injection" | "credential_leak" | "data_exfil"
    pattern_name: str  # Which pattern matched
    severity: ThreatLevel
    matched_text: str  # The matched portion (truncated for safety)


@dataclass
class SecurityResult:
    """Result of a security scan."""

    passed: bool
    findings: list[SecurityFinding] = field(default_factory=list)
    action: ThreatLevel = ThreatLevel.LOG_ONLY


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Each pattern: (name, compiled_regex)
# Grouped by category with a default severity.

_PROMPT_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Role override attempts
    (
        "role_override_ignore",
        re.compile(
            r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?|context)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_override_disregard",
        re.compile(
            r"disregard\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_override_forget",
        re.compile(
            r"forget\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_override_you_are_now",
        re.compile(
            r"you\s+are\s+now\s+(?:a\s+)?(?:new|different|unrestricted|unfiltered)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_override_new_instructions",
        re.compile(
            r"new\s+instructions?\s*:",
            re.IGNORECASE,
        ),
    ),
    (
        "role_override_system_colon",
        re.compile(
            r"^system\s*:",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "role_override_system_header",
        re.compile(
            r"###\s*SYSTEM",
            re.IGNORECASE,
        ),
    ),
    (
        "role_override_override_all",
        re.compile(
            r"override\s+(all\s+)?(safety|security|content)\s+(filters?|policies|rules?|restrictions?)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_override_do_not_follow",
        re.compile(
            r"do\s+not\s+follow\s+(your|the|any)\s+(previous|original|initial)\s+(instructions?|rules?|guidelines?)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_override_from_now_on",
        re.compile(
            r"from\s+now\s+on,?\s+(you\s+)?(will|must|should|shall)\s+(ignore|disregard|forget|override)",
            re.IGNORECASE,
        ),
    ),
    # Delimiter injection
    (
        "delimiter_system_block",
        re.compile(
            r"```\s*system",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter_inst_tag",
        re.compile(
            r"\[/?INST\]",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter_llama_sys",
        re.compile(
            r"<<\s*SYS\s*>>",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter_chatml_system",
        re.compile(
            r"<\|im_start\|>\s*system",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter_chatml_end",
        re.compile(
            r"<\|im_end\|>",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter_human_turn",
        re.compile(
            r"<\|?\s*(?:human|user|assistant)\s*\|?>",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter_end_turn",
        re.compile(
            r"<\|endofturn\|>|<\|eot_id\|>",
            re.IGNORECASE,
        ),
    ),
    # Encoding evasion
    (
        "evasion_base64_instruct",
        re.compile(
            # base64 for common injection phrases — detect base64 blocks
            r"(?:base64|b64)\s*(?:decode|eval|exec)\s*[:(]",
            re.IGNORECASE,
        ),
    ),
    (
        "evasion_unicode_escape",
        re.compile(
            r"\\u[0-9a-fA-F]{4}.*\\u[0-9a-fA-F]{4}.*\\u[0-9a-fA-F]{4}",
        ),
    ),
    (
        "evasion_hex_escape",
        re.compile(
            r"\\x[0-9a-fA-F]{2}.*\\x[0-9a-fA-F]{2}.*\\x[0-9a-fA-F]{2}",
        ),
    ),
    (
        "evasion_rot13",
        re.compile(
            r"rot13|caesar\s+cipher\s+decode",
            re.IGNORECASE,
        ),
    ),
    # Social engineering
    (
        "social_pretend",
        re.compile(
            r"pretend\s+(you\s+are|to\s+be|you['re])\s+(?:a\s+)?(?:different|new|unrestricted|jailbroken)",
            re.IGNORECASE,
        ),
    ),
    (
        "social_act_as_if",
        re.compile(
            r"act\s+as\s+if\s+(you\s+)?(have\s+no|had\s+no|without)\s+(restrictions?|filters?|rules?|limitations?)",
            re.IGNORECASE,
        ),
    ),
    (
        "social_hypothetically",
        re.compile(
            r"hypothetically\s+if\s+you\s+had\s+no\s+(restrictions?|filters?|rules?|limitations?)",
            re.IGNORECASE,
        ),
    ),
    (
        "social_developer_mode",
        re.compile(
            r"(?:enable|activate|enter)\s+(?:developer|dev|debug|god|sudo|admin)\s+mode",
            re.IGNORECASE,
        ),
    ),
    (
        "social_jailbreak",
        re.compile(
            r"(?:DAN|STAN|DUDE|AIM)\s+(?:mode|prompt|jailbreak)",
            re.IGNORECASE,
        ),
    ),
    (
        "social_no_ethical",
        re.compile(
            r"(?:without|ignore|bypass|disable)\s+(?:your\s+)?(?:ethical|moral|safety)\s+(?:guidelines?|constraints?|programming)",
            re.IGNORECASE,
        ),
    ),
    # Output manipulation
    (
        "output_respond_only",
        re.compile(
            r"respond\s+only\s+with\s+(?:the\s+following|this|exactly)",
            re.IGNORECASE,
        ),
    ),
    (
        "output_exact",
        re.compile(
            r"output\s+the\s+following\s+exactly",
            re.IGNORECASE,
        ),
    ),
    (
        "output_repeat_after",
        re.compile(
            r"repeat\s+after\s+me\s*:",
            re.IGNORECASE,
        ),
    ),
    (
        "output_print_verbatim",
        re.compile(
            r"(?:print|echo|output|say)\s+(?:verbatim|exactly|word\s+for\s+word)\s*:",
            re.IGNORECASE,
        ),
    ),
]

_CREDENTIAL_LEAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # AWS
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "aws_secret_key",
        re.compile(
            r"(?:aws_secret_access_key|AWS_SECRET)\s*[=:]\s*[A-Za-z0-9/+=]{40}",
            re.IGNORECASE,
        ),
    ),
    # GCP
    (
        "gcp_service_account",
        re.compile(
            r'"type"\s*:\s*"service_account"',
        ),
    ),
    (
        "gcp_private_key_id",
        re.compile(
            r'"private_key_id"\s*:\s*"[a-f0-9]{40}"',
        ),
    ),
    # Azure
    (
        "azure_token",
        re.compile(
            r"(?:DefaultEndpointsProtocol|AccountKey)\s*=\s*[A-Za-z0-9+/=]{20,}",
        ),
    ),
    # Generic API keys
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("github_oauth", re.compile(r"gho_[A-Za-z0-9]{36}")),
    ("gitlab_pat", re.compile(r"glpat-[A-Za-z0-9\-_]{20,}")),
    ("slack_bot_token", re.compile(r"xoxb-[0-9]+-[A-Za-z0-9]+")),
    ("slack_user_token", re.compile(r"xoxp-[0-9]+-[A-Za-z0-9]+")),
    (
        "slack_webhook",
        re.compile(
            r"hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+",
        ),
    ),
    ("stripe_key", re.compile(r"(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{20,}")),
    ("sendgrid_key", re.compile(r"SG\.[A-Za-z0-9_\-]{22,}\.[A-Za-z0-9_\-]{22,}")),
    ("twilio_key", re.compile(r"SK[a-f0-9]{32}")),
    # Private keys
    (
        "private_key_pem",
        re.compile(
            r"-----BEGIN\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----",
        ),
    ),
    # Connection strings
    (
        "connection_string_mongo",
        re.compile(
            r"mongodb(?:\+srv)?://[^\s'\"]+:[^\s'\"]+@[^\s'\"]+",
        ),
    ),
    (
        "connection_string_postgres",
        re.compile(
            r"postgres(?:ql)?://[^\s'\"]+:[^\s'\"]+@[^\s'\"]+",
        ),
    ),
    (
        "connection_string_mysql",
        re.compile(
            r"mysql://[^\s'\"]+:[^\s'\"]+@[^\s'\"]+",
        ),
    ),
    (
        "connection_string_redis",
        re.compile(
            r"redis://:[^\s'\"]+@[^\s'\"]+",
        ),
    ),
    # JWT / Bearer tokens
    (
        "jwt_token",
        re.compile(
            r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        ),
    ),
    (
        "bearer_token",
        re.compile(
            r"(?:Authorization|Bearer)\s*[:=]\s*Bearer\s+[A-Za-z0-9._\-]{20,}",
            re.IGNORECASE,
        ),
    ),
    # .env patterns
    (
        "env_api_key",
        re.compile(
            r"(?:API_KEY|API_SECRET|SECRET_KEY|ACCESS_TOKEN|AUTH_TOKEN)\s*=\s*['\"]?[A-Za-z0-9_\-]{16,}",
            re.IGNORECASE,
        ),
    ),
    (
        "env_password",
        re.compile(
            r"(?:PASSWORD|PASSWD|DB_PASS)\s*=\s*['\"]?[^\s'\"]{8,}",
            re.IGNORECASE,
        ),
    ),
]

_DATA_EXFIL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "exfil_curl_post",
        re.compile(
            r"curl\s+.*-X\s*POST\s+.*https?://",
            re.IGNORECASE,
        ),
    ),
    (
        "exfil_wget_post",
        re.compile(
            r"wget\s+--post",
            re.IGNORECASE,
        ),
    ),
    (
        "exfil_nc_pipe",
        re.compile(
            r"\|\s*(?:nc|ncat|netcat)\s+",
            re.IGNORECASE,
        ),
    ),
]

# Default severity per category
_DEFAULT_SEVERITY: dict[str, ThreatLevel] = {
    "prompt_injection": ThreatLevel.BLOCK,
    "credential_leak": ThreatLevel.BLOCK,
    "data_exfil": ThreatLevel.WARN,
}

# Maximum characters of matched text to include in findings
_MAX_MATCH_LEN = 80


# ---------------------------------------------------------------------------
# Security policy (loaded from policy.json "security" section)
# ---------------------------------------------------------------------------


@dataclass
class SecurityPolicy:
    """Security policy configuration."""

    enabled: bool = True
    prompt_injection: ThreatLevel = ThreatLevel.BLOCK
    credential_leak: ThreatLevel = ThreatLevel.BLOCK
    data_exfil: ThreatLevel = ThreatLevel.WARN
    default_level: ThreatLevel = ThreatLevel.WARN


def parse_security_policy(data: dict | None) -> SecurityPolicy:
    """Parse the 'security' section from policy.json."""
    if not data or not isinstance(data, dict):
        return SecurityPolicy()

    def _to_level(val: str | None, default: ThreatLevel) -> ThreatLevel:
        if val is None:
            return default
        try:
            return ThreatLevel(val)
        except ValueError:
            return default

    return SecurityPolicy(
        enabled=data.get("enabled", True),
        prompt_injection=_to_level(data.get("prompt_injection"), ThreatLevel.BLOCK),
        credential_leak=_to_level(data.get("credential_leak"), ThreatLevel.BLOCK),
        data_exfil=_to_level(data.get("data_exfil"), ThreatLevel.WARN),
        default_level=_to_level(data.get("default_level"), ThreatLevel.WARN),
    )


# ---------------------------------------------------------------------------
# Main scanning function
# ---------------------------------------------------------------------------


def scan_task(
    task: str,
    policy_overrides: dict | None = None,
) -> SecurityResult:
    """Scan a task string for security threats.

    Args:
        task: The task/prompt text to scan.
        policy_overrides: Optional dict to override default severity per category.
            Keys: "prompt_injection", "credential_leak", "data_exfil"
            Values: "block", "warn", "log"

    Returns:
        SecurityResult with pass/fail status and any findings.
    """
    sec_policy = parse_security_policy(policy_overrides)

    if not sec_policy.enabled:
        return SecurityResult(passed=True)

    findings: list[SecurityFinding] = []

    # Determine effective severity per category
    severity_map = {
        "prompt_injection": sec_policy.prompt_injection,
        "credential_leak": sec_policy.credential_leak,
        "data_exfil": sec_policy.data_exfil,
    }

    # Scan prompt injection patterns
    for name, pattern in _PROMPT_INJECTION_PATTERNS:
        m = pattern.search(task)
        if m:
            findings.append(
                SecurityFinding(
                    category="prompt_injection",
                    pattern_name=name,
                    severity=severity_map["prompt_injection"],
                    matched_text=m.group()[:_MAX_MATCH_LEN],
                )
            )

    # Scan credential leak patterns
    for name, pattern in _CREDENTIAL_LEAK_PATTERNS:
        m = pattern.search(task)
        if m:
            matched = m.group()
            # Redact most of the matched text for safety
            if len(matched) > 8:
                matched = matched[:4] + "****" + matched[-4:]
            findings.append(
                SecurityFinding(
                    category="credential_leak",
                    pattern_name=name,
                    severity=severity_map["credential_leak"],
                    matched_text=matched[:_MAX_MATCH_LEN],
                )
            )

    # Scan data exfiltration patterns
    for name, pattern in _DATA_EXFIL_PATTERNS:
        m = pattern.search(task)
        if m:
            findings.append(
                SecurityFinding(
                    category="data_exfil",
                    pattern_name=name,
                    severity=severity_map["data_exfil"],
                    matched_text=m.group()[:_MAX_MATCH_LEN],
                )
            )

    if not findings:
        return SecurityResult(passed=True)

    # Determine the most severe action
    worst = ThreatLevel.LOG_ONLY
    for f in findings:
        if f.severity == ThreatLevel.BLOCK:
            worst = ThreatLevel.BLOCK
            break
        if f.severity == ThreatLevel.WARN and worst != ThreatLevel.BLOCK:
            worst = ThreatLevel.WARN

    passed = worst != ThreatLevel.BLOCK
    return SecurityResult(passed=passed, findings=findings, action=worst)
