"""MCP Skill: mcp_check_apc_params — APC 補償參數飽和度檢查。

查詢指定蝕刻機台/反應室的 APC（Advanced Process Control）前饋與反饋
補償參數，判斷是否已達飽和上限。

PRD reference
-------------
- Tool Name : ``mcp_check_apc_params``
- Input     : ``{"target_equipment": str, "target_chamber": str}``
"""

from typing import Any

from app.skills.base import BaseMCPSkill


class EtchApcCheckSkill(BaseMCPSkill):
    """檢查蝕刻製程 APC 模型的前饋/反饋補償參數是否已達飽和上限。

    飽和代表 APC 模型已無法透過補償修正製程偏移，通常需要安排
    Chamber Wet Clean 清洗以恢復蝕刻速率基準線。
    """

    @property
    def name(self) -> str:
        return "mcp_check_apc_params"

    @property
    def description(self) -> str:
        return (
            "檢查指定蝕刻機台與反應室的 APC（先進製程控制）前饋/反饋補償參數是否達到飽和上限。"
            "當懷疑 CD（Critical Dimension）偏移由 APC 補償失效所引起時請呼叫此工具。"
            "若 saturation_flag 為 True，表示 APC 模型補償量已接近或超過閾值，"
            "無法繼續修正製程偏差，建議安排 Chamber Wet Clean 以恢復製程基準線。"
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "target_equipment": {
                    "type": "string",
                    "description": (
                        "蝕刻機台代碼，例如 'EAP01'、'EAP02'。"
                        "對應事件物件中的 eqp_id 欄位。"
                    ),
                },
                "target_chamber": {
                    "type": "string",
                    "description": (
                        "反應室代碼，例如 'C1'、'C2'、'PM1'。"
                        "對應事件物件中的 chamber_id 欄位。"
                    ),
                },
            },
            "required": ["target_equipment", "target_chamber"],
        }

    async def execute(
        self,
        target_equipment: str,
        target_chamber: str,
        **kwargs: Any,
    ) -> dict:
        """查詢 APC 模型參數並判斷飽和狀態。

        模擬場景：APC 已達飽和（典型的 Wet Clean 觸發情境）。

        Returns:
            dict containing APC parameter snapshot and saturation analysis.
        """
        return {
            "equipment": target_equipment,
            "chamber": target_chamber,
            "apc_model_status": "SATURATED",
            "feed_forward_bias_nm": 4.8,
            "feed_back_correction_pct": -6.2,
            "saturation_flag": True,
            "saturation_threshold_nm": 5.0,
            "consecutive_max_corrections": 7,
            "trend": "CD 持續偏高（UCL 方向），前饋補償量連續 7 個批號遞增",
            "recommendation": (
                "APC 前饋補償值（4.8 nm）已接近飽和閾值（5.0 nm）。"
                "反饋修正量（-6.2%）持續擴大，顯示機台蝕刻速率基準線已發生漂移。"
                "建議安排 Chamber Wet Clean 清除腔體內累積的反應副產物，"
                "完成後重新執行 Recipe 標定，APC 模型即可恢復正常補償範圍。"
            ),
        }
