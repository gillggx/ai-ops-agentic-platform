"""
Base Skill class for the AI Agent layer.

Define the abstract base class that all skills must inherit from.
定義所有 Skill 必須繼承的抽象基類。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    """
    Metadata for a skill.
    
    Contains information about the skill's purpose, inputs, and outputs.
    包含 Skill 的用途、輸入和輸出的信息。
    """

    name: str = Field(..., description="Skill name (Skill 名稱)")
    description: str = Field(..., description="Skill description (Skill 描述)")
    version: str = Field(default="1.0.0", description="Skill version (Skill 版本)")
    author: Optional[str] = Field(default=None, description="Skill author (Skill 作者)")
    tags: List[str] = Field(
        default_factory=list,
        description="Skill tags for categorization (分類標籤)"
    )


class SkillInput(BaseModel):
    """
    Input parameter definition for a skill method.
    
    定義 Skill 方法的輸入參數。
    """

    name: str = Field(..., description="Parameter name (參數名稱)")
    type: str = Field(..., description="Parameter type (參數類型)")
    description: str = Field(..., description="Parameter description (參數描述)")
    required: bool = Field(default=True, description="Whether required (是否必需)")
    default: Optional[Any] = Field(default=None, description="Default value (默認值)")


class SkillOutput(BaseModel):
    """
    Output definition for a skill method.
    
    定義 Skill 方法的輸出。
    """

    name: str = Field(..., description="Output field name (輸出字段名)")
    type: str = Field(..., description="Output type (輸出類型)")
    description: str = Field(..., description="Output description (輸出描述)")


class SkillMethod(BaseModel):
    """
    Definition of a single skill method exposed to the MCP protocol.
    
    定義暴露給 MCP 協議的單個 Skill 方法。
    """

    name: str = Field(..., description="Method name (方法名)")
    description: str = Field(..., description="Method description (方法描述)")
    inputs: List[SkillInput] = Field(
        default_factory=list,
        description="Input parameters (輸入參數)"
    )
    outputs: List[SkillOutput] = Field(
        default_factory=list,
        description="Output fields (輸出字段)"
    )


class BaseSkill(ABC):
    """
    Abstract base class for all skills in the AI Agent layer.
    
    All skills must inherit from this class and implement the required methods.
    所有 Skill 必須繼承此類並實現所需的方法。
    
    Key responsibilities:
    - Define skill metadata (name, description, version)
    - Implement execute() method for skill logic
    - Define exposed methods for MCP protocol
    - Handle error cases
    
    主要職責：
    - 定義 Skill 元數據
    - 實現 execute() 方法
    - 定義暴露給 MCP 的方法
    - 處理錯誤情況
    
    Example:
        class MySkill(BaseSkill):
            def __init__(self):
                super().__init__(
                    name="MySkill",
                    description="My custom skill"
                )
            
            async def execute(self, method: str, params: dict) -> dict:
                if method == "do_something":
                    return await self.do_something(params)
                raise SkillNotFoundError(method)
            
            async def do_something(self, params: dict) -> dict:
                return {"result": "success"}
            
            def get_exposed_methods(self) -> List[SkillMethod]:
                return [
                    SkillMethod(
                        name="do_something",
                        description="Do something",
                        inputs=[...],
                        outputs=[...]
                    )
                ]
    """

    def __init__(self, name: str, description: str, **metadata_kwargs):
        """
        Initialize the skill.
        
        Args:
            name: Skill name (Skill 名稱)
            description: Skill description (Skill 描述)
            **metadata_kwargs: Additional metadata
        
        初始化 Skill。
        """
        self.metadata = SkillMetadata(
            name=name,
            description=description,
            **metadata_kwargs
        )

    @property
    def name(self) -> str:
        """Get skill name."""
        return self.metadata.name

    @property
    def description(self) -> str:
        """Get skill description."""
        return self.metadata.description

    @property
    def version(self) -> str:
        """Get skill version."""
        return self.metadata.version

    @abstractmethod
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a skill method.
        
        This method must be implemented by subclasses. It routes method calls
        to the appropriate handler.
        
        Args:
            method: str - Name of the method to execute
            params: Dict - Parameters for the method
        
        Returns:
            Dict - Execution result
        
        Raises:
            SkillNotFoundError: If method not found
            SkillExecutionError: If execution fails
        
        執行 Skill 方法。子類必須實現此方法。
        """
        pass

    @abstractmethod
    def get_exposed_methods(self) -> List[SkillMethod]:
        """
        Get the list of methods exposed to the MCP protocol.
        
        Returns:
            List[SkillMethod] - List of exposed methods
        
        獲取暴露給 MCP 協議的方法列表。
        """
        pass

    def __repr__(self) -> str:
        """Return detailed representation."""
        return (
            f"{self.__class__.__name__}("
            f"name={self.name!r}, "
            f"version={self.version!r})"
        )

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"{self.name} (v{self.version})"
