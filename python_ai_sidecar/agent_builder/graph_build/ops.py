"""Op + OpType — the 5 atomic actions plan_node can produce.

LLM uses logical node ids (n1, n2, ...) when planning. The graph runtime
(call_tool_node) maps logical → real ids as add_node ops complete and
substitutes them on subsequent ops automatically.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class OpType(str, Enum):
    ADD_NODE = "add_node"
    CONNECT = "connect"
    SET_PARAM = "set_param"
    RUN_PREVIEW = "run_preview"
    REMOVE_NODE = "remove_node"


class Op(BaseModel):
    """One atomic plan step. Schema is permissive — validate_plan_node
    enforces type-specific required fields."""

    type: OpType

    # ADD_NODE
    block_id: Optional[str] = None
    block_version: Optional[str] = "1.0.0"

    # SET_PARAM / REMOVE_NODE / RUN_PREVIEW
    node_id: Optional[str] = None  # logical id e.g. "n1"

    # CONNECT
    src_id: Optional[str] = None
    src_port: Optional[str] = None
    dst_id: Optional[str] = None
    dst_port: Optional[str] = None

    # ADD_NODE (initial params) / SET_PARAM (single key+value)
    params: Optional[dict[str, Any]] = None

    # Filled by graph runtime — never produced by LLM
    result_node_id: Optional[str] = None
    result_status: Literal["pending", "ok", "error"] = "pending"
    error_message: Optional[str] = None
    repair_attempts: int = 0

    @model_validator(mode="after")
    def _check_type_specific(self) -> "Op":
        """Ensure each op type has its required fields. Errors here surface
        in validate_plan_node so repair_plan can fix them."""
        if self.type == OpType.ADD_NODE:
            if not self.block_id:
                raise ValueError("add_node requires block_id")
        elif self.type == OpType.CONNECT:
            missing = [
                f for f in ("src_id", "src_port", "dst_id", "dst_port")
                if not getattr(self, f)
            ]
            if missing:
                raise ValueError(f"connect missing fields: {missing}")
        elif self.type == OpType.SET_PARAM:
            if not self.node_id:
                raise ValueError("set_param requires node_id")
            if not self.params or "key" not in self.params:
                raise ValueError("set_param requires params={'key':..., 'value':...}")
        elif self.type == OpType.RUN_PREVIEW:
            if not self.node_id:
                raise ValueError("run_preview requires node_id")
        elif self.type == OpType.REMOVE_NODE:
            if not self.node_id:
                raise ValueError("remove_node requires node_id")
        return self

    def short_summary(self) -> str:
        """One-line description for confirm card / SSE summaries."""
        if self.type == OpType.ADD_NODE:
            return f"add {self.block_id} (as {self.node_id or '?'})"
        if self.type == OpType.CONNECT:
            return f"connect {self.src_id}.{self.src_port} → {self.dst_id}.{self.dst_port}"
        if self.type == OpType.SET_PARAM:
            k = (self.params or {}).get("key", "?")
            v = (self.params or {}).get("value", "?")
            return f"{self.node_id}.{k} = {v!r}"
        if self.type == OpType.RUN_PREVIEW:
            return f"preview {self.node_id}"
        if self.type == OpType.REMOVE_NODE:
            return f"remove {self.node_id}"
        return self.type.value
