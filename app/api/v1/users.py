"""
Users Router - User management CRUD endpoints

用户路由 - 用户管理CRUD端点
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_db,
    get_current_user,
    get_current_active_user,
    get_current_admin,
)
from app.services.auth_service import AuthService
from app.services.security_service import SecurityService
from app.ontology.schemas import (
    UserCreate,
    UserRead,
    UserUpdate,
    SuccessResponse,
    ErrorResponse,
    PagedResponse,
)
from app.ontology.models import User
from app.ontology.repositories import UserRepository
from app.core.logger import logger
from app.core.exceptions import NotFoundError, ValidationError, ServiceError


router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not Found"},
        409: {"model": ErrorResponse, "description": "Conflict"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)


@router.get(
    "",
    response_model=PagedResponse,
    status_code=status.HTTP_200_OK,
    summary="List Users",
    description="Get paginated list of all users (admin only).",
)
async def list_users(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum items to return"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    role: Optional[str] = Query(None, description="Filter by role"),
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get paginated list of all users.
    
    获取所有用户的分页列表。
    
    Args:
        skip: Number of items to skip / 要跳过的项目数
        limit: Maximum items to return / 返回的最大项目数
        is_active: Filter by active status / 按活跃状态筛选
        role: Filter by role / 按角色筛选
        current_user: Current admin user / 当前管理员用户
        db: Database session / 数据库会话
        
    Returns:
        Paginated response with user list
        包含用户列表的分页响应
        
    Raises:
        HTTPException 401: If not authenticated / 如果未认证
        HTTPException 403: If not admin / 如果不是管理员
    """
    try:
        user_repo = UserRepository(db)
        
        # Get total count
        # 获取总计数
        total = await user_repo.count()
        
        # Get paginated results
        # 获取分页结果
        users = await user_repo.get_all(skip=skip, limit=limit)
        
        # Filter by is_active if specified
        # 如果指定，则按is_active筛选
        if is_active is not None:
            users = [u for u in users if u.is_active == is_active]
        
        # Filter by role if specified
        # 如果指定，则按role筛选
        if role is not None:
            users = [u for u in users if role in (u.roles or "")]
        
        logger.info(f"Listed {len(users)} users / 列出了 {len(users)} 个用户")
        
        return {
            "success": True,
            "data": [
                {
                    "id": str(u.id),
                    "username": u.username,
                    "email": u.email,
                    "role": u.roles,
                    "is_active": u.is_active,
                    "created_at": u.created_at.isoformat() if hasattr(u, 'created_at') else None,
                    "updated_at": u.updated_at.isoformat() if hasattr(u, 'updated_at') else None,
                }
                for u in users
            ],
            "total": len(users),
            "page": (skip // limit) + 1,
            "page_size": limit,
        }
        
    except Exception as e:
        logger.error(f"Error listing users / 列出用户错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list users / 无法列出用户",
        )


@router.get(
    "/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get User",
    description="Get user by ID.",
)
async def get_user(
    user_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get user by ID.
    
    通过ID获取用户。
    
    Args:
        user_id: User ID / 用户ID
        current_user: Current authenticated user / 当前认证用户
        db: Database session / 数据库会话
        
    Returns:
        Success response with user data
        包含用户数据的成功响应
        
    Raises:
        HTTPException 401: If not authenticated / 如果未认证
        HTTPException 404: If user not found / 如果未找到用户
    """
    try:
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(int(user_id))
        
        if not user:
            logger.warning(f"User not found / 未找到用户: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found / 未找到用户",
            )
        
        return {
            "success": True,
            "data": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "role": user.roles,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat() if hasattr(user, 'created_at') else None,
                "updated_at": user.updated_at.isoformat() if hasattr(user, 'updated_at') else None,
            },
            "message": "User retrieved / 用户已检索",
        }
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format / 无效的用户ID格式",
        )
    except Exception as e:
        logger.error(f"Error getting user / 获取用户错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user / 无法获取用户",
        )


@router.put(
    "/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update User",
    description="Update user information.",
)
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Update user information.
    
    更新用户信息。
    
    Args:
        user_id: User ID / 用户ID
        user_data: Updated user data / 更新的用户数据
        current_user: Current authenticated user / 当前认证用户
        db: Database session / 数据库会话
        
    Returns:
        Success response with updated user data
        包含更新的用户数据的成功响应
        
    Raises:
        HTTPException 401: If not authenticated / 如果未认证
        HTTPException 403: If not user's own profile or admin / 如果不是用户自己的资料或管理员
        HTTPException 404: If user not found / 如果未找到用户
    """
    try:
        user_id_int = int(user_id)
        
        # Check if user is updating own profile or is admin
        # 检查用户是否在更新自己的资料或是管理员
        if str(current_user.id) != user_id and not current_user.is_superuser:
            logger.warning(f"Unauthorized user update attempt / 未授权的用户更新尝试: {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only update your own profile / 您只能更新自己的资料",
            )
        
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(user_id_int)
        
        if not user:
            logger.warning(f"User not found for update / 未找到要更新的用户: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found / 未找到用户",
            )
        
        # Prepare update data
        # 准备更新数据
        update_dict = user_data.model_dump(exclude_unset=True)
        
        # Hash password if updating
        # 如果更新密码，则进行哈希
        if "password" in update_dict and update_dict["password"]:
            if len(update_dict["password"]) < 6:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password must be at least 6 characters / 密码长度必须至少6个字符",
                )
            security_service = SecurityService()
            update_dict["password_hash"] = security_service.hash_password(update_dict["password"])
            del update_dict["password"]
        
        # Update user
        # 更新用户
        for key, value in update_dict.items():
            if hasattr(user, key):
                setattr(user, key, value)
        
        db.add(user)
        await db.commit()
        await db.refresh(user)
        
        logger.info(f"User updated successfully / 用户更新成功: {user_id}")
        
        return {
            "success": True,
            "data": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "role": user.roles,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat() if hasattr(user, 'created_at') else None,
                "updated_at": user.updated_at.isoformat() if hasattr(user, 'updated_at') else None,
            },
            "message": "User updated successfully / 用户已成功更新",
        }
        
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format / 无效的用户ID格式",
        )
    except Exception as e:
        logger.error(f"Error updating user / 更新用户错误: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user / 无法更新用户",
        )


@router.delete(
    "/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete User",
    description="Delete user (admin only).",
)
async def delete_user(
    user_id: str,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Delete user.
    
    删除用户。
    
    Args:
        user_id: User ID / 用户ID
        current_user: Current admin user / 当前管理员用户
        db: Database session / 数据库会话
        
    Returns:
        Success response confirming deletion
        确认删除的成功响应
        
    Raises:
        HTTPException 401: If not authenticated / 如果未认证
        HTTPException 403: If not admin / 如果不是管理员
        HTTPException 404: If user not found / 如果未找到用户
    """
    try:
        user_id_int = int(user_id)
        
        # Don't allow deleting self
        # 不允许删除自己
        if str(current_user.id) == user_id:
            logger.warning(f"User attempted self-deletion / 用户尝试自我删除: {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete your own account / 无法删除您自己的账户",
            )
        
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(user_id_int)
        
        if not user:
            logger.warning(f"User not found for deletion / 未找到要删除的用户: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found / 未找到用户",
            )
        
        # Delete user
        # 删除用户
        await db.delete(user)
        await db.commit()
        
        logger.info(f"User deleted successfully / 用户删除成功: {user_id}")
        
        return {
            "success": True,
            "data": None,
            "message": "User deleted successfully / 用户已成功删除",
        }
        
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format / 无效的用户ID格式",
        )
    except Exception as e:
        logger.error(f"Error deleting user / 删除用户错误: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user / 无法删除用户",
        )
