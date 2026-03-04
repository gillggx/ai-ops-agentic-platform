"""Builder Service — LLM-powered design-time assistant for the Skill Builder UI.

Three capabilities
------------------
``auto_map``
    Semantically maps Event Object attributes to MCP tool input parameters.
    Solves the problem of mismatched field names (e.g. ``eqp_id`` ↔ ``target_equipment``).

``validate_logic``
    Validates that a user-written diagnostic prompt only references fields
    that the selected MCP tool's output schema actually provides.

``suggest_logic``
    Analyses the SPC OOC Event Schema and returns 3-5 expert-level PE
    (Process Engineer) diagnostic logic suggestions to guide Skill configuration.
"""

import json
import logging

import anthropic

from app.config import get_settings
from app.schemas.builder import (
    AutoMapResponse,
    FieldMapping,
    SuggestLogicResponse,
    ValidateLogicResponse,
)

logger = logging.getLogger(__name__)

_MODEL = get_settings().LLM_MODEL


class BuilderService:
    """LLM-powered design-time helper for the Glass Box Skill Builder."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    # ------------------------------------------------------------------
    # /auto-map
    # ------------------------------------------------------------------

    async def auto_map(
        self,
        event_schema: dict,
        tool_input_schema: dict,
    ) -> AutoMapResponse:
        """Semantically map Event attributes → MCP tool input parameters.

        Args:
            event_schema: The ``attributes`` schema of a SPC OOC Event Object.
            tool_input_schema: The ``input_schema`` from a ``BaseMCPSkill``.

        Returns:
            ``AutoMapResponse`` with ``mappings`` and ``unmapped_tool_params``.
        """
        prompt = f"""你是半導體製程系統整合專家。

以下是一個 SPC OOC Event Object 的屬性結構（event_schema）：
{json.dumps(event_schema, ensure_ascii=False, indent=2)}

以下是一個 MCP 診斷工具的輸入參數結構（tool_input_schema）：
{json.dumps(tool_input_schema, ensure_ascii=False, indent=2)}

請根據語意對應，將 event_schema 的屬性名稱映射到 tool_input_schema 的參數名稱。
例如：eqp_id → target_equipment（兩者都代表蝕刻機台代碼）。

請以 JSON 格式回傳，結構如下：
{{
  "mappings": [
    {{
      "event_field": "<event 屬性名>",
      "tool_param": "<tool 參數名>",
      "confidence": "HIGH|MEDIUM|LOW",
      "reasoning": "<映射推理說明>"
    }}
  ],
  "unmapped_tool_params": ["<未映射的 tool 參數>"],
  "summary": "<整體映射結果摘要>"
}}

只回傳 JSON，不要有其他文字。"""

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)

        mappings = [FieldMapping(**m) for m in data.get("mappings", [])]
        return AutoMapResponse(
            mappings=mappings,
            unmapped_tool_params=data.get("unmapped_tool_params", []),
            summary=data.get("summary", ""),
        )

    # ------------------------------------------------------------------
    # /validate-logic
    # ------------------------------------------------------------------

    async def validate_logic(
        self,
        user_prompt: str,
        tool_output_schema: dict,
    ) -> ValidateLogicResponse:
        """Validate that user_prompt only references fields in tool_output_schema.

        Args:
            user_prompt: The diagnostic logic written by the user in Builder UI.
            tool_output_schema: Description of fields the MCP tool actually returns.

        Returns:
            ``ValidateLogicResponse`` with ``is_valid``, ``issues``, ``suggestions``.
        """
        prompt = f"""你是半導體製程 AI 系統的語意防呆引擎。

使用者撰寫了以下診斷邏輯提示詞：
\"\"\"{user_prompt}\"\"\"

MCP 工具的輸出結構（tool_output_schema）為：
{json.dumps(tool_output_schema, ensure_ascii=False, indent=2)}

請判斷：
1. user_prompt 是否引用了 tool_output_schema 中**不存在**的欄位？
2. 邏輯是否有語意矛盾（如「APC 飽和則 saturation_flag=false」）？
3. 有什麼改善建議？

請以 JSON 格式回傳：
{{
  "is_valid": true|false,
  "issues": ["<問題描述>"],
  "suggestions": ["<改善建議>"],
  "validated_fields": ["<確認存在的欄位>"]
}}

只回傳 JSON，不要有其他文字。"""

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)

        return ValidateLogicResponse(
            is_valid=data.get("is_valid", True),
            issues=data.get("issues", []),
            suggestions=data.get("suggestions", []),
            validated_fields=data.get("validated_fields", []),
        )

    # ------------------------------------------------------------------
    # /suggest-logic
    # ------------------------------------------------------------------

    async def suggest_logic(
        self,
        event_schema: dict,
        context: str = "",
    ) -> SuggestLogicResponse:
        """Generate 3-5 PE-grade diagnostic logic suggestions from the Event Schema.

        Args:
            event_schema: SPC OOC Event Object attribute structure with descriptions.
            context: Optional additional context (e.g. factory environment, common issues).

        Returns:
            ``SuggestLogicResponse`` with ``suggestions`` and ``event_analysis``.
        """
        context_section = f"\n額外背景資訊：{context}" if context else ""
        prompt = f"""你是一位台積電資深蝕刻製程工程師（Process Engineer），\
擁有豐富的 SPC OOC 排障與 APC 調校經驗。

以下是一個 SPC OOC Event Object 的屬性結構：
{json.dumps(event_schema, ensure_ascii=False, indent=2)}{context_section}

請根據這些屬性，提供 3~5 條專業的排障邏輯提示，幫助 PE 設定 Skill 的診斷條件。
每條提示應：
- 以動詞開頭（例如：「檢查...」「若...則...」「當...時...」）
- 具體指出使用哪個 Event 屬性、觸發什麼條件、採取什麼行動
- 符合半導體蝕刻製程的實務慣例

請以 JSON 格式回傳：
{{
  "event_analysis": "<對 Event Schema 的語意解析，說明各屬性的診斷意義>",
  "suggestions": [
    "<第 1 條排障邏輯提示>",
    "<第 2 條排障邏輯提示>",
    ...
  ]
}}

只回傳 JSON，不要有其他文字。"""

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)

        return SuggestLogicResponse(
            suggestions=data.get("suggestions", []),
            event_analysis=data.get("event_analysis", ""),
        )
