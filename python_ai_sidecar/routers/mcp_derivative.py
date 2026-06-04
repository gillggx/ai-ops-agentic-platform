"""mcp_derivative router — /internal/mcp/generate-derivatives.

Java's MCPGenerationProxy posts here when the admin form's "Generate from
description" button fires. The sidecar runs Claude Haiku 4.5, parses the
structured JSON, and returns the drafts so the user can edit them in the
form before committing via POST /api/v1/mcp-definitions.

This endpoint does NOT write to the DB — that's the Java side's job inside
the atomic create. Keeping the LLM call read-only avoids partial-failure
debugging (LLM said X, DB shows Y).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth import CallerContext, ServiceAuth
from ..mcp_derivative.generator import generate_derivatives

log = logging.getLogger("python_ai_sidecar.mcp_derivative")
router = APIRouter(prefix="/internal/mcp", tags=["mcp-derivative"])


class GenerateRequest(BaseModel):
    """Payload from Java's MCPGenerationProxy."""

    mcp_id: int | None = Field(
        default=None,
        description="Existing MCP id when regenerating. None when generating "
                    "for a draft (form not yet saved).",
    )
    name: str
    description: str
    input_schema: Any | None = None
    output_schema: Any | None = None
    api_config: Any | None = None
    want_block: bool = True
    want_skill: bool = True


@router.post("/generate-derivatives")
async def generate_derivatives_endpoint(
    body: GenerateRequest,
    caller: CallerContext = ServiceAuth,
) -> dict[str, Any]:
    """Generate block + skill drafts from an MCP description."""
    log.info(
        "MCP derivative generation: mcp_name=%s want_block=%s want_skill=%s caller_uid=%s",
        body.name, body.want_block, body.want_skill, caller.user_id,
    )
    try:
        result = await generate_derivatives(
            mcp_name=body.name,
            mcp_description=body.description,
            input_schema=body.input_schema,
            output_schema=body.output_schema,
            api_config=body.api_config,
            want_block=body.want_block,
            want_skill=body.want_skill,
        )
    except RuntimeError as e:
        # e.g. ANTHROPIC_API_KEY missing.
        log.warning("MCP derivative generation config error: %s", e)
        raise HTTPException(status_code=503, detail=str(e)) from e

    return result.to_dict()
