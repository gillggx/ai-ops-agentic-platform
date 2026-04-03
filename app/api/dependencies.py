"""
API Dependencies - Dependency injection for FastAPI endpoints

API 依赖 - FastAPI端点的依赖注入
"""

from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.services.auth_service import AuthService
from app.services.security_service import SecurityService
from app.ontology.models import User
from app.core.logger import logger
from app.core.exceptions import (
    AuthenticationError,
    InvalidTokenError,
    TokenExpiredError,
)


# Security scheme for OpenAPI documentation
# OpenAPI文档的安全方案
security = HTTPBearer(description="JWT token in Authorization header")


async def get_db() -> AsyncSession:
    """
    Get database session dependency.
    
    获取数据库会话依赖。
    
    Returns:
        AsyncSession: Database session / 数据库会话
        
    Yields:
        AsyncSession: Async database session / 异步数据库会话
    """
    async for session in get_async_session():
        yield session


async def get_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """
    Extract JWT token from Authorization header.
    
    从Authorization标头中提取JWT令牌。
    
    Args:
        credentials: HTTP Bearer credentials / HTTP Bearer凭证
        
    Returns:
        str: JWT token / JWT令牌
        
    Raises:
        HTTPException: If token is missing or invalid format / 如果令牌缺失或格式无效
    """
    if not credentials.credentials:
        logger.warning("Request missing authorization token / 请求缺少授权令牌")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token / 缺少授权令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return credentials.credentials


async def get_current_user(
    token: str = Depends(get_token),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Get current authenticated user from JWT token.
    
    从JWT令牌获取当前认证用户。
    
    Args:
        token: JWT token from Authorization header / 来自Authorization标头的JWT令牌
        db: Database session / 数据库会话
        
    Returns:
        User: Authenticated user / 认证用户
        
    Raises:
        HTTPException: If token is invalid, expired, or user not found
                      如果令牌无效、已过期或未找到用户
    """
    try:
        # Validate token
        # 验证令牌
        security_service = SecurityService()
        payload = security_service.decode_token(token, token_type="access")
        
        user_id = payload.get("sub")
        if not user_id:
            logger.warning("Token missing user ID / 令牌缺少用户ID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token / 无效的令牌",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Get user from database
        # 从数据库获取用户
        auth_service = AuthService(db)
        user = await auth_service.get_current_user(token)
        
        if not user:
            logger.warning(f"User not found from token / 从令牌未找到用户 - {user_id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found / 用户未找到",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return user
        
    except TokenExpiredError:
        logger.warning("Token has expired / 令牌已过期")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired / 令牌已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError as e:
        logger.warning(f"Invalid token / 无效的令牌: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token / 无效的令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except AuthenticationError as e:
        logger.warning(f"Authentication error / 认证错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed / 认证失败",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.error(f"Error getting current user / 获取当前用户错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error / 内部服务器错误",
        )


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Get current active user (user must be active).
    
    获取当前活跃用户（用户必须活跃）。
    
    Args:
        current_user: Current authenticated user / 当前认证用户
        
    Returns:
        User: Active user / 活跃用户
        
    Raises:
        HTTPException: If user is inactive / 如果用户未激活
    """
    if not current_user.is_active:
        logger.warning(f"Attempt to use inactive user / 尝试使用未激活用户 - {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive / 用户账户未激活",
        )
    return current_user


async def get_current_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Get current admin user (user must have admin role).
    
    获取当前管理员用户（用户必须具有管理员角色）。
    
    Args:
        current_user: Current active user / 当前活跃用户
        
    Returns:
        User: Admin user / 管理员用户
        
    Raises:
        HTTPException: If user doesn't have admin role / 如果用户没有管理员角色
    """
    if not current_user.is_superuser:
        logger.warning(f"Unauthorized admin access attempt / 未授权的管理员访问尝试 - {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required / 需要管理员权限",
        )
    return current_user


async def get_optional_user(
    token: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Get current user if token is provided, otherwise return None.
    
    如果提供了令牌，获取当前用户；否则返回None。
    
    Args:
        token: Optional JWT token / 可选的JWT令牌
        db: Database session / 数据库会话
        
    Returns:
        User or None: User if authenticated, None otherwise / 如果认证则返回用户，否则返回None
    """
    if not token:
        return None
    
    try:
        security_service = SecurityService()
        payload = security_service.decode_token(token, token_type="access")
        user_id = payload.get("sub")
        
        if not user_id:
            return None
        
        auth_service = AuthService(db)
        user = await auth_service.get_current_user(token)
        return user if user and user.is_active else None
        
    except Exception as e:
        logger.debug(f"Optional user extraction failed / 可选用户提取失败: {str(e)}")
        return None
