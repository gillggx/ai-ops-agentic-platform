"""
FastAPI-based MCP Server implementation.

FastAPI MCP 服務器實現。
"""

from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .errors import (
    AuthenticationError,
    AuthorizationError,
    MCPError,
    SkillExecutionError,
    SkillNotFoundError,
)
from ..skills import BaseSkill, SkillRegistry


class FastAPIMCPServer:
    """
    FastAPI-based MCP Server for managing tools and skills.
    
    FastAPI MCP 服務器，用於管理工具和技能。
    
    Responsibilities:
    - Register and manage skills
    - Handle MCP protocol requests
    - Execute skill methods
    - Manage authentication/authorization
    - Error handling and logging
    
    職責:
    - 註冊和管理技能
    - 處理 MCP 協議請求
    - 執行技能方法
    - 管理認證/授權
    - 錯誤處理和日誌
    
    Example:
        app = FastAPI()
        server = FastAPIMCPServer(app)
        
        skill = MySkill()
        server.register_skill(skill)
        
        # Now server handles /mcp/execute, /mcp/list, etc.
    """

    def __init__(
        self,
        app: FastAPI,
        prefix: str = "/mcp",
        auth_handler: Optional[Callable] = None,
    ):
        """
        Initialize the MCP server.
        
        Args:
            app: FastAPI - FastAPI application instance
            prefix: str - URL prefix for MCP endpoints (default: /mcp)
            auth_handler: Optional callable for authentication
        
        初始化 MCP 服務器。
        """
        self.app = app
        self.prefix = prefix
        self.skill_registry = SkillRegistry()
        self.auth_handler = auth_handler
        self._setup_routes()

    def _setup_routes(self) -> None:
        """
        Set up FastAPI routes for MCP protocol.
        
        設置 MCP 協議的 FastAPI 路由。
        """
        # Health check
        @self.app.get(f"{self.prefix}/health")
        async def health() -> Dict[str, Any]:
            """
            Health check endpoint.
            
            健康檢查端點。
            """
            return {
                "status": "healthy",
                "skills_count": len(self.skill_registry),
            }

        # List all skills
        @self.app.get(f"{self.prefix}/skills")
        async def list_skills() -> Dict[str, Any]:
            """
            List all registered skills and their methods.
            
            列出所有已註冊的技能及其方法。
            """
            return {
                "success": True,
                "skills": self.skill_registry.get_metadata(),
            }

        # Get specific skill
        @self.app.get(f"{self.prefix}/skills/{{skill_name}}")
        async def get_skill(skill_name: str) -> Dict[str, Any]:
            """
            Get details of a specific skill.
            
            獲取特定技能的詳細信息。
            """
            skill = self.skill_registry.get(skill_name)
            if not skill:
                raise HTTPException(
                    status_code=404,
                    detail=f"Skill '{skill_name}' not found",
                )

            methods = skill.get_exposed_methods()
            return {
                "success": True,
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "methods": [m.model_dump() for m in methods],
            }

        # Execute skill method
        @self.app.post(f"{self.prefix}/execute")
        async def execute_skill(request: Request) -> Dict[str, Any]:
            """
            Execute a skill method.
            
            執行技能方法。
            
            Request body:
            {
                "skill": "skill_name",
                "method": "method_name",
                "params": {...}
            }
            """
            try:
                # Authenticate if handler provided
                if self.auth_handler:
                    await self.auth_handler(request)

                # Parse request
                body = await request.json()
                skill_name = body.get("skill")
                method_name = body.get("method")
                params = body.get("params", {})

                # Validate input
                if not skill_name or not method_name:
                    raise ValueError("skill and method are required")

                # Execute
                result = await self.skill_registry.execute(
                    skill_name=skill_name,
                    method_name=method_name,
                    params=params,
                )

                return {
                    "success": True,
                    "data": result,
                }

            except SkillNotFoundError as e:
                raise HTTPException(status_code=404, detail=e.message)
            except SkillExecutionError as e:
                raise HTTPException(status_code=500, detail=e.message)
            except AuthenticationError as e:
                raise HTTPException(status_code=401, detail=e.message)
            except AuthorizationError as e:
                raise HTTPException(status_code=403, detail=e.message)
            except MCPError as e:
                raise HTTPException(status_code=e.status_code, detail=e.message)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

    def register_skill(self, skill: BaseSkill) -> None:
        """
        Register a new skill with the server.
        
        Args:
            skill: BaseSkill - Skill instance to register
        
        Raises:
            ValueError: If skill is invalid or already registered
        
        註冊新技能。
        """
        self.skill_registry.register(skill)

    def unregister_skill(self, skill_name: str) -> None:
        """
        Unregister a skill.
        
        Args:
            skill_name: str - Name of skill to unregister
        
        Raises:
            SkillNotFoundError: If skill not found
        
        註銷技能。
        """
        self.skill_registry.unregister(skill_name)

    def get_skill(self, skill_name: str) -> Optional[BaseSkill]:
        """
        Get a registered skill.
        
        Args:
            skill_name: str - Name of skill
        
        Returns:
            BaseSkill or None - Skill instance or None
        
        獲取已註冊的技能。
        """
        return self.skill_registry.get(skill_name)

    def list_all_skills(self) -> List[BaseSkill]:
        """
        List all registered skills.
        
        Returns:
            List[BaseSkill] - List of skill instances
        
        列出所有已註冊的技能。
        """
        return self.skill_registry.list_all()

    def get_skill_count(self) -> int:
        """
        Get number of registered skills.
        
        Returns:
            int - Number of skills
        
        獲取已註冊的技能數量。
        """
        return len(self.skill_registry)

    async def execute_skill(
        self,
        skill_name: str,
        method_name: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a skill method directly.
        
        Args:
            skill_name: str - Skill name
            method_name: str - Method name
            params: Dict - Method parameters
        
        Returns:
            Dict - Execution result
        
        Raises:
            SkillNotFoundError: If skill not found
            SkillExecutionError: If execution fails
        
        直接執行技能方法。
        """
        return await self.skill_registry.execute(
            skill_name=skill_name,
            method_name=method_name,
            params=params,
        )

    def __repr__(self) -> str:
        """Return detailed representation."""
        return (
            f"FastAPIMCPServer(prefix={self.prefix!r}, "
            f"skills={len(self.skill_registry)})"
        )

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"MCP Server with {len(self.skill_registry)} skills"
