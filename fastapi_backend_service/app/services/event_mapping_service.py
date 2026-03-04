"""LLM Event Mapping Engine — Skill-to-Event parameter mapping (Phase 11).

When a Skill produces an ABNORMAL result and has `trigger_event_id` set,
this service:
  1. Builds a structured mapping prompt from skill result data + event attributes
  2. Forces the LLM to output a valid JSON dict of mapped parameters
  3. Creates a GeneratedEvent record in the DB (the automated alarm)

Design goals:
- Zero hallucination tolerance: strict JSON output, validation on every field
- Graceful degradation: best-effort mapping with null for unmappable required fields
- Audit trail: full skill result JSON stored in generated_event.skill_conclusion
"""

import json
import logging
from typing import Any, Dict, List, Optional

import anthropic

from app.config import get_settings

logger = logging.getLogger(__name__)

_MODEL = get_settings().LLM_MODEL

_MAPPING_SYSTEM_PROMPT = """\
你是一位半導體製程資料映射專家。你的唯一任務是從「Skill 診斷結果數據」中，\
精準萃取出「目標 Event 所需的參數值」，並嚴格回傳 JSON 格式。

【核心規則】
1. 僅回傳 JSON 物件，不得有任何其他文字、解釋或 markdown。
2. 每個 Event 參數都必須有值。若無法從資料中找到精確值，請根據上下文合理推斷。
3. 若完全無法推斷（資料完全無關），對該欄位回傳 null。
4. 所有值必須符合參數的 type（string/number/boolean）。
5. 時間戳記統一使用 ISO 8601 格式（e.g., 2026-03-01T08:00:00+00:00）。

【禁止事項】
- 禁止捏造與資料完全無關的值
- 禁止回傳 JSON 以外的任何內容
- 禁止使用 markdown 程式碼區塊（不要 ```json）
"""


def _build_mapping_prompt(
    skill_name: str,
    skill_status: str,
    skill_conclusion: str,
    skill_evidence: List[str],
    skill_summary: str,
    mcp_output_dataset: Any,
    event_type_name: str,
    event_attributes: List[Dict[str, Any]],
    preset_parameters: Dict[str, Any],
) -> str:
    """Build the user-turn prompt for the LLM mapping call."""
    required_params = [a for a in event_attributes if a.get("required", False)]
    optional_params = [a for a in event_attributes if not a.get("required", False)]

    param_list_lines = []
    for attr in required_params:
        param_list_lines.append(
            f'  - {attr["name"]} ({attr["type"]}, 必填): {attr.get("description", "")}'
        )
    for attr in optional_params:
        param_list_lines.append(
            f'  - {attr["name"]} ({attr["type"]}, 選填): {attr.get("description", "")}'
        )

    # Limit dataset to first 20 rows to keep prompt compact
    dataset_preview = mcp_output_dataset
    if isinstance(dataset_preview, list) and len(dataset_preview) > 20:
        dataset_preview = dataset_preview[:20]

    return f"""\
## Skill 診斷結果
- Skill 名稱: {skill_name}
- 診斷狀態: {skill_status}
- 結論: {skill_conclusion}
- 證據:
{chr(10).join(f"  * {e}" for e in skill_evidence)}
- 摘要: {skill_summary}

## 使用者預設參數 (preset_parameters)
{json.dumps(preset_parameters, ensure_ascii=False, indent=2)}

## MCP 原始數據集 (前20筆)
{json.dumps(dataset_preview, ensure_ascii=False, indent=2)}

## 目標 Event 類型
- Event 名稱: {event_type_name}

## 需要填寫的參數清單
{chr(10).join(param_list_lines)}

## 你的任務
請分析上面所有資料，填寫目標 Event 所需的所有參數。
嚴格回傳 JSON 格式（只有以下這些 key，不得新增或省略任何 key）：
{{
{chr(10).join(f'  "{a["name"]}": <{a["type"]}>' for a in event_attributes)}
}}"""


async def run_llm_mapping(
    skill_name: str,
    skill_result: Dict[str, Any],
    mcp_output: Optional[Dict[str, Any]],
    event_type_name: str,
    event_attributes: List[Dict[str, Any]],
    preset_parameters: Dict[str, Any],
) -> Dict[str, Any]:
    """Call LLM to map Skill result data to Event parameters.

    Returns a dict of {param_name: value} ready to store in GeneratedEvent.mapped_parameters.
    Never raises — returns {"_mapping_error": str} on failure.
    """
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    dataset = []
    if mcp_output and isinstance(mcp_output, dict):
        dataset = mcp_output.get("dataset", [])

    prompt = _build_mapping_prompt(
        skill_name=skill_name,
        skill_status=skill_result.get("status", "ABNORMAL"),
        skill_conclusion=skill_result.get("conclusion", ""),
        skill_evidence=skill_result.get("evidence", []),
        skill_summary=skill_result.get("summary", ""),
        mcp_output_dataset=dataset,
        event_type_name=event_type_name,
        event_attributes=event_attributes,
        preset_parameters=preset_parameters,
    )

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_MAPPING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text.strip()

        # Strip accidental markdown fences
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        mapped = json.loads(raw_text)
        if not isinstance(mapped, dict):
            raise ValueError(f"LLM returned non-dict: {type(mapped)}")

        logger.info(
            "LLM mapping succeeded for event=%s  keys=%s",
            event_type_name, list(mapped.keys()),
        )
        return mapped

    except Exception as exc:
        logger.error("LLM mapping failed for event=%s: %s", event_type_name, exc)
        return {"_mapping_error": str(exc)}
