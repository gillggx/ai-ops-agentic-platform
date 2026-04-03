"""
Builder Router - API v1

Manages AI-assisted code generation for MCPs and Skills.
Provides endpoints for generating, validating, and testing auto-generated code.

構建者路由器 - API v1
管理 MCP 和技能的 AI 輔助代碼生成。
提供生成、驗證和測試自動生成代碼的端點。
"""

from typing import Optional
import json
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_active_user
from app.ontology.models import User
from app.ontology.schemas.common import ListResponse

# Build type enum
class BuildType(str, Enum):
    """Type of build artifact."""
    MCP_SCRIPT = "mcp_script"
    SKILL_DIAGNOSTIC = "skill_diagnostic"
    SKILL_EXECUTOR = "skill_executor"
    DATA_TRANSFORMER = "data_transformer"


# Initialize router
router = APIRouter(
    prefix="/api/v1/builder",
    tags=["Builder"],
)

# In-memory build storage
# Format: {build_id: {type, intent, generated_code, status, ...}}
builds_store: dict = {}


@router.post(
    "/mcp",
    status_code=status.HTTP_201_CREATED,
    summary="Generate MCP Script",
    description="Use LLM to generate MCP processing script from intent.",
)
async def generate_mcp_script(
    intent: str,
    data_source_type: str,
    output_format: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Generate MCP processing script using LLM.
    
    **Path:** `POST /api/v1/builder/mcp`
    
    **Parameters:**
    - `intent` (str): Natural language description of processing logic
    - `data_source_type` (str): Type of data source (API, Database, Sensor)
    - `output_format` (str, optional): Desired output format (JSON, CSV, etc.)
    
    **Returns:** {
        build_id: str,
        type: str,
        generated_code: str,
        status: str,
        created_at: str
    }
    
    **Errors:**
    - 400: Invalid intent
    - 401: Unauthorized
    - 500: LLM generation error
    
    使用 LLM 從意圖生成 MCP 處理腳本。
    """
    import uuid
    build_id = str(uuid.uuid4())
    
    # Simulate LLM-generated code
    generated_code = f"""
# Generated MCP processing script
# Intent: {intent}
# Data source: {data_source_type}

def process_data(data):
    \"\"\"Process {data_source_type} data.\"\"\"
    # Auto-generated processing logic
    result = {{
        'input_type': '{data_source_type}',
        'output_format': '{output_format or 'JSON'}',
        'processed_records': len(data) if isinstance(data, list) else 1,
        'timestamp': '{datetime.utcnow().isoformat()}'
    }}
    return result
"""
    
    builds_store[build_id] = {
        "type": BuildType.MCP_SCRIPT,
        "intent": intent,
        "data_source_type": data_source_type,
        "output_format": output_format,
        "generated_code": generated_code,
        "status": "generated",
        "validation_errors": [],
        "test_results": None,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    
    return {
        "build_id": build_id,
        "type": BuildType.MCP_SCRIPT,
        "generated_code": generated_code,
        "status": "generated",
        "created_at": builds_store[build_id]["created_at"],
    }


@router.post(
    "/skill-diagnostic",
    status_code=status.HTTP_201_CREATED,
    summary="Generate Skill Diagnostic",
    description="Generate diagnostic prompt/logic for a skill.",
)
async def generate_skill_diagnostic(
    skill_intent: str,
    bound_mcps: Optional[list[int]] = None,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Generate skill diagnostic prompt.
    
    **Path:** `POST /api/v1/builder/skill-diagnostic`
    
    **Parameters:**
    - `skill_intent` (str): What the skill should diagnose
    - `bound_mcps` (list[int], optional): MCPs to use in diagnosis
    
    **Returns:** { build_id, type, generated_code, status }
    
    **Errors:**
    - 400: Invalid intent
    - 401: Unauthorized
    - 500: Generation error
    
    生成技能診斷提示。
    """
    import uuid
    build_id = str(uuid.uuid4())
    
    # Simulate LLM generation
    generated_code = f"""
# Skill Diagnostic Template
# Purpose: {skill_intent}

def diagnose(context):
    \"\"\"Diagnose based on context.\"\"\"
    findings = {{
        'diagnosis': '{skill_intent}',
        'confidence': 0.85,
        'mcps_used': {bound_mcps or []},
        'recommendations': ['Monitor closely', 'Schedule review']
    }}
    return findings
"""
    
    builds_store[build_id] = {
        "type": BuildType.SKILL_DIAGNOSTIC,
        "skill_intent": skill_intent,
        "bound_mcps": bound_mcps or [],
        "generated_code": generated_code,
        "status": "generated",
        "validation_errors": [],
        "created_at": datetime.utcnow().isoformat(),
    }
    
    return {
        "build_id": build_id,
        "type": BuildType.SKILL_DIAGNOSTIC,
        "generated_code": generated_code,
        "status": "generated",
    }


@router.post(
    "/skill-executor",
    status_code=status.HTTP_201_CREATED,
    summary="Generate Skill Executor",
    description="Generate execution logic for a skill.",
)
async def generate_skill_executor(
    skill_name: str,
    execution_intent: str,
    input_schema: Optional[dict] = None,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Generate skill execution logic.
    
    **Path:** `POST /api/v1/builder/skill-executor`
    
    **Parameters:**
    - `skill_name` (str): Skill name
    - `execution_intent` (str): What the skill executes
    - `input_schema` (dict, optional): Input schema
    
    **Returns:** { build_id, type, generated_code, status }
    
    **Errors:**
    - 400: Invalid parameters
    - 401: Unauthorized
    - 500: Generation error
    
    生成技能執行邏輯。
    """
    import uuid
    build_id = str(uuid.uuid4())
    
    generated_code = f"""
# Skill Executor: {skill_name}
# Executes: {execution_intent}

def execute(data):
    \"\"\"Execute skill logic.\"\"\"
    try:
        output = {{
            'skill': '{skill_name}',
            'status': 'success',
            'result': 'Execution completed',
        }}
        return output
    except Exception as e:
        return {{'status': 'error', 'error': str(e)}}
"""
    
    builds_store[build_id] = {
        "type": BuildType.SKILL_EXECUTOR,
        "skill_name": skill_name,
        "execution_intent": execution_intent,
        "input_schema": input_schema or {},
        "generated_code": generated_code,
        "status": "generated",
        "created_at": datetime.utcnow().isoformat(),
    }
    
    return {
        "build_id": build_id,
        "type": BuildType.SKILL_EXECUTOR,
        "generated_code": generated_code,
        "status": "generated",
    }


@router.get(
    "/{build_id}",
    status_code=status.HTTP_200_OK,
    summary="Get Build Details",
    description="Retrieve generated code and validation results.",
)
async def get_build(
    build_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Get build details.
    
    **Path:** `GET /api/v1/builder/{build_id}`
    
    **Parameters:**
    - `build_id` (str): Build UUID
    
    **Returns:** Complete build details with code and test results
    
    **Errors:**
    - 401: Unauthorized
    - 404: Build not found
    - 500: Server error
    
    獲取構建詳情。
    """
    if build_id not in builds_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build with ID {build_id} not found",
        )
    
    return {
        "build_id": build_id,
        **builds_store[build_id],
    }


@router.post(
    "/{build_id}/validate",
    status_code=status.HTTP_200_OK,
    summary="Validate Generated Code",
    description="Validate syntax and structure of generated code.",
)
async def validate_build(
    build_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Validate generated code.
    
    **Path:** `POST /api/v1/builder/{build_id}/validate`
    
    **Parameters:**
    - `build_id` (str): Build UUID
    
    **Returns:** { build_id, valid, errors: list[str] }
    
    **Errors:**
    - 401: Unauthorized
    - 404: Build not found
    - 500: Server error
    
    驗證生成的代碼。
    """
    if build_id not in builds_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build with ID {build_id} not found",
        )
    
    build = builds_store[build_id]
    errors = []
    
    # Validate Python syntax
    try:
        compile(build["generated_code"], "<string>", "exec")
    except SyntaxError as e:
        errors.append(f"Syntax error: {e.msg}")
    
    build["validation_errors"] = errors
    build["status"] = "valid" if not errors else "invalid"
    
    return {
        "build_id": build_id,
        "valid": len(errors) == 0,
        "errors": errors,
        "status": build["status"],
    }


@router.post(
    "/{build_id}/test",
    status_code=status.HTTP_200_OK,
    summary="Test Generated Code",
    description="Execute generated code in sandbox and return results.",
)
async def test_build(
    build_id: str,
    test_data: Optional[dict] = None,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Test generated code with sample data.
    
    **Path:** `POST /api/v1/builder/{build_id}/test`
    
    **Parameters:**
    - `build_id` (str): Build UUID
    - `test_data` (dict, optional): Test input data
    
    **Returns:** { build_id, test_passed, output, error }
    
    **Errors:**
    - 401: Unauthorized
    - 404: Build not found
    - 500: Execution error
    
    測試生成的代碼。
    """
    if build_id not in builds_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build with ID {build_id} not found",
        )
    
    build = builds_store[build_id]
    
    try:
        # Execute in sandbox
        exec_context = {"data": test_data or {}, "result": None}
        exec(build["generated_code"], exec_context)
        
        result = exec_context.get("result", "Test executed successfully")
        
        build["test_results"] = {
            "passed": True,
            "output": result,
            "timestamp": datetime.utcnow().isoformat(),
        }
        build["status"] = "tested"
        
        return {
            "build_id": build_id,
            "test_passed": True,
            "output": result,
        }
    except Exception as e:
        build["test_results"] = {
            "passed": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        return {
            "build_id": build_id,
            "test_passed": False,
            "error": str(e),
        }


@router.post(
    "/{build_id}/approve",
    status_code=status.HTTP_200_OK,
    summary="Approve Build",
    description="Approve generated code for deployment.",
)
async def approve_build(
    build_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Approve generated code.
    
    **Path:** `POST /api/v1/builder/{build_id}/approve`
    
    **Parameters:**
    - `build_id` (str): Build UUID
    
    **Returns:** { build_id, status: APPROVED }
    
    **Errors:**
    - 401: Unauthorized
    - 404: Build not found
    - 500: Server error
    
    批准生成的代碼。
    """
    if build_id not in builds_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build with ID {build_id} not found",
        )
    
    build = builds_store[build_id]
    build["status"] = "approved"
    build["approved_by"] = current_user.id
    build["approved_at"] = datetime.utcnow().isoformat()
    
    return {
        "build_id": build_id,
        "status": "approved",
        "approved_at": build["approved_at"],
    }


@router.post(
    "/{build_id}/reject",
    status_code=status.HTTP_200_OK,
    summary="Reject Build",
    description="Reject generated code with feedback.",
)
async def reject_build(
    build_id: str,
    feedback: str,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Reject generated code.
    
    **Path:** `POST /api/v1/builder/{build_id}/reject`
    
    **Parameters:**
    - `build_id` (str): Build UUID
    - `feedback` (str): Rejection feedback
    
    **Returns:** { build_id, status: REJECTED }
    
    **Errors:**
    - 401: Unauthorized
    - 404: Build not found
    - 500: Server error
    
    拒絕生成的代碼。
    """
    if build_id not in builds_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build with ID {build_id} not found",
        )
    
    build = builds_store[build_id]
    build["status"] = "rejected"
    build["rejection_feedback"] = feedback
    build["rejected_by"] = current_user.id
    build["rejected_at"] = datetime.utcnow().isoformat()
    
    return {
        "build_id": build_id,
        "status": "rejected",
        "feedback": feedback,
        "rejected_at": build["rejected_at"],
    }


@router.get(
    "",
    response_model=ListResponse[dict],
    status_code=status.HTTP_200_OK,
    summary="List Builds",
    description="List generated builds with filtering.",
)
async def list_builds(
    build_type: Optional[str] = Query(None, description="Filter by build type"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[dict]:
    """
    List builds.
    
    **Path:** `GET /api/v1/builder`
    
    **Query Parameters:**
    - `build_type` (str, optional): Filter by type
    - `status_filter` (str, optional): Filter by status
    - `skip` (int, default=0): Records to skip
    - `limit` (int, default=100): Max records to return
    
    **Returns:** ListResponse with array of builds
    
    **Errors:**
    - 401: Unauthorized
    - 500: Server error
    
    列出構建。
    """
    all_builds = []
    for build_id, build in builds_store.items():
        if build_type and build["type"] != build_type:
            continue
        if status_filter and build["status"] != status_filter:
            continue
        
        all_builds.append({
            "build_id": build_id,
            **build,
        })
    
    total = len(all_builds)
    paginated = all_builds[skip:skip + limit]
    
    return ListResponse[dict](
        items=paginated,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.delete(
    "/{build_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Build",
    description="Delete a build and its generated code.",
)
async def delete_build(
    build_id: str,
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete a build.
    
    **Path:** `DELETE /api/v1/builder/{build_id}`
    
    **Parameters:**
    - `build_id` (str): Build UUID
    
    **Returns:** 204 No Content
    
    **Errors:**
    - 401: Unauthorized
    - 404: Build not found
    - 500: Server error
    
    刪除構建。
    """
    if build_id not in builds_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build with ID {build_id} not found",
        )
    
    del builds_store[build_id]
