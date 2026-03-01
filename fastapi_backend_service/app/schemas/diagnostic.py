"""Pydantic schemas for the diagnostic agent endpoint.

``DiagnoseRequest``  — accepted by ``POST /api/v1/diagnose``.
``ToolCallRecord``   — captures a single tool invocation for the report.
``DiagnoseResponse`` — the final structured response returned to the caller.
"""

from typing import Any, Dict

from pydantic import BaseModel, Field


class EventDrivenDiagnoseRequest(BaseModel):
    """Request body for POST /api/v1/diagnose/event-driven."""

    event_type: str = Field(..., description="Event type name, e.g. SPC_OOC_Etch_CD")
    event_id: str = Field(..., description="Unique event identifier")
    params: Dict[str, str] = Field(default_factory=dict, description="Event parameters")


class DiagnoseRequest(BaseModel):
    """Request body for the /diagnose endpoint."""

    issue_description: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="使用者對問題的自然語言描述，例如「系統變好慢」。",
        examples=["系統變好慢，CPU 使用率好像很高"],
    )


class ToolCallRecord(BaseModel):
    """Records a single tool invocation during the agent loop."""

    tool_name: str = Field(description="呼叫的工具名稱")
    tool_input: dict[str, Any] = Field(description="傳入工具的參數")
    tool_result: dict[str, Any] = Field(description="工具回傳的結果")


class DiagnoseResponse(BaseModel):
    """Structured response returned after the diagnostic agent loop completes."""

    issue_description: str = Field(description="原始問題描述")
    tools_invoked: list[ToolCallRecord] = Field(
        default_factory=list,
        description="Agent 在本次診斷中依序呼叫的工具清單",
    )
    diagnosis_report: str = Field(
        description="LLM 統整所有工具結果後產出的 Markdown 格式診斷報告",
    )
    total_turns: int = Field(
        description="Agent 執行的總迴圈次數",
        ge=0,
    )
