"""MCP Skill: mcp_event_triage — 半導體蝕刻製程 SPC OOC 事件分類閘道。

這是 Diagnostic Agent 迴圈中**強制第一呼叫**的技能。接收製程工程師
描述的原始症狀，轉換為標準化的 ``SPC_OOC_Etch_CD`` Event Object：

- 將症狀歸類為標準事件類型（event_type）。
- 嘗試從症狀文字中萃取關鍵製程屬性（機台、配方、SPC 規則等）。
- 回傳 ``recommended_skills``：後續 Agent 必須依序呼叫的診斷工具清單。

設計原則
--------
保持 Agent 核心迴圈領域無關性：分診工具承擔路由智能，Agent 核心迴圈
本身不含任何蝕刻製程硬編碼邏輯。

PRD reference
-------------
- Tool Name    : ``mcp_event_triage``
- Input        : ``{"user_symptom": "<string>"}``
- Core Event   : ``SPC_OOC_Etch_CD``
- SPC 屬性     : lot_id, eqp_id, chamber_id, recipe_name,
                 rule_violated, consecutive_ooc_count, control_limit_type
"""

import re
import uuid
from typing import Any

from app.skills.base import BaseMCPSkill

# ---------------------------------------------------------------------------
# 半導體蝕刻製程分類規則（優先權由上到下，第一個匹配即採用）
# ---------------------------------------------------------------------------

_TRIAGE_RULES: list[dict] = [
    # ── 蝕刻製程 SPC/AEI/CD 異常 ──────────────────────────────────────────
    {
        "keywords": [
            "spc", "ooc", "out of control", "cd異常", "cd 異常",
            "aei", "etch", "蝕刻", "apc", "recipe", "配方",
            "critical dimension", "製程異常", "機台異常",
            "3 sigma", "3sigma", "ucl", "lcl", "控制限",
            "連續", "同側", "批號", "lot", "chamber", "反應室",
            "ec offset", "equipment constant",
        ],
        "event_type": "SPC_OOC_Etch_CD",
        "urgency": "high",
        "recommended_skills": [
            "mcp_check_recipe_offset",
            "mcp_check_equipment_constants",
            "mcp_check_apc_params",
        ],
    },
    # ── 機台停機 / 服務中斷 ────────────────────────────────────────────────
    {
        "keywords": [
            "掛了", "down", "crash", "unavailable", "503", "500", "連不上",
            "service unavailable", "無法存取", "停機", "alarm", "緊急停止",
        ],
        "event_type": "Equipment_Down",
        "urgency": "critical",
        "recommended_skills": ["mcp_check_equipment_constants"],
    },
    # ── 部署 / 配方版本升級 ────────────────────────────────────────────────
    {
        "keywords": [
            "部署", "deploy", "上線", "release", "rollback", "版本", "upgrade",
            "更新", "golden recipe", "golden version",
        ],
        "event_type": "Recipe_Deployment_Issue",
        "urgency": "medium",
        "recommended_skills": ["mcp_check_recipe_offset", "mcp_check_apc_params"],
    },
]

_UNKNOWN_RULE: dict = {
    "event_type": "Unknown_Fab_Symptom",
    "urgency": "low",
    "recommended_skills": ["mcp_check_equipment_constants"],
}

# ---------------------------------------------------------------------------
# SPC OOC 屬性萃取器
# ---------------------------------------------------------------------------


def _extract_eqp_id(symptom: str) -> str:
    """嘗試從症狀文字萃取機台代碼（如 EAP01）。"""
    m = re.search(r'\b([A-Z]{2,4}\d{1,3}[A-Z]?)\b', symptom.upper())
    if m:
        return m.group(1)
    m2 = re.search(r'機台\s*[:\s]?\s*(\S+)', symptom)
    if m2:
        return m2.group(1).strip('，,。.')
    return "UNKNOWN"


def _extract_chamber_id(symptom: str) -> str:
    """嘗試萃取反應室代碼（如 C1、PM2）。"""
    m = re.search(
        r'\b(?:chamber|反應室|PM|腔體)\s*[:\s]?\s*([A-Za-z]?\d+)\b',
        symptom, re.IGNORECASE,
    )
    return m.group(1) if m else "UNKNOWN"


def _extract_lot_id(symptom: str) -> str:
    """嘗試萃取批號。"""
    m = re.search(r'(?:lot|批號)[:\s_-]*([A-Za-z0-9\-_]+)', symptom, re.IGNORECASE)
    return m.group(1).strip() if m else "UNKNOWN"


def _extract_recipe_name(symptom: str) -> str:
    """嘗試萃取配方名稱。"""
    m = re.search(r'(?:recipe|配方)[:\s_-]*([A-Za-z0-9\-_\.]+)', symptom, re.IGNORECASE)
    return m.group(1).strip() if m else "UNKNOWN"


def _extract_rule_violated(symptom: str) -> str:
    """嘗試萃取觸發的 SPC 規則。"""
    if re.search(r'3\s*sigma', symptom, re.IGNORECASE):
        return "3-sigma OOC"
    m = re.search(r'連續.*?(\d+).*?點', symptom)
    if m:
        return f"連續 {m.group(1)} 點同側 OOC"
    if "ucl" in symptom.lower():
        return "超出 UCL"
    if "lcl" in symptom.lower():
        return "低於 LCL"
    return "OOC"


def _extract_ooc_count(symptom: str) -> int:
    """嘗試萃取連續 OOC 次數。"""
    m = re.search(r'(?:連續|continuous).*?(\d+)', symptom, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 1


def _extract_control_limit_type(symptom: str) -> str:
    """判斷觸發的是 UCL 還是 LCL。"""
    if "ucl" in symptom.lower() or "上限" in symptom or "偏高" in symptom:
        return "UCL"
    if "lcl" in symptom.lower() or "下限" in symptom or "偏低" in symptom:
        return "LCL"
    return "UNKNOWN"


def _classify(symptom: str) -> dict:
    """回傳第一個匹配的規則，否則回傳未知規則。"""
    symptom_lower = symptom.lower()
    for rule in _TRIAGE_RULES:
        if any(kw in symptom_lower for kw in rule["keywords"]):
            return rule
    return _UNKNOWN_RULE


# ---------------------------------------------------------------------------
# EventTriageSkill
# ---------------------------------------------------------------------------


class EventTriageSkill(BaseMCPSkill):
    """將製程工程師的原始症狀描述轉換為標準化 SPC OOC Event Object。

    **本技能必須是 Agent 呼叫的第一個工具**，回傳的 recommended_skills
    欄位驅動後續所有診斷工具的呼叫順序。
    """

    @property
    def name(self) -> str:
        return "mcp_event_triage"

    @property
    def description(self) -> str:
        return (
            "【必須優先且唯一呼叫】收到任何製程異常症狀描述時，"
            "第一步且唯一的第一步必須呼叫此工具。"
            "它會分析症狀，歸類為標準蝕刻製程事件類型（如 SPC_OOC_Etch_CD），"
            "並萃取關鍵屬性（機台、反應室、配方、SPC 規則）。"
            "回傳的 recommended_skills 欄位列出接下來應依序呼叫的診斷工具。"
            "在取得 Event Object 之前，絕對禁止呼叫任何其他工具。"
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "user_symptom": {
                    "type": "string",
                    "description": (
                        "製程工程師描述的原始問題症狀，"
                        "例如「機台 EAP01 C1 發生 AEI CD 偏高，連續 3 批 OOC」"
                        "或「Lot A1234 使用配方 ETCH_CD_V3，SPC 觸發 3-sigma 規則」。"
                    ),
                },
            },
            "required": ["user_symptom"],
        }

    async def execute(self, user_symptom: str, **kwargs: Any) -> dict:
        """分類症狀並回傳結構化 SPC OOC Event Object。

        Returns:
            dict 包含以下欄位：

            - ``event_id``           : 唯一事件識別碼（``EVT-XXXXXXXX``）。
            - ``event_type``         : 標準事件類型（如 ``SPC_OOC_Etch_CD``）。
            - ``attributes``         : 包含症狀文字、urgency 及萃取的 SPC 屬性。
            - ``recommended_skills`` : Agent 後續應依序呼叫的工具名稱清單。
        """
        matched = _classify(user_symptom)
        event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"

        # 基礎屬性
        attributes: dict[str, Any] = {
            "symptom": user_symptom,
            "urgency": matched["urgency"],
        }

        # 蝕刻製程 SPC OOC 專屬屬性萃取
        if matched["event_type"] == "SPC_OOC_Etch_CD":
            attributes.update({
                "lot_id": _extract_lot_id(user_symptom),
                "eqp_id": _extract_eqp_id(user_symptom),
                "chamber_id": _extract_chamber_id(user_symptom),
                "recipe_name": _extract_recipe_name(user_symptom),
                "rule_violated": _extract_rule_violated(user_symptom),
                "consecutive_ooc_count": _extract_ooc_count(user_symptom),
                "control_limit_type": _extract_control_limit_type(user_symptom),
            })

        return {
            "event_id": event_id,
            "event_type": matched["event_type"],
            "attributes": attributes,
            "recommended_skills": matched["recommended_skills"],
        }
