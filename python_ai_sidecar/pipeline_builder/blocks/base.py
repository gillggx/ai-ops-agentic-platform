"""BlockExecutor ABC and ExecutionContext for Pipeline Builder."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


class BlockExecutionError(Exception):
    """Raised by a Block when it fails. Carries a structured ErrorEnvelope so
    the reflect_op / reflect_plan LLM can disambiguate without parsing English.

    Backward compat: legacy callers pass (code, message, hint=...) and we
    auto-wrap into an envelope. New callers pass the structured kwargs
    (param/given/expected/rationale) directly.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: Optional[str] = None,
        param: Optional[str] = None,
        given: Any = None,
        expected: Optional[dict[str, Any]] = None,
        rationale: Optional[str] = None,
        node_id: Optional[str] = None,
        block_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        # Late import — error_envelope is a sibling module to avoid circular
        from python_ai_sidecar.pipeline_builder.error_envelope import ErrorEnvelope
        self.envelope = ErrorEnvelope(
            code=code, message=message, hint=hint,
            param=param, given=given, expected=expected,
            rationale=rationale, node_id=node_id, block_id=block_id,
        )

    # Back-compat attribute access — old callers read .code / .message / .hint
    @property
    def code(self) -> str:
        return self.envelope.code

    @property
    def message(self) -> str:
        return self.envelope.message

    @property
    def hint(self) -> Optional[str]:
        return self.envelope.hint

    def to_dict(self) -> dict[str, Any]:
        return self.envelope.to_dict()


@dataclass
class ExecutionContext:
    """Shared context passed to every block during a pipeline run.

    Attributes:
        run_id: DB id of PipelineRun (for log correlation).
        params_for_http: shared HTTP config (timeout, base URL) — optional.
        extras: arbitrary key-value scratchpad.
    """

    run_id: Optional[int] = None
    extras: dict[str, Any] = field(default_factory=dict)


class BlockExecutor(ABC):
    """Base class for all block executors.

    Subclasses override :meth:`execute` (async).
    """

    #: Stable id registered in DB (unique identifier used in Pipeline JSON).
    block_id: str = ""

    def __init__(self) -> None:
        if not self.block_id:
            raise RuntimeError(f"{type(self).__name__} missing block_id")

    @abstractmethod
    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Execute block logic.

        Args:
            params: User-supplied parameters, already validated against param_schema.
            inputs: Mapping of input port name -> upstream output object.
            context: Shared ExecutionContext.

        Returns:
            Mapping of output port name -> value.

        Raises:
            BlockExecutionError: Structured failure with code + message.
        """

    @staticmethod
    def require(params: dict[str, Any], key: str, *, expected: Optional[dict[str, Any]] = None, rationale: Optional[str] = None) -> Any:
        """Utility to pull a required parameter or raise BlockExecutionError.

        `expected` / `rationale` are optional but encouraged: they get
        forwarded to the ErrorEnvelope so the reflect LLM sees structured
        info instead of just "required param missing".
        """
        from python_ai_sidecar.pipeline_builder.error_envelope import PARAM_MISSING
        if key not in params or params[key] is None:
            raise BlockExecutionError(
                code=PARAM_MISSING,
                message=f"Required parameter '{key}' is missing",
                param=key,
                given=None,
                expected=expected,
                rationale=rationale,
            )
        return params[key]
