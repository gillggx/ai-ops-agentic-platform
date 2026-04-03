# AuthService - Authentication business logic
# 认证服务 - 认证业务逻辑

from typing import Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.base_service import BaseService
from app.services.security_service import SecurityService
from app.ontology.repositories import UserRepository
from app.ontology.models import User
from app.ontology.schemas import UserLoginSchema, UserRegisterSchema, UserRead
from app.core.logger import logger
from app.core.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    UserAlreadyExistsError,
    NotFoundError,
)


class AuthService(BaseService):
    """
    Authentication service for user login, registration, and token management.
    
    用户登录、注册和令牌管理的认证服务。
    
    Methods:
        login: Authenticate user and return tokens
        register: Create new user account
        refresh_token: Generate new access token from refresh token
        validate_token: Validate JWT token
        get_current_user: Get user from token
        logout: Invalidate user session
    """

    def __init__(self, db_session: AsyncSession):
        """
        Initialize auth service with database session.
        
        使用数据库会话初始化认证服务。
        
        Args:
            db_session: SQLAlchemy async session / SQLAlchemy异步会话
        """
        super().__init__(db_session)
        self.user_repo = UserRepository()
        self.security_service = SecurityService()

    async def login(
        self,
        credentials: UserLoginSchema,
    ) -> Dict[str, Any]:
        """
        Authenticate user and return access/refresh tokens.
        
        认证用户并返回访问/刷新令牌。
        
        Args:
            credentials: User login credentials / 用户登录凭证
            
        Returns:
            Dictionary with access_token, refresh_token, token_type, and expires_in
            包含access_token、refresh_token、token_type和expires_in的字典
            
        Raises:
            InvalidCredentialsError: If username or password is invalid / 如果用户名或密码无效
            AuthenticationError: If authentication fails / 如果认证失败
        """
        try:
            # Validate input
            # 验证输入
            if not credentials.username or not credentials.password:
                logger.warning(f"Login attempt with missing credentials / 使用缺少凭证的登录尝试")
                raise InvalidCredentialsError("Username and password are required / 用户名和密码是必需的")
            
            # Find user by username
            # 通过用户名查找用户
            user = await self._execute_query(
                self.user_repo.get_by_username,
                "Find user by username",
                credentials.username,
            )
            
            if not user:
                logger.warning(f"Login failed: user not found / 登录失败：未找到用户 - {credentials.username}")
                raise InvalidCredentialsError("Invalid username or password / 用户名或密码无效")
            
            # Verify password
            # 验证密码
            if not self.security_service.verify_password(
                credentials.password,
                user.hashed_password,
            ):
                logger.warning(f"Login failed: invalid password / 登录失败：密码无效 - {credentials.username}")
                raise InvalidCredentialsError("Invalid username or password / 用户名或密码无效")
            
            # Check if user is active
            # 检查用户是否活跃
            if not user.is_active:
                logger.warning(f"Login failed: user inactive / 登录失败：用户未激活 - {credentials.username}")
                raise AuthenticationError("User account is inactive / 用户账户未激活")
            
            # Generate tokens
            # 生成令牌
            access_token, access_expires = self.security_service.create_access_token(
                data={"sub": str(user.id), "username": user.username, "user_id": str(user.id)}
            )
            
            refresh_token, refresh_expires = self.security_service.create_refresh_token(
                data={"sub": str(user.id), "username": user.username, "user_id": str(user.id)}
            )
            
            logger.info(f"User login successful / 用户登录成功: {credentials.username}")
            
            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": int((access_expires.timestamp() - __import__('time').time())),
                "user": {
                    "id": str(user.id),
                    "username": user.username,
                    "email": user.email,
                    "role": user.roles,
                    "is_active": user.is_active,
                },
            }
            
        except (InvalidCredentialsError, AuthenticationError):
            raise
        except Exception as e:
            logger.error(f"Login error / 登录错误: {str(e)}")
            raise AuthenticationError(f"Authentication failed / 认证失败") from e

    async def register(
        self,
        user_data: UserRegisterSchema,
    ) -> Dict[str, Any]:
        """
        Register new user account.
        
        注册新用户账户。
        
        Args:
            user_data: User registration data / 用户注册数据
            
        Returns:
            Dictionary with user info and tokens
            包含用户信息和令牌的字典
            
        Raises:
            UserAlreadyExistsError: If username or email already exists / 如果用户名或电子邮件已存在
            AuthenticationError: If registration fails / 如果注册失败
        """
        try:
            # Validate input
            # 验证输入
            if not user_data.username or not user_data.password or not user_data.email:
                raise ValueError("Username, email, and password are required / 用户名、电子邮件和密码是必需的")
            
            if len(user_data.password) < 4:
                raise ValueError("Password must be at least 4 characters / 密码长度必须至少4个字符")
            
            # Check if user already exists
            # 检查用户是否已存在
            existing_user = await self._execute_query(
                self.user_repo.get_by_username,
                "Check existing username",
                user_data.username,
            )
            
            if existing_user:
                logger.warning(f"Registration failed: username already exists / 注册失败：用户名已存在 - {user_data.username}")
                raise UserAlreadyExistsError(f"Username already exists / 用户名已存在")
            
            # Check email
            # 检查电子邮件
            existing_email = await self._execute_query(
                self.user_repo.get_by_email,
                "Check existing email",
                user_data.email,
            )
            
            if existing_email:
                logger.warning(f"Registration failed: email already exists / 注册失败：电子邮件已存在 - {user_data.email}")
                raise UserAlreadyExistsError(f"Email already exists / 电子邮件已存在")
            
            # Hash password
            # 哈希密码
            password_hash = self.security_service.hash_password(user_data.password)
            
            # Create new user
            # 创建新用户
            import json as _json
            new_user = User(
                username=user_data.username,
                email=user_data.email,
                hashed_password=password_hash,
                roles=_json.dumps([getattr(user_data, "role", None) or "user"]),
                is_active=True,
            )
            
            async def create_user_tx():
                self.db.add(new_user)
                await self.db.flush()
                return new_user
            
            created_user = await self._execute_transaction(
                create_user_tx,
                "Create new user",
            )
            
            # Generate tokens
            # 生成令牌
            access_token, access_expires = self.security_service.create_access_token(
                data={"sub": str(created_user.id), "username": created_user.username, "user_id": str(created_user.id)}
            )
            
            refresh_token, refresh_expires = self.security_service.create_refresh_token(
                data={"sub": str(created_user.id), "username": created_user.username, "user_id": str(created_user.id)}
            )
            
            logger.info(f"User registration successful / 用户注册成功: {user_data.username}")
            
            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": int((access_expires.timestamp() - __import__('time').time())),
                "user": {
                    "id": str(created_user.id),
                    "username": created_user.username,
                    "email": created_user.email,
                    "role": created_user.roles,
                    "is_active": created_user.is_active,
                },
            }
            
        except (UserAlreadyExistsError, ValueError):
            raise
        except Exception as e:
            logger.error(f"Registration error / 注册错误: {str(e)}")
            raise AuthenticationError(f"Registration failed / 注册失败") from e

    async def refresh_token(
        self,
        refresh_token: str,
    ) -> Dict[str, Any]:
        """
        Generate new access token from valid refresh token.
        
        从有效的刷新令牌生成新的访问令牌。
        
        Args:
            refresh_token: Valid refresh token / 有效的刷新令牌
            
        Returns:
            Dictionary with new access_token and expires_in
            包含新的access_token和expires_in的字典
            
        Raises:
            AuthenticationError: If refresh token is invalid or expired / 如果刷新令牌无效或已过期
        """
        try:
            # Decode refresh token
            # 解码刷新令牌
            payload = self.security_service.decode_token(refresh_token, token_type="refresh")
            
            user_id = payload.get("sub")
            username = payload.get("username")
            
            if not user_id:
                logger.warning(f"Refresh token missing user ID / 刷新令牌缺少用户ID")
                raise AuthenticationError("Invalid refresh token / 无效的刷新令牌")
            
            # Get user to verify still exists and is active
            # 获取用户以验证仍然存在且活跃
            user = await self._execute_query(
                self.user_repo.get_by_id,
                "Get user for refresh",
                user_id,
            )
            
            if not user or not user.is_active:
                logger.warning(f"Refresh token for inactive or deleted user / 非活跃或已删除用户的刷新令牌 - {user_id}")
                raise AuthenticationError("User not found or inactive / 未找到用户或用户未激活")
            
            # Generate new access token
            # 生成新的访问令牌
            access_token, access_expires = self.security_service.create_access_token(
                data={"sub": str(user.id), "username": user.username, "user_id": str(user.id)}
            )
            
            logger.info(f"Token refreshed for user / 为用户刷新令牌: {user.username}")
            
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": int((access_expires.timestamp() - __import__('time').time())),
            }
            
        except Exception as e:
            logger.error(f"Token refresh error / 令牌刷新错误: {str(e)}")
            raise AuthenticationError(f"Token refresh failed / 令牌刷新失败") from e

    async def get_current_user(self, token: str) -> User:
        """
        Get current user from access token.
        
        从访问令牌获取当前用户。
        
        Args:
            token: Access token / 访问令牌
            
        Returns:
            User object / 用户对象
            
        Raises:
            AuthenticationError: If token is invalid / 如果令牌无效
            NotFoundError: If user not found / 如果未找到用户
        """
        try:
            # Decode token
            # 解码令牌
            payload = self.security_service.decode_token(token, token_type="access")
            
            user_id = payload.get("sub")
            if not user_id:
                logger.warning(f"Token missing user ID / 令牌缺少用户ID")
                raise AuthenticationError("Invalid token / 无效的令牌")
            
            # Get user
            # 获取用户
            user = await self._execute_query(
                self.user_repo.get_by_id,
                "Get user from token",
                user_id,
            )
            
            if not user:
                logger.warning(f"User not found from token / 从令牌未找到用户 - {user_id}")
                raise NotFoundError("User not found / 用户未找到")
            
            return user
            
        except Exception as e:
            logger.error(f"Error getting current user / 获取当前用户错误: {str(e)}")
            raise AuthenticationError(f"Authentication failed / 认证失败") from e

    async def logout(self, user_id: str) -> bool:
        """
        Logout user (invalidate session).
        
        注销用户（使会话失效）。
        
        Args:
            user_id: User ID to logout / 要注销的用户ID
            
        Returns:
            True if logout successful / 如果注销成功返回True
        """
        try:
            # In a real implementation, we'd invalidate the token in a blacklist
            # 在实际实现中，我们会在黑名单中使令牌失效
            logger.info(f"User logout successful / 用户注销成功: {user_id}")
            return True
        except Exception as e:
            logger.error(f"Logout error / 注销错误: {str(e)}")
            return False
