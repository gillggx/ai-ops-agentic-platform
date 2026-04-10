"""SkillAuthoringService — interactive multi-turn Skill creation.

Wraps the Phase 1-3 generation flow inside a stateful session that supports:
  - clarification (Agent asks user to confirm intent)
  - planning (generate steps_mapping)
  - try-run (test against mock payload)
  - feedback (user rates result)
  - revision (LLM regenerates based on feedback)
  - save (promote to skill_definitions)

State machine:
    drafting → clarifying → planned → tested → reviewed → saved
                                            ↓ (feedback=wrong/partial)
                                        revising → planned (loop)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill_authoring_session import SkillAuthoringSessionModel
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.diagnostic_rule import GenerateRuleStepsRequest, PatrolContext
from app.services.diagnostic_rule_service import DiagnosticRuleService

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _j(s: Optional[str], default: Any = None) -> Any:
    if not s:
        return default if default is not None else []
    try:
        return json.loads(s)
    except Exception:
        return default if default is not None else []


class SkillAuthoringService:
    def __init__(self, db: AsyncSession, llm=None) -> None:
        self._db = db
        self._llm = llm

    # ── Session CRUD ──────────────────────────────────────────────────────────

    async def create_session(
        self,
        user_id: int,
        target_type: str,
        initial_prompt: str,
        target_context: Optional[Dict[str, Any]] = None,
    ) -> SkillAuthoringSessionModel:
        """Create a new authoring session in 'drafting' state."""
        first_turn = {
            "role": "user",
            "type": "initial_prompt",
            "content": initial_prompt,
            "timestamp": _now_iso(),
        }
        session = SkillAuthoringSessionModel(
            user_id=user_id,
            target_type=target_type,
            state="drafting",
            initial_prompt=initial_prompt,
            target_context=json.dumps(target_context or {}, ensure_ascii=False),
            turns=json.dumps([first_turn], ensure_ascii=False),
        )
        self._db.add(session)
        await self._db.commit()
        await self._db.refresh(session)
        return session

    async def get_session(self, session_id: int) -> Optional[SkillAuthoringSessionModel]:
        result = await self._db.execute(
            select(SkillAuthoringSessionModel).where(SkillAuthoringSessionModel.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_sessions(self, user_id: int, limit: int = 50) -> List[SkillAuthoringSessionModel]:
        result = await self._db.execute(
            select(SkillAuthoringSessionModel)
            .where(SkillAuthoringSessionModel.user_id == user_id)
            .order_by(SkillAuthoringSessionModel.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _save_session(self, session: SkillAuthoringSessionModel) -> None:
        session.updated_at = datetime.now(tz=timezone.utc)
        await self._db.commit()

    async def _append_turn(self, session: SkillAuthoringSessionModel, turn: dict) -> None:
        turns = _j(session.turns, [])
        turn.setdefault("timestamp", _now_iso())
        turns.append(turn)
        session.turns = json.dumps(turns, ensure_ascii=False)

    # ── Phase 0: Clarify ──────────────────────────────────────────────────────

    async def clarify(self, session: SkillAuthoringSessionModel) -> AsyncGenerator[str, None]:
        """LLM produces an understanding + clarification questions."""
        if not self._llm:
            yield _sse({"type": "error", "message": "LLM not configured"})
            return

        # Build MCP catalog hint
        from app.services.diagnostic_rule_service import _build_mcp_catalog_from_db
        mcp_catalog = await _build_mcp_catalog_from_db(self._db)

        target_type_label = {
            "my_skill": "My Skill（Agent chat 中可呼叫的常用工具）",
            "auto_patrol": "Auto-Patrol（Event Poller 自動巡檢，達條件會發告警）",
            "diagnostic_rule": "Diagnostic Rule（Alarm 觸發後的深度診斷）",
        }.get(session.target_type, session.target_type)

        system = f"""\
你是 Skill 設計助手。使用者想建立一個 {target_type_label}，原始描述是：

「{session.initial_prompt}」

你的任務：**不要寫 code**。先用自然語言確認你理解到的內容，並指出任何模糊的地方。

可用的資料來源：
{mcp_catalog}

回傳純 JSON（不要 markdown fence、不要解釋）：
{{
  "understanding": "我理解你要做的事是：...",
  "checklist": [
    "可驗證的需求項目 1",
    "可驗證的需求項目 2"
  ],
  "ambiguities": [
    {{
      "point": "「相同 APC OOC」的意思",
      "options": ["同一個 APC 模型 (apcID 相同)", "相同的 APC 參數數值"]
    }}
  ],
  "questions": [
    "你說的「相同 APC OOC」是指 5 次 process 都使用同一個 APC 模型嗎？還是 APC parameter 數值相同？"
  ],
  "suggested_input_schema": [
    {{"key": "equipment_id", "type": "string", "required": true, "description": "..."}}
  ]
}}

⚠️ 限制：
- ambiguities 最多 3 項
- questions 最多 3 題
- 不要寫任何 python_code
- 如果需求很清楚沒有歧義，questions 可以為空陣列
"""
        yield _sse({"type": "phase", "phase": "clarify", "message": "理解需求中..."})

        try:
            resp = await self._llm.create(
                system=system,
                messages=[{"role": "user", "content": session.initial_prompt}],
                max_tokens=1500,
            )
            text = resp.text or ""
        except Exception as exc:
            logger.warning("clarify LLM failed: %s", exc)
            yield _sse({"type": "error", "message": f"LLM clarify failed: {exc}"})
            return

        # Robust JSON extraction
        from app.services.diagnostic_rule_service import _extract_json
        try:
            parsed = _extract_json(text)
        except Exception as exc:
            logger.warning("clarify JSON parse failed: %s, text=%s", exc, text[:300])
            yield _sse({"type": "error", "message": f"LLM 回應解析失敗: {exc}"})
            return

        understanding = parsed.get("understanding", "")
        checklist = parsed.get("checklist", [])
        ambiguities = parsed.get("ambiguities", [])
        questions = parsed.get("questions", [])
        suggested_input = parsed.get("suggested_input_schema", [])

        # Save to session
        session.current_understanding = understanding
        session.current_input_schema = json.dumps(suggested_input, ensure_ascii=False)
        session.state = "clarifying"

        agent_turn = {
            "role": "agent",
            "type": "clarification",
            "content": understanding,
            "checklist": checklist,
            "ambiguities": ambiguities,
            "questions": questions,
            "suggested_input_schema": suggested_input,
            "timestamp": _now_iso(),
        }
        await self._append_turn(session, agent_turn)
        await self._save_session(session)

        yield _sse({"type": "clarification", **agent_turn})
        yield _sse({"type": "state", "state": session.state})
        yield _sse({"type": "done"})

    # ── User responds to clarification ────────────────────────────────────────

    async def respond(
        self,
        session: SkillAuthoringSessionModel,
        user_response: str,
    ) -> None:
        """Append user's clarification reply to turns."""
        await self._append_turn(session, {
            "role": "user",
            "type": "clarification_response",
            "content": user_response,
            "timestamp": _now_iso(),
        })
        await self._save_session(session)

    # ── Phase 1-3: Generate steps ─────────────────────────────────────────────

    async def generate(self, session: SkillAuthoringSessionModel) -> AsyncGenerator[str, None]:
        """Run Phase 1/1.5/2/3 generation, taking into account the clarified intent."""
        import sys
        print(f"[AUTHORING] generate START session={session.id}", file=sys.stderr, flush=True)
        # Build enriched description from initial prompt + understanding + user responses
        turns = _j(session.turns, [])
        responses = [t["content"] for t in turns if t.get("role") == "user" and t.get("type") == "clarification_response"]

        description_parts = [session.initial_prompt]
        if session.current_understanding:
            description_parts.append(f"\n[已澄清的理解]\n{session.current_understanding}")
        if responses:
            description_parts.append("\n[使用者補充說明]")
            for r in responses:
                description_parts.append(f"- {r}")
        enriched_description = "\n".join(description_parts)

        # Build patrol_context if applicable
        target_ctx = _j(session.target_context, {})
        patrol_ctx = None
        if session.target_type == "auto_patrol":
            patrol_ctx = PatrolContext(
                trigger_mode=target_ctx.get("trigger_mode", "event"),
                data_context=target_ctx.get("data_context", "recent_ooc"),
                target_scope_type=target_ctx.get("target_scope_type", "event_driven"),
            )
        elif session.target_type == "diagnostic_rule":
            patrol_ctx = PatrolContext(
                trigger_mode="event",
                data_context="recent_ooc",
                target_scope_type="event_driven",
            )

        gen_svc = DiagnosticRuleService(
            repo=SkillDefinitionRepository(self._db),
            db=self._db,
            llm=self._llm,
        )

        # Forward Phase 1-3 SSE events from generate_steps_stream
        steps_mapping: List[dict] = []
        input_schema: List[dict] = []
        output_schema: List[dict] = []
        gen_failed = False

        async for sse_line in gen_svc.generate_steps_stream(
            GenerateRuleStepsRequest(
                auto_check_description=enriched_description,
                patrol_context=patrol_ctx,
            )
        ):
            yield sse_line

            # Try to capture the final result from done event
            if sse_line.startswith("data: "):
                try:
                    # _sse() format: "data: {json}\n\n"
                    json_str = sse_line[6:].rstrip("\n")
                    payload = json.loads(json_str)
                    t = payload.get("type", "")
                    import sys
                    print(f"[AUTHORING] gen event: type={t}", file=sys.stderr, flush=True)
                    if t == "step_plan":
                        if payload.get("steps"):
                            steps_mapping = payload["steps"]
                        if payload.get("input_schema"):
                            input_schema = payload["input_schema"]
                        if payload.get("output_schema"):
                            output_schema = payload["output_schema"]
                        logger.info("[AUTHORING] step_plan captured: steps=%d input=%d output=%d",
                                    len(steps_mapping), len(input_schema), len(output_schema))
                    elif t == "done":
                        result = payload.get("result", {})
                        if result.get("steps_mapping"):
                            steps_mapping = result["steps_mapping"]
                        if result.get("input_schema"):
                            input_schema = result["input_schema"]
                        if result.get("output_schema"):
                            output_schema = result["output_schema"]
                        logger.info("[AUTHORING] done captured: steps=%d input=%d output=%d",
                                    len(steps_mapping), len(input_schema), len(output_schema))
                    elif t == "error":
                        gen_failed = True
                        logger.warning("[AUTHORING] gen error: %s", payload.get("error"))
                except Exception as parse_exc:
                    logger.warning("[AUTHORING] generate parse failed: %s, line=%s", parse_exc, sse_line[:300])

        import sys
        print(f"[AUTHORING] generate loop done: gen_failed={gen_failed}, steps={len(steps_mapping)}", file=sys.stderr, flush=True)

        if gen_failed or not steps_mapping:
            session.state = "drafting"
            await self._append_turn(session, {
                "role": "agent",
                "type": "generation_failed",
                "content": "生成失敗，請補充更多細節後再試一次",
                "timestamp": _now_iso(),
            })
            await self._save_session(session)
            return

        # Save generated artifacts
        import sys
        print(f"[AUTHORING] saving session={session.id} state→planned steps={len(steps_mapping)}", file=sys.stderr, flush=True)
        session.current_steps_mapping = json.dumps(steps_mapping, ensure_ascii=False)
        session.current_input_schema = json.dumps(input_schema, ensure_ascii=False)
        session.current_output_schema = json.dumps(output_schema, ensure_ascii=False)
        session.state = "planned"

        await self._append_turn(session, {
            "role": "agent",
            "type": "code_generated",
            "content": f"已生成 {len(steps_mapping)} 個步驟",
            "steps_count": len(steps_mapping),
            "input_schema_count": len(input_schema),
            "output_schema_count": len(output_schema),
            "timestamp": _now_iso(),
        })
        try:
            await self._save_session(session)
            print(f"[AUTHORING] save committed for session={session.id}", file=sys.stderr, flush=True)
        except Exception as save_exc:
            print(f"[AUTHORING] save FAILED: {save_exc}", file=sys.stderr, flush=True)

        yield _sse({"type": "state", "state": session.state})

    # ── Try-Run ───────────────────────────────────────────────────────────────

    async def try_run(
        self,
        session: SkillAuthoringSessionModel,
        mock_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run the current steps_mapping against a mock payload."""
        from app.config import get_settings
        from app.services.skill_executor_service import SkillExecutorService, build_mcp_executor

        settings = get_settings()
        executor = SkillExecutorService(
            skill_repo=SkillDefinitionRepository(self._db),
            mcp_executor=build_mcp_executor(self._db, sim_url=settings.ONTOLOGY_SIM_URL),
        )

        steps = _j(session.current_steps_mapping, [])
        output_schema = _j(session.current_output_schema, [])

        if not steps:
            return {"success": False, "error": "尚未生成 steps，無法試跑"}

        payload = mock_payload or {
            "equipment_id": "EQP-01",
            "lot_id": "LOT-0001",
            "step": "STEP_020",
            "event_time": "",
        }

        result = await executor.try_run_draft(
            steps=steps,
            mock_payload=payload,
            output_schema=output_schema,
        )

        # Persist result
        result_dict = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        session.last_test_result = json.dumps(result_dict, ensure_ascii=False, default=str)
        session.state = "tested"

        await self._append_turn(session, {
            "role": "agent",
            "type": "test_result",
            "content": "試跑完成",
            "success": result_dict.get("success"),
            "summary": (result_dict.get("findings") or {}).get("summary", "") if result_dict.get("findings") else "",
            "condition_met": (result_dict.get("findings") or {}).get("condition_met") if result_dict.get("findings") else None,
            "elapsed_ms": result_dict.get("total_elapsed_ms"),
            "timestamp": _now_iso(),
        })
        await self._save_session(session)

        return result_dict

    # ── Feedback & Revise ─────────────────────────────────────────────────────

    async def feedback(
        self,
        session: SkillAuthoringSessionModel,
        rating: str,           # "correct" | "wrong" | "partial"
        comment: str = "",
    ) -> None:
        """Record user feedback on the test result."""
        await self._append_turn(session, {
            "role": "user",
            "type": "feedback",
            "rating": rating,
            "content": comment,
            "timestamp": _now_iso(),
        })
        if rating == "correct":
            session.state = "reviewed"
        else:
            # Will trigger revise
            session.state = "revising"
        await self._save_session(session)

    async def revise(self, session: SkillAuthoringSessionModel) -> AsyncGenerator[str, None]:
        """Ask LLM to fix the code based on the latest user feedback."""
        if not self._llm:
            yield _sse({"type": "error", "message": "LLM not configured"})
            return

        turns = _j(session.turns, [])
        # Find the latest user feedback
        last_feedback = None
        for t in reversed(turns):
            if t.get("role") == "user" and t.get("type") == "feedback":
                last_feedback = t
                break

        if not last_feedback:
            yield _sse({"type": "error", "message": "找不到使用者 feedback"})
            return

        rating = last_feedback.get("rating", "wrong")
        feedback_text = last_feedback.get("content", "")
        steps = _j(session.current_steps_mapping, [])
        test_result = _j(session.last_test_result, {})

        system = f"""\
這是一個 Skill 修正任務。使用者測試了你之前生成的 code 後給了 feedback。

原始需求：{session.initial_prompt}

你之前理解的需求：
{session.current_understanding or '(無)'}

你之前生成的 code：
{json.dumps(steps, ensure_ascii=False, indent=2)[:3000]}

試跑結果：
condition_met: {test_result.get('findings', {}).get('condition_met') if isinstance(test_result, dict) else 'unknown'}
summary: {(test_result.get('findings', {}) if isinstance(test_result, dict) else {}).get('summary', '')}

使用者評分：{rating}
使用者 feedback：「{feedback_text}」

請：
1. 分析 feedback 指出的問題（是邏輯錯誤、需求理解錯誤、還是輸出格式錯誤）
2. 提出修正方案
3. 重新生成完整的 steps_mapping

回傳純 JSON：
{{
  "diagnosis": "問題分析",
  "fix_summary": "我做了哪些修改",
  "revised_steps_mapping": [
    {{"step_id": "step1", "nl_segment": "...", "python_code": "..."}},
    ...
  ]
}}

⚠️ 限制：
- 必須回完整的 steps_mapping（不是 diff）
- python_code 必須能直接執行（不要 markdown fence）
- 保持原本的 input_schema / output_schema 設計（除非 feedback 明確要求改）
"""
        yield _sse({"type": "phase", "phase": "revise", "message": "根據 feedback 修正中..."})

        try:
            resp = await self._llm.create(
                system=system,
                messages=[{"role": "user", "content": feedback_text or "請修正"}],
                max_tokens=4096,
            )
            text = resp.text or ""
        except Exception as exc:
            yield _sse({"type": "error", "message": f"LLM revise failed: {exc}"})
            return

        from app.services.diagnostic_rule_service import _extract_json
        try:
            parsed = _extract_json(text)
        except Exception as exc:
            yield _sse({"type": "error", "message": f"修正回應解析失敗: {exc}"})
            return

        diagnosis = parsed.get("diagnosis", "")
        fix_summary = parsed.get("fix_summary", "")
        revised = parsed.get("revised_steps_mapping", [])

        if not revised:
            yield _sse({"type": "error", "message": "LLM 未回傳新的 steps"})
            return

        session.current_steps_mapping = json.dumps(revised, ensure_ascii=False)
        session.state = "planned"

        await self._append_turn(session, {
            "role": "agent",
            "type": "code_revised",
            "content": fix_summary,
            "diagnosis": diagnosis,
            "steps_count": len(revised),
            "timestamp": _now_iso(),
        })
        await self._save_session(session)

        yield _sse({
            "type": "code_revised",
            "diagnosis": diagnosis,
            "fix_summary": fix_summary,
            "steps_count": len(revised),
        })
        yield _sse({"type": "state", "state": session.state})
        yield _sse({"type": "done"})

    # ── Save ──────────────────────────────────────────────────────────────────

    async def save(
        self,
        session: SkillAuthoringSessionModel,
        name: str,
        description: str = "",
    ) -> int:
        """Promote the session to skill_definitions row. Returns new skill_id."""
        repo = SkillDefinitionRepository(self._db)
        steps = _j(session.current_steps_mapping, [])
        input_schema = _j(session.current_input_schema, [])
        output_schema = _j(session.current_output_schema, [])

        if not steps:
            raise ValueError("Session has no steps to save")

        # Determine source/binding_type/visibility based on target_type
        if session.target_type == "my_skill":
            source = "skill"
            binding_type = "none"
            visibility = "public"
            trigger_mode = "manual"
        elif session.target_type == "auto_patrol":
            source = "auto_patrol"
            binding_type = "event"
            visibility = "private"
            trigger_mode = "event"
        elif session.target_type == "diagnostic_rule":
            source = "rule"
            binding_type = "alarm"
            visibility = "public"
            trigger_mode = "event"
        else:
            source = "skill"
            binding_type = "none"
            visibility = "public"
            trigger_mode = "manual"

        obj = await repo.create({
            "name": name,
            "description": description or session.initial_prompt[:200],
            "auto_check_description": session.initial_prompt,
            "steps_mapping": steps,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "source": source,
            "binding_type": binding_type,
            "visibility": visibility,
            "trigger_mode": trigger_mode,
            "created_by": session.user_id,
        })

        session.promoted_skill_id = obj.id
        session.state = "saved"
        await self._append_turn(session, {
            "role": "system",
            "type": "saved",
            "content": f"已儲存為 Skill #{obj.id}",
            "skill_id": obj.id,
            "timestamp": _now_iso(),
        })
        await self._save_session(session)

        return obj.id
