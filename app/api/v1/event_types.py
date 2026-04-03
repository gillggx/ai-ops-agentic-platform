"""
EventTypes Router - Event type management endpoints

事件类型路由 - 事件类型管理端点
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
    EventTypeCreate,
    EventTypeRead,
    SuccessResponse,
    ErrorResponse,
    PagedResponse,
)
from app.ontology.models import User
from app.ontology.repositories import EventTypeRepository
from app.core.logger import logger


router = APIRouter(
    prefix="/event-types",
    tags=["event-types"],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Not Found"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)


@router.get(
    "",
    response_model=PagedResponse,
    status_code=status.HTTP_200_OK,
    summary="List Event Types",
    description="Get list of event types.",
)
async def list_event_types(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum items to return"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get list of event types.
    
    获取事件类型列表。
    """
    try:
        repo = EventTypeRepository(db)
        event_types = await repo.get_all(skip=skip, limit=limit)
        
        logger.info(f"Listed {len(event_types)} event types / 列出了 {len(event_types)} 个事件类型")
        
        return {
            "success": True,
            "data": [
                {
                    "id": str(et.id),
                    "name": et.name,
                    "description": et.description,
                    "category": getattr(et, "category", None),
                }
                for et in event_types
            ],
            "total": len(event_types),
            "page": (skip // limit) + 1,
            "page_size": limit,
        }
        
    except Exception as e:
        logger.error(f"Error listing event types / 列出事件类型错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list event types / 无法列出事件类型",
        )


@router.post(
    "",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Event Type",
    description="Create a new event type.",
)
async def create_event_type(
    data: EventTypeCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Create a new event type.
    
    创建新事件类型。
    """
    try:
        from app.ontology.models import EventType
        
        event_type = EventType(**data.model_dump())
        db.add(event_type)
        await db.commit()
        await db.refresh(event_type)
        
        logger.info(f"Event type created: {event_type.id} / 事件类型已创建: {event_type.id}")
        
        return {
            "success": True,
            "data": {
                "id": str(event_type.id),
                "name": event_type.name,
                "description": event_type.description,
                "category": getattr(event_type, "category", None),
            },
            "message": "Event type created successfully / 事件类型创建成功",
        }
        
    except Exception as e:
        logger.error(f"Error creating event type / 创建事件类型错误: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create event type / 无法创建事件类型",
        )


@router.get(
    "/{type_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Event Type",
    description="Get event type by ID.",
)
async def get_event_type(
    type_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get event type by ID.
    
    通过ID获取事件类型。
    """
    try:
        repo = EventTypeRepository(db)
        event_type = await repo.get_by_id(int(type_id))
        
        if not event_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event type not found / 未找到事件类型",
            )
        
        return {
            "success": True,
            "data": {
                "id": str(event_type.id),
                "name": event_type.name,
                "description": event_type.description,
                "category": getattr(event_type, "category", None),
            },
            "message": "Event type retrieved / 事件类型已检索",
        }
        
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error getting event type / 获取事件类型错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get event type / 无法获取事件类型",
        )


@router.put(
    "/{type_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Event Type",
    description="Update event type.",
)
async def update_event_type(
    type_id: str,
    data: EventTypeCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Update event type.
    
    更新事件类型。
    """
    try:
        repo = EventTypeRepository(db)
        event_type = await repo.get_by_id(int(type_id))
        
        if not event_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event type not found / 未找到事件类型",
            )
        
        update_dict = data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            if hasattr(event_type, key):
                setattr(event_type, key, value)
        
        db.add(event_type)
        await db.commit()
        await db.refresh(event_type)
        
        logger.info(f"Event type updated: {type_id} / 事件类型已更新: {type_id}")
        
        return {
            "success": True,
            "data": {
                "id": str(event_type.id),
                "name": event_type.name,
                "description": event_type.description,
                "category": getattr(event_type, "category", None),
            },
            "message": "Event type updated successfully / 事件类型更新成功",
        }
        
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error updating event type / 更新事件类型错误: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update event type / 无法更新事件类型",
        )


@router.delete(
    "/{type_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Event Type",
    description="Delete event type.",
)
async def delete_event_type(
    type_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Delete event type.
    
    删除事件类型。
    """
    try:
        repo = EventTypeRepository(db)
        event_type = await repo.get_by_id(int(type_id))
        
        if not event_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event type not found / 未找到事件类型",
            )
        
        await db.delete(event_type)
        await db.commit()
        
        logger.info(f"Event type deleted: {type_id} / 事件类型已删除: {type_id}")
        
        return {
            "success": True,
            "data": None,
            "message": "Event type deleted successfully / 事件类型删除成功",
        }
        
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error deleting event type / 删除事件类型错误: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete event type / 无法删除事件类型",
        )
