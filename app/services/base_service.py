# BaseService - Base class for all services
# 基础服务 - 所有服务的基类

from typing import Optional, Any, Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logger import logger
from app.core.exceptions import ServiceError, NotFoundError


class BaseService:
    """
    Base service class for all business logic services.
    
    所有业务逻辑服务的基础服务类。
    
    Provides common functionality:
    - Database session management
    - Error handling and logging
    - Common query patterns
    
    提供公共功能：
    - 数据库会话管理
    - 错误处理和日志记录
    - 常见查询模式
    """

    def __init__(self, db_session: AsyncSession):
        """
        Initialize base service with database session.
        
        使用数据库会话初始化基础服务。
        
        Args:
            db_session: SQLAlchemy async session / SQLAlchemy异步会话
        """
        self.db = db_session
        self.logger = logger

    async def _execute_query(
        self,
        query_func,
        operation_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute database query with error handling.
        
        执行数据库查询并进行错误处理。
        
        Args:
            query_func: Function to execute / 要执行的函数
            operation_name: Name of operation for logging / 操作名称用于日志记录
            *args: Positional arguments / 位置参数
            **kwargs: Keyword arguments / 关键字参数
            
        Returns:
            Query result / 查询结果
            
        Raises:
            ServiceError: If query execution fails / 如果查询执行失败
        """
        try:
            self.logger.debug(f"Executing {operation_name} / 执行 {operation_name}")
            # Inject self.db as first argument if query_func is a repository method
            import inspect
            sig = inspect.signature(query_func)
            params = list(sig.parameters.keys())
            if params and params[0] == "db":
                result = await query_func(self.db, *args, **kwargs)
            else:
                result = await query_func(*args, **kwargs)
            self.logger.debug(f"{operation_name} completed successfully / {operation_name} 完成")
            return result
        except Exception as e:
            self.logger.error(f"Error in {operation_name} / {operation_name} 出错: {str(e)}")
            raise ServiceError(f"{operation_name} failed / {operation_name} 失败: {str(e)}") from e

    async def _execute_transaction(
        self,
        transaction_func,
        operation_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute database transaction with commit/rollback.
        
        执行数据库事务并提交/回滚。
        
        Args:
            transaction_func: Async function to execute / 要执行的异步函数
            operation_name: Name of operation for logging / 操作名称用于日志记录
            *args: Positional arguments / 位置参数
            **kwargs: Keyword arguments / 关键字参数
            
        Returns:
            Transaction result / 事务结果
            
        Raises:
            ServiceError: If transaction fails / 如果事务失败
        """
        try:
            self.logger.debug(f"Starting transaction: {operation_name} / 启动事务: {operation_name}")
            result = await transaction_func(*args, **kwargs)
            await self.db.commit()
            self.logger.info(f"Transaction committed: {operation_name} / 事务提交: {operation_name}")
            return result
        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Transaction failed: {operation_name} / 事务失败: {operation_name} - {str(e)}")
            raise ServiceError(f"Transaction failed: {operation_name} / 事务失败: {operation_name}") from e

    def _validate_required_fields(
        self,
        data: Dict[str, Any],
        required_fields: List[str],
    ) -> None:
        """
        Validate that required fields are present in data.
        
        验证数据中是否存在必需字段。
        
        Args:
            data: Data dictionary / 数据字典
            required_fields: List of required field names / 必需字段名称列表
            
        Raises:
            ValueError: If required field is missing / 如果缺少必需字段
        """
        for field in required_fields:
            if field not in data or data[field] is None:
                raise ValueError(f"Missing required field: {field} / 缺少必需字段: {field}")

    def _sanitize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize data by removing None values and empty strings.
        
        通过删除None值和空字符串来清理数据。
        
        Args:
            data: Data dictionary / 数据字典
            
        Returns:
            Sanitized data / 清理后的数据
        """
        return {
            key: value
            for key, value in data.items()
            if value is not None and value != ""
        }

    async def _get_or_raise(
        self,
        query_result: Optional[Any],
        entity_name: str,
        entity_id: Any,
    ) -> Any:
        """
        Return query result or raise NotFoundError.
        
        返回查询结果或抛出NotFoundError。
        
        Args:
            query_result: Result from database query / 数据库查询的结果
            entity_name: Name of entity (for error message) / 实体名称（用于错误消息）
            entity_id: ID of entity (for error message) / 实体ID（用于错误消息）
            
        Returns:
            Query result if found / 如果找到则返回查询结果
            
        Raises:
            NotFoundError: If result is None / 如果结果为None
        """
        if query_result is None:
            self.logger.warning(f"{entity_name} not found: {entity_id} / {entity_name} 未找到: {entity_id}")
            raise NotFoundError(f"{entity_name} not found / {entity_name} 未找到")
        return query_result
