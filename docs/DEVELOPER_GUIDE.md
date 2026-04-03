# Developer Onboarding Guide

开发者入职指南

## Welcome!

Welcome to the Glass Box AI Diagnostic Platform backend team! This guide will help you get up to speed with our development practices, code organization, and workflow.

欢迎加入玻璃盒 AI 诊断平台后端团队！本指南将帮助您快速了解我们的开发实践、代码组织和工作流程。

## Table of Contents

- [Quick Start](#quick-start)
- [Development Environment](#development-environment)
- [Project Structure](#project-structure)
- [Coding Standards](#coding-standards)
- [Git Workflow](#git-workflow)
- [Testing](#testing)
- [Documentation](#documentation)
- [Debugging](#debugging)
- [Common Tasks](#common-tasks)
- [Resources](#resources)

## Quick Start

### Prerequisites

- Python 3.11 or later
- Git
- Docker & Docker Compose (for containerized development)
- PostgreSQL 13+ (optional, for local development)
- Redis 6+ (optional, for local development)

### Getting Started in 5 Minutes

```bash
# 1. Clone the repository
git clone https://github.com/your-org/fastapi-backend.git
cd fastapi-backend

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. Setup environment
cp .env.example .env
# Edit .env with your local settings

# 5. Start development server
python main.py

# API is now available at http://localhost:8000
# API docs at http://localhost:8000/docs
```

### Alternative: Using Docker

```bash
# Start all services with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f fastapi_app

# Stop services
docker-compose down
```

## Development Environment

### IDE Setup

#### Visual Studio Code

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/venv/bin/python",
  "python.linting.enabled": true,
  "python.linting.flake8Enabled": true,
  "python.formatting.provider": "black",
  "[python]": {
    "editor.defaultFormatter": "ms-python.python",
    "editor.formatOnSave": true
  }
}
```

#### PyCharm

1. File → Settings → Project → Python Interpreter
2. Select the virtual environment from `venv/` folder
3. Enable code inspections and type checking

### Environment Variables

Create `.env` file in project root:

```env
# Application
APP_NAME=Glass Box AI Diagnostic Platform
DEBUG=true
ENVIRONMENT=development

# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost/fastapi_db
DATABASE_ECHO=false
DATABASE_POOL_SIZE=5

# Cache
REDIS_URL=redis://localhost:6379/0

# Security
SECRET_KEY=dev-key-not-for-production
ALGORITHM=HS256

# Logging
LOG_LEVEL=DEBUG
LOG_FORMAT=json

# Testing
TEST_DATABASE_URL=sqlite+aiosqlite:///:memory:
```

### Tools & Extensions

**Essential Tools:**
- pytest - Testing framework
- black - Code formatter
- flake8 - Linter
- mypy - Type checker
- httpx - HTTP client for tests

**Install Development Tools:**
```bash
pip install -r requirements-dev.txt
```

## Project Structure

```
fastapi-backend/
├── app/                      # Main application package
│   ├── api/                  # API routes
│   │   ├── routes/          # Endpoint handlers
│   │   ├── dependencies.py   # Dependency injection
│   │   └── schemas/         # Request/response models
│   ├── core/                # Core functionality
│   │   ├── database.py      # Database configuration
│   │   ├── cache.py         # Caching layer
│   │   ├── async_utils.py   # Async utilities
│   │   ├── events.py        # Event system
│   │   ├── message_queue.py # Message queue
│   │   └── monitoring.py    # Monitoring
│   ├── ontology/            # Domain models
│   │   ├── models/         # SQLAlchemy models
│   │   ├── repositories/   # Data access layer
│   │   └── schemas/        # Pydantic schemas
│   ├── ai_agent/           # AI agent integration
│   │   ├── mcp.py          # MCP server
│   │   └── skills.py       # MCP skills
│   ├── ai_ops/             # Operations & monitoring
│   │   ├── logging.py      # Logging setup
│   │   ├── monitoring.py   # Metrics
│   │   └── security.py     # Security utilities
│   └── middleware.py        # Custom middleware
├── tests/                    # Test suite
│   ├── test_api.py          # API tests
│   ├── test_performance.py  # Performance tests
│   ├── test_security.py     # Security tests
│   ├── test_load.py         # Load tests
│   └── conftest.py          # Pytest fixtures
├── deploy/                  # Deployment configs
│   ├── kubernetes/          # K8s manifests
│   ├── helm/               # Helm charts
│   └── scripts/            # Deployment scripts
├── docs/                    # Documentation
│   ├── ARCHITECTURE.md
│   ├── DEPLOYMENT_GUIDE.md
│   ├── API.md
│   └── DEVELOPER_GUIDE.md
├── main.py                 # Application entry point
├── requirements.txt        # Dependencies
├── requirements-dev.txt    # Dev dependencies
├── Dockerfile              # Container definition
└── docker-compose.yml      # Service orchestration
```

## Coding Standards

### Python Style Guide

We follow **PEP 8** with the following conventions:

```python
"""
Module docstring - brief description.

Longer description if needed.

模块文档字符串 - 简要描述。
"""

from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)


class MyClass:
    """
    Class docstring - what it does.
    
    类文档字符串。
    """

    def __init__(self, param: str) -> None:
        """
        Initialize the class.
        
        Args:
            param: Parameter description
        
        初始化类。
        """
        self.param = param

    async def async_method(self, value: int) -> Optional[str]:
        """
        Method with dual-language docstring.
        
        Args:
            value: Input value
        
        Returns:
            Result or None
        
        具有双语文档字符串的方法。
        """
        if value > 0:
            return f"Value: {value}"
        return None
```

### Code Formatting

```bash
# Format code with black
black app tests

# Check format without changes
black --check app tests

# Lint with flake8
flake8 app tests

# Type checking with mypy
mypy app
```

### Type Annotations

Always use type hints:

```python
# Good
async def get_user(user_id: int) -> Optional[User]:
    pass

# Avoid
async def get_user(user_id):
    pass

# Collections
def process_items(items: List[str]) -> Dict[str, int]:
    pass
```

### Docstrings

Use **Google-style docstrings** with English + Chinese:

```python
def calculate_total(items: List[float], tax_rate: float = 0.1) -> float:
    """
    Calculate total with tax.
    
    Args:
        items: List of prices
        tax_rate: Tax rate (default 0.1 = 10%)
    
    Returns:
        Total amount including tax
    
    Raises:
        ValueError: If items list is empty
    
    计算包含税款的总额。
    """
    if not items:
        raise ValueError("Items list cannot be empty")
    
    subtotal = sum(items)
    return subtotal * (1 + tax_rate)
```

## Git Workflow

### Branch Naming

```
feature/description      - New feature
bugfix/description       - Bug fix
refactor/description     - Code refactoring
docs/description         - Documentation
test/description         - Test improvements
chore/description        - Maintenance
```

### Commit Messages

```
Format: <type>: <subject>

<body>

<footer>

Examples:
feat: Add user authentication endpoint
fix: Correct database connection timeout
docs: Update API documentation
test: Add integration tests for cache layer
```

### Creating a Pull Request

```bash
# 1. Create feature branch
git checkout -b feature/my-feature

# 2. Make changes and commit
git add .
git commit -m "feat: add new feature"

# 3. Push to remote
git push origin feature/my-feature

# 4. Create PR on GitHub
# - Describe changes
# - Reference related issues
# - Request reviewers
```

### Code Review Process

1. **Automated Checks**: GitHub Actions runs tests and linting
2. **Manual Review**: Team members review for:
   - Code quality
   - Performance implications
   - Security concerns
   - Test coverage
3. **Approval**: At least 1 approval required
4. **Merge**: Squash and merge to main

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_api.py

# Run with coverage
pytest --cov=app tests/

# Run only fast tests
pytest -m "not slow"

# Run with verbose output
pytest -v
```

### Writing Tests

```python
import pytest
from httpx import AsyncClient

class TestUserEndpoints:
    """Tests for user endpoints."""

    @pytest.mark.asyncio
    async def test_create_user(self, client: AsyncClient):
        """Test creating a new user."""
        response = await client.post(
            "/api/v1/users",
            json={
                "username": "testuser",
                "email": "test@example.com",
                "password": "securepassword"
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_get_user(self, client: AsyncClient):
        """Test retrieving a user."""
        response = await client.get("/api/v1/users/1")
        
        assert response.status_code == 200
```

### Test Coverage

Maintain at least **80% coverage**:

```bash
# Generate coverage report
pytest --cov=app --cov-report=html

# View report
open htmlcov/index.html
```

## Documentation

### API Documentation

Our API documentation is auto-generated from docstrings:

- **Interactive Docs**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc

### Writing API Docs

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/users/{user_id}", response_model=User)
async def get_user(
    user_id: int,
    include_posts: bool = False
) -> User:
    """
    Get a user by ID.
    
    **Parameters:**
    - **user_id**: The user's ID
    - **include_posts**: Whether to include user's posts
    
    **Returns:**
    - User object with profile information
    
    **Raises:**
    - 404: User not found
    - 500: Server error
    """
    # Implementation
    pass
```

## Debugging

### Logging

```python
import logging

logger = logging.getLogger(__name__)

# Different log levels
logger.debug("Detailed debug information")
logger.info("General information")
logger.warning("Warning message")
logger.error("Error occurred")
logger.critical("Critical issue")
```

### Debugger Breakpoints

```python
# Using debugger
import pdb; pdb.set_trace()

# Or in Python 3.7+
breakpoint()
```

### Debugging with VS Code

Add to `.vscode/launch.json`:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "FastAPI Debug",
            "type": "python",
            "request": "launch",
            "module": "uvicorn",
            "args": ["main:app", "--reload"],
            "jinja": true
        }
    ]
}
```

## Common Tasks

### Adding a New Endpoint

1. **Create route file** (if needed): `app/api/routes/new_route.py`
2. **Define schema**: `app/ontology/schemas/new_schema.py`
3. **Implement endpoint**:
   ```python
   @router.get("/items/{item_id}")
   async def get_item(item_id: int) -> Item:
       """Get item by ID."""
       return await item_service.get(item_id)
   ```
4. **Add tests**: `tests/test_new_route.py`
5. **Update API docs** (automatic)

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Review the migration file
# Then apply it
alembic upgrade head

# Rollback if needed
alembic downgrade -1
```

### Adding a New Dependency

```bash
# 1. Install package
pip install package_name

# 2. Add to requirements.txt or requirements-dev.txt
pip freeze | grep package_name >> requirements.txt

# 3. Update colleagues
git add requirements.txt
git commit -m "chore: add dependency"
```

## Resources

### Documentation
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Docs](https://docs.sqlalchemy.org/)
- [Pydantic Docs](https://docs.pydantic.dev/)
- [Redis Docs](https://redis.io/docs/)

### Tools & Libraries
- [Python Type Hints](https://docs.python.org/3/library/typing.html)
- [Pytest Documentation](https://docs.pytest.org/)
- [Black Code Formatter](https://black.readthedocs.io/)

### Internal Resources
- Architecture Guide: See `docs/ARCHITECTURE.md`
- Deployment Guide: See `docs/DEPLOYMENT_GUIDE.md`
- API Documentation: See Swagger at `/docs`

### Useful Commands

```bash
# See all useful commands
make help

# Format code
make format

# Run tests
make test

# Check coverage
make coverage

# Run linting
make lint

# Build Docker image
make docker-build

# Deploy to staging
make deploy-staging
```

## Getting Help

- **Slack**: #backend-dev channel
- **GitHub Discussions**: For design questions
- **GitHub Issues**: For bugs and feature requests
- **1-on-1**: Schedule with team lead

---

**Happy coding!** 🚀

If you have questions or suggestions for this guide, please submit a PR or contact the backend team.
