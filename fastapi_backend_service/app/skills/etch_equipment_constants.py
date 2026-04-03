"""MCP Skill: mcp_check_equipment_constants — EC 黃金基準值比對。

連線蝕刻機台，讀取 Equipment Constants（EC）的當前值並與黃金基準值
（Golden Baseline）進行逐參數比對，偵測硬體老化或氣體流量飄移。

PRD reference
-------------
- Tool Name : ``mcp_check_equipment_constants``
- Input     : ``{"eqp_name": str, "chamber_name": str}``
"""

from typing import Any

from app.skills.base import BaseMCPSkill


class EtchEquipmentConstantsSkill(BaseMCPSkill):
    """比對蝕刻機台的 EC 黃金基準值，偵測硬體老化或製程氣體飄移。

    Equipment Constants 包含硬體校正參數（氣體流量修正係數、壓力感測器校準值等）。
    這些值會因元件老化、清洗後重新裝機或零件更換而產生偏移，進而影響 CD 控制能力。
    """

    @property
    def name(self) -> str:
        return "mcp_check_equipment_constants"

    @property
    def description(self) -> str:
        return (
            "連線蝕刻機台，讀取 Equipment Constants（EC）並與 golden 基準值逐一比對，"
            "偵測硬體老化、氣體流量感測器飄移或機台元件耗損等跡象。"
            "若 hardware_aging_risk 為 HIGH 或 out_of_spec_count > 0，"
            "表示機台硬體狀態異常，必須立即通報設備工程師（EE）"
            "進行機台保養、感測器校準或消耗品更換。"
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "eqp_name": {
                    "type": "string",
                    "description": (
                        "蝕刻機台名稱，例如 'EAP01'、'EAP02'。"
                        "對應事件物件中的 eqp_id 欄位。"
                    ),
                },
                "chamber_name": {
                    "type": "string",
                    "description": (
                        "反應室名稱，例如 'C1'、'C2'、'PM1'。"
                        "對應事件物件中的 chamber_id 欄位。"
                    ),
                },
            },
            "required": ["eqp_name", "chamber_name"],
        }

    async def execute(
        self,
        eqp_name: str,
        chamber_name: str,
        **kwargs: Any,
    ) -> dict:
        """比對 EC 與黃金基準值，評估硬體老化風險。

        模擬場景：EC 偏差在規格內，硬體風險低（引導往 APC 飽和根因）。

        Returns:
            dict containing EC comparison table and hardware aging assessment.
        """
        return {
            "eqp_name": eqp_name,
            "chamber_name": chamber_name,
            "ec_comparison": [
                {
                    "parameter": "CF4_Flow_Rate_sccm",
                    "description": "四氟化碳主蝕刻氣體質量流量控制器讀值",
                    "golden_value": 100.0,
                    "current_value": 101.2,
                    "deviation_pct": 1.2,
                    "spec_limit_pct": 5.0,
                    "within_spec": True,
                },
                {
                    "parameter": "Chamber_Pressure_mTorr",
                    "description": "製程腔體工作壓力（電容壓力計讀值）",
                    "golden_value": 30.0,
                    "current_value": 30.8,
                    "deviation_pct": 2.7,
                    "spec_limit_pct": 5.0,
                    "within_spec": True,
                },
                {
                    "parameter": "RF_Power_W",
                    "description": "射頻電漿功率（實際輸出值）",
                    "golden_value": 1200.0,
                    "current_value": 1198.5,
                    "deviation_pct": -0.1,
                    "spec_limit_pct": 3.0,
                    "within_spec": True,
                },
                {
                    "parameter": "Bias_Voltage_V",
                    "description": "偏壓電極電壓（離子轟擊能量控制）",
                    "golden_value": -350.0,
                    "current_value": -352.1,
                    "deviation_pct": 0.6,
                    "spec_limit_pct": 3.0,
                    "within_spec": True,
                },
                {
                    "parameter": "He_BackSide_Pressure_Torr",
                    "description": "晶圓背面氦氣冷卻壓力",
                    "golden_value": 12.0,
                    "current_value": 12.3,
                    "deviation_pct": 2.5,
                    "spec_limit_pct": 10.0,
                    "within_spec": True,
                },
            ],
            "max_deviation_pct": 2.7,
            "out_of_spec_count": 0,
            "hardware_aging_risk": "LOW",
            "last_pm_date": "2026-01-20",
            "days_since_last_pm": 39,
            "recommended_pm_interval_days": 60,
            "conclusion": (
                f"機台 {eqp_name} 反應室 {chamber_name} 的所有 Equipment Constants "
                f"偏差均在規格內（最大偏差 2.7%，規格上限 5%）。"
                "無明顯硬體老化、氣體流量感測器飄移或機台元件耗損跡象。"
                f"上次 PM 距今 39 天（建議間隔 60 天），尚在維護週期內。"
                "CD 偏移非 EC 異常所致，建議檢查 APC 補償狀態。"
            ),
        }
