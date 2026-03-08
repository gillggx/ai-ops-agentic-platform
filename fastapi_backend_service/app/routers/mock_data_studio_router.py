"""Mock Data Studio Router — CRUD + run + generate-code + quick-sample."""

import json
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.mock_data_source import MockDataSourceModel
from app.models.mcp_definition import MCPDefinitionModel
from app.models.user import UserModel
from app.schemas.mock_data_source import (
    MockDataGenerateRequest,
    MockDataRunRequest,
    MockDataRunResponse,
    MockDataSourceCreate,
    MockDataSourceResponse,
    MockDataSourceUpdate,
)
from app.services.mock_data_studio_service import MockDataStudioService, execute_generate_fn
from app.services.mcp_builder_service import MCPBuilderService
from app.services.sandbox_service import execute_script

router = APIRouter(prefix="/mock-data", tags=["mock-data-studio"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_response(m: MockDataSourceModel) -> MockDataSourceResponse:
    return MockDataSourceResponse.model_validate(m)


def _app_err(status_code: int, detail: str, error_code: str) -> AppException:
    return AppException(status_code=status_code, detail=detail, error_code=error_code)


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=StandardResponse)
async def list_mock_data_sources(
    is_active: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: UserModel = Depends(get_current_user),
):
    stmt = select(MockDataSourceModel).order_by(MockDataSourceModel.updated_at.desc())
    if is_active is not None:
        stmt = stmt.where(MockDataSourceModel.is_active == is_active)
    result = await db.execute(stmt)
    items = result.scalars().all()
    return StandardResponse(
        status="success",
        message=f"{len(items)} mock data sources",
        data=[_to_response(m).model_dump() for m in items],
    )


@router.post("", response_model=StandardResponse)
async def create_mock_data_source(
    body: MockDataSourceCreate,
    db: AsyncSession = Depends(get_db),
    _user: UserModel = Depends(get_current_user),
):
    existing = await db.execute(
        select(MockDataSourceModel).where(MockDataSourceModel.name == body.name)
    )
    if existing.scalar_one_or_none():
        raise _app_err(409, f"Name '{body.name}' already exists", "CONFLICT")

    m = MockDataSourceModel(
        name=body.name,
        description=body.description,
        input_schema=body.input_schema,
        python_code=body.python_code,
        is_active=body.is_active,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return StandardResponse(status="success", message="Created", data=_to_response(m).model_dump())


@router.get("/{mock_id}", response_model=StandardResponse)
async def get_mock_data_source(
    mock_id: int,
    db: AsyncSession = Depends(get_db),
    _user: UserModel = Depends(get_current_user),
):
    m = await db.get(MockDataSourceModel, mock_id)
    if not m:
        raise _app_err(404, "Not found", "NOT_FOUND")
    return StandardResponse(status="success", message="OK", data=_to_response(m).model_dump())


@router.patch("/{mock_id}", response_model=StandardResponse)
async def update_mock_data_source(
    mock_id: int,
    body: MockDataSourceUpdate,
    db: AsyncSession = Depends(get_db),
    _user: UserModel = Depends(get_current_user),
):
    m = await db.get(MockDataSourceModel, mock_id)
    if not m:
        raise _app_err(404, "Not found", "NOT_FOUND")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(m, field, value)
    await db.commit()
    await db.refresh(m)
    return StandardResponse(status="success", message="Updated", data=_to_response(m).model_dump())


@router.delete("/{mock_id}", response_model=StandardResponse)
async def delete_mock_data_source(
    mock_id: int,
    db: AsyncSession = Depends(get_db),
    _user: UserModel = Depends(get_current_user),
):
    m = await db.get(MockDataSourceModel, mock_id)
    if not m:
        raise _app_err(404, "Not found", "NOT_FOUND")
    await db.delete(m)
    await db.commit()
    return StandardResponse(status="success", message="Deleted", data={"id": mock_id})


# ── Run endpoint ──────────────────────────────────────────────────────────────

@router.post("/{mock_id}/run", response_model=StandardResponse)
async def run_mock_data_source(
    mock_id: int,
    body: MockDataRunRequest,
    db: AsyncSession = Depends(get_db),
    _user: UserModel = Depends(get_current_user),
):
    """Execute the mock data source's generate() function."""
    m = await db.get(MockDataSourceModel, mock_id)
    if not m:
        raise _app_err(404, "Not found", "NOT_FOUND")
    if not m.python_code:
        raise _app_err(400, "尚未生成程式碼，請先點擊「AI 生成」", "NO_CODE")
    if not m.is_active:
        raise _app_err(400, "此 Mock 資料源已停用", "INACTIVE")

    try:
        dataset = await execute_generate_fn(m.python_code, body.params)
    except Exception as e:
        raise _app_err(422, f"generate() 執行失敗：{e}", "SANDBOX_ERROR")

    rows = dataset if isinstance(dataset, list) else [dataset]
    llm_readable = json.dumps(dataset, ensure_ascii=False)[:2000]

    m.sample_output = json.dumps(rows[:20], ensure_ascii=False)
    await db.commit()

    response_data = MockDataRunResponse(
        mock_data_source_id=mock_id,
        name=m.name,
        dataset=dataset,
        llm_readable_data=llm_readable,
        ui_render_payload={"chart_type": "table", "rows": rows},
        endpoint_url=f"/api/v1/mock-data/{mock_id}/run",
    )
    return StandardResponse(status="success", message="OK", data=response_data.model_dump())


# ── Quick Sample (no Python code required) ────────────────────────────────────

class QuickSampleRequest(BaseModel):
    description: str
    count: int = 20


@router.post("/{mock_id}/quick-sample", response_model=StandardResponse)
async def quick_sample(
    mock_id: int,
    body: QuickSampleRequest,
    db: AsyncSession = Depends(get_db),
    _user: UserModel = Depends(get_current_user),
):
    """Ask LLM to generate sample rows directly as JSON (no Python execution).

    Returns the raw JSON data for preview + MCP Builder simulation.
    Saves it as sample_output on the model.
    """
    m = await db.get(MockDataSourceModel, mock_id)
    if not m:
        raise _app_err(404, "Not found", "NOT_FOUND")

    svc = MockDataStudioService()
    try:
        rows = await svc.quick_sample(
            description=body.description or m.description,
            count=body.count,
        )
    except Exception as e:
        raise _app_err(500, f"LLM 生成失敗: {e}", "LLM_ERROR")

    # Persist as sample_output
    m.sample_output = json.dumps(rows[:50], ensure_ascii=False)
    await db.commit()

    return StandardResponse(
        status="success",
        message=f"生成 {len(rows)} 筆假資料",
        data={
            "rows": rows,
            "count": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
            "endpoint_url": f"/api/v1/mock-data/{mock_id}/run",
            "mock_data_source_id": mock_id,
            "name": m.name,
        },
    )


# ── LLM code generation ───────────────────────────────────────────────────────

@router.post("/{mock_id}/generate-code", response_model=StandardResponse)
async def generate_code_for_mock(
    mock_id: int,
    body: MockDataGenerateRequest,
    db: AsyncSession = Depends(get_db),
    _user: UserModel = Depends(get_current_user),
):
    """Use Claude to generate python_code + input_schema."""
    m = await db.get(MockDataSourceModel, mock_id)
    if not m:
        raise _app_err(404, "Not found", "NOT_FOUND")

    svc = MockDataStudioService()
    try:
        result = await svc.generate_code(
            description=body.description,
            input_schema=body.input_schema or m.input_schema,
            sample_params=body.sample_params,
        )
    except Exception as e:
        raise _app_err(500, f"LLM 生成失敗: {e}", "LLM_ERROR")

    if result.get("python_code"):
        m.python_code = result["python_code"]
    if result.get("input_schema"):
        schema_val = result["input_schema"]
        m.input_schema = (
            json.dumps(schema_val, ensure_ascii=False)
            if isinstance(schema_val, dict) else schema_val
        )
    await db.commit()
    await db.refresh(m)

    return StandardResponse(
        status="success",
        message="程式碼生成完成",
        data={
            "mock_data_source": _to_response(m).model_dump(),
            "sample_params": result.get("sample_params", {}),
        },
    )


# ── Playground: LLM design processing logic on mock data ─────────────────────

class PlaygroundRequest(BaseModel):
    processing_intent: str
    params: dict = {}


def _derive_schema(rows: List[Any]) -> dict:
    """Derive a simple output_schema dict from the first row of data."""
    if not rows:
        return {"fields": []}
    first = rows[0] if isinstance(rows[0], dict) else {}
    fields = []
    for k, v in first.items():
        t = "number" if isinstance(v, (int, float)) else "boolean" if isinstance(v, bool) else "string"
        fields.append({"name": k, "type": t, "description": ""})
    return {"fields": fields}


@router.post("/{mock_id}/playground", response_model=StandardResponse)
async def playground_run(
    mock_id: int,
    body: PlaygroundRequest,
    db: AsyncSession = Depends(get_db),
    _user: UserModel = Depends(get_current_user),
):
    """Run LLM-designed processing logic on mock data rows.

    Does NOT require a DataSubject — derives schema directly from mock data rows.
    Flow: generate(params) → derive schema → LLM script → sandbox execute → return.
    """
    m = await db.get(MockDataSourceModel, mock_id)
    if not m:
        raise _app_err(404, "Not found", "NOT_FOUND")

    # Step 1: Get raw rows
    rows: List[Any] = []
    if m.python_code:
        try:
            dataset = await execute_generate_fn(m.python_code, body.params)
            rows = dataset if isinstance(dataset, list) else [dataset]
        except Exception as e:
            raise _app_err(422, f"generate() 執行失敗: {e}", "SANDBOX_ERROR")
    elif m.sample_output:
        try:
            rows = json.loads(m.sample_output)
        except json.JSONDecodeError:
            pass

    if not rows:
        raise _app_err(400, "尚無資料可處理，請先生成程式碼或執行試跑", "NO_DATA")

    # Step 2: Derive schema from actual row structure
    output_schema = _derive_schema(rows)

    # Step 3: Ask LLM to generate processing script
    builder = MCPBuilderService()
    try:
        result = await builder.generate_for_try_run(
            processing_intent=body.processing_intent,
            data_subject_name=m.name,
            data_subject_output_schema=output_schema,
        )
    except Exception as e:
        raise _app_err(500, f"LLM 生成失敗: {e}", "LLM_ERROR")

    script = result.get("processing_script", "")
    if not script or "def process" not in script:
        return StandardResponse(
            status="error",
            message=result.get("processing_script", "LLM 未生成可用腳本"),
            data={"success": False, "error": result.get("processing_script", "")},
        )

    # Step 4: Execute script in sandbox
    try:
        output_data = await execute_script(script, rows)
    except (ValueError, TimeoutError) as e:
        return StandardResponse(
            status="success",
            message="沙盒執行失敗",
            data={"success": False, "script": script, "error": str(e)},
        )

    return StandardResponse(
        status="success",
        message="Playground 執行完成",
        data={
            "success": True,
            "script": script,
            "output_data": output_data,
            "row_count": len(rows),
        },
    )


# ── Promote to System MCP ────────────────────────────────────────────────────

@router.post("/{mock_id}/promote-to-system-mcp", response_model=StandardResponse)
async def promote_to_system_mcp(
    mock_id: int,
    db: AsyncSession = Depends(get_db),
    _user: UserModel = Depends(get_current_user),
):
    """Create (or update) a System MCP entry that wraps this mock data source.

    The System MCP api_config points to POST /api/v1/mock-data/{id}/public-run
    so any Custom MCP or Skill can consume it like a real production data source.
    """
    m = await db.get(MockDataSourceModel, mock_id)
    if not m:
        raise _app_err(404, "Not found", "NOT_FOUND")
    if not m.python_code:
        raise _app_err(400, "請先生成程式碼才能升級為 System MCP", "NO_CODE")

    api_config = json.dumps({
        "endpoint_url": f"/api/v1/mock-data/{mock_id}/public-run",
        "method": "POST",
        "headers": {},
    }, ensure_ascii=False)

    # Check if a System MCP with this name already exists
    existing = await db.execute(
        select(MCPDefinitionModel).where(
            MCPDefinitionModel.name == m.name,
            MCPDefinitionModel.mcp_type == "system",
        )
    )
    sys_mcp = existing.scalar_one_or_none()

    if sys_mcp:
        # Update api_config + input_schema to reflect latest mock source state
        sys_mcp.api_config = api_config
        if m.input_schema:
            sys_mcp.input_schema = m.input_schema
        sys_mcp.description = m.description or sys_mcp.description
        await db.commit()
        await db.refresh(sys_mcp)
        return StandardResponse(
            status="success",
            message=f"System MCP「{sys_mcp.name}」已更新 (id={sys_mcp.id})",
            data={"system_mcp_id": sys_mcp.id, "name": sys_mcp.name, "updated": True},
        )

    # Create new System MCP
    sys_mcp = MCPDefinitionModel(
        name=m.name,
        description=m.description or "",
        mcp_type="system",
        api_config=api_config,
        input_schema=m.input_schema,
        processing_intent="",
        visibility="public",
    )
    db.add(sys_mcp)
    await db.commit()
    await db.refresh(sys_mcp)
    return StandardResponse(
        status="success",
        message=f"System MCP「{sys_mcp.name}」建立成功 (id={sys_mcp.id})",
        data={"system_mcp_id": sys_mcp.id, "name": sys_mcp.name, "updated": False},
    )


# ── Public run (no auth — for System MCP api_config) ─────────────────────────

class _FlexBody(BaseModel):
    """Accepts either {"params": {...}} (standard) or flat dict (sent by System MCP executor)."""
    params: Optional[dict] = None
    model_config = {"extra": "allow"}


@router.post("/{mock_id}/public-run")
async def public_run_mock_data_source(
    mock_id: int,
    body: _FlexBody,
    db: AsyncSession = Depends(get_db),
):
    """No-auth endpoint for System MCP api_config to call.

    Accepts two body formats:
    - Standard: {"params": {"operationNumber": "9800", ...}}
    - Flat (sent by generic System MCP executor): {"operationNumber": "9800", ...}
    """
    m = await db.get(MockDataSourceModel, mock_id)
    if not m or not m.python_code or not m.is_active:
        raise _app_err(400, "Mock source not ready", "NOT_READY")

    # If body has explicit `params` key, use it; otherwise treat entire body as params
    if body.params is not None:
        params = body.params
    else:
        params = {k: v for k, v in body.model_dump().items() if k != "params" and v is not None}

    try:
        dataset = await execute_generate_fn(m.python_code, params)
    except Exception as e:
        raise _app_err(422, f"generate() 執行失敗：{e}", "SANDBOX_ERROR")

    return dataset if isinstance(dataset, list) else [dataset]
