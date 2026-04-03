"""
SystemParameters Router - System parameter management endpoints

系统参数路由 - 系统参数管理端点
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_db,
    get_current_active_user,
    get_current_admin,
)
from app.ontology.schemas import (
    SystemParameterCreate,
    SystemParameterRead,
    SystemParameterReadWithoutSecret,
    SystemParameterUpdate,
    SuccessResponse,
    ErrorResponse,
    PagedResponse,
)
from app.ontology.models import User
from app.ontology.repositories import SystemParameterRepository
from app.core.logger import logger


router = APIRouter(
    prefix="/system-parameters",
    tags=["system-parameters"],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not Found"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)


@router.get(
    "",
    response_model=PagedResponse,
    status_code=status.HTTP_200_OK,
    summary="List System Parameters",
    description="Get list of system parameters.",
)
async def list_system_parameters(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum items to return"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get list of system parameters.
    
    获取系统参数列表。
    """
    try:
        repo = SystemParameterRepository(db)
        params = await repo.get_all(skip=skip, limit=limit)
        
        logger.info(f"Listed {len(params)} system parameters / 列出了 {len(params)} 个系统参数")
        
        return {
            "success": True,
            "data": [
                {
                    "id": str(p.id),
                    "key": p.key,
                    "value": p.value if not p.is_secret else "***",
                    "is_secret": p.is_secret,
                    "description": p.description,
                }
                for p in params
            ],
            "total": len(params),
            "page": (skip // limit) + 1,
            "page_size": limit,
        }
        
    except Exception as e:
        logger.error(f"Error listing system parameters / 列出系统参数错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list system parameters / 无法列出系统参数",
        )


@router.post(
    "",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create System Parameter",
    description="Create a new system parameter (admin only).",
)
async def create_system_parameter(
    data: SystemParameterCreate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Create a new system parameter.
    
    创建新系统参数。
    """
    try:
        from app.ontology.models import SystemParameter
        
        param = SystemParameter(**data.model_dump())
        db.add(param)
        await db.commit()
        await db.refresh(param)
        
        logger.info(f"System parameter created: {param.key} / 系统参数已创建: {param.key}")
        
        return {
            "success": True,
            "data": {
                "id": str(param.id),
                "key": param.key,
                "value": param.value if not param.is_secret else "***",
                "is_secret": param.is_secret,
                "description": param.description,
            },
            "message": "System parameter created successfully / 系统参数创建成功",
        }
        
    except Exception as e:
        logger.error(f"Error creating system parameter / 创建系统参数错误: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create system parameter / 无法创建系统参数",
        )


@router.get(
    "/{param_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get System Parameter",
    description="Get system parameter by ID.",
)
async def get_system_parameter(
    param_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get system parameter by ID.
    
    通过ID获取系统参数。
    """
    try:
        repo = SystemParameterRepository(db)
        param = await repo.get_by_id(int(param_id))
        
        if not param:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="System parameter not found / 未找到系统参数",
            )
        
        return {
            "success": True,
            "data": {
                "id": str(param.id),
                "key": param.key,
                "value": param.value if not param.is_secret else "***",
                "is_secret": param.is_secret,
                "description": param.description,
            },
            "message": "System parameter retrieved / 系统参数已检索",
        }
        
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error getting system parameter / 获取系统参数错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get system parameter / 无法获取系统参数",
        )


@router.put(
    "/{param_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update System Parameter",
    description="Update system parameter (admin only).",
)
async def update_system_parameter(
    param_id: str,
    data: SystemParameterUpdate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Update system parameter.
    
    更新系统参数。
    """
    try:
        repo = SystemParameterRepository(db)
        param = await repo.get_by_id(int(param_id))
        
        if not param:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="System parameter not found / 未找到系统参数",
            )
        
        update_dict = data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            if hasattr(param, key):
                setattr(param, key, value)
        
        db.add(param)
        await db.commit()
        await db.refresh(param)
        
        logger.info(f"System parameter updated: {param_id} / 系统参数已更新: {param_id}")
        
        return {
            "success": True,
            "data": {
                "id": str(param.id),
                "key": param.key,
                "value": param.value if not param.is_secret else "***",
                "is_secret": param.is_secret,
                "description": param.description,
            },
            "message": "System parameter updated successfully / 系统参数更新成功",
        }
        
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error updating system parameter / 更新系统参数错误: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update system parameter / 无法更新系统参数",
        )


@router.delete(
    "/{param_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete System Parameter",
    description="Delete system parameter (admin only).",
)
async def delete_system_parameter(
    param_id: str,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Delete system parameter.
    
    删除系统参数。
    """
    try:
        repo = SystemParameterRepository(db)
        param = await repo.get_by_id(int(param_id))
        
        if not param:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="System parameter not found / 未找到系统参数",
            )
        
        await db.delete(param)
        await db.commit()
        
        logger.info(f"System parameter deleted: {param_id} / 系统参数已删除: {param_id}")
        
        return {
            "success": True,
            "data": None,
            "message": "System parameter deleted successfully / 系统参数删除成功",
        }
        
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error deleting system parameter / 删除系统参数错误: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete system parameter / 无法删除系统参数",
        )
