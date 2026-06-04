"""mcp_derivative — LLM-assisted generation of Pipeline Builder block + skill
drafts from a System MCP's description.

Public entry points:
    - generator.generate_derivatives(...): runs Claude Haiku 4.5 to produce
      structured drafts. Returns dict with {block_draft, skill_draft,
      lint_issues, llm_model, input_tokens, output_tokens, prompt_version}.
    - proxy_executor.McpProxyBlockExecutor: runtime executor for auto-generated
      blocks (source=mcp_auto). Delegates to the same code path as
      block_mcp_call but reads mcp_name from the block spec's implementation.

Wiring:
    - routers/mcp_derivative.py mounts POST /internal/mcp/generate-derivatives
    - pipeline_builder/blocks/__init__.py registers McpProxyBlockExecutor
      against the synthetic key "__mcp_proxy__"; block_registry maps
      implementation.type=="mcp_proxy" to it.
"""

from python_ai_sidecar.mcp_derivative.generator import (
    PROMPT_VERSION,
    GenerateResult,
    generate_derivatives,
    lint_mcp_description,
)

__all__ = [
    "PROMPT_VERSION",
    "GenerateResult",
    "generate_derivatives",
    "lint_mcp_description",
]
