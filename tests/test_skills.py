"""
Unit tests for AI Agent Skills.

AI 代理技能单元测试。
"""

import pytest

from app.ai_agent.skills import (
    BaseSkill,
    AgentManagementSkill,
    DataProcessingSkill,
    AnalyticsSkill,
    BusinessLogicSkill,
    SkillRegistry,
)
from app.ai_agent.mcp.errors import SkillNotFoundError


class TestSkillMetadata:
    """Tests for skill metadata."""

    def test_agent_management_skill_creation(self):
        """Test creating AgentManagementSkill."""
        skill = AgentManagementSkill()
        assert skill.name == "AgentManagement"
        assert "agent" in skill.description.lower()
        assert skill.version == "1.0.0"

    def test_data_processing_skill_creation(self):
        """Test creating DataProcessingSkill."""
        skill = DataProcessingSkill()
        assert skill.name == "DataProcessing"
        assert "data" in skill.description.lower()

    def test_analytics_skill_creation(self):
        """Test creating AnalyticsSkill."""
        skill = AnalyticsSkill()
        assert skill.name == "Analytics"
        assert "analytics" in skill.description.lower()

    def test_business_logic_skill_creation(self):
        """Test creating BusinessLogicSkill."""
        skill = BusinessLogicSkill()
        assert skill.name == "BusinessLogic"
        assert "business" in skill.description.lower()


class TestSkillExposedMethods:
    """Tests for skill exposed methods."""

    def test_agent_management_methods(self):
        """Test AgentManagementSkill exposed methods."""
        skill = AgentManagementSkill()
        methods = skill.get_exposed_methods()
        assert len(methods) == 4
        method_names = [m.name for m in methods]
        assert "create_agent" in method_names
        assert "get_agent_status" in method_names
        assert "list_agents" in method_names
        assert "update_agent_config" in method_names

    def test_data_processing_methods(self):
        """Test DataProcessingSkill exposed methods."""
        skill = DataProcessingSkill()
        methods = skill.get_exposed_methods()
        assert len(methods) == 4
        method_names = [m.name for m in methods]
        assert "validate_data" in method_names
        assert "transform_data" in method_names
        assert "aggregate_data" in method_names
        assert "clean_data" in method_names

    def test_analytics_methods(self):
        """Test AnalyticsSkill exposed methods."""
        skill = AnalyticsSkill()
        methods = skill.get_exposed_methods()
        assert len(methods) == 4
        method_names = [m.name for m in methods]
        assert "analyze_data" in method_names
        assert "calculate_metrics" in method_names

    def test_business_logic_methods(self):
        """Test BusinessLogicSkill exposed methods."""
        skill = BusinessLogicSkill()
        methods = skill.get_exposed_methods()
        assert len(methods) == 4
        method_names = [m.name for m in methods]
        assert "execute_rule" in method_names
        assert "make_decision" in method_names


class TestSkillRegistry:
    """Tests for SkillRegistry."""

    def test_registry_creation(self):
        """Test creating SkillRegistry."""
        registry = SkillRegistry()
        assert len(registry) == 0

    def test_register_skill(self):
        """Test registering a skill."""
        registry = SkillRegistry()
        skill = AgentManagementSkill()
        registry.register_skill(skill)
        assert len(registry) == 1
        assert registry.has(skill.name)

    def test_get_skill(self):
        """Test getting a skill."""
        registry = SkillRegistry()
        skill = DataProcessingSkill()
        registry.register_skill(skill)
        retrieved = registry.get(skill.name)
        assert retrieved is not None
        assert retrieved.name == skill.name

    def test_list_all_skills(self):
        """Test listing all skills."""
        registry = SkillRegistry()
        skill1 = AgentManagementSkill()
        skill2 = DataProcessingSkill()
        registry.register_skill(skill1)
        registry.register_skill(skill2)
        all_skills = registry.list_all()
        assert len(all_skills) == 2

    def test_unregister_skill(self):
        """Test unregistering a skill."""
        registry = SkillRegistry()
        skill = AnalyticsSkill()
        registry.register_skill(skill)
        assert len(registry) == 1
        registry.unregister_skill(skill.name)
        assert len(registry) == 0

    def test_get_nonexistent_skill(self):
        """Test getting nonexistent skill."""
        registry = SkillRegistry()
        skill = registry.get("nonexistent")
        assert skill is None

    def test_has_skill(self):
        """Test checking if skill exists."""
        registry = SkillRegistry()
        skill = BusinessLogicSkill()
        registry.register_skill(skill)
        assert registry.has(skill.name)
        assert not registry.has("nonexistent")

    def test_get_metadata(self):
        """Test getting metadata."""
        registry = SkillRegistry()
        skill = AgentManagementSkill()
        registry.register_skill(skill)
        metadata = registry.get_metadata()
        assert skill.name in metadata
        assert metadata[skill.name]["version"] == skill.version

    @pytest.mark.asyncio
    async def test_execute_skill(self):
        """Test executing a skill method."""
        registry = SkillRegistry()
        skill = AgentManagementSkill()
        registry.register_skill(skill)
        
        # Execute create_agent method
        result = await registry.execute(
            skill_name="AgentManagement",
            method_name="create_agent",
            params={"agent_name": "test", "agent_type": "worker"},
        )
        assert "agent_id" in result
        assert result["status"] == "created"

    @pytest.mark.asyncio
    async def test_execute_nonexistent_skill(self):
        """Test executing nonexistent skill."""
        registry = SkillRegistry()
        with pytest.raises(SkillNotFoundError):
            await registry.execute(
                skill_name="nonexistent",
                method_name="method",
                params={},
            )
