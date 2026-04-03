"""
Skill Definitions Router - API v1

Manages Skill definitions and instances.
Provides CRUD operations, diagnosis, execution, and binding endpoints.

技能定義路由器 - API v1
管理技能定義和實例。
提供 CRUD 操作、診斷、執行和綁定端點。
"""

from typing import Optional
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_active_user
from app.ontology.models import SkillDefinition, Skill, User
from app.ontology.repositories import (
    SkillDefinitionRepository,
    SkillRepository,
)
from app.ontology.schemas.skill import (
    SkillDefinitionCreate,
    SkillDefinitionRead,
    SkillCreate,
    SkillRead,
)
from app.ontology.schemas.common import ListResponse

# Initialize router
router = APIRouter(
    prefix="/api/v1/skill-definitions",
    tags=["Skill Definitions"],
)

# Initialize repositories
skill_def_repo = SkillDefinitionRepository()
skill_repo = SkillRepository()


@router.post(
    "",
    response_model=SkillDefinitionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Skill Definition",
    description="Create a new skill definition with MCPs binding and diagnostic prompt.",
)
async def create_skill_definition(
    schema: SkillDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SkillDefinitionRead:
    """
    Create a new skill definition.
    
    **Path:** `POST /api/v1/skill-definitions`
    
    **Parameters:**
    - `name` (str): Unique skill name (max 200 chars)
    - `description` (str): Description of what skill does
    - `version` (str, default="1.0.0"): Semantic version
    - `mcp_ids` (str, default="[]"): JSON array of bound MCP definition IDs
    - `diagnostic_prompt` (str, optional): Template for diagnosis logic
    - `human_recommendation` (str, optional): Expert recommendation text
    
    **Returns:** SkillDefinitionRead with created skill details
    
    **Errors:**
    - 400: Duplicate name or invalid data
    - 401: Unauthorized
    - 500: Server error
    
    創建新的技能定義。
    """
    # Check if name already exists
    existing = await skill_def_repo.get_by_name(db, schema.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Skill definition with name '{schema.name}' already exists",
        )
    
    # Validate mcp_ids JSON
    try:
        mcp_ids = json.loads(schema.mcp_ids) if schema.mcp_ids else []
        if not isinstance(mcp_ids, list):
            raise ValueError("mcp_ids must be a JSON array")
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mcp_ids JSON: {str(e)}",
        )
    
    # Create new skill definition
    skill_def = SkillDefinition(
        name=schema.name,
        description=schema.description,
        version=schema.version,
        mcp_ids=schema.mcp_ids,
        diagnostic_prompt=schema.diagnostic_prompt,
        human_recommendation=schema.human_recommendation,
    )
    
    return await skill_def_repo.create(db, skill_def)


@router.get(
    "",
    response_model=ListResponse[SkillDefinitionRead],
    status_code=status.HTTP_200_OK,
    summary="List Skill Definitions",
    description="List all skill definitions with pagination.",
)
async def list_skill_definitions(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[SkillDefinitionRead]:
    """
    List all skill definitions with pagination.
    
    **Path:** `GET /api/v1/skill-definitions`
    
    **Query Parameters:**
    - `skip` (int, default=0): Records to skip for pagination
    - `limit` (int, default=100): Max records to return (1-1000)
    
    **Returns:** ListResponse with array of SkillDefinitionRead
    
    **Errors:**
    - 401: Unauthorized
    - 500: Server error
    
    列出所有技能定義。
    """
    skill_defs = await skill_def_repo.get_all(db, skip=skip, limit=limit)
    total = await skill_def_repo.count_all(db)
    
    return ListResponse[SkillDefinitionRead](
        items=skill_defs,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{skill_id}",
    response_model=SkillDefinitionRead,
    status_code=status.HTTP_200_OK,
    summary="Get Skill Definition",
    description="Retrieve a specific skill definition by ID.",
)
async def get_skill_definition(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SkillDefinitionRead:
    """
    Get a specific skill definition by ID.
    
    **Path:** `GET /api/v1/skill-definitions/{skill_id}`
    
    **Parameters:**
    - `skill_id` (int): Skill definition ID
    
    **Returns:** SkillDefinitionRead
    
    **Errors:**
    - 401: Unauthorized
    - 404: Skill definition not found
    - 500: Server error
    
    獲取特定的技能定義。
    """
    skill_def = await skill_def_repo.get_by_id(db, skill_id)
    if not skill_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill definition with ID {skill_id} not found",
        )
    
    return skill_def


@router.put(
    "/{skill_id}",
    response_model=SkillDefinitionRead,
    status_code=status.HTTP_200_OK,
    summary="Update Skill Definition",
    description="Update an existing skill definition.",
)
async def update_skill_definition(
    skill_id: int,
    schema: SkillDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SkillDefinitionRead:
    """
    Update an existing skill definition.
    
    **Path:** `PUT /api/v1/skill-definitions/{skill_id}`
    
    **Parameters:**
    - `skill_id` (int): Skill definition ID
    - Request body: SkillDefinitionCreate fields to update
    
    **Returns:** Updated SkillDefinitionRead
    
    **Errors:**
    - 400: Duplicate name or invalid data
    - 401: Unauthorized
    - 404: Skill definition not found
    - 500: Server error
    
    更新現有的技能定義。
    """
    skill_def = await skill_def_repo.get_by_id(db, skill_id)
    if not skill_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill definition with ID {skill_id} not found",
        )
    
    # Check for duplicate name if name is being changed
    if schema.name != skill_def.name:
        existing = await skill_def_repo.get_by_name(db, schema.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Skill definition with name '{schema.name}' already exists",
            )
    
    # Validate mcp_ids JSON
    try:
        mcp_ids = json.loads(schema.mcp_ids) if schema.mcp_ids else []
        if not isinstance(mcp_ids, list):
            raise ValueError("mcp_ids must be a JSON array")
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mcp_ids JSON: {str(e)}",
        )
    
    # Update fields
    skill_def.name = schema.name
    skill_def.description = schema.description
    skill_def.version = schema.version
    skill_def.mcp_ids = schema.mcp_ids
    skill_def.diagnostic_prompt = schema.diagnostic_prompt
    skill_def.human_recommendation = schema.human_recommendation
    
    return await skill_def_repo.update(db, skill_def)


@router.delete(
    "/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Skill Definition",
    description="Delete a skill definition and all associated instances.",
)
async def delete_skill_definition(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete a skill definition.
    
    **Path:** `DELETE /api/v1/skill-definitions/{skill_id}`
    
    **Parameters:**
    - `skill_id` (int): Skill definition ID
    
    **Returns:** 204 No Content
    
    **Errors:**
    - 401: Unauthorized
    - 404: Skill definition not found
    - 500: Server error
    
    刪除技能定義及其所有相關實例。
    """
    skill_def = await skill_def_repo.get_by_id(db, skill_id)
    if not skill_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill definition with ID {skill_id} not found",
        )
    
    await skill_def_repo.delete(db, skill_def)


@router.post(
    "/{skill_id}/diagnose",
    status_code=status.HTTP_200_OK,
    summary="Run Skill Diagnosis",
    description="Run diagnosis logic on a skill to evaluate its effectiveness.",
)
async def diagnose_skill(
    skill_id: int,
    context_data: dict = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Run diagnosis on a skill.
    
    Executes the diagnostic_prompt template with provided context.
    
    **Path:** `POST /api/v1/skill-definitions/{skill_id}/diagnose`
    
    **Parameters:**
    - `skill_id` (int): Skill definition ID
    - `context_data` (dict, optional): Context for diagnosis
    
    **Returns:** { success: bool, result: any, error: str (optional) }
    
    **Errors:**
    - 401: Unauthorized
    - 404: Skill definition not found
    - 500: Server error / execution error
    
    在技能上運行診斷邏輯。
    """
    skill_def = await skill_def_repo.get_by_id(db, skill_id)
    if not skill_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill definition with ID {skill_id} not found",
        )
    
    if not skill_def.diagnostic_prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No diagnostic prompt defined for this skill",
        )
    
    try:
        from datetime import datetime
        
        # Create execution context
        execution_context = {
            "context": context_data or {},
            "diagnosis_result": None,
        }
        
        # Execute diagnostic prompt as Python code
        # (In production, this would use LLM)
        exec(skill_def.diagnostic_prompt, execution_context)
        
        result = execution_context.get("diagnosis_result", "Diagnosis completed")
        
        # Store result
        skill_def.last_diagnosis_result = json.dumps(result) if result else None
        await skill_def_repo.update(db, skill_def)
        
        return {
            "success": True,
            "result": result,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@router.post(
    "/{skill_id}/execute",
    status_code=status.HTTP_200_OK,
    summary="Execute Skill",
    description="Execute a skill with provided data.",
)
async def execute_skill(
    skill_id: int,
    execution_data: dict = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Execute a skill.
    
    Executes the skill's logic with provided data.
    
    **Path:** `POST /api/v1/skill-definitions/{skill_id}/execute`
    
    **Parameters:**
    - `skill_id` (int): Skill definition ID
    - `execution_data` (dict, optional): Data for execution
    
    **Returns:** { success: bool, output: any, error: str (optional) }
    
    **Errors:**
    - 401: Unauthorized
    - 404: Skill definition not found
    - 500: Server error / execution error
    
    執行一個技能。
    """
    skill_def = await skill_def_repo.get_by_id(db, skill_id)
    if not skill_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill definition with ID {skill_id} not found",
        )
    
    try:
        # Create execution context
        execution_context = {
            "data": execution_data or {},
            "skill_output": None,
        }
        
        # Execute based on whether diagnostic prompt exists
        if skill_def.diagnostic_prompt:
            exec(skill_def.diagnostic_prompt, execution_context)
        
        output = execution_context.get("skill_output", {"status": "executed"})
        
        return {
            "success": True,
            "output": output,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@router.post(
    "/{skill_id}/bind-mcp/{mcp_id}",
    response_model=SkillDefinitionRead,
    status_code=status.HTTP_200_OK,
    summary="Bind MCP to Skill",
    description="Bind an MCP definition to a skill.",
)
async def bind_mcp_to_skill(
    skill_id: int,
    mcp_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SkillDefinitionRead:
    """
    Bind an MCP definition to a skill.
    
    Adds the MCP ID to the skill's bound MCPs list.
    
    **Path:** `POST /api/v1/skill-definitions/{skill_id}/bind-mcp/{mcp_id}`
    
    **Parameters:**
    - `skill_id` (int): Skill definition ID
    - `mcp_id` (int): MCP definition ID to bind
    
    **Returns:** Updated SkillDefinitionRead
    
    **Errors:**
    - 401: Unauthorized
    - 404: Skill or MCP not found
    - 400: MCP already bound
    - 500: Server error
    
    將 MCP 定義綁定到技能。
    """
    skill_def = await skill_def_repo.get_by_id(db, skill_id)
    if not skill_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill definition with ID {skill_id} not found",
        )
    
    try:
        mcp_ids = json.loads(skill_def.mcp_ids) if skill_def.mcp_ids else []
        
        if mcp_id in mcp_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"MCP {mcp_id} is already bound to this skill",
            )
        
        mcp_ids.append(mcp_id)
        skill_def.mcp_ids = json.dumps(mcp_ids)
        
        return await skill_def_repo.update(db, skill_def)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mcp_ids format: {str(e)}",
        )
