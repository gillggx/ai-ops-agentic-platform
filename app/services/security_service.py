# SecurityService - JWT & Password Hashing
# 安全服务 - JWT和密码哈希

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import bcrypt as _bcrypt
from jose import jwt, JWTError
from app.core.constants import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRATION_HOURS
from app.core.logger import logger
from app.core.exceptions import (
    AuthenticationError,
    TokenExpiredError,
    InvalidTokenError,
    InsufficientPermissionsError,
)


# Use bcrypt directly — passlib 1.7.4 is incompatible with bcrypt >= 4.x
def _hash(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt(rounds=12)).decode()

def _verify(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


class SecurityService:
    """
    Service for cryptographic operations: JWT token generation/validation, password hashing.
    
    加密操作服务：JWT令牌生成/验证、密码哈希。
    
    Methods:
        hash_password: Hash password using bcrypt
        verify_password: Verify password against hash
        create_access_token: Create JWT access token
        create_refresh_token: Create JWT refresh token
        decode_token: Decode and validate JWT token
        get_token_expiration: Get token expiration time
    """

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash password using bcrypt.
        
        使用bcrypt哈希密码。
        
        Args:
            password: Plain text password / 纯文本密码
            
        Returns:
            Hashed password / 哈希后的密码
            
        Raises:
            ValueError: If password is invalid / 如果密码无效
        """
        if not password or len(password) < 4:
            raise ValueError("Password must be at least 4 characters long / 密码长度必须至少4个字符")
        
        try:
            hashed = _hash(password)
            logger.debug(f"Password hashed successfully / 密码哈希成功")
            return hashed
        except Exception as e:
            logger.error(f"Error hashing password / 密码哈希出错: {str(e)}")
            raise ValueError(f"Password hashing failed / 密码哈希失败") from e

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Verify plain password against hash using bcrypt.
        
        使用bcrypt验证纯文本密码与哈希值。
        
        Args:
            plain_password: Plain text password / 纯文本密码
            hashed_password: Hashed password from database / 来自数据库的哈希密码
            
        Returns:
            True if password matches, False otherwise / 密码匹配返回True，否则返回False
        """
        if not plain_password or not hashed_password:
            return False
        
        try:
            is_valid = _verify(plain_password, hashed_password)
            if is_valid:
                logger.debug(f"Password verified successfully / 密码验证成功")
            else:
                logger.warning(f"Password verification failed / 密码验证失败")
            return is_valid
        except Exception as e:
            logger.error(f"Error verifying password / 密码验证出错: {str(e)}")
            return False

    @staticmethod
    def create_access_token(
        data: Dict[str, Any],
        expires_delta: Optional[timedelta] = None,
    ) -> tuple[str, datetime]:
        """
        Create JWT access token.
        
        创建JWT访问令牌。
        
        Args:
            data: Payload data to encode / 要编码的有效负载数据
            expires_delta: Custom expiration time / 自定义过期时间
            
        Returns:
            Tuple of (token, expiration_datetime) / (令牌，过期时间)的元组
            
        Raises:
            ValueError: If token creation fails / 如果令牌创建失败
        """
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
        
        to_encode.update({"exp": expire, "type": "access"})
        
        try:
            encoded_jwt = jwt.encode(
                to_encode,
                JWT_SECRET_KEY,
                algorithm=JWT_ALGORITHM,
            )
            logger.info(f"Access token created for user {data.get('sub')} / 为用户 {data.get('sub')} 创建访问令牌")
            return encoded_jwt, expire
        except Exception as e:
            logger.error(f"Error creating access token / 创建访问令牌出错: {str(e)}")
            raise ValueError(f"Token creation failed / 令牌创建失败") from e

    @staticmethod
    def create_refresh_token(
        data: Dict[str, Any],
        expires_delta: Optional[timedelta] = None,
    ) -> tuple[str, datetime]:
        """
        Create JWT refresh token (longer expiration).
        
        创建JWT刷新令牌（更长的过期时间）。
        
        Args:
            data: Payload data to encode / 要编码的有效负载数据
            expires_delta: Custom expiration time / 自定义过期时间
            
        Returns:
            Tuple of (token, expiration_datetime) / (令牌，过期时间)的元组
            
        Raises:
            ValueError: If token creation fails / 如果令牌创建失败
        """
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            # Refresh token expires in 7 days
            # 刷新令牌在7天后过期
            expire = datetime.now(timezone.utc) + timedelta(days=7)
        
        to_encode.update({"exp": expire, "type": "refresh"})
        
        try:
            encoded_jwt = jwt.encode(
                to_encode,
                JWT_SECRET_KEY,
                algorithm=JWT_ALGORITHM,
            )
            logger.info(f"Refresh token created for user {data.get('sub')} / 为用户 {data.get('sub')} 创建刷新令牌")
            return encoded_jwt, expire
        except Exception as e:
            logger.error(f"Error creating refresh token / 创建刷新令牌出错: {str(e)}")
            raise ValueError(f"Refresh token creation failed / 刷新令牌创建失败") from e

    @staticmethod
    def decode_token(token: str, token_type: str = "access") -> Dict[str, Any]:
        """
        Decode and validate JWT token.
        
        解码并验证JWT令牌。
        
        Args:
            token: JWT token to decode / 要解码的JWT令牌
            token_type: Expected token type ('access' or 'refresh') / 期望的令牌类型
            
        Returns:
            Decoded payload / 解码的有效负载
            
        Raises:
            InvalidTokenError: If token is invalid / 如果令牌无效
            TokenExpiredError: If token has expired / 如果令牌已过期
            InsufficientPermissionsError: If token type doesn't match / 如果令牌类型不匹配
        """
        if not token:
            logger.warning("Empty token provided / 提供了空令牌")
            raise InvalidTokenError("Token is required / 需要令牌")
        
        try:
            payload = jwt.decode(
                token,
                JWT_SECRET_KEY,
                algorithms=[JWT_ALGORITHM],
            )
            
            # Verify token type
            # 验证令牌类型
            if payload.get("type") != token_type:
                logger.warning(f"Token type mismatch: expected {token_type}, got {payload.get('type')} / 令牌类型不匹配")
                raise InsufficientPermissionsError(f"Invalid token type / 无效的令牌类型")
            
            return payload
            
        except JWTError as e:
            if "expired" in str(e).lower():
                logger.warning(f"Token expired / 令牌已过期")
                raise TokenExpiredError("Token has expired / 令牌已过期") from None
            else:
                logger.warning(f"Invalid token / 无效的令牌: {str(e)}")
                raise InvalidTokenError("Invalid token / 无效的令牌") from e
        except Exception as e:
            logger.error(f"Error decoding token / 解码令牌出错: {str(e)}")
            raise InvalidTokenError("Token validation failed / 令牌验证失败") from e

    @staticmethod
    def get_token_expiration(token: str) -> Optional[datetime]:
        """
        Get token expiration time without full validation.
        
        不进行完全验证而获取令牌过期时间。
        
        Args:
            token: JWT token / JWT令牌
            
        Returns:
            Expiration datetime or None if invalid / 过期时间或无效令牌时为None
        """
        try:
            payload = jwt.decode(
                token,
                JWT_SECRET_KEY,
                algorithms=[JWT_ALGORITHM],
            )
            exp_timestamp = payload.get("exp")
            if exp_timestamp:
                return datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
            return None
        except Exception as e:
            logger.debug(f"Error getting token expiration / 获取令牌过期时间出错: {str(e)}")
            return None

    @staticmethod
    def refresh_access_token(refresh_token: str, user_id: str) -> tuple[str, datetime]:
        """
        Create new access token from refresh token.
        
        从刷新令牌创建新的访问令牌。
        
        Args:
            refresh_token: Valid refresh token / 有效的刷新令牌
            user_id: User ID / 用户ID
            
        Returns:
            Tuple of (new_access_token, expiration) / (新访问令牌，过期时间)的元组
            
        Raises:
            TokenExpiredError: If refresh token is expired / 如果刷新令牌已过期
            InvalidTokenError: If refresh token is invalid / 如果刷新令牌无效
        """
        # Validate refresh token
        # 验证刷新令牌
        payload = SecurityService.decode_token(refresh_token, token_type="refresh")
        
        # Create new access token with same user_id
        # 使用相同的user_id创建新的访问令牌
        return SecurityService.create_access_token(
            data={"sub": user_id, "user_id": user_id}
        )
