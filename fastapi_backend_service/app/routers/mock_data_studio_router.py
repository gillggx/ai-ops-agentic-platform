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
    except (ValueError, TimeoutError) as e:
        raise _app_err(422, str(e), "SANDBOX_ERROR")

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


# ── Public run (no auth — for System MCP api_config) ─────────────────────────

@router.post("/{mock_id}/public-run")
async def public_run_mock_data_source(
    mock_id: int,
    body: MockDataRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """No-auth endpoint for System MCP api_config to call."""
    m = await db.get(MockDataSourceModel, mock_id)
    if not m or not m.python_code or not m.is_active:
        raise _app_err(400, "Mock source not ready", "NOT_READY")

    try:
        dataset = await execute_generate_fn(m.python_code, body.params)
    except (ValueError, TimeoutError) as e:
        raise _app_err(422, str(e), "SANDBOX_ERROR")

    return dataset if isinstance(dataset, list) else [dataset]
