"""Agent Builder session, operation, chat, and stream event dataclasses.

SESSION MODEL:
  An AgentBuilderSession is an ephemeral, in-memory record of one agent "run".
  It owns the pipeline_json being mutated, an ordered operations log, a chat
  transcript (for UI display), and error events. Sessions are NOT persisted to
  DB in Phase 3.2; the final pipeline is only written to pb_pipelines when the
  user explicitly clicks Accept.

CANCELLATION:
  Each session has an asyncio.Event used as a cooperative cancel flag. The
  orchestrator checks it between tool calls; the `/cancel` endpoint sets it.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON


SessionStatus = Literal["running", "finished", "failed", "cancelled", "needs_input"]


def _now_ts() -> float:
    return datetime.now(tz=timezone.utc).timestamp()


@dataclass
class Operation:
    """One Agent tool call, its arguments, result, and timing."""
    op: str
    args: dict[str, Any]
    result: dict[str, Any]
    elapsed_ms: float
    ts: float = field(default_factory=_now_ts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "args": self.args,
            "result": self.result,
            "elapsed_ms": self.elapsed_ms,
            "ts": self.ts,
        }


@dataclass
class ChatMsg:
    """Agent's `explain()` message for chat panel."""
    content: str
    highlight_nodes: list[str] = field(default_factory=list)
    ts: float = field(default_factory=_now_ts)

    def to_dict(self) -> dict[str, Any]:
        return {"content": self.content, "highlight_nodes": self.highlight_nodes, "ts": self.ts}


@dataclass
class ErrorEvent:
    """A tool call failure seen by the Agent (Agent may retry)."""
    op: str
    message: str
    hint: Optional[str] = None
    ts: float = field(default_factory=_now_ts)

    def to_dict(self) -> dict[str, Any]:
        d = {"op": self.op, "message": self.message, "ts": self.ts}
        if self.hint:
            d["hint"] = self.hint
        return d


@dataclass
class StreamEvent:
    """Unit of communication from backend orchestrator to SSE client."""
    # PR-E3b: `suggestion_card` — agent proposes a series of actions without
    # applying them; frontend renders a card with Apply/Dismiss buttons.
    # `advisor_answer` is emitted by the Block Advisor (agent_builder/advisor)
    # when the user's message is a Q&A intent (EXPLAIN/COMPARE/RECOMMEND/AMBIGUOUS)
    # rather than a build instruction. Carries `{kind, markdown, ...}`.
    type: Literal[
        # Legacy v1 + advisor:
        "chat", "operation", "error", "done",
        "suggestion_card", "advisor_answer",
        # Phase 10 graph_build v2:
        "plan_proposed", "plan_validating", "plan_repaired",
        "confirm_pending", "confirm_received",
        "op_dispatched", "op_completed", "op_error", "op_repaired",
        "build_finalized",
    ]
    data: dict[str, Any]

    def to_sse(self) -> str:
        """Render as a named SSE event frame.

        Format:
            event: <type>
            data: <json>\n\n
        """
        import json
        return f"event: {self.type}\ndata: {json.dumps(self.data, ensure_ascii=False, default=str)}\n\n"


@dataclass
class AgentBuilderSession:
    """Ephemeral state for one agent run. Not persisted to DB."""

    session_id: str
    user_prompt: str
    base_pipeline_id: Optional[int]
    # Working state — mutated by tool calls
    pipeline_json: PipelineJSON
    # Ordered audit records
    operations: list[Operation] = field(default_factory=list)
    chat: list[ChatMsg] = field(default_factory=list)
    errors: list[ErrorEvent] = field(default_factory=list)
    # Status flags
    status: SessionStatus = "running"
    summary: Optional[str] = None
    started_at: float = field(default_factory=_now_ts)
    finished_at: Optional[float] = None
    # Cancellation (cooperative)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    # ----------------------------------------------------------------------
    # Constructors
    # ----------------------------------------------------------------------

    @classmethod
    def new(
        cls,
        user_prompt: str,
        base_pipeline: Optional[PipelineJSON] = None,
        base_pipeline_id: Optional[int] = None,
    ) -> "AgentBuilderSession":
        pipeline = base_pipeline or PipelineJSON(
            version="1.0",
            name="New Pipeline (Agent)",
            metadata={"created_by": "agent"},
            nodes=[],
            edges=[],
        )
        return cls(
            session_id=str(uuid.uuid4()),
            user_prompt=user_prompt,
            base_pipeline_id=base_pipeline_id,
            pipeline_json=pipeline,
        )

    # ----------------------------------------------------------------------
    # Mutators
    # ----------------------------------------------------------------------

    def record_op(self, op: Operation) -> None:
        self.operations.append(op)

    def record_chat(self, msg: ChatMsg) -> None:
        self.chat.append(msg)

    def record_error(self, err: ErrorEvent) -> None:
        self.errors.append(err)

    def mark_finished(self, summary: str) -> None:
        self.status = "finished"
        self.summary = summary
        self.finished_at = _now_ts()

    def mark_failed(self, reason: str) -> None:
        self.status = "failed"
        self.summary = reason
        self.finished_at = _now_ts()

    def mark_cancelled(self) -> None:
        self.status = "cancelled"
        self.finished_at = _now_ts()

    def request_cancel(self) -> None:
        self.cancel_event.set()

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    # ----------------------------------------------------------------------
    # Serialization
    # ----------------------------------------------------------------------

    def to_public_dict(self) -> dict[str, Any]:
        """Safe JSON-serializable view (no asyncio.Event, etc.)."""
        return {
            "session_id": self.session_id,
            "status": self.status,
            "user_prompt": self.user_prompt,
            "base_pipeline_id": self.base_pipeline_id,
            "pipeline_json": self.pipeline_json.model_dump(by_alias=True),
            "operations": [op.to_dict() for op in self.operations],
            "chat": [c.to_dict() for c in self.chat],
            "errors": [e.to_dict() for e in self.errors],
            "summary": self.summary,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
