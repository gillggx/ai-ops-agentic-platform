"""
Items Router - Generic item management endpoints

项目路由 - 通用项目管理端点
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.api.dependencies import (
    get_db,
    get_current_user,
    get_current_active_user,
)
from app.ontology.schemas import (
    SuccessResponse,
    ErrorResponse,
    PagedResponse,
)
from app.ontology.models import User
from app.core.logger import logger


router = APIRouter(
    prefix="/items",
    tags=["items"],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Not Found"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)


# In-memory storage for demo purposes (will be replaced with DB model in Phase 1C)
# 用于演示的内存存储（将在Phase 1C中用DB模型替换）
_items_db: Dict[int, Dict[str, Any]] = {}
_item_id_counter = 1


@router.get(
    "",
    response_model=PagedResponse,
    status_code=status.HTTP_200_OK,
    summary="List Items",
    description="Get paginated list of items.",
)
async def list_items(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum items to return"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get paginated list of items.
    
    获取项目的分页列表。
    """
    try:
        items = list(_items_db.values())[skip:skip+limit]
        
        logger.info(f"Listed {len(items)} items / 列出了 {len(items)} 个项目")
        
        return {
            "success": True,
            "data": items,
            "total": len(_items_db),
            "page": (skip // limit) + 1,
            "page_size": limit,
        }
        
    except Exception as e:
        logger.error(f"Error listing items / 列出项目错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list items / 无法列出项目",
        )


@router.post(
    "",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Item",
    description="Create a new item.",
)
async def create_item(
    data: Dict[str, Any],
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Create a new item.
    
    创建新项目。
    """
    try:
        global _item_id_counter
        
        item = {
            "id": _item_id_counter,
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "metadata": data.get("metadata", {}),
            "created_at": datetime.utcnow().isoformat(),
            "created_by": str(current_user.id),
        }
        
        _items_db[_item_id_counter] = item
        _item_id_counter += 1
        
        logger.info(f"Item created: {item['id']} / 项目已创建: {item['id']}")
        
        return {
            "success": True,
            "data": item,
            "message": "Item created successfully / 项目创建成功",
        }
        
    except Exception as e:
        logger.error(f"Error creating item / 创建项目错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create item / 无法创建项目",
        )


@router.get(
    "/{item_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Item",
    description="Get item by ID.",
)
async def get_item(
    item_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get item by ID.
    
    通过ID获取项目。
    """
    try:
        if item_id not in _items_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Item not found / 未找到项目",
            )
        
        item = _items_db[item_id]
        
        return {
            "success": True,
            "data": item,
            "message": "Item retrieved / 项目已检索",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting item / 获取项目错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get item / 无法获取项目",
        )


@router.put(
    "/{item_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Item",
    description="Update item.",
)
async def update_item(
    item_id: int,
    data: Dict[str, Any],
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Update item.
    
    更新项目。
    """
    try:
        if item_id not in _items_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Item not found / 未找到项目",
            )
        
        item = _items_db[item_id]
        
        # Only creator or admin can update
        # 只有创建者或管理员可以更新
        if item.get("created_by") != str(current_user.id) and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only update your own items / 您只能更新自己的项目",
            )
        
        if "name" in data:
            item["name"] = data["name"]
        if "description" in data:
            item["description"] = data["description"]
        if "metadata" in data:
            item["metadata"] = data["metadata"]
        
        item["updated_at"] = datetime.utcnow().isoformat()
        item["updated_by"] = str(current_user.id)
        
        logger.info(f"Item updated: {item_id} / 项目已更新: {item_id}")
        
        return {
            "success": True,
            "data": item,
            "message": "Item updated successfully / 项目更新成功",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating item / 更新项目错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update item / 无法更新项目",
        )


@router.delete(
    "/{item_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Item",
    description="Delete item.",
)
async def delete_item(
    item_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Delete item.
    
    删除项目。
    """
    try:
        if item_id not in _items_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Item not found / 未找到项目",
            )
        
        item = _items_db[item_id]
        
        # Only creator or admin can delete
        # 只有创建者或管理员可以删除
        if item.get("created_by") != str(current_user.id) and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own items / 您只能删除自己的项目",
            )
        
        del _items_db[item_id]
        
        logger.info(f"Item deleted: {item_id} / 项目已删除: {item_id}")
        
        return {
            "success": True,
            "data": None,
            "message": "Item deleted successfully / 项目删除成功",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting item / 删除项目错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete item / 无法删除项目",
        )
