"""Mock Data Studio Router — CRUD + run + generate-code for programmable mock data sources."""

import json
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
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


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=StandardResponse)
async def list_mock_data_sources(
    is_active: Optional[bool] = Query(default=None, description="Filter by is_active"),
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
        raise AppException(status_code=409, message=f"Name '{body.name}' already exists", error_code="CONFLICT")

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
        raise AppException(status_code=404, message="Not found", error_code="NOT_FOUND")
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
        raise AppException(status_code=404, message="Not found", error_code="NOT_FOUND")
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
        raise AppException(status_code=404, message="Not found", error_code="NOT_FOUND")
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
    """Execute the mock data source's generate() function and return System MCP-compatible response."""
    m = await db.get(MockDataSourceModel, mock_id)
    if not m:
        raise AppException(status_code=404, message="Not found", error_code="NOT_FOUND")
    if not m.python_code:
        raise AppException(status_code=400, message="No python_code defined. Use /generate-code first.", error_code="NO_CODE")
    if not m.is_active:
        raise AppException(status_code=400, message="This mock data source is inactive.", error_code="INACTIVE")

    try:
        dataset = await execute_generate_fn(m.python_code, body.params)
    except (ValueError, TimeoutError) as e:
        raise AppException(status_code=422, message=str(e), error_code="SANDBOX_ERROR")

    # Build System MCP-compatible response
    rows = dataset if isinstance(dataset, list) else [dataset]
    llm_readable = json.dumps(dataset, ensure_ascii=False)[:2000]
    endpoint_url = f"/api/v1/mock-data/{mock_id}/run"

    # Save sample_output
    m.sample_output = json.dumps(rows[:20], ensure_ascii=False)
    await db.commit()

    response_data = MockDataRunResponse(
        mock_data_source_id=mock_id,
        name=m.name,
        dataset=dataset,
        llm_readable_data=llm_readable,
        ui_render_payload={"chart_type": "table", "rows": rows},
        endpoint_url=endpoint_url,
    )
    return StandardResponse(status="success", message="OK", data=response_data.model_dump())


# ── LLM code generation ───────────────────────────────────────────────────────

@router.post("/{mock_id}/generate-code", response_model=StandardResponse)
async def generate_code_for_mock(
    mock_id: int,
    body: MockDataGenerateRequest,
    db: AsyncSession = Depends(get_db),
    _user: UserModel = Depends(get_current_user),
):
    """Use Claude to generate python_code + input_schema for this mock data source."""
    m = await db.get(MockDataSourceModel, mock_id)
    if not m:
        raise AppException(status_code=404, message="Not found", error_code="NOT_FOUND")

    svc = MockDataStudioService()
    try:
        result = await svc.generate_code(
            description=body.description,
            input_schema=body.input_schema or m.input_schema,
            sample_params=body.sample_params,
        )
    except Exception as e:
        raise AppException(status_code=500, message=f"LLM error: {e}", error_code="LLM_ERROR")

    # Persist generated code and input_schema
    if result.get("python_code"):
        m.python_code = result["python_code"]
    if result.get("input_schema"):
        schema_val = result["input_schema"]
        m.input_schema = json.dumps(schema_val, ensure_ascii=False) if isinstance(schema_val, dict) else schema_val
    await db.commit()
    await db.refresh(m)

    return StandardResponse(
        status="success",
        message="Code generated",
        data={
            "mock_data_source": _to_response(m).model_dump(),
            "sample_params": result.get("sample_params", {}),
        },
    )


# ── Public run endpoint (no auth — for System MCP api_config calls) ───────────

@router.post("/{mock_id}/public-run")
async def public_run_mock_data_source(
    mock_id: int,
    body: MockDataRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Public (no-auth) version of /run — allows System MCP api_config to call this endpoint."""
    m = await db.get(MockDataSourceModel, mock_id)
    if not m:
        raise AppException(status_code=404, message="Not found", error_code="NOT_FOUND")
    if not m.python_code or not m.is_active:
        raise AppException(status_code=400, message="Mock source not ready", error_code="NOT_READY")

    try:
        dataset = await execute_generate_fn(m.python_code, body.params)
    except (ValueError, TimeoutError) as e:
        raise AppException(status_code=422, message=str(e), error_code="SANDBOX_ERROR")

    rows = dataset if isinstance(dataset, list) else [dataset]
    return rows
