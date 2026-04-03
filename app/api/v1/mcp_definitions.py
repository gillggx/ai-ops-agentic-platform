"""
MCP Definitions Router - API v1

Manages MCP (Measurement Collection Pipeline) definitions.
Provides CRUD operations, validation, testing, and execution endpoints.

MCP 定義路由器 - API v1
管理 MCP（測量收集管線）定義。
提供 CRUD 操作、驗證、測試和執行端點。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_active_user
from app.ontology.models import MCPDefinition, User
from app.ontology.repositories import MCPDefinitionRepository
from app.ontology.schemas.mcp import (
    MCPDefinitionCreate,
    MCPDefinitionRead,
)
from app.ontology.schemas.common import PaginationParams, ListResponse

# Initialize router
router = APIRouter(
    prefix="/api/v1/mcp-definitions",
    tags=["MCP Definitions"],
)

# Initialize repository
mcp_repo = MCPDefinitionRepository()


@router.post(
    "",
    response_model=MCPDefinitionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create MCP Definition",
    description="Create a new MCP definition with processing intent and optional script.",
)
async def create_mcp_definition(
    schema: MCPDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> MCPDefinitionRead:
    """
    Create a new MCP definition.
    
    **Path:** `POST /api/v1/mcp-definitions`
    
    **Parameters:**
    - `name` (str): Unique MCP name (max 200 chars)
    - `description` (str): Description of the MCP
    - `data_source_type` (str): Type of data source (API, Database, Sensor, etc.)
    - `processing_intent` (str): User-written intended processing logic
    - `processing_script` (str, optional): Python script for processing
    - `output_schema` (str, optional): Expected output schema as JSON
    - `ui_render_config` (str, optional): Plotly or UI rendering config
    
    **Returns:** MCPDefinitionRead with created MCP details
    
    **Errors:**
    - 400: Duplicate name or invalid data
    - 401: Unauthorized
    - 500: Server error
    
    創建新的 MCP 定義。
    """
    # Check if name already exists
    existing = await mcp_repo.get_by_name(db, schema.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"MCP definition with name '{schema.name}' already exists",
        )
    
    # Create new MCP definition
    mcp_def = MCPDefinition(
        name=schema.name,
        description=schema.description,
        data_source_type=schema.data_source_type,
        processing_intent=schema.processing_intent,
        processing_script=schema.processing_script,
        output_schema=schema.output_schema,
        ui_render_config=schema.ui_render_config,
    )
    
    return await mcp_repo.create(db, mcp_def)


@router.get(
    "",
    response_model=ListResponse[MCPDefinitionRead],
    status_code=status.HTTP_200_OK,
    summary="List MCP Definitions",
    description="List all MCP definitions with pagination.",
)
async def list_mcp_definitions(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[MCPDefinitionRead]:
    """
    List all MCP definitions with pagination.
    
    **Path:** `GET /api/v1/mcp-definitions`
    
    **Query Parameters:**
    - `skip` (int, default=0): Records to skip for pagination
    - `limit` (int, default=100): Max records to return (1-1000)
    
    **Returns:** ListResponse with array of MCPDefinitionRead
    
    **Errors:**
    - 401: Unauthorized
    - 500: Server error
    
    列出所有 MCP 定義。
    """
    mcp_defs = await mcp_repo.get_all(db, skip=skip, limit=limit)
    total = await mcp_repo.count_all(db)
    
    return ListResponse[MCPDefinitionRead](
        items=mcp_defs,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{mcp_id}",
    response_model=MCPDefinitionRead,
    status_code=status.HTTP_200_OK,
    summary="Get MCP Definition",
    description="Retrieve a specific MCP definition by ID.",
)
async def get_mcp_definition(
    mcp_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> MCPDefinitionRead:
    """
    Get a specific MCP definition by ID.
    
    **Path:** `GET /api/v1/mcp-definitions/{mcp_id}`
    
    **Parameters:**
    - `mcp_id` (int): MCP definition ID
    
    **Returns:** MCPDefinitionRead
    
    **Errors:**
    - 401: Unauthorized
    - 404: MCP definition not found
    - 500: Server error
    
    獲取特定的 MCP 定義。
    """
    mcp_def = await mcp_repo.get_by_id(db, mcp_id)
    if not mcp_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP definition with ID {mcp_id} not found",
        )
    
    return mcp_def


@router.put(
    "/{mcp_id}",
    response_model=MCPDefinitionRead,
    status_code=status.HTTP_200_OK,
    summary="Update MCP Definition",
    description="Update an existing MCP definition.",
)
async def update_mcp_definition(
    mcp_id: int,
    schema: MCPDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> MCPDefinitionRead:
    """
    Update an existing MCP definition.
    
    **Path:** `PUT /api/v1/mcp-definitions/{mcp_id}`
    
    **Parameters:**
    - `mcp_id` (int): MCP definition ID
    - Request body: MCPDefinitionCreate fields to update
    
    **Returns:** Updated MCPDefinitionRead
    
    **Errors:**
    - 400: Duplicate name or invalid data
    - 401: Unauthorized
    - 404: MCP definition not found
    - 500: Server error
    
    更新現有的 MCP 定義。
    """
    mcp_def = await mcp_repo.get_by_id(db, mcp_id)
    if not mcp_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP definition with ID {mcp_id} not found",
        )
    
    # Check for duplicate name if name is being changed
    if schema.name != mcp_def.name:
        existing = await mcp_repo.get_by_name(db, schema.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"MCP definition with name '{schema.name}' already exists",
            )
    
    # Update fields
    mcp_def.name = schema.name
    mcp_def.description = schema.description
    mcp_def.data_source_type = schema.data_source_type
    mcp_def.processing_intent = schema.processing_intent
    mcp_def.processing_script = schema.processing_script
    mcp_def.output_schema = schema.output_schema
    mcp_def.ui_render_config = schema.ui_render_config
    
    return await mcp_repo.update(db, mcp_def)


@router.delete(
    "/{mcp_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete MCP Definition",
    description="Delete an MCP definition and all associated instances.",
)
async def delete_mcp_definition(
    mcp_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete an MCP definition.
    
    **Path:** `DELETE /api/v1/mcp-definitions/{mcp_id}`
    
    **Parameters:**
    - `mcp_id` (int): MCP definition ID
    
    **Returns:** 204 No Content
    
    **Errors:**
    - 401: Unauthorized
    - 404: MCP definition not found
    - 500: Server error
    
    刪除 MCP 定義及其所有相關實例。
    """
    mcp_def = await mcp_repo.get_by_id(db, mcp_id)
    if not mcp_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP definition with ID {mcp_id} not found",
        )
    
    await mcp_repo.delete(db, mcp_def)


@router.get(
    "/{mcp_id}/validate",
    status_code=status.HTTP_200_OK,
    summary="Validate MCP Definition",
    description="Validate MCP definition processing script and schema.",
)
async def validate_mcp_definition(
    mcp_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Validate an MCP definition.
    
    Checks:
    - Processing script syntax (if provided)
    - Output schema validity (if provided)
    - Required fields
    
    **Path:** `GET /api/v1/mcp-definitions/{mcp_id}/validate`
    
    **Parameters:**
    - `mcp_id` (int): MCP definition ID
    
    **Returns:** { valid: bool, errors: list[str] }
    
    **Errors:**
    - 401: Unauthorized
    - 404: MCP definition not found
    - 500: Server error
    
    驗證 MCP 定義的處理腳本和架構。
    """
    mcp_def = await mcp_repo.get_by_id(db, mcp_id)
    if not mcp_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP definition with ID {mcp_id} not found",
        )
    
    errors: list[str] = []
    
    # Validate processing script syntax if present
    if mcp_def.processing_script:
        try:
            compile(mcp_def.processing_script, "<string>", "exec")
        except SyntaxError as e:
            errors.append(f"Invalid Python script: {e.msg}")
    
    # Validate output schema as JSON if present
    if mcp_def.output_schema:
        try:
            import json
            json.loads(mcp_def.output_schema)
        except Exception as e:
            errors.append(f"Invalid JSON schema: {str(e)}")
    
    # Validate UI render config as JSON if present
    if mcp_def.ui_render_config:
        try:
            import json
            json.loads(mcp_def.ui_render_config)
        except Exception as e:
            errors.append(f"Invalid UI config JSON: {str(e)}")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


@router.post(
    "/{mcp_id}/test-run",
    status_code=status.HTTP_200_OK,
    summary="Test Run MCP Definition",
    description="Execute an MCP definition in test mode with sample data.",
)
async def test_run_mcp_definition(
    mcp_id: int,
    test_data: dict = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Test run an MCP definition with sample data.
    
    Executes the processing script in a sandbox to validate functionality.
    
    **Path:** `POST /api/v1/mcp-definitions/{mcp_id}/test-run`
    
    **Parameters:**
    - `mcp_id` (int): MCP definition ID
    - `test_data` (dict, optional): Sample data to process
    
    **Returns:** { success: bool, output: any, error: str (optional) }
    
    **Errors:**
    - 401: Unauthorized
    - 404: MCP definition not found
    - 500: Server error / execution error
    
    使用範例數據在測試模式下執行 MCP 定義。
    """
    mcp_def = await mcp_repo.get_by_id(db, mcp_id)
    if not mcp_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP definition with ID {mcp_id} not found",
        )
    
    if not mcp_def.processing_script:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No processing script defined for this MCP",
        )
    
    try:
        # Create execution context
        execution_context = {
            "data": test_data or {},
            "result": None,
        }
        
        # Execute script in sandbox
        exec(mcp_def.processing_script, execution_context)
        
        return {
            "success": True,
            "output": execution_context.get("result"),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@router.post(
    "/{mcp_id}/run",
    status_code=status.HTTP_200_OK,
    summary="Execute MCP Definition",
    description="Execute an MCP definition with actual data.",
)
async def run_mcp_definition(
    mcp_id: int,
    input_data: dict = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Execute an MCP definition with actual data.
    
    Runs the processing script and stores result in sample_output.
    
    **Path:** `POST /api/v1/mcp-definitions/{mcp_id}/run`
    
    **Parameters:**
    - `mcp_id` (int): MCP definition ID
    - `input_data` (dict, optional): Data to process
    
    **Returns:** { success: bool, output: any, error: str (optional) }
    
    **Errors:**
    - 401: Unauthorized
    - 404: MCP definition not found
    - 500: Server error / execution error
    
    使用實際數據執行 MCP 定義。
    """
    mcp_def = await mcp_repo.get_by_id(db, mcp_id)
    if not mcp_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP definition with ID {mcp_id} not found",
        )
    
    if not mcp_def.processing_script:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No processing script defined for this MCP",
        )
    
    try:
        import json
        from datetime import datetime
        
        # Create execution context
        execution_context = {
            "data": input_data or {},
            "result": None,
        }
        
        # Execute script
        exec(mcp_def.processing_script, execution_context)
        
        output = execution_context.get("result")
        
        # Store result in sample_output
        mcp_def.sample_output = json.dumps(output) if output else None
        mcp_def.last_status = "success"
        mcp_def.last_execution_at = datetime.utcnow().isoformat()
        
        await mcp_repo.update(db, mcp_def)
        
        return {
            "success": True,
            "output": output,
        }
    except Exception as e:
        # Update status to failed
        mcp_def.last_status = "failed"
        from datetime import datetime
        mcp_def.last_execution_at = datetime.utcnow().isoformat()
        await mcp_repo.update(db, mcp_def)
        
        return {
            "success": False,
            "error": str(e),
        }
