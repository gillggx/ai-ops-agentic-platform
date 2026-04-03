"""Passive skill: ask the user for recent system changes.

This is a *Type-A (passive)* skill — it does NOT call an external API.
Instead it returns a structured question that the agent should surface to
the human operator.  The agent loop treats the result as informational and
can relay the question back to the end-user in the diagnostic report.

In the MVP the returned dict contains:
- ``question_for_user`` — the exact question to relay
- ``context``           — why the agent needs this information
"""

from typing import Any

from app.skills.base import BaseMCPSkill


class AskUserRecentChangesSkill(BaseMCPSkill):
    """Generate a structured question asking the user about recent changes."""

    @property
    def name(self) -> str:
        return "ask_user_recent_changes"

    @property
    def description(self) -> str:
        return (
            "當診斷資訊不足，需要詢問使用者最近是否有對系統進行變更時，請呼叫此工具。"
            "適用情境：部署新版本、設定變更、資料庫 migration、流量突增等。"
            "此工具會產生一個結構化問題，由診斷系統轉交給人工操作員回答。"
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "問題的主題範疇，例如 'deployment'、'config'、"
                        "'database'、'traffic'。"
                    ),
                },
                "time_window": {
                    "type": "string",
                    "description": "詢問的時間範圍，例如 '過去 24 小時'、'過去 1 週'。",
                    "default": "過去 24 小時",
                },
            },
            "required": ["topic"],
        }

    async def execute(self, topic: str, time_window: str = "過去 24 小時", **kwargs: Any) -> dict:
        """Return a structured question directed at the human operator."""
        questions_map: dict[str, str] = {
            "deployment": f"在{time_window}內，是否有進行任何服務部署或版本升級？請說明部署的服務名稱與版本。",
            "config": f"在{time_window}內，是否有修改任何服務設定檔（如環境變數、Nginx/DB 設定）？",
            "database": f"在{time_window}內，是否有執行資料庫 migration、索引變更或大量資料寫入？",
            "traffic": f"在{time_window}內，系統的請求量是否有異常暴增或暴降？",
        }
        question = questions_map.get(
            topic,
            f"在{time_window}內，系統在「{topic}」方面是否有任何異常或變更？請詳述。",
        )
        return {
            "question_for_user": question,
            "topic": topic,
            "time_window": time_window,
            "context": (
                "診斷引擎需要人工提供的補充資訊才能完成根因分析。"
                "請盡快回答上述問題以協助完成診斷。"
            ),
        }
