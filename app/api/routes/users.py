"""
User API Routes

用户 API 路由。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...ontology.schemas import UserCreate, UserRead, UserUpdate
from ...ontology.services import UserService
from ..dependencies import get_db, get_current_user

router = APIRouter(prefix="/users", tags=["users"])
user_service = UserService()


@router.post("", response_model=UserRead, status_code=201)
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    """
    Create a new user.
    
    Args:
        user_in: UserCreate - User creation data
        db: AsyncSession - Database session
    
    Returns:
        UserRead - Created user
    
    Raises:
        HTTPException: If user already exists or validation fails
    
    创建新用户。
    """
    # Check if user already exists
    existing = await user_service.get_by_username(db, user_in.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    existing = await user_service.get_by_email(db, user_in.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create user
    user = await user_service.create(db, user_in)
    await db.commit()
    return user


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    """
    Get user by ID.
    
    Args:
        user_id: int - User ID
        db: AsyncSession - Database session
    
    Returns:
        UserRead - User data
    
    Raises:
        HTTPException: If user not found
    
    按 ID 获取用户。
    """
    user = await user_service.read(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("", response_model=list[UserRead])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[UserRead]:
    """
    List all users with pagination.
    
    Args:
        skip: int - Records to skip
        limit: int - Max records to return
        db: AsyncSession - Database session
    
    Returns:
        list[UserRead] - List of users
    
    列出所有用户。
    """
    users = await user_service.list_all(db, skip=skip, limit=limit)
    return users


@router.put("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    user_in: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
) -> UserRead:
    """
    Update user.
    
    Args:
        user_id: int - User ID
        user_in: UserUpdate - Update data
        db: AsyncSession - Database session
        current_user: User - Current authenticated user
    
    Returns:
        UserRead - Updated user
    
    Raises:
        HTTPException: If user not found or unauthorized
    
    更新用户。
    """
    # Check authorization
    if current_user.id != user_id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Update user
    user = await user_service.update(db, user_id, user_in)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.commit()
    return user


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
) -> None:
    """
    Delete user.
    
    Args:
        user_id: int - User ID
        db: AsyncSession - Database session
        current_user: User - Current authenticated user
    
    Raises:
        HTTPException: If unauthorized or user not found
    
    删除用户。
    """
    # Check authorization
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only superusers can delete")

    deleted = await user_service.delete(db, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")

    await db.commit()


@router.post("/{user_id}/deactivate", response_model=UserRead)
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
) -> UserRead:
    """
    Deactivate user account.
    
    Args:
        user_id: int - User ID
        db: AsyncSession - Database session
        current_user: User - Current authenticated user
    
    Returns:
        UserRead - Updated user
    
    停用用户。
    """
    if current_user.id != user_id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")

    user = await user_service.deactivate_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.commit()
    return user


@router.post("/{user_id}/activate", response_model=UserRead)
async def activate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
) -> UserRead:
    """
    Activate user account.
    
    Args:
        user_id: int - User ID
        db: AsyncSession - Database session
        current_user: User - Current authenticated user
    
    Returns:
        UserRead - Updated user
    
    激活用户。
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only superusers can activate")

    user = await user_service.activate_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.commit()
    return user
