"""
Skill Registry for managing and executing skills.

Skill 註冊表用於管理和執行技能。
"""

from typing import Any, Dict, List, Optional

from .base import BaseSkill, SkillMethod
from ..mcp.errors import SkillExecutionError, SkillNotFoundError


class SkillRegistry:
    """
    Registry for managing all available skills.
    
    管理所有可用 Skill 的註冊表。
    
    Provides:
    - Dynamic skill registration
    - Skill lookup and retrieval
    - Method execution routing
    - Skill metadata aggregation
    
    功能：
    - 動態 Skill 註冊
    - Skill 查詢和檢索
    - 方法執行路由
    - Skill 元數據聚合
    
    Example:
        >>> registry = SkillRegistry()
        >>> registry.register(MySkill())
        >>> result = await registry.execute("my_skill", "do_something", {...})
    """

    def __init__(self):
        """Initialize the registry."""
        self._skills: Dict[str, BaseSkill] = {}
        self._methods: Dict[str, Dict[str, BaseSkill]] = {}

    def register(self, skill: BaseSkill) -> None:
        """
        Register a new skill.
        
        Args:
            skill: BaseSkill - The skill instance to register
        
        Raises:
            ValueError: If skill name is invalid or already registered
        
        註冊一個新 Skill。
        """
        if not isinstance(skill, BaseSkill):
            raise ValueError(f"Invalid skill type: {type(skill)}")

        skill_name = skill.name
        if not skill_name or not isinstance(skill_name, str):
            raise ValueError("Skill name must be a non-empty string")

        if skill_name in self._skills:
            raise ValueError(f"Skill '{skill_name}' is already registered")

        # Store skill by name
        self._skills[skill_name] = skill

        # Index methods for fast lookup
        if skill_name not in self._methods:
            self._methods[skill_name] = {}

        for method in skill.get_exposed_methods():
            self._methods[skill_name][method.name] = skill

    def unregister(self, skill_name: str) -> None:
        """
        Unregister a skill.
        
        Args:
            skill_name: str - Name of the skill to unregister
        
        Raises:
            SkillNotFoundError: If skill not found
        
        註銷一個 Skill。
        """
        if skill_name not in self._skills:
            raise SkillNotFoundError(skill_name)

        del self._skills[skill_name]
        if skill_name in self._methods:
            del self._methods[skill_name]

    def get(self, skill_name: str) -> Optional[BaseSkill]:
        """
        Get a skill by name.
        
        Args:
            skill_name: str - Name of the skill
        
        Returns:
            BaseSkill or None - The skill if found, None otherwise
        
        按名稱獲取 Skill。
        """
        return self._skills.get(skill_name)

    def has(self, skill_name: str) -> bool:
        """
        Check if a skill is registered.
        
        Args:
            skill_name: str - Name of the skill
        
        Returns:
            bool - True if skill is registered
        
        檢查 Skill 是否已註冊。
        """
        return skill_name in self._skills

    def list_all(self) -> List[BaseSkill]:
        """
        Get all registered skills.
        
        Returns:
            List[BaseSkill] - List of all registered skills
        
        獲取所有已註冊的 Skill。
        """
        return list(self._skills.values())

    def get_methods(self, skill_name: str) -> List[SkillMethod]:
        """
        Get all exposed methods for a skill.
        
        Args:
            skill_name: str - Name of the skill
        
        Returns:
            List[SkillMethod] - List of exposed methods
        
        Raises:
            SkillNotFoundError: If skill not found
        
        獲取 Skill 的所有暴露方法。
        """
        skill = self.get(skill_name)
        if not skill:
            raise SkillNotFoundError(skill_name)

        return skill.get_exposed_methods()

    async def execute(
        self,
        skill_name: str,
        method_name: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a skill method.
        
        Args:
            skill_name: str - Name of the skill
            method_name: str - Name of the method to execute
            params: Dict - Parameters for the method
        
        Returns:
            Dict - Execution result
        
        Raises:
            SkillNotFoundError: If skill not found
            SkillExecutionError: If execution fails
        
        執行 Skill 方法。
        """
        # Verify skill exists
        skill = self.get(skill_name)
        if not skill:
            raise SkillNotFoundError(skill_name)

        # Execute the skill method
        try:
            result = await skill.execute(method_name, params)
            return result
        except Exception as e:
            # Wrap non-SkillExecutionError exceptions
            if isinstance(e, SkillExecutionError):
                raise
            raise SkillExecutionError(
                skill_name=skill_name,
                error=str(e)
            ) from e

    def get_metadata(self) -> Dict[str, Any]:
        """
        Get metadata for all registered skills.
        
        Returns:
            Dict - Metadata indexed by skill name
        
        獲取所有已註冊 Skill 的元數據。
        """
        metadata = {}
        for skill_name, skill in self._skills.items():
            metadata[skill_name] = {
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "methods": [m.dict() for m in skill.get_exposed_methods()],
            }
        return metadata

    def __len__(self) -> int:
        """Return the number of registered skills."""
        return len(self._skills)

    def __repr__(self) -> str:
        return (
            f"SkillRegistry(skills={len(self._skills)}, "
            f"methods={sum(len(m) for m in self._methods.values())})"
        )

    def __str__(self) -> str:
        return f"SkillRegistry with {len(self)} skills"
