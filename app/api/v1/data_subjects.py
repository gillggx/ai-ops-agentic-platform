"""
DataSubjects Router - Data subject management endpoints

数据主体路由 - 数据主体管理端点
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_db,
    get_current_user,
    get_current_active_user,
)
from app.ontology.schemas import (
    DataSubjectCreate,
    DataSubjectRead,
    DataSubjectUpdate,
    SuccessResponse,
    ErrorResponse,
    PagedResponse,
)
from app.ontology.models import User
from app.ontology.repositories import DataSubjectRepository
from app.core.logger import logger


router = APIRouter(
    prefix="/data-subjects",
    tags=["data-subjects"],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Not Found"},
        409: {"model": ErrorResponse, "description": "Conflict"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)


@router.get(
    "",
    response_model=PagedResponse,
    status_code=status.HTTP_200_OK,
    summary="List Data Subjects",
    description="Get paginated list of data subjects.",
)
async def list_data_subjects(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum items to return"),
    category: Optional[str] = Query(None, description="Filter by category"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get paginated list of data subjects.
    
    获取数据主体的分页列表。
    
    Args:
        skip: Number of items to skip / 要跳过的项目数
        limit: Maximum items to return / 返回的最大项目数
        category: Filter by category / 按类别筛选
        current_user: Current authenticated user / 当前认证用户
        db: Database session / 数据库会话
        
    Returns:
        Paginated response with data subjects
        包含数据主体的分页响应
    """
    try:
        repo = DataSubjectRepository(db)
        subjects = await repo.get_all(skip=skip, limit=limit)
        
        if category:
            subjects = [s for s in subjects if s.category == category]
        
        logger.info(f"Listed {len(subjects)} data subjects / 列出了 {len(subjects)} 个数据主体")
        
        return {
            "success": True,
            "data": [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "category": s.category,
                    "external_id": s.external_id,
                    "metadata": s.custom_metadata or {},
                }
                for s in subjects
            ],
            "total": len(subjects),
            "page": (skip // limit) + 1,
            "page_size": limit,
        }
        
    except Exception as e:
        logger.error(f"Error listing data subjects / 列出数据主体错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list data subjects / 无法列出数据主体",
        )


@router.post(
    "",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Data Subject",
    description="Create a new data subject.",
)
async def create_data_subject(
    data: DataSubjectCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Create a new data subject.
    
    创建新数据主体。
    
    Args:
        data: Data subject creation data / 数据主体创建数据
        current_user: Current authenticated user / 当前认证用户
        db: Database session / 数据库会话
        
    Returns:
        Success response with created data subject
        包含创建的数据主体的成功响应
    """
    try:
        from app.ontology.models import DataSubject
        
        subject = DataSubject(**data.model_dump())
        db.add(subject)
        await db.commit()
        await db.refresh(subject)
        
        logger.info(f"Data subject created: {subject.id} / 数据主体已创建: {subject.id}")
        
        return {
            "success": True,
            "data": {
                "id": str(subject.id),
                "name": subject.name,
                "category": subject.category,
                "external_id": subject.external_id,
                "metadata": subject.custom_metadata or {},
            },
            "message": "Data subject created successfully / 数据主体创建成功",
        }
        
    except Exception as e:
        logger.error(f"Error creating data subject / 创建数据主体错误: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create data subject / 无法创建数据主体",
        )


@router.get(
    "/{subject_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Data Subject",
    description="Get data subject by ID.",
)
async def get_data_subject(
    subject_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get data subject by ID.
    
    通过ID获取数据主体。
    """
    try:
        repo = DataSubjectRepository(db)
        subject = await repo.get_by_id(int(subject_id))
        
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Data subject not found / 未找到数据主体",
            )
        
        return {
            "success": True,
            "data": {
                "id": str(subject.id),
                "name": subject.name,
                "category": subject.category,
                "external_id": subject.external_id,
                "metadata": subject.custom_metadata or {},
            },
            "message": "Data subject retrieved / 数据主体已检索",
        }
        
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error getting data subject / 获取数据主体错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get data subject / 无法获取数据主体",
        )


@router.put(
    "/{subject_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Data Subject",
    description="Update data subject.",
)
async def update_data_subject(
    subject_id: str,
    data: DataSubjectUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Update data subject.
    
    更新数据主体。
    """
    try:
        repo = DataSubjectRepository(db)
        subject = await repo.get_by_id(int(subject_id))
        
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Data subject not found / 未找到数据主体",
            )
        
        update_dict = data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            if hasattr(subject, key):
                setattr(subject, key, value)
        
        db.add(subject)
        await db.commit()
        await db.refresh(subject)
        
        logger.info(f"Data subject updated: {subject_id} / 数据主体已更新: {subject_id}")
        
        return {
            "success": True,
            "data": {
                "id": str(subject.id),
                "name": subject.name,
                "category": subject.category,
                "external_id": subject.external_id,
                "metadata": subject.custom_metadata or {},
            },
            "message": "Data subject updated successfully / 数据主体更新成功",
        }
        
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error updating data subject / 更新数据主体错误: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update data subject / 无法更新数据主体",
        )


@router.delete(
    "/{subject_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Data Subject",
    description="Delete data subject.",
)
async def delete_data_subject(
    subject_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Delete data subject.
    
    删除数据主体。
    """
    try:
        repo = DataSubjectRepository(db)
        subject = await repo.get_by_id(int(subject_id))
        
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Data subject not found / 未找到数据主体",
            )
        
        await db.delete(subject)
        await db.commit()
        
        logger.info(f"Data subject deleted: {subject_id} / 数据主体已删除: {subject_id}")
        
        return {
            "success": True,
            "data": None,
            "message": "Data subject deleted successfully / 数据主体删除成功",
        }
        
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error deleting data subject / 删除数据主体错误: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete data subject / 无法删除数据主体",
        )
