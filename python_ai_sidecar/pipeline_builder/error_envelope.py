"""ErrorEnvelope — structured error contract shared by tools, blocks, and validator.

Why: when LLMs reflect/repair, they need more than a free-text error message.
They need to know WHICH param is wrong, WHAT value was given, WHAT range was
expected, and WHERE that constraint comes from (block description / schema).
A flat `(code, message, hint)` tuple gives the LLM no structure to work with —
it has to parse English. Worse, hints often drift toward fix recipes ("set
limit to 50") which violates the description-driven-truth principle in
CLAUDE.md.

This module:
  1. Defines stable error codes (12 total — covers the failure modes the agent
     loop actually needs to disambiguate)
  2. Provides ErrorEnvelope: structured fields (param/given/expected/rationale)
     that BlockExecutionError + ToolError + validator issues all populate
  3. Keeps `message` for human/log readability; LLM prompts read the
     structured fields directly

The 12 codes are chosen so that any agent-side handler can switch on `code`
and get useful behaviour without parsing strings. More codes can be added,
but resist per-block codes — keep them generic across blocks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ── Error codes (12 total) ───────────────────────────────────────────────
# Param-level (most common, drive repair_op / reflect_op)
PARAM_MISSING = "PARAM_MISSING"               # required param not supplied
PARAM_VALUE_INVALID = "PARAM_VALUE_INVALID"   # value out of range / bad enum value / regex mismatch
PARAM_TYPE_WRONG = "PARAM_TYPE_WRONG"         # int got string, etc.
PARAM_REF_UNRESOLVED = "PARAM_REF_UNRESOLVED" # logical id / $input ref doesn't bind

# Structure-level (drive reflect_plan when canvas is structurally broken)
STRUCTURE_ORPHAN = "STRUCTURE_ORPHAN"               # node has no incoming edge
STRUCTURE_PORT_MISMATCH = "STRUCTURE_PORT_MISMATCH" # connect to a port that doesn't exist / wrong type
STRUCTURE_CYCLE = "STRUCTURE_CYCLE"                 # cycle in DAG
STRUCTURE_TERMINAL_VIOLATION = "STRUCTURE_TERMINAL_VIOLATION"  # downstream of a terminal block (e.g. step_check)

# Block-level (drive block-aware repair)
BLOCK_NOT_FOUND = "BLOCK_NOT_FOUND"           # unknown block_id
BLOCK_VERSION_MISMATCH = "BLOCK_VERSION_MISMATCH"  # block_version not supported

# Runtime / data-level (drive reflect_op / reflect_plan after preview)
DATA_EMPTY = "DATA_EMPTY"                     # block returned 0 rows / null output
DATA_SHAPE_WRONG = "DATA_SHAPE_WRONG"         # column missing, wrong dtype in output

# ── Convenience tuple for membership checks ───────────────────────────────
ALL_CODES: tuple[str, ...] = (
    PARAM_MISSING, PARAM_VALUE_INVALID, PARAM_TYPE_WRONG, PARAM_REF_UNRESOLVED,
    STRUCTURE_ORPHAN, STRUCTURE_PORT_MISMATCH, STRUCTURE_CYCLE, STRUCTURE_TERMINAL_VIOLATION,
    BLOCK_NOT_FOUND, BLOCK_VERSION_MISMATCH,
    DATA_EMPTY, DATA_SHAPE_WRONG,
)


@dataclass
class ErrorEnvelope:
    """Structured error payload — populated wherever a tool/block/validator
    detects a failure, consumed by the agent reflection prompts.

    Field rationale:
      code: stable identifier; LLM switches on this
      message: short human-readable summary (log + fallback for LLM)
      param: which param caused this (None for structure errors)
      given: literal value the agent supplied (for `param` failures)
      expected: declarative description of what would have been valid —
                pulled from block param_schema. NEVER a fix recipe.
                Examples: {"type":"int", "min":1, "max":1000} or
                          {"enum":["xbar_chart","ewma_chart"]}
      rationale: short snippet from block.description explaining the
                 constraint's intent (description-driven truth).
      node_id: logical or real id of the failing node (if applicable)
      block_id: block where the error originated
      hint: deprecated free-text — kept for backward compat with old
            callers; new callers should leave it None and use the
            structured fields above.
    """

    code: str
    message: str
    param: Optional[str] = None
    given: Any = None
    expected: Optional[dict[str, Any]] = None
    rationale: Optional[str] = None
    node_id: Optional[str] = None
    block_id: Optional[str] = None
    hint: Optional[str] = None  # legacy

    def to_dict(self) -> dict[str, Any]:
        """Compact dict for SSE / LLM prompts. Omits None fields so the
        prompt isn't cluttered with empty slots."""
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        for k in ("param", "given", "expected", "rationale", "node_id", "block_id", "hint"):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        return out

    @classmethod
    def from_legacy(cls, code: str, message: str, hint: Optional[str] = None) -> "ErrorEnvelope":
        """Promote a (code, message, hint) triple to an envelope.
        Used by old call sites until they're migrated to structured fields.
        """
        return cls(code=code, message=message, hint=hint)
