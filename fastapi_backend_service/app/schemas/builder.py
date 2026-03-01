"""Pydantic v2 schemas for the LLM-powered Builder API.

Three design-time assistants:
- ``AutoMapRequest / AutoMapResponse``     → 智能映射 (semantic field mapping)
- ``ValidateLogicRequest / ValidateLogicResponse`` → 語意防呆 (logic validation)
- ``SuggestLogicRequest / SuggestLogicResponse``  → 智能提示 (expert suggestions)
"""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# /auto-map
# ---------------------------------------------------------------------------


class AutoMapRequest(BaseModel):
    """Input for the auto-mapping endpoint."""

    event_schema: dict = Field(
        ...,
        description=(
            "SPC OOC Event Object 中 attributes 欄位的 JSON Schema，"
            "例如 {'eqp_id': {'type': 'string', 'description': '蝕刻機台代碼'}, ...}"
        ),
    )
    tool_input_schema: dict = Field(
        ...,
        description=(
            "MCP 工具的 input_schema（來自 BaseMCPSkill.input_schema），"
            "例如 {'properties': {'target_equipment': {...}, 'target_chamber': {...}}}"
        ),
    )


class FieldMapping(BaseModel):
    """A single semantic mapping from event attribute to tool parameter."""

    event_field: str = Field(..., description="Event Object 中的屬性名稱")
    tool_param: str = Field(..., description="對應的 MCP 工具輸入參數名稱")
    confidence: str = Field(..., description="映射信心度：HIGH / MEDIUM / LOW")
    reasoning: str = Field(..., description="LLM 映射推理說明")


class AutoMapResponse(BaseModel):
    """Output of the auto-mapping endpoint."""

    mappings: list[FieldMapping] = Field(..., description="語意映射清單")
    unmapped_tool_params: list[str] = Field(
        default_factory=list,
        description="未能從 Event 中找到對應值的工具參數",
    )
    summary: str = Field(..., description="整體映射結果摘要")


# ---------------------------------------------------------------------------
# /validate-logic
# ---------------------------------------------------------------------------


class ValidateLogicRequest(BaseModel):
    """Input for the logic validation endpoint."""

    user_prompt: str = Field(
        ...,
        min_length=10,
        description=(
            "使用者在 Builder UI 撰寫的診斷邏輯提示詞，"
            "例如「若 APC 補償量超過 5nm 則建議 Wet Clean」"
        ),
    )
    tool_output_schema: dict = Field(
        ...,
        description=(
            "MCP 工具 execute() 的回傳值結構描述（欄位名稱與型別），"
            "用於驗證 user_prompt 是否引用了工具實際提供的欄位"
        ),
    )


class ValidateLogicResponse(BaseModel):
    """Output of the logic validation endpoint."""

    is_valid: bool = Field(..., description="True 表示邏輯合法，False 表示有問題")
    issues: list[str] = Field(
        default_factory=list,
        description="發現的問題清單（當 is_valid=False 時填入）",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="改善建議（即使 is_valid=True 也可能有最佳化建議）",
    )
    validated_fields: list[str] = Field(
        default_factory=list,
        description="Prompt 中引用到且工具確實提供的欄位",
    )


# ---------------------------------------------------------------------------
# /suggest-logic
# ---------------------------------------------------------------------------


class SuggestLogicRequest(BaseModel):
    """Input for the logic suggestion endpoint."""

    event_schema: dict = Field(
        ...,
        description=(
            "SPC OOC Event Object 的完整屬性結構（含 description），"
            "LLM 將解析語意後產生排障建議"
        ),
    )
    context: str = Field(
        default="",
        description="額外背景資訊（選填），例如目前工廠環境、常見問題類型",
    )


class SuggestLogicResponse(BaseModel):
    """Output of the logic suggestion endpoint."""

    suggestions: list[str] = Field(
        ...,
        description="3~5 條 PE 等級的排障邏輯提示，每條以動詞開頭",
    )
    event_analysis: str = Field(
        ...,
        description="LLM 對 Event Schema 的解析摘要（說明為何給出上述建議）",
    )
