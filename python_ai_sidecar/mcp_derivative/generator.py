"""mcp_derivative.generator — LLM-assisted generation of block + skill drafts
from a System MCP description.

Forced to Claude Haiku 4.5 by default (cheap + fast) per the V54 spec. Caller
can override via env ``MCP_DERIVATIVE_LLM_MODEL`` if needed. Provider follows
the global LLM_PROVIDER (Anthropic / OpenRouter via internal-proxy).

Prompt design follows the V54 / CLAUDE.md "Core Principle 0" rule: prompt
contains *principles* about what good descriptions look like, never
case-specific rules. If LLM output keeps drifting, fix the principle wording
or move the rule into a deterministic lint step — never grow a case list.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from python_ai_sidecar.agent_helpers_native.llm_client import (
    AnthropicLLMClient,
    BaseLLMClient,
    LLMResponse,
    get_llm_client,
)

logger = logging.getLogger(__name__)

# Bump whenever the prompt below changes — stored on the MCP row for audit.
PROMPT_VERSION = "v1-2026-06-03"

# Hardcoded default per spec §2.5 decision (user-approved). Override via env
# only for experimentation — production code paths should not pass force_model.
DEFAULT_LLM_MODEL = os.environ.get(
    "MCP_DERIVATIVE_LLM_MODEL", "claude-haiku-4-5-20251001"
)

# Description lint thresholds (pre-LLM gate). Frontend mirrors these; sidecar
# re-checks because frontend is bypassable.
MIN_DESCRIPTION_CHARS = 200
RECOMMENDED_DESCRIPTION_CHARS = 400


# ── Public types ──────────────────────────────────────────────────────────────


@dataclass
class GenerateResult:
    """Structured response from generate_derivatives."""

    block_draft: dict[str, Any] | None = None
    skill_draft: dict[str, Any] | None = None
    lint_issues: list[dict[str, Any]] = field(default_factory=list)
    llm_model: str = ""
    prompt_version: str = PROMPT_VERSION
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_draft": self.block_draft,
            "skill_draft": self.skill_draft,
            "lint_issues": self.lint_issues,
            "llm_model": self.llm_model,
            "prompt_version": self.prompt_version,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


# ── Public API ────────────────────────────────────────────────────────────────


def lint_mcp_description(description: str | None) -> list[dict[str, Any]]:
    """Deterministic pre-LLM checks on the MCP description.

    Returns a list of issue dicts ``{severity, field, message}``. Empty list
    means the description is usable. ``severity="error"`` blocks generation;
    ``severity="warn"`` is advisory only.
    """
    issues: list[dict[str, Any]] = []
    text = (description or "").strip()

    if not text:
        issues.append({
            "severity": "error",
            "field": "description",
            "message": "MCP description is empty. LLM cannot generate block + skill drafts.",
        })
        return issues

    if len(text) < MIN_DESCRIPTION_CHARS:
        issues.append({
            "severity": "error",
            "field": "description",
            "message": (
                f"Description too short ({len(text)} chars, need ≥ {MIN_DESCRIPTION_CHARS}). "
                "Add: what it returns, key field semantics, typical use cases."
            ),
        })
    elif len(text) < RECOMMENDED_DESCRIPTION_CHARS:
        issues.append({
            "severity": "warn",
            "field": "description",
            "message": (
                f"Description is short ({len(text)} chars). LLM output quality improves "
                f"sharply past {RECOMMENDED_DESCRIPTION_CHARS} chars. Consider documenting "
                "return field types + use-when scenarios."
            ),
        })

    lower = text.lower()
    has_returns_section = any(k in lower for k in (
        "returns", "return", "回傳", "回應", "response", "output"
    ))
    if not has_returns_section:
        issues.append({
            "severity": "warn",
            "field": "description",
            "message": (
                "Description doesn't appear to document what the MCP returns. "
                "LLM cannot describe block output if return shape is implicit."
            ),
        })

    has_use_when = any(k in lower for k in (
        "use when", "use case", "when to", "when ", "用於", "使用場景", "情境"
    ))
    if not has_use_when:
        issues.append({
            "severity": "warn",
            "field": "description",
            "message": (
                "Description doesn't say WHEN to use this MCP. "
                "Skill use_case / when_to_use will be vague."
            ),
        })

    return issues


async def generate_derivatives(
    *,
    mcp_name: str,
    mcp_description: str,
    input_schema: Any | None = None,
    output_schema: Any | None = None,
    api_config: Any | None = None,
    want_block: bool = True,
    want_skill: bool = True,
    force_client: BaseLLMClient | None = None,
) -> GenerateResult:
    """Call the LLM to generate block + skill drafts for an MCP.

    Args:
        mcp_name: snake_case identifier (e.g. ``rework_request``).
        mcp_description: rich free-text description (≥ 200 chars).
        input_schema: JSON-stringified or dict form of MCP input fields.
        output_schema: JSON-stringified or dict form of the MCP response shape.
        api_config: ``{endpoint_url, method}`` — informational only for the LLM.
        want_block / want_skill: caller may opt out per spec §2.5 decision 4.
        force_client: test injection — bypasses get_llm_client().

    Returns: GenerateResult with drafts populated for requested artefacts.
    """
    lint_issues = lint_mcp_description(mcp_description)
    blocking = [i for i in lint_issues if i.get("severity") == "error"]
    if blocking:
        # Don't burn LLM tokens on input that's certain to fail.
        return GenerateResult(lint_issues=lint_issues, llm_model="")

    client = force_client or _haiku_client()
    system_prompt = _build_system_prompt(want_block=want_block, want_skill=want_skill)
    user_prompt = _build_user_prompt(
        name=mcp_name,
        description=mcp_description,
        input_schema=input_schema,
        output_schema=output_schema,
        api_config=api_config,
        want_block=want_block,
        want_skill=want_skill,
    )

    resp: LLMResponse = await client.create(
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=2400,
    )

    parsed = _safe_parse_json(resp.text)
    if parsed is None:
        lint_issues.append({
            "severity": "error",
            "field": "_llm_output",
            "message": "LLM output was not valid JSON; cannot use draft.",
        })
        logger.warning(
            "MCP derivative generator: invalid JSON from LLM for mcp_name=%s. Raw: %s",
            mcp_name, resp.text[:400],
        )
        return GenerateResult(
            lint_issues=lint_issues,
            llm_model=DEFAULT_LLM_MODEL,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
        )

    block_draft = parsed.get("block_draft") if want_block else None
    skill_draft = parsed.get("skill_draft") if want_skill else None
    extra_issues = parsed.get("lint_issues") or []
    if isinstance(extra_issues, list):
        for issue in extra_issues:
            if isinstance(issue, dict):
                lint_issues.append(issue)

    return GenerateResult(
        block_draft=block_draft,
        skill_draft=skill_draft,
        lint_issues=lint_issues,
        llm_model=DEFAULT_LLM_MODEL,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
    )


# ── Internals ─────────────────────────────────────────────────────────────────


def _haiku_client() -> BaseLLMClient:
    """Build a per-call Anthropic client pinned to Haiku 4.5.

    We bypass the cached get_llm_client() because that uses the global
    LLM_MODEL — typically Sonnet, which would be 10x the cost for this
    bounded structured-output task.
    """
    from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings
    settings = get_settings()
    if settings.LLM_PROVIDER != "anthropic":
        # Caller (sidecar) configured a different provider. Honour it via the
        # cached client; the model may not be Haiku but that's a deployment
        # choice. Log for visibility.
        logger.info(
            "MCP derivative generator: LLM_PROVIDER=%s, using cached client "
            "(model=%s) instead of Haiku.",
            settings.LLM_PROVIDER, settings.LLM_MODEL,
        )
        return get_llm_client()
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "MCP derivative generator requires ANTHROPIC_API_KEY when "
            "LLM_PROVIDER=anthropic."
        )
    return AnthropicLLMClient(
        api_key=settings.ANTHROPIC_API_KEY,
        model=DEFAULT_LLM_MODEL,
    )


def _build_system_prompt(*, want_block: bool, want_skill: bool) -> str:
    """Build the system prompt. Principles only — no case-specific rules.

    CLAUDE.md Core Principle 0: every rule here is phrased as a one-line
    principle that applies to all MCPs. If a future MCP slips through, fix
    the principle wording or move the check into the deterministic lint
    step — do not append "for MCPs like X, also do Y".
    """
    pieces: list[str] = [
        "You generate Pipeline Builder artefact drafts from a System MCP "
        "description. The MCP description is the single source of truth — "
        "your output must be derivable from it without external knowledge.",
        "",
        "OUTPUT FORMAT: respond with ONLY a JSON object. No prose, no markdown. "
        "Top-level keys: block_draft, skill_draft, lint_issues. Each may be "
        "null if not requested or not derivable.",
        "",
        "PRINCIPLES",
        "1. block_draft.description must explain what the BLOCK RETURNS to "
        "   downstream pipeline nodes (column names + semantics), not what "
        "   the underlying HTTP API does.",
        "2. block_draft.param_schema mirrors the MCP input_schema in JSON "
        "   Schema 'object' style: {type: object, properties: {<name>: "
        "   {type, description}}, required: [...]}.",
        "3. block_draft.examples is a list of {q, plan} objects where q is "
        "   a natural-language user question and plan is a one-line text "
        "   description of how the block would be used. Use the MCP "
        "   description's use-cases to derive examples; do not invent "
        "   scenarios.",
        "4. block_draft.output_columns_hint lists the dataframe columns the "
        "   block emits with {name, type, description}. Derive from the MCP "
        "   description's return shape; mark uncertain entries with "
        "   description prefix '[inferred]'.",
        "5. skill_draft.use_case is ONE business-language sentence (≤ 25 words) "
        "   stating who uses this and why. Avoid implementation jargon.",
        "6. skill_draft.when_to_use is a list of 2-4 short trigger phrases "
        "   in the language the user would naturally ask (e.g. \"哪些 lot 有 "
        "   rework?\" or \"recent reworks for LOT-0123\"). Each phrase ≤ 15 words.",
        "7. skill_draft.inputs_schema mirrors the required user-facing inputs "
        "   (subset of MCP input — exclude internal-only params).",
        "8. skill_draft.outputs_schema is a single object with shape "
        "   {kind: 'dataframe'|'scalar'|'panel', columns: [...]}.",
        "9. skill_draft.tags is 1-3 short kebab-case domain tags derived from "
        "   the description (e.g. ['spc','quality']).",
        "10. lint_issues is a list of {severity, field, message} for any "
        "    derivation that required guessing. Use severity 'warn' for "
        "    uncertain inferences, 'error' only when the description is so "
        "    sparse that the draft is unusable.",
        "",
        "PRINCIPLE FOR SLUG / NAME",
        "- block_draft.block_name follows the pattern 'block_mcp_<mcp_name>'.",
        "- skill_draft.slug is kebab-case, ≤ 60 chars, derived from mcp_name "
        "  (e.g. 'mcp-rework-request').",
        "- skill_draft.name is Title-Case human-readable (e.g. 'Rework Request "
        "  Lookup').",
        "",
        "WHAT NOT TO DO",
        "- Do NOT invent fields that aren't mentioned or implied in the "
        "  description.",
        "- Do NOT copy the MCP description verbatim into block.description; "
        "  rewrite from the block consumer's perspective.",
        "- Do NOT add markdown formatting, code fences, or commentary to the "
        "  JSON output.",
    ]
    if not want_block:
        pieces.append("\nblock_draft: set to null. Caller does not want it.")
    if not want_skill:
        pieces.append("\nskill_draft: set to null. Caller does not want it.")
    return "\n".join(pieces)


def _build_user_prompt(
    *,
    name: str,
    description: str,
    input_schema: Any | None,
    output_schema: Any | None,
    api_config: Any | None,
    want_block: bool,
    want_skill: bool,
) -> str:
    """Build the user message — contains the MCP being summarised."""
    parts = [
        f"MCP_NAME: {name}",
        "",
        "MCP_DESCRIPTION:",
        description.strip(),
        "",
    ]
    if input_schema:
        parts.append("MCP_INPUT_SCHEMA (JSON):")
        parts.append(_to_json_str(input_schema))
        parts.append("")
    if output_schema:
        parts.append("MCP_OUTPUT_SCHEMA (JSON):")
        parts.append(_to_json_str(output_schema))
        parts.append("")
    if api_config:
        parts.append("MCP_API_CONFIG (JSON):")
        parts.append(_to_json_str(api_config))
        parts.append("")

    parts.append("REQUESTED_OUTPUTS:")
    parts.append(f"- block_draft: {'yes' if want_block else 'no (return null)'}")
    parts.append(f"- skill_draft: {'yes' if want_skill else 'no (return null)'}")
    parts.append("")
    parts.append("Respond with the JSON object now.")
    return "\n".join(parts)


def _to_json_str(value: Any) -> str:
    """Normalise input schema / output schema to a pretty JSON string for the
    user message. Strings already parsed elsewhere are passed through if they
    look like JSON; otherwise the raw value is dumped.
    """
    if value is None:
        return "null"
    if isinstance(value, str):
        # Already-stringified JSON: pretty-print if parseable, else show raw.
        try:
            return json.dumps(json.loads(value), indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            return value
    return json.dumps(value, indent=2, ensure_ascii=False)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)\s*```", re.IGNORECASE)


def _safe_parse_json(text: str) -> dict[str, Any] | None:
    """Best-effort parse: strip code fences, locate the outermost JSON object."""
    if not text or not text.strip():
        return None

    candidate = text.strip()

    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    # Try to locate the first '{' and last '}' as a recovery — covers models
    # that prepend a sentence despite the prompt instruction.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(candidate[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None
