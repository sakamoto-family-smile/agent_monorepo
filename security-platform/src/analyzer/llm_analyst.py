"""Optional LLM-based analysis for vulnerabilities.

Supports Claude (Anthropic) and Gemini via Vertex AI (Google) interchangeably.
Provider selection:
  1. LLM_PROVIDER env var ("claude" or "gemini") — explicit override
  2. Auto-detect: use Claude if ANTHROPIC_API_KEY set, Gemini if VERTEX_AI_PROJECT set
  3. If neither is configured, analysis is skipped gracefully.

Gemini uses Vertex AI (Application Default Credentials) instead of an API key.
Run `gcloud auth application-default login` to authenticate locally.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from ..config import settings

logger = logging.getLogger(__name__)

Provider = Literal["claude", "gemini"]

ANALYSIS_PROMPT = """You are a security analyst specializing in AI agent systems, MCP (Model Context Protocol) servers, and LLM security.

Analyze the following vulnerability and provide:
1. A concise attack summary (2-3 sentences explaining the threat vector)
2. Applicability assessment for agent systems using MCP tools
3. Recommended actions for mitigation

Vulnerability details:
- Title: {title}
- CVE/GHSA: {ids}
- Severity: {severity} (CVSS: {cvss})
- Affected component: {component}
- Description: {description}
- Tags: {tags}

Respond in JSON format only (no markdown):
{{
  "attack_summary": "...",
  "applicability": "...",
  "recommended_actions": "..."
}}
"""


def _resolve_provider() -> Provider | None:
    """Determine which LLM provider to use based on config."""
    explicit = (settings.llm_provider or "").lower().strip()
    if explicit in ("claude", "gemini"):
        return explicit  # type: ignore[return-value]

    # Auto-detect from available keys / config
    if settings.anthropic_api_key:
        return "claude"
    if settings.vertex_ai_project:
        return "gemini"
    return None


async def _analyze_with_claude(prompt: str) -> dict[str, str]:
    """Call Claude claude-haiku-4-5 (cost-efficient) for analysis."""
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed; run: uv add anthropic")
        return {}

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text if message.content else "{}"
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Claude response was not valid JSON: %s", exc)
        return {}
    except Exception as exc:
        logger.warning("Claude analysis failed: %s", exc)
        return {}


async def _analyze_with_gemini(prompt: str) -> dict[str, str]:
    """Call Gemini Flash via Vertex AI (cost-efficient) for analysis.

    Uses google-genai SDK with vertexai=True (Application Default Credentials).
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning(
            "google-genai package not installed; run: uv add google-genai"
        )
        return {}

    client = genai.Client(
        vertexai=True,
        project=settings.vertex_ai_project,
        location=settings.vertex_ai_location,
    )
    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=2048,
                temperature=1.0,  # required for thinking mode
                thinking_config=types.ThinkingConfig(thinking_budget=1024),
            ),
        )
        raw = response.text or "{}"
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        logger.warning("Gemini response was not valid JSON: %s", exc)
        return {}
    except Exception as exc:
        logger.warning("Gemini (Vertex AI) analysis failed: %s", exc)
        return {}


async def analyze_vulnerability(vuln_dict: dict[str, Any]) -> dict[str, str]:
    """Analyze a vulnerability using the configured LLM provider.

    Returns a dict with keys: attack_summary, applicability, recommended_actions.
    Returns empty dict if no LLM is configured or analysis fails.
    """
    provider = _resolve_provider()
    if provider is None:
        logger.debug("No LLM API key configured, skipping LLM analysis")
        return {}

    ids = " / ".join(filter(None, [vuln_dict.get("cve_id"), vuln_dict.get("ghsa_id")]))
    component = vuln_dict.get("affected_component_name", "unknown")
    tags = ", ".join(vuln_dict.get("tags", []) or [])

    prompt = ANALYSIS_PROMPT.format(
        title=vuln_dict.get("title", ""),
        ids=ids or "N/A",
        severity=vuln_dict.get("severity", ""),
        cvss=vuln_dict.get("cvss_score", "N/A"),
        component=component,
        description=(vuln_dict.get("description", "") or "")[:800],
        tags=tags or "none",
    )

    logger.debug("Running LLM analysis with provider=%s for %s", provider, ids or "unknown")

    if provider == "claude":
        result = await _analyze_with_claude(prompt)
    else:
        result = await _analyze_with_gemini(prompt)

    if not result:
        return {}

    return {
        "attack_summary": str(result.get("attack_summary", "")),
        "applicability": str(result.get("applicability", "")),
        "recommended_actions": str(result.get("recommended_actions", "")),
    }
