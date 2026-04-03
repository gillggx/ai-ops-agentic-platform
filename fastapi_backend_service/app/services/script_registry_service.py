"""Script Registry Service — versioned diagnose() code lifecycle management.

Status flow: draft → approved → active → deprecated
Human review is required before any script goes active.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.repositories.script_version_repository import ScriptVersionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.automation import (
    ScriptTestRunRequest,
    ScriptTestRunResponse,
    ScriptVersionCreate,
    ScriptVersionResponse,
)
from app.services.sandbox_service import execute_diagnose_fn, _static_check

logger = logging.getLogger(__name__)


class ScriptRegistryService:
    def __init__(
        self,
        script_repo: ScriptVersionRepository,
        skill_repo: SkillDefinitionRepository,
    ) -> None:
        self._scripts = script_repo
        self._skills = skill_repo

    # ── List ────────────────────────────────────────────────────────────────

    async def list_versions(self, skill_id: int) -> List[ScriptVersionResponse]:
        await self._require_skill(skill_id)
        rows = await self._scripts.get_by_skill(skill_id)
        return [ScriptVersionResponse.model_validate(r) for r in rows]

    async def list_pending(self) -> List[ScriptVersionResponse]:
        """All draft scripts waiting for human approval."""
        rows = await self._scripts.get_pending_approval()
        return [ScriptVersionResponse.model_validate(r) for r in rows]

    # ── Read ─────────────────────────────────────────────────────────────────

    async def get_version(self, version_id: int) -> ScriptVersionResponse:
        row = await self._scripts.get_by_id(version_id)
        if not row:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"ScriptVersion id={version_id} 不存在")
        return ScriptVersionResponse.model_validate(row)

    # ── Create ───────────────────────────────────────────────────────────────

    async def register(self, skill_id: int, payload: ScriptVersionCreate) -> ScriptVersionResponse:
        """Register a new draft version. Called by Agent after generating diagnose() code."""
        await self._require_skill(skill_id)
        # Static security check before persisting
        try:
            _static_check(payload.code)
        except ValueError as exc:
            raise AppException(status_code=422, error_code="FORBIDDEN_CODE", detail=str(exc))

        ver_num = await self._scripts.next_version(skill_id)
        row = await self._scripts.create(
            skill_id=skill_id,
            version=ver_num,
            status="draft",
            code=payload.code,
            change_note=payload.change_note,
        )
        logger.info("ScriptVersion created: skill_id=%d version=%d id=%d", skill_id, ver_num, row.id)
        return ScriptVersionResponse.model_validate(row)

    # ── Approve / Rollback ───────────────────────────────────────────────────

    async def approve(self, version_id: int, reviewed_by: str) -> ScriptVersionResponse:
        """Human approves a draft → promotes it to active, deprecates previous active."""
        row = await self._get_or_404(version_id)
        if row.status != "draft":
            raise AppException(
                status_code=422,
                error_code="INVALID_TRANSITION",
                detail=f"只有 draft 狀態的版本可以核准，目前狀態：{row.status}",
            )
        # Deprecate current active version first
        await self._scripts.deactivate_all(row.skill_id)
        updated = await self._scripts.update(
            row,
            status="active",
            reviewed_by=reviewed_by,
            approved_at=datetime.now(tz=timezone.utc),
        )
        logger.info("ScriptVersion approved: id=%d skill_id=%d by=%s", version_id, row.skill_id, reviewed_by)
        return ScriptVersionResponse.model_validate(updated)

    async def rollback(self, skill_id: int, target_version: int) -> ScriptVersionResponse:
        """Rollback to a specific approved/deprecated version → promotes it back to active."""
        await self._require_skill(skill_id)
        rows = await self._scripts.get_by_skill(skill_id)
        target = next((r for r in rows if r.version == target_version), None)
        if not target:
            raise AppException(
                status_code=404,
                error_code="NOT_FOUND",
                detail=f"Skill {skill_id} 沒有 version={target_version} 的版本",
            )
        if target.status not in ("approved", "deprecated", "active"):
            raise AppException(
                status_code=422,
                error_code="INVALID_ROLLBACK",
                detail=f"無法回滾到狀態為 {target.status!r} 的版本",
            )
        await self._scripts.deactivate_all(skill_id)
        updated = await self._scripts.update(target, status="active")
        logger.info("ScriptVersion rollback: skill_id=%d → version=%d", skill_id, target_version)
        return ScriptVersionResponse.model_validate(updated)

    # ── Test Run ─────────────────────────────────────────────────────────────

    async def test_run(self, skill_id: int, req: ScriptTestRunRequest) -> ScriptTestRunResponse:
        """Execute a script version in sandbox with a test EventContext — no DB write."""
        await self._require_skill(skill_id)

        # Resolve which version to test
        if req.version is not None:
            row = next(
                (r for r in await self._scripts.get_by_skill(skill_id) if r.version == req.version),
                None,
            )
            if not row:
                raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Version {req.version} 不存在")
        else:
            row = await self._scripts.get_latest_draft(skill_id) or await self._scripts.get_active(skill_id)
            if not row:
                raise AppException(status_code=422, error_code="NO_SCRIPT", detail="此 Skill 尚無可執行的腳本版本")

        t0 = time.monotonic()
        try:
            # Pass EventContext as mcp_outputs input — script decides what to do with it
            result: Dict[str, Any] = await execute_diagnose_fn(
                code=row.code,
                mcp_outputs={"event_context": req.event_context.model_dump()},
                timeout=10.0,
            )
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return ScriptTestRunResponse(
                status="success",
                diag_status=str(result.get("status", "")).upper() or None,
                diagnosis_message=result.get("diagnosis_message"),
                problem_object=result.get("problem_object"),
                duration_ms=elapsed_ms,
            )
        except TimeoutError as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return ScriptTestRunResponse(status="timeout", error=str(exc), duration_ms=elapsed_ms)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return ScriptTestRunResponse(status="error", error=str(exc), duration_ms=elapsed_ms)

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _require_skill(self, skill_id: int) -> None:
        skill = await self._skills.get_by_id(skill_id)
        if not skill:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Skill id={skill_id} 不存在")

    async def _get_or_404(self, version_id: int):
        row = await self._scripts.get_by_id(version_id)
        if not row:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"ScriptVersion id={version_id} 不存在")
        return row
