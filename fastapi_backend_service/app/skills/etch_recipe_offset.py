"""MCP Skill: mcp_check_recipe_offset — MES/RMS 配方人為修改紀錄查詢。

查詢 MES（Manufacturing Execution System）或 RMS（Recipe Management System）
中指定配方的近期修改歷程，判斷是否存在未經 review 的人為操作。

PRD reference
-------------
- Tool Name : ``mcp_check_recipe_offset``
- Input     : ``{"recipe_id": str, "equipment_id": str}``
"""

from typing import Any

from app.skills.base import BaseMCPSkill


class EtchRecipeOffsetSkill(BaseMCPSkill):
    """查詢 MES/RMS 確認配方（Recipe）近期是否有人為修改紀錄。

    人為修改配方參數（如 RF Power、氣體流量比）是 SPC OOC 的常見根因之一。
    若發現未授權的修改，必須立即通報配方管理員並恢復至 golden 版本。
    """

    @property
    def name(self) -> str:
        return "mcp_check_recipe_offset"

    @property
    def description(self) -> str:
        return (
            "查詢 MES/RMS 系統，確認指定蝕刻配方在近期是否有人工修改紀錄。"
            "當懷疑 CD 偏移由製程工程師誤操作配方參數（RF 功率、氣體流量、壓力等）所引起時，"
            "請呼叫此工具。若 has_human_modification 為 True，表示有未經正式 ECO 流程的"
            "人為修改，應歸咎人為失誤，必須立即通報配方管理員調查並恢復 golden 版本。"
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "recipe_id": {
                    "type": "string",
                    "description": (
                        "配方識別碼，例如 'ETCH_CD_MAIN_V3'、'W5N_TRENCH_R2'。"
                        "對應事件物件中的 recipe_name 欄位。"
                    ),
                },
                "equipment_id": {
                    "type": "string",
                    "description": (
                        "蝕刻機台代碼，例如 'EAP01'、'EAP02'。"
                        "對應事件物件中的 eqp_id 欄位。"
                    ),
                },
            },
            "required": ["recipe_id", "equipment_id"],
        }

    async def execute(
        self,
        recipe_id: str,
        equipment_id: str,
        **kwargs: Any,
    ) -> dict:
        """查詢配方修改歷程，判斷是否存在人為操作。

        模擬場景：配方無人為修改（排除此根因，引導往 APC/EC 路徑）。

        Returns:
            dict containing recipe modification history and audit summary.
        """
        return {
            "recipe_id": recipe_id,
            "equipment_id": equipment_id,
            "has_human_modification": False,
            "modification_count_7d": 0,
            "last_verified_golden_version": "2026-02-15T10:00:00Z",
            "current_version_hash": "a3f9bc12",
            "golden_version_hash": "a3f9bc12",
            "version_match": True,
            "audit_log": [],
            "checked_parameters": [
                "RF_Power_W",
                "CF4_Flow_Rate_sccm",
                "O2_Flow_Rate_sccm",
                "Chamber_Pressure_mTorr",
                "Etch_Time_sec",
                "Bias_Voltage_V",
            ],
            "conclusion": (
                f"配方 {recipe_id} 在過去 7 天內無任何人為修改紀錄。"
                "當前版本 hash 與 golden 基準完全一致（a3f9bc12）。"
                "CD 偏移非配方人為失誤所致，建議繼續檢查 EC 偏移或 APC 飽和。"
            ),
        }
