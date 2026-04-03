"""Base class for all MCP-compatible Skill / Tool definitions.

Every Skill must subclass ``BaseMCPSkill`` and implement:
- ``name``        — unique snake_case identifier
- ``description`` — human-readable description the LLM uses to decide when to call it
- ``input_schema`` — JSON Schema dict describing the expected input parameters
- ``execute()``   — the actual async logic that runs when the tool is invoked

Two public helpers expose the schema in different formats:

``to_anthropic_tool()``
    Returns the tool dict accepted by ``anthropic.messages.create(tools=[...])``.
    Key: ``input_schema`` (Anthropic SDK convention).

``to_mcp_schema()``
    Returns the MCP-standard JSON Schema dict with camelCase ``inputSchema``
    as required by the PRD spec.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseMCPSkill(ABC):
    """Abstract base class for all diagnostic skills / MCP tools.

    Subclasses define a unit of work (API call, RAG lookup, user question, …)
    that the diagnostic agent can invoke autonomously.
    """

    # -----------------------------------------------------------------------
    # Abstract properties — subclasses MUST define these
    # -----------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique snake_case tool name used as the identifier by the LLM."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Natural-language description the LLM reads to decide when to use this tool."""

    @property
    @abstractmethod
    def input_schema(self) -> dict:
        """JSON Schema object describing the tool's expected input parameters."""

    # -----------------------------------------------------------------------
    # Abstract method — subclasses MUST implement this
    # -----------------------------------------------------------------------

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict:
        """Execute the skill with the provided keyword arguments.

        Args:
            **kwargs: Input parameters as defined by ``input_schema``.

        Returns:
            A dict containing the skill result.  The dict is serialised to a
            string and returned to the LLM as a ``tool_result`` message.
        """

    # -----------------------------------------------------------------------
    # Public schema helpers
    # -----------------------------------------------------------------------

    def to_anthropic_tool(self) -> dict:
        """Return the Anthropic SDK tool definition dict.

        Format::

            {
              "name": "mcp_mock_cpu_check",
              "description": "...",
              "input_schema": { "type": "object", "properties": {...}, "required": [...] }
            }

        This dict can be passed directly inside the ``tools`` list of
        ``anthropic.messages.create()``.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def to_mcp_schema(self) -> dict:
        """Return the MCP-standard JSON Schema dict (camelCase keys).

        Format matches the PRD spec::

            {
              "name": "mcp_mock_cpu_check",
              "description": "...",
              "inputSchema": { "type": "object", "properties": {...}, "required": [...] }
            }
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.__class__.__name__} name={self.name!r}>"
