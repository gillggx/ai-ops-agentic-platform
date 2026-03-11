"""Agent Router — tools manifest and execution endpoints for AI agents.

v14 additions:
  POST /agent/approve/{token}          — HITL approval gate
  GET  /agent/sessions/{sid}/workspace — read canvas workspace state
  POST /agent/sessions/{sid}/workspace — write canvas overrides

v15.4 additions:
  POST /agent/jit-analyze              — run custom Python against full MCP dataset server-side

v15.5 additions:
  POST /agent/promote-jit              — wrap validated JIT code → MCP processing_script + optional Skill metadata
"""

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.agent_session import AgentSessionModel
from app.models.user import UserModel
from app.repositories.data_subject_repository import DataSubjectRepository
from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.repositories.system_parameter_repository import SystemParameterRepository
from app.services.agent_orchestrator import set_approval

router = APIRouter(prefix="/agent", tags=["agent"])


def _j(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _build_tool_markdown(skill, mcp_map: Dict[int, Any]) -> str:
    """Build XML-tagged Markdown tool description for a public skill.

    Strictly follows PRD v12 Section 3.2 format to prevent agent hallucination.
    """
    skill_id = skill.id
    skill_name = skill.name or ""
    skill_desc = skill.description or ""
    diagnostic_prompt = skill.diagnostic_prompt or ""
    problem_subject = skill.problem_subject or ""
    human_recommendation = skill.human_recommendation or ""

    # Collect required parameters from bound MCPs
    mcp_ids: List[int] = _j(skill.mcp_ids) or []
    required_params: List[Dict] = []
    for mid in mcp_ids:
        mcp = mcp_map.get(mid)
        if not mcp:
            continue
        input_def = _j(mcp.input_definition)
        if not input_def:
            continue
        for p in input_def.get("params", []):
            if p.get("required", True) and p.get("source") != "data_subject":
                required_params.append({
                    "name": p.get("name"),
                    "type": p.get("type", "string"),
                    "description": p.get("description", ""),
                    "required": True,
                })

    params_schema = json.dumps(
        {"type": "object", "properties": {
            p["name"]: {"type": p["type"], "description": p["description"]}
            for p in required_params
        }, "required": [p["name"] for p in required_params]},
        ensure_ascii=False, indent=2
    )

    return f"""---
name: {skill_name}
description: 本技能是一套完整的自動化診斷管線。{skill_desc}
---
## 1. 執行規劃與優先級 (Planning Guidance)
- **優先使用**：當意圖符合時，直接呼叫本技能。絕對不要要求使用者先提供 raw_data 或去呼叫底層 MCP，系統會自動撈取。

## 2. 依賴參數與介面 (Interface)
- API: `POST /api/v1/execute/skill/{skill_id}`
- **必須傳遞參數**:
```json
{params_schema}
```
- ⚠️ **邊界鐵律**: 呼叫 API 後，僅允許讀取 `llm_readable_data` 進行判斷。絕對禁止解析 `ui_render_payload`。

## 3. 判斷邏輯與防呆處置 (Reasoning Rules)
請嚴格遵循以下 `<rules>` 標籤內的指示撰寫最終報告：
<rules>
  <condition>{diagnostic_prompt}</condition>
  <target_extraction>{problem_subject}</target_extraction>
  <expert_action>
    ⚠️ 若狀態為 ABNORMAL，必須強制在報告結尾附加處置建議：
    Action: {human_recommendation}
  </expert_action>
</rules>"""


@router.get(
    "/tools_manifest",
    summary="取得 Agent 工具清單 (公開技能)",
    response_model=Dict[str, Any],
)
async def get_tools_manifest(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return all public skills as XML-tagged Markdown tool descriptions.

    Used by the AI agent to discover available diagnostic tools.
    Only 'public' skills appear here. Private skills belong to their owners only.
    """
    skill_repo = SkillDefinitionRepository(db)
    mcp_repo = MCPDefinitionRepository(db)

    all_skills = await skill_repo.get_all()
    public_skills = [s for s in all_skills if s.visibility == "public"]

    # Collect all referenced MCP ids to batch-load
    all_mcp_ids: List[int] = []
    for skill in public_skills:
        ids = _j(skill.mcp_ids) or []
        all_mcp_ids.extend(ids)
    all_mcp_ids = list(set(all_mcp_ids))

    all_mcps = await mcp_repo.get_all()
    mcp_map = {m.id: m for m in all_mcps}

    tools = []
    for skill in public_skills:
        md = _build_tool_markdown(skill, mcp_map)
        tools.append({
            "skill_id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "markdown": md,
        })

    # ── Meta-tool: patch_skill_markdown (PRD v12 §4.5.3) ──────────────────
    meta_tools = [
        {
            "tool_name": "patch_skill_markdown",
            "description": (
                "讀取或更新指定 Skill 的原生 OpenClaw Markdown。"
                "當使用者要求修改某個 Skill 的判斷條件、目標物件或處置建議時使用此工具。"
            ),
            "endpoints": {
                "read": "GET /api/v1/agentic/skills/{skill_id}/raw",
                "write": "PUT /api/v1/agentic/skills/{skill_id}/raw",
            },
            "write_body": {"raw_markdown": "<完整的 OpenClaw Markdown 字串>"},
            "workflow": (
                "1. GET /agentic/skills/{skill_id}/raw 取得原始 Markdown\n"
                "2. 在 <condition> 區塊修改判斷條件\n"
                "3. PUT /agentic/skills/{skill_id}/raw 覆蓋更新\n"
                "4. 從回傳的 deep_link 引導使用者進入 ⌨️ Raw 模式進行最終 Code Review"
            ),
            "constraints": (
                "⚠️ 只能修改 <condition>、<target_extraction>、<expert_action> 及 YAML header 的 name/description。"
                "禁止修改 API 端點或參數 Schema。"
            ),
        }
    ]

    # ── [P1 v15] Section 3: Agent Tools (per-user JIT tool chest) ─────────
    agent_tools_manifest = []
    try:
        from app.services.agent_tool_service import AgentToolService
        at_svc = AgentToolService(db)
        agent_tools_list = await at_svc.get_all(user_id=current_user.id)
        agent_tools_manifest = [
            {
                "tool_id": t.id,
                "name": t.name,
                "description": t.description,
                "usage_count": t.usage_count,
            }
            for t in agent_tools_list
        ]
    except Exception:
        pass  # agent_tools table may not exist yet (migration pending)

    return {
        "tools": tools,
        "total": len(tools),
        "meta_tools": meta_tools,
        "agent_tools": agent_tools_manifest,
        "agent_tools_total": len(agent_tools_manifest),
    }


# ── v14: HITL Approval Endpoint ───────────────────────────────────────────────

class ApprovalRequest(BaseModel):
    approved: bool


@router.post(
    "/approve/{token}",
    summary="v14 HITL — 批准或拒絕高風險工具操作",
    response_model=Dict[str, Any],
)
async def approve_tool(
    token: str,
    body: ApprovalRequest,
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Signal approval or rejection for a pending destructive tool call.

    The agent SSE stream emits 'approval_required' with an approval_token.
    The frontend calls this endpoint to unblock the suspended agent.
    """
    ok = set_approval(token, body.approved)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Approval token '{token}' not found or already resolved.")
    return {
        "token": token,
        "approved": body.approved,
        "message": "批准成功，Agent 將繼續執行。" if body.approved else "已拒絕，Agent 將取消操作。",
    }


# ── v14: Workspace State Endpoints ────────────────────────────────────────────

class WorkspaceUpdateRequest(BaseModel):
    canvas_overrides: Dict[str, Any]


@router.get(
    "/sessions/{session_id}/workspace",
    summary="v14 取得工作區狀態 (canvas overrides)",
    response_model=Dict[str, Any],
)
async def get_workspace(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    result = await db.execute(
        select(AgentSessionModel).where(
            AgentSessionModel.session_id == session_id,
            AgentSessionModel.user_id == current_user.id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Session 不存在")
    workspace = {}
    if row.workspace_state:
        try:
            workspace = json.loads(row.workspace_state)
        except Exception:
            pass
    return {"session_id": session_id, "canvas_overrides": workspace}


@router.post(
    "/sessions/{session_id}/workspace",
    summary="v14 更新工作區 Canvas Overrides",
    response_model=Dict[str, Any],
)
async def update_workspace(
    session_id: str,
    body: WorkspaceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update canvas overrides for a session. These will be injected as
    highest-priority context in the next agent call for this session."""
    result = await db.execute(
        select(AgentSessionModel).where(
            AgentSessionModel.session_id == session_id,
            AgentSessionModel.user_id == current_user.id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Session 不存在")
    row.workspace_state = json.dumps(body.canvas_overrides, ensure_ascii=False)
    await db.commit()
    return {
        "session_id": session_id,
        "canvas_overrides": body.canvas_overrides,
        "message": "Canvas overrides 已更新，下次 Agent 呼叫時生效。",
    }


# ── v15.4: JIT Analyze — server-side Python sandbox with full MCP dataset ─────

class JitAnalyzeRequest(BaseModel):
    mcp_id: int
    run_params: Dict[str, Any] = {}
    python_code: str
    title: str = "JIT 分析"


@router.post(
    "/jit-analyze",
    response_model=StandardResponse,
    summary="v15.4 JIT 分析 — 以自訂 Python 對 MCP 全量資料進行沙盒分析",
)
async def jit_analyze(
    body: JitAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> StandardResponse:
    """Fetch full MCP dataset server-side then run user-supplied Python in sandbox.

    The Python code must define ``process(raw_data: list) -> dict``.
    ``df`` (pandas DataFrame from the full dataset) is pre-injected in the sandbox.
    """
    from app.services.mcp_builder_service import MCPBuilderService
    from app.services.mcp_definition_service import MCPDefinitionService
    from app.services.sandbox_service import execute_script

    svc = MCPDefinitionService(
        repo=MCPDefinitionRepository(db),
        ds_repo=DataSubjectRepository(db),
        llm=MCPBuilderService(),
        sp_repo=SystemParameterRepository(db),
    )

    # 1. Fetch MCP data (full dataset via run_with_data)
    mcp_result = await svc.run_with_data(body.mcp_id, body.run_params)
    if not mcp_result.success:
        return StandardResponse.error(message=mcp_result.error or "MCP 資料取得失敗")

    od = mcp_result.output_data or {}
    # Prefer raw dataset (before processing_script transforms) for JIT analysis
    dataset = od.get("_raw_dataset") or od.get("dataset") or []
    row_count = len(dataset) if isinstance(dataset, list) else 0

    # 2. Run JIT Python in sandbox (df pre-injected from dataset)
    try:
        sandbox_result = await execute_script(body.python_code, dataset)
    except (ValueError, TimeoutError) as exc:
        return StandardResponse.error(message=f"沙盒執行失敗：{exc}")
    except Exception as exc:
        return StandardResponse.error(message=f"未預期錯誤：{exc}")

    # 3. Extract chart JSON if present
    chart_json: Optional[str] = None
    ui_render = sandbox_result.get("ui_render") or {}
    charts = ui_render.get("charts") or []
    if charts and charts[0]:
        chart_json = charts[0]
    elif ui_render.get("chart_data"):
        chart_json = ui_render["chart_data"]
    elif sandbox_result.get("chart_data"):
        chart_json = sandbox_result["chart_data"]

    # 4. Build LLM-readable summary (strip large / chart payloads)
    _SKIP = {"ui_render", "_raw_dataset", "dataset", "chart_data", "output_schema"}
    llm_parts: Dict[str, Any] = {}
    for k, v in sandbox_result.items():
        if k in _SKIP:
            continue
        if isinstance(v, str) and len(v) > 500:
            llm_parts[k] = v[:300] + "…[截斷]"
        elif isinstance(v, list) and len(v) > 5:
            llm_parts[k] = f"[list of {len(v)} items]"
        elif isinstance(v, dict) and len(json.dumps(v)) > 400:
            llm_parts[k] = f"{{dict, {len(v)} keys}}"
        else:
            llm_parts[k] = v

    return StandardResponse.success(
        data={
            "mcp_id": body.mcp_id,
            "row_count": row_count,
            "title": body.title,
            "jit_result": sandbox_result,
            "chart_json": chart_json,
            "has_chart": bool(chart_json),
            "llm_readable_data": json.dumps(llm_parts, ensure_ascii=False)[:2000],
        },
        message=body.title,
    )


# ── v15.5: Promote JIT — wrap validated code → MCP/Skill pre-fill ─────────────

_PROMOTE_MODEL = "claude-sonnet-4-6"

_WRAP_SCRIPT_PROMPT = """\
你是一位 Python 專家。使用者剛在沙盒中執行了一段 JIT 分析程式碼，並且確認結果正確。
現在要把這段程式碼「升格」成符合本系統標準的 MCP processing_script。

## 規則
1. **保留**原始分析邏輯（回歸、統計、視覺化等）完全不動。
2. 在腳本**結尾**補充標準輸出格式：
   ```python
   # --- 標準 MCP 輸出 ---
   llm_readable_data = <一行字串，概括分析結果，供 LLM 閱讀>
   ui_render_payload = {
       "chart_type": "table",   # 若有圖表改為 "chart"
       "rows": [result_dict],   # 必須是 list of dict
   }
   output = {
       "dataset": [result_dict],
       "llm_readable_data": llm_readable_data,
       "ui_render_payload": ui_render_payload,
   }
   ```
3. `df` 已預注入（pandas DataFrame，含全量資料）；`np`、`pd`、`go`、`px` 均可直接使用。
4. 若原始程式碼已有 chart_data / plotly 輸出，保留並放入 `ui_render_payload["chart_data"]`。
5. **只回傳 Python 程式碼**，不要任何 markdown fence 或說明文字。

## 原始程式碼
{python_code}
"""

_SKILL_META_PROMPT = """\
根據以下 MCP 分析結果，為一個 Skill（診斷技能）生成三個欄位的內容。
Skill 的用途：執行這個 MCP，然後根據輸出值判斷狀態 (NORMAL / ABNORMAL)。

## MCP 分析標題
{title}

## 範例輸出欄位（MCP 結果 key 名）
{output_keys}

請以 JSON 回答，格式如下（所有值用繁體中文）：
{{
  "diagnostic_prompt": "若 <指標> < <閾值> → status=ABNORMAL，diagnosis_message=<說明>；否則 NORMAL",
  "problem_subject": "<被診斷的目標物件，例如：lot_id、tool_id>",
  "human_recommendation": "<ABNORMAL 時的人工處置建議，一句話>"
}}

只回傳 JSON，不要其他文字。
"""


class PromoteJitRequest(BaseModel):
    mcp_id: int
    run_params: Dict[str, Any] = {}
    python_code: str
    title: str = "JIT 分析"
    target: str = "mcp"  # "mcp" | "skill"
    output_keys: List[str] = []  # hint: keys in jit_result for skill meta generation


@router.post(
    "/promote-jit",
    response_model=StandardResponse,
    summary="v15.5 固化 JIT — 把驗證過的 JIT 程式碼升格為 MCP（直接存 DB）",
)
async def promote_jit(
    body: PromoteJitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> StandardResponse:
    """Wrap validated JIT python_code into MCP processing_script format.
    Creates the MCP in DB directly (bypassing try-run). Returns new_mcp_id.
    For 'skill' target: also generates Skill diagnostic metadata for pre-fill.
    """
    import anthropic as _anthropic

    from app.config import get_settings

    settings = get_settings()
    client = _anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    # 1. Wrap python_code → MCP processing_script
    wrap_prompt = _WRAP_SCRIPT_PROMPT.format(python_code=body.python_code)
    try:
        wrap_resp = await client.messages.create(
            model=_PROMOTE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": wrap_prompt}],
        )
        processing_script: str = wrap_resp.content[0].text.strip()
        # Strip accidental markdown fences
        if processing_script.startswith("```"):
            lines = processing_script.splitlines()
            processing_script = "\n".join(
                ln for ln in lines if not ln.strip().startswith("```")
            ).strip()
    except Exception as exc:
        return StandardResponse.error(message=f"LLM 包裝失敗：{exc}")

    # 2. Resolve system_mcp_id (data source) from the source MCP
    mcp_repo = MCPDefinitionRepository(db)
    src_mcp = await mcp_repo.get_by_id(body.mcp_id)
    system_mcp_id: Optional[int] = None
    if src_mcp:
        system_mcp_id = getattr(src_mcp, "system_mcp_id", None) or getattr(src_mcp, "data_subject_id", None)

    # 3. Create MCP in DB directly with the wrapped processing_script
    mcp_name = f"{body.title}（固化）"
    try:
        new_mcp = await mcp_repo.create(
            name=mcp_name,
            description=f"由 JIT 分析升格而來：{body.title}",
            processing_intent=body.title,
            processing_script=processing_script,
            mcp_type="custom",
            system_mcp_id=system_mcp_id,
            data_subject_id=system_mcp_id,  # legacy compat
            visibility="private",
        )
        await db.commit()
        await db.refresh(new_mcp)
        new_mcp_id: int = new_mcp.id
    except Exception as exc:
        await db.rollback()
        return StandardResponse.error(message=f"MCP 建立失敗：{exc}")

    result_data: Dict[str, Any] = {
        "new_mcp_id": new_mcp_id,
        "mcp_name": mcp_name,
        "system_mcp_id": system_mcp_id,
    }

    # 4. (Optional) Generate Skill metadata for pre-fill
    if body.target == "skill":
        output_keys_str = ", ".join(body.output_keys) if body.output_keys else "（不明）"
        skill_prompt = _SKILL_META_PROMPT.format(
            title=body.title,
            output_keys=output_keys_str,
        )
        try:
            skill_resp = await client.messages.create(
                model=_PROMOTE_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": skill_prompt}],
            )
            raw_json = skill_resp.content[0].text.strip()
            skill_meta = json.loads(raw_json)
        except Exception:
            skill_meta = {
                "diagnostic_prompt": f"執行 {body.title} MCP，依輸出值判斷 NORMAL/ABNORMAL",
                "problem_subject": "待填寫（lot_id / tool_id）",
                "human_recommendation": "請根據分析結果採取相應處置",
            }
        result_data["skill_meta"] = skill_meta

    return StandardResponse.success(data=result_data, message=f"固化完成：MCP #{new_mcp_id} 已建立")


# ── v15.6: promote-analysis — template result → MCP + optional Skill ─────────

def _generate_template_script(template: str, params: Dict[str, Any], title: str) -> str:
    """Generate a sandbox-safe processing_script that calls run_analysis().
    pd, np, go and run_analysis are all pre-injected by sandbox_service.py —
    no imports needed inside the script.
    """
    # Use repr() so Python None stays as None (json.dumps would emit null which breaks sandbox)
    params_repr = repr(params)
    return f"""# Auto-generated processing_script (template: {template})
# pd / np / go / run_analysis are pre-injected by sandbox_service.

def process(raw_data):
    _df = pd.DataFrame(raw_data) if isinstance(raw_data, list) else df
    result = run_analysis({template!r}, _df, {params_repr})
    rows = result.get('result_table') or []
    chart = result.get('chart_data')
    return {{
        'llm_readable_data': result.get('llm_readable_data', ''),
        'dataset': rows,
        'ui_render': {{
            'type': 'plotly',
            'chart_data': chart,
            'charts': [chart] if chart else [],
        }},
    }}
"""


class PromoteAnalysisRequest(BaseModel):
    mcp_id: int
    run_params: Dict[str, Any] = {}
    template: str
    params: Dict[str, Any] = {}
    stats: Dict[str, Any] = {}   # r_squared, slope, etc. from analyze_data result
    title: str = ""
    target: str = "mcp"          # "mcp" or "skill"


@router.post(
    "/promote-analysis",
    response_model=StandardResponse,
    summary="v15.6 固化分析模板 → MCP（+ 可選 Skill，R²>0.7 自動生成判斷條件）",
)
async def promote_analysis(
    body: PromoteAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> StandardResponse:
    """Promote an analyze_data template result directly to a Custom MCP (no LLM needed).
    For 'skill' target: auto-generates diagnostic_prompt from R² / slope stats.
    """
    processing_script = _generate_template_script(body.template, body.params, body.title)

    # Resolve system_mcp_id from source MCP
    mcp_repo = MCPDefinitionRepository(db)
    src_mcp = await mcp_repo.get_by_id(body.mcp_id)
    system_mcp_id: Optional[int] = None
    if src_mcp:
        system_mcp_id = getattr(src_mcp, "system_mcp_id", None) or getattr(src_mcp, "data_subject_id", None)

    mcp_name = f"{body.title}（模板固化）" if body.title else f"{body.template} 分析 MCP"
    try:
        new_mcp = await mcp_repo.create(
            name=mcp_name,
            description=f"由 analyze_data/{body.template} 模板自動固化。{body.title}",
            processing_intent=body.title or body.template,
            processing_script=processing_script,
            mcp_type="custom",
            system_mcp_id=system_mcp_id,
            data_subject_id=system_mcp_id,
            visibility="private",
        )
        await db.commit()
        await db.refresh(new_mcp)
        new_mcp_id: int = new_mcp.id
    except Exception as exc:
        await db.rollback()
        return StandardResponse.error(message=f"MCP 建立失敗：{exc}")

    result_data: Dict[str, Any] = {"new_mcp_id": new_mcp_id, "mcp_name": mcp_name}

    # Re-run the original analysis with the same data + params → store as sample_output
    # ("用原本的資料再跑一次" — so MCP Editor shows the computed result immediately)
    try:
        import pandas as _pd
        from app.services.analysis_library import run_analysis as _run_analysis
        from app.services.mcp_definition_service import MCPDefinitionService

        _svc = MCPDefinitionService(db)
        _run_result = await _svc.run_with_data(body.mcp_id, body.run_params)
        _od = (_run_result.output_data or {}) if _run_result.success else {}
        _raw = _od.get("_raw_dataset") or _od.get("dataset") or []
        if _raw:
            _df = _pd.DataFrame(_raw)
            _analysis = _run_analysis(body.template, _df, body.params)
            _rows = _analysis.get("result_table") or []
            _sample: Dict[str, Any] = {
                "llm_readable_data": _analysis.get("llm_readable_data", ""),
                "dataset": _rows,
                "ui_render_payload": {
                    "chart_type": "plotly",
                    "chart_data": _analysis.get("chart_data"),
                    "rows": _rows,
                    "columns": list(_rows[0].keys()) if _rows else [],
                    "stats": _analysis.get("stats") or {},
                },
            }
            await mcp_repo.update(new_mcp, sample_output=_sample)
            await db.commit()
            result_data["sample_row_count"] = len(_rows)
    except Exception:
        pass  # sample_output is best-effort; MCP is already created

    # Skill target: generate diagnostic_prompt from stats (no LLM needed)
    if body.target == "skill":
        r2 = float(body.stats.get("r_squared", 0))
        slope = float(body.stats.get("slope", 0))
        value_col = body.params.get("value_col", "value")
        if r2 > 0.7:
            trend_dir = "上升" if slope > 0 else "下降"
            diag_prompt = (
                f"若 R² > 0.7（當前 R²={r2:.4f}），表示 {value_col} 有顯著{trend_dir}趨勢（slope={slope:.4f}）。"
                f"判定：ABNORMAL。若 R² ≤ 0.7，表示趨勢不顯著，判定：NORMAL。"
            )
            human_rec = f"R²={r2:.4f} 趨勢顯著（{trend_dir}），建議追查 {value_col} {trend_dir}原因並確認製程穩定性。"
        else:
            diag_prompt = (
                f"監控 {value_col} 線性趨勢是否升至 R² > 0.7（當前 R²={r2:.4f}，趨勢不顯著）。"
                f"判定：NORMAL。若未來 R² > 0.7，升級為 ABNORMAL。"
            )
            human_rec = ""
        result_data["skill_meta"] = {
            "diagnostic_prompt": diag_prompt,
            "problem_subject": value_col,
            "human_recommendation": human_rec,
        }

    return StandardResponse.success(data=result_data, message=f"模板固化完成：MCP #{new_mcp_id}")


# ── v15.6: Structured Analysis Template Library ───────────────────────────────

class AnalyzeDataRequest(BaseModel):
    mcp_id: int
    run_params: Dict[str, Any] = {}
    template: str
    params: Dict[str, Any] = {}
    title: str = ""


@router.get(
    "/analyze-data/templates",
    summary="v15.6 取得分析模板清單",
    response_model=StandardResponse,
)
async def get_analysis_templates(
    current_user: UserModel = Depends(get_current_user),
) -> StandardResponse:
    """Return available analysis templates with descriptions and required params."""
    from app.services.analysis_library import TEMPLATES
    return StandardResponse.success(data={"templates": TEMPLATES})


@router.post(
    "/analyze-data",
    response_model=StandardResponse,
    summary="v15.6 結構化分析 — 呼叫預建分析模板（datetime/Y 軸等已正確處理）",
)
async def analyze_data(
    body: AnalyzeDataRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> StandardResponse:
    """Fetch full MCP dataset then run a pre-built, server-verified analysis template.

    Agent only maps column names; all numpy/plotly details are handled server-side.
    Eliminates common LLM mistakes: datetime regression, Y-axis range, missing traces.
    """
    from app.services.analysis_library import TEMPLATES, run_analysis
    from app.services.mcp_builder_service import MCPBuilderService
    from app.services.mcp_definition_service import MCPDefinitionService

    if body.template not in TEMPLATES:
        return StandardResponse.error(
            message=f"未知模板 '{body.template}'，可用：{list(TEMPLATES.keys())}"
        )

    svc = MCPDefinitionService(
        repo=MCPDefinitionRepository(db),
        ds_repo=DataSubjectRepository(db),
        llm=MCPBuilderService(),
        sp_repo=SystemParameterRepository(db),
    )

    # 1. Fetch full MCP dataset
    mcp_result = await svc.run_with_data(body.mcp_id, body.run_params)
    if not mcp_result.success:
        return StandardResponse.error(message=mcp_result.error or "MCP 資料取得失敗")

    od = mcp_result.output_data or {}
    dataset = od.get("_raw_dataset") or od.get("dataset") or []
    if not dataset:
        return StandardResponse.error(message="MCP 回傳空資料集，無法分析")

    import pandas as _pd
    df = _pd.DataFrame(dataset)

    # 2. Run template
    try:
        result = run_analysis(body.template, df, body.params)
    except ValueError as exc:
        return StandardResponse.error(message=f"分析參數錯誤：{exc}")
    except Exception as exc:
        return StandardResponse.error(message=f"分析失敗：{exc}")

    title = body.title or f"{body.template} 分析"
    return StandardResponse.success(
        data={
            "mcp_id": body.mcp_id,
            "template": body.template,
            "row_count": len(df),
            "title": title,
            "stats": result.get("stats"),
            "chart_json": result.get("chart_data"),
            "has_chart": bool(result.get("chart_data")),
            "llm_readable_data": result.get("llm_readable_data", ""),
            "result_table": result.get("result_table"),  # per-row data table
        },
        message=title,
    )
