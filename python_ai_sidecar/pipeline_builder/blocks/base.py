"""BlockExecutor ABC and ExecutionContext for Pipeline Builder."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


class BlockExecutionError(Exception):
    """Raised by a Block when it fails. Carries a structured error code."""

    def __init__(self, code: str, message: str, *, hint: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "hint": self.hint}


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
    def require(params: dict[str, Any], key: str) -> Any:
        """Utility to pull a required parameter or raise BlockExecutionError."""
        if key not in params or params[key] is None:
            raise BlockExecutionError(
                code="MISSING_PARAM",
                message=f"Required parameter '{key}' is missing",
            )
        return params[key]
