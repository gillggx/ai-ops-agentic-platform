"""
Auth Router - Authentication endpoints

认证路由 - 认证端点
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_db,
    get_current_user,
    get_current_active_user,
)
from app.services.auth_service import AuthService
from app.ontology.schemas import (
    UserLoginSchema,
    UserRegisterSchema,
    UserRead,
    SuccessResponse,
    ErrorResponse,
)
from app.ontology.models import User
from app.core.logger import logger
from app.core.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    UserAlreadyExistsError,
)


router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Not Found"},
        409: {"model": ErrorResponse, "description": "Conflict"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)


@router.post(
    "/login",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="User Login",
    description="Authenticate user with username and password, return access and refresh tokens.",
)
async def login(
    credentials: UserLoginSchema,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Authenticate user and return tokens.
    
    认证用户并返回令牌。
    
    Args:
        credentials: User login credentials (username, password) / 用户登录凭证
        db: Database session / 数据库会话
        
    Returns:
        Success response with access_token, refresh_token, token_type, expires_in, and user info
        包含access_token、refresh_token、token_type、expires_in和用户信息的成功响应
        
    Raises:
        HTTPException 401: If credentials are invalid / 如果凭证无效
        HTTPException 403: If user account is inactive / 如果用户账户未激活
    """
    try:
        auth_service = AuthService(db)
        result = await auth_service.login(credentials)
        
        logger.info(f"User logged in successfully / 用户登录成功: {credentials.username}")
        
        return {
            "success": True,
            "data": result,
            "message": "Login successful / 登录成功",
        }
        
    except InvalidCredentialsError as e:
        logger.warning(f"Login failed: invalid credentials / 登录失败：无效凭证")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password / 用户名或密码无效",
        )
    except AuthenticationError as e:
        logger.warning(f"Login failed: authentication error / 登录失败：认证错误 - {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Login error / 登录错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed / 登录失败",
        )


@router.post(
    "/register",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="User Registration",
    description="Register new user account with username, email, and password.",
)
async def register(
    user_data: UserRegisterSchema,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Register new user account.
    
    注册新用户账户。
    
    Args:
        user_data: User registration data (username, email, password, role) / 用户注册数据
        db: Database session / 数据库会话
        
    Returns:
        Success response with access_token, refresh_token, token_type, expires_in, and user info
        包含access_token、refresh_token、token_type、expires_in和用户信息的成功响应
        
    Raises:
        HTTPException 400: If password is too short or required fields missing / 如果密码太短或缺少必需字段
        HTTPException 409: If username or email already exists / 如果用户名或电子邮件已存在
    """
    try:
        auth_service = AuthService(db)
        result = await auth_service.register(user_data)
        
        logger.info(f"User registered successfully / 用户注册成功: {user_data.username}")
        
        return {
            "success": True,
            "data": result,
            "message": "Registration successful / 注册成功",
        }
        
    except UserAlreadyExistsError as e:
        logger.warning(f"Registration failed: user exists / 注册失败：用户已存在 - {user_data.username}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except ValueError as e:
        logger.warning(f"Registration failed: validation error / 注册失败：验证错误 - {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Registration error / 注册错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed / 注册失败",
        )


@router.post(
    "/refresh",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh Token",
    description="Generate new access token from valid refresh token.",
)
async def refresh(
    request_data: Dict[str, str] = None,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Generate new access token from refresh token.
    
    从刷新令牌生成新的访问令牌。
    
    Args:
        request_data: Dictionary with refresh_token / 包含refresh_token的字典
        db: Database session / 数据库会话
        
    Returns:
        Success response with new access_token, token_type, and expires_in
        包含新的access_token、token_type和expires_in的成功响应
        
    Raises:
        HTTPException 400: If refresh_token is missing / 如果缺少refresh_token
        HTTPException 401: If refresh_token is invalid or expired / 如果refresh_token无效或已过期
    """
    try:
        if not request_data or "refresh_token" not in request_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="refresh_token is required / 需要refresh_token",
            )
        
        refresh_token = request_data["refresh_token"]
        auth_service = AuthService(db)
        result = await auth_service.refresh_token(refresh_token)
        
        logger.info(f"Token refreshed successfully / 令牌刷新成功")
        
        return {
            "success": True,
            "data": result,
            "message": "Token refreshed / 令牌已刷新",
        }
        
    except AuthenticationError as e:
        logger.warning(f"Token refresh failed / 令牌刷新失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Token refresh error / 令牌刷新错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed / 令牌刷新失败",
        )


@router.get(
    "/me",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Current User",
    description="Get current authenticated user information.",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Get current authenticated user information.
    
    获取当前认证用户信息。
    
    Args:
        current_user: Current authenticated user from JWT token / 来自JWT令牌的当前认证用户
        
    Returns:
        Success response with current user information
        包含当前用户信息的成功响应
        
    Raises:
        HTTPException 401: If not authenticated / 如果未认证
        HTTPException 403: If user is inactive / 如果用户未激活
    """
    try:
        user_data = {
            "id": str(current_user.id),
            "username": current_user.username,
            "email": current_user.email,
            "role": current_user.role,
            "is_active": current_user.is_active,
            "created_at": current_user.created_at.isoformat() if hasattr(current_user, 'created_at') else None,
            "updated_at": current_user.updated_at.isoformat() if hasattr(current_user, 'updated_at') else None,
        }
        
        logger.debug(f"Retrieved current user info / 检索当前用户信息: {current_user.username}")
        
        return {
            "success": True,
            "data": user_data,
            "message": "User information retrieved / 用户信息已检索",
        }
        
    except Exception as e:
        logger.error(f"Error getting user info / 获取用户信息错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user information / 无法检索用户信息",
        )


@router.post(
    "/logout",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="User Logout",
    description="Logout current user and invalidate session.",
)
async def logout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Logout user and invalidate session.
    
    注销用户并使会话失效。
    
    Args:
        current_user: Current authenticated user / 当前认证用户
        db: Database session / 数据库会话
        
    Returns:
        Success response confirming logout
        确认注销的成功响应
        
    Raises:
        HTTPException 401: If not authenticated / 如果未认证
    """
    try:
        auth_service = AuthService(db)
        await auth_service.logout(str(current_user.id))
        
        logger.info(f"User logged out successfully / 用户注销成功: {current_user.username}")
        
        return {
            "success": True,
            "data": None,
            "message": "Logout successful / 注销成功",
        }
        
    except Exception as e:
        logger.error(f"Logout error / 注销错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed / 注销失败",
        )
