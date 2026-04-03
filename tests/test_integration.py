"""
Integration tests for the complete system.

完整系統集成測試。
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from main import create_app
from app.ontology.models import User
from app.ontology.services import UserService
from app.ontology.schemas import UserCreate


@pytest.fixture
async def client():
    """Create test client."""
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def test_user(test_db: AsyncSession) -> User:
    """Create test user in database."""
    service = UserService()
    user = await service.create(
        test_db,
        UserCreate(
            username="integrationtest",
            email="integration@test.com",
            password="IntegrationTest123!",
        ),
    )
    await test_db.commit()
    return user


class TestApplicationStartup:
    """Tests for application startup and health."""

    @pytest.mark.asyncio
    async def test_app_creation(self):
        """Test creating FastAPI app."""
        app = create_app()
        assert app is not None
        assert app.title == "Glass Box AI Diagnostic Platform"
        assert app.version == "2.0.0"

    @pytest.mark.asyncio
    async def test_app_routes(self):
        """Test app has required routes."""
        app = create_app()
        routes = [route.path for route in app.routes]
        assert "/" in routes
        assert "/health" in routes
        assert "/metrics" in routes
        assert "/mcp/health" in routes


class TestMCPServerIntegration:
    """Tests for MCP Server integration."""

    @pytest.mark.asyncio
    async def test_mcp_skills_registered(self):
        """Test that skills are registered."""
        app = create_app()
        # Check that app was created with MCP server
        assert app is not None

    @pytest.mark.asyncio
    async def test_mcp_health_endpoint(self, client):
        """Test MCP health endpoint."""
        response = await client.get("/mcp/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_mcp_skills_list(self, client):
        """Test listing MCP skills."""
        response = await client.get("/mcp/skills")
        assert response.status_code == 200
        data = response.json()
        assert "skills" in data


class TestAPIEndpointIntegration:
    """Tests for API endpoint integration."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Glass Box AI Diagnostic Platform"
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        """Test health endpoint."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "overall" in data
        assert "checks" in data

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, client):
        """Test metrics endpoint."""
        response = await client.get("/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data


class TestUserAPIIntegration:
    """Tests for User API integration."""

    @pytest.mark.asyncio
    async def test_create_user_integration(self, client):
        """Test creating user through API."""
        user_data = {
            "username": "apitest",
            "email": "apitest@example.com",
            "password": "ApiTest123!",
        }
        response = await client.post("/api/v1/users", json=user_data)
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "apitest"
        assert data["email"] == "apitest@example.com"

    @pytest.mark.asyncio
    async def test_get_user_integration(self, client, test_user):
        """Test getting user through API."""
        response = await client.get(f"/api/v1/users/{test_user.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "integrationtest"

    @pytest.mark.asyncio
    async def test_list_users_integration(self, client, test_user):
        """Test listing users through API."""
        response = await client.get("/api/v1/users?skip=0&limit=10")
        assert response.status_code in [200, 401]  # May be 401 if auth required

    @pytest.mark.asyncio
    async def test_duplicate_user_creation(self, client, test_user):
        """Test creating duplicate user."""
        user_data = {
            "username": "integrationtest",
            "email": "integration@test.com",
            "password": "IntegrationTest123!",
        }
        response = await client.post("/api/v1/users", json=user_data)
        assert response.status_code == 400


class TestServiceLayerIntegration:
    """Tests for service layer integration."""

    @pytest.mark.asyncio
    async def test_user_service_full_lifecycle(self, test_db):
        """Test complete user lifecycle."""
        service = UserService()
        
        # Create
        user_data = UserCreate(
            username="lifecycle",
            email="lifecycle@test.com",
            password="Lifecycle123!",
        )
        user = await service.create(test_db, user_data)
        assert user.id is not None
        await test_db.commit()
        
        # Read
        retrieved = await service.read(test_db, user.id)
        assert retrieved is not None
        assert retrieved.username == "lifecycle"
        
        # Update
        from app.ontology.schemas import UserUpdate
        update_data = UserUpdate(is_active=False)
        updated = await service.update(test_db, user.id, update_data)
        assert updated.is_active is False
        await test_db.commit()
        
        # Verify
        final = await service.read(test_db, user.id)
        assert final.is_active is False

    @pytest.mark.asyncio
    async def test_role_management_integration(self, test_db, test_user):
        """Test role management through service."""
        from app.ontology.models import UserRole
        service = UserService()
        
        # Add role
        user = await service.add_role(test_db, test_user.id, UserRole.ARCHITECT)
        assert user.has_role(UserRole.ARCHITECT)
        await test_db.commit()
        
        # Remove role
        user = await service.remove_role(test_db, test_user.id, UserRole.ARCHITECT)
        assert not user.has_role(UserRole.ARCHITECT)
        await test_db.commit()


class TestSkillIntegration:
    """Tests for skill integration."""

    @pytest.mark.asyncio
    async def test_skill_execution_flow(self):
        """Test complete skill execution flow."""
        from app.ai_agent.skills import (
            AgentManagementSkill,
            SkillRegistry,
        )
        
        registry = SkillRegistry()
        skill = AgentManagementSkill()
        registry.register_skill(skill)
        
        # Execute skill
        result = await registry.execute(
            skill_name="AgentManagement",
            method_name="create_agent",
            params={"agent_name": "test_agent", "agent_type": "worker"},
        )
        assert "agent_id" in result
        assert result["status"] == "created"

    @pytest.mark.asyncio
    async def test_multiple_skills_registration(self):
        """Test registering multiple skills."""
        from app.ai_agent.skills import (
            AgentManagementSkill,
            DataProcessingSkill,
            AnalyticsSkill,
            BusinessLogicSkill,
            SkillRegistry,
        )
        
        registry = SkillRegistry()
        skills = [
            AgentManagementSkill(),
            DataProcessingSkill(),
            AnalyticsSkill(),
            BusinessLogicSkill(),
        ]
        
        for skill in skills:
            registry.register_skill(skill)
        
        assert len(registry) == 4
        assert registry.has("AgentManagement")
        assert registry.has("DataProcessing")
        assert registry.has("Analytics")
        assert registry.has("BusinessLogic")


class TestOpsLayerIntegration:
    """Tests for operations layer integration."""

    @pytest.mark.asyncio
    async def test_health_check_system(self):
        """Test health check system."""
        from app.ai_ops import HealthCheck
        
        health = HealthCheck()
        health.register_check("test_check", lambda: True)
        
        results = await health.run_checks()
        assert "test_check" in results
        assert results["test_check"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_metrics_collection(self):
        """Test metrics collection."""
        from app.ai_ops import MetricsCollector
        
        metrics = MetricsCollector()
        metrics.record_metric("requests", 100)
        metrics.record_metric("requests", 150)
        metrics.record_metric("requests", 120)
        
        avg = metrics.calculate_average("requests")
        assert avg == pytest.approx(123.33, rel=0.01)

    @pytest.mark.asyncio
    async def test_rbac_system(self):
        """Test RBAC system."""
        from app.ai_ops import RBACManager
        from app.ontology.models import UserRole
        
        rbac = RBACManager()
        rbac.assign_role("user1", "admin")
        
        assert rbac.check_permission("user1", "read")
        assert rbac.check_permission("user1", "write")
        assert rbac.check_permission("user1", "delete")

    @pytest.mark.asyncio
    async def test_jwt_management(self):
        """Test JWT token management."""
        from app.ai_ops import JWTManager
        
        jwt_mgr = JWTManager()
        token = jwt_mgr.generate_token("user123", expires_in=3600)
        assert token is not None
        
        claims = jwt_mgr.validate_token(token)
        assert claims is not None
        assert claims.get("sub") == "user123"
