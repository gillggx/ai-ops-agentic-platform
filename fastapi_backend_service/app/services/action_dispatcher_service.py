"""Action Dispatcher Service — human-in-the-loop action execution.

Critical actions (hold_equipment, escalate) always require frontend confirmation.
Non-critical actions (monitor, notify_engineer) may auto-execute when auto_execute=True.
"""

import logging
from typing import Any, Dict

from app.schemas.automation import DispatchActionRequest, DispatchActionResponse

logger = logging.getLogger(__name__)

# Actions that always require human confirmation regardless of auto_execute flag
_ALWAYS_CONFIRM = frozenset({"hold_equipment", "escalate", "create_ocap"})

# Severity levels that force confirmation
_CRITICAL_SEVERITIES = frozenset({"critical"})


class ActionDispatcherService:
    """Dispatch automation actions with human-in-the-loop safety gates."""

    async def dispatch(self, req: DispatchActionRequest) -> DispatchActionResponse:
        """Evaluate and (conditionally) execute an action.

        Returns requires_confirm=True when frontend must show a confirmation dialog
        before the action takes real effect. The caller (Agent MCP / cron runner) is
        responsible for re-calling with confirmed=True after human approval.
        """
        requires_confirm = self._needs_confirmation(req)

        if requires_confirm:
            logger.info(
                "Action PENDING confirmation: type=%s target=%s severity=%s",
                req.action_type, req.target_id, req.severity,
            )
            return DispatchActionResponse(
                dispatched=False,
                action_type=req.action_type,
                target_id=req.target_id,
                message=f"⚠️ 動作「{req.action_type}」需要人工確認後才能執行。目標：{req.target_id}",
                requires_confirm=True,
            )

        # Auto-execute non-critical actions
        result_message = await self._execute(req)
        logger.info(
            "Action DISPATCHED: type=%s target=%s severity=%s",
            req.action_type, req.target_id, req.severity,
        )
        return DispatchActionResponse(
            dispatched=True,
            action_type=req.action_type,
            target_id=req.target_id,
            message=result_message,
            requires_confirm=False,
        )

    def _needs_confirmation(self, req: DispatchActionRequest) -> bool:
        if req.action_type in _ALWAYS_CONFIRM:
            return True
        if req.severity in _CRITICAL_SEVERITIES:
            return True
        if not req.auto_execute:
            return True
        return False

    async def _execute(self, req: DispatchActionRequest) -> str:
        """Perform the actual action. Extend this method to integrate with real systems."""
        # Dispatch table — add real integrations (MES, JIRA, Slack, etc.) here
        handlers = {
            "notify_engineer": self._notify_engineer,
            "monitor": self._start_monitor,
            "hold_equipment": self._hold_equipment,
            "escalate": self._escalate,
            "create_ocap": self._create_ocap,
        }
        handler = handlers.get(req.action_type, self._unknown_action)
        return await handler(req)

    async def _notify_engineer(self, req: DispatchActionRequest) -> str:
        # TODO: integrate with real notification system (email, Slack, etc.)
        logger.info("[notify_engineer] target=%s message=%s evidence=%s",
                    req.target_id, req.message, req.evidence)
        return f"已通知工程師負責設備 {req.target_id}：{req.message}"

    async def _start_monitor(self, req: DispatchActionRequest) -> str:
        logger.info("[monitor] target=%s", req.target_id)
        return f"已設定監控任務，目標：{req.target_id}"

    async def _hold_equipment(self, req: DispatchActionRequest) -> str:
        # Should only reach here after human confirmation
        logger.warning("[hold_equipment] EXECUTED target=%s severity=%s", req.target_id, req.severity)
        return f"設備 {req.target_id} 已被 HOLD，嚴重性：{req.severity}"

    async def _escalate(self, req: DispatchActionRequest) -> str:
        logger.warning("[escalate] EXECUTED target=%s", req.target_id)
        return f"已升級警告至管理層，目標：{req.target_id}"

    async def _create_ocap(self, req: DispatchActionRequest) -> str:
        logger.warning("[create_ocap] EXECUTED target=%s", req.target_id)
        return f"已建立 OCAP 工單，目標：{req.target_id}"

    async def _unknown_action(self, req: DispatchActionRequest) -> str:
        logger.error("[unknown_action] type=%s", req.action_type)
        return f"未知動作類型：{req.action_type}"
