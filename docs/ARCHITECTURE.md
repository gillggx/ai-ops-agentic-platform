# FastAPI Backend Architecture Guide

FastAPI 后端架构指南

## Table of Contents

- [Overview](#overview)
- [Architecture Layers](#architecture-layers)
- [Core Components](#core-components)
- [Data Flow](#data-flow)
- [Design Patterns](#design-patterns)
- [Performance Optimization](#performance-optimization)
- [Scalability](#scalability)
- [Security](#security)

## Overview

The Glass Box AI Diagnostic Platform backend is built on a three-layer architecture:

玻璃盒 AI 诊断平台后端建立在三层架构上：

1. **API Layer** - FastAPI endpoints and request handling
   - FastAPI 端点和请求处理

2. **Business Logic Layer** - Core domain logic and MCP Skills
   - 核心域逻辑和 MCP 技能

3. **Data Layer** - Database, cache, and external integrations
   - 数据库、缓存和外部集成

### Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                  API Layer                           │
│  (FastAPI, Routes, Middleware, Authentication)     │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│              Business Logic Layer                    │
│  (MCP Skills, Domain Logic, Services)              │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│              Data Layer                              │
│  (Database, Cache, Message Queue, Monitoring)      │
└─────────────────────────────────────────────────────┘
```

## Architecture Layers

### API Layer

The API layer handles all HTTP requests and responses.

API 层处理所有 HTTP 请求和响应。

**Components:**
- FastAPI application instance
- Route handlers
- Request/Response models (Pydantic schemas)
- Middleware (CORS, logging, error handling)
- Authentication/Authorization

**Key Files:**
- `main.py` - Application entry point
- `app/api/routes.py` - API route definitions
- `app/api/dependencies.py` - Dependency injection
- `app/middleware.py` - Custom middleware

**Request Flow:**
```
HTTP Request
    ↓
CORS Middleware
    ↓
Authentication Middleware
    ↓
Route Handler
    ↓
Business Logic
    ↓
Data Layer
    ↓
HTTP Response
```

### Business Logic Layer

The business logic layer implements domain-specific operations and MCP Skills.

业务逻辑层实现了特定于域的操作和 MCP 技能。

**Components:**
- MCP Skills (Agent Management, Data Processing, Analytics)
- Service classes
- Domain models
- Business rules and validations

**Key Files:**
- `app/ai_agent/mcp.py` - MCP server implementation
- `app/ai_agent/skills.py` - Skill definitions
- `app/ontology/models/` - Domain models
- `app/ontology/schemas/` - API schemas

**Service Pattern:**
```python
# Services encapsulate business logic
class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create_user(self, user_data: UserCreate) -> User:
        # Business logic here
        pass
```

### Data Layer

The data layer manages all data persistence and external integrations.

数据层管理所有数据持久性和外部集成。

**Components:**
- PostgreSQL database with async SQLAlchemy
- Redis cache with multiple backends
- RabbitMQ message queue
- Monitoring (Prometheus/Grafana)
- Connection pooling and query optimization

**Key Files:**
- `app/core/database.py` - Database configuration
- `app/core/cache.py` - Caching layer
- `app/ontology/repositories/` - Data access objects

## Core Components

### FastAPI Application

```python
# Main application creation
app = FastAPI(
    title="Glass Box AI Diagnostic Platform",
    description="Three-layer FastAPI backend",
    version="2.0.0"
)

# Middleware setup
app.add_middleware(CORSMiddleware, ...)

# Route registration
app.include_router(user_routes, prefix="/api/v1")
```

### MCP Skills

MCP (Model Context Protocol) Skills provide extensible business capabilities.

MCP 技能提供可扩展的业务功能。

**Skill Types:**

1. **AgentManagementSkill** - Manage AI agents
   - 管理 AI 代理

2. **DataProcessingSkill** - Process data
   - 处理数据

3. **AnalyticsSkill** - Analyze patterns
   - 分析模式

4. **BusinessLogicSkill** - Custom business logic
   - 自定义业务逻辑

### Database Schema

**Key Tables:**
- `users` - User accounts
- `agents` - AI agents
- `events` - System events
- `audit_logs` - Audit trail
- `sessions` - User sessions

**Indexing Strategy:**
- Primary keys on all tables
- Foreign keys with cascading rules
- Composite indices for common queries
- Partial indices for filtered queries

### Caching Strategy

**Cache Layers:**
1. **Application Cache** (Redis) - Session data, computed results
   - 应用程序缓存（Redis）

2. **Query Cache** (Redis) - Database query results
   - 查询缓存

3. **Service Cache** (In-Memory) - Hot data, configurations
   - 服务缓存

**Cache Invalidation:**
```python
# Time-based expiration
await cache.set(key, value, ttl=300)

# Event-based invalidation
async def on_user_updated(user_id: int):
    await cache.delete(f"user:{user_id}")
```

## Data Flow

### Create User Request

```
1. HTTP POST /api/v1/users
   ↓
2. Route Handler receives UserCreate schema
   ↓
3. Validate request (Pydantic)
   ↓
4. Check cache for duplicate prevention
   ↓
5. Call UserService.create_user()
   ↓
6. Insert into database
   ↓
7. Cache user data
   ↓
8. Emit user_created event (optional)
   ↓
9. Return HTTP 201 with User schema
```

### Query User with Cache

```
1. HTTP GET /api/v1/users/{user_id}
   ↓
2. Check cache (key: user:{user_id})
   ↓
3a. If cached: return cached data
3b. If not cached:
    - Query database
    - Store in cache (TTL: 5 minutes)
    - Return data
```

## Design Patterns

### Repository Pattern

Data access is abstracted through repositories.

数据访问通过存储库进行抽象。

```python
class UserRepository(BaseRepository[User]):
    async def get_by_email(self, email: str) -> Optional[User]:
        query = select(User).where(User.email == email)
        return await self.session.scalar(query)
```

### Service Pattern

Business logic is encapsulated in service classes.

业务逻辑封装在服务类中。

```python
class UserService:
    def __init__(self, repo: UserRepository):
        self.repo = repo
    
    async def register_user(self, data: UserRegister):
        # Validation
        existing = await self.repo.get_by_email(data.email)
        if existing:
            raise UserAlreadyExists()
        
        # Create
        user = User(**data.model_dump())
        return await self.repo.create(user)
```

### Dependency Injection

FastAPI's dependency injection provides testability.

FastAPI 的依赖注入提供了可测试性。

```python
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_manager().async_session() as session:
        yield session

@router.get("/users")
async def list_users(session: AsyncSession = Depends(get_session)):
    # session is injected
    pass
```

### Strategy Pattern

Caching backends use strategy pattern.

缓存后端使用策略模式。

```python
# Different cache implementations
cache = RedisCache(url="redis://localhost:6379")
# or
cache = InMemoryCache()

# Same interface
await cache.get(key)
await cache.set(key, value)
```

## Performance Optimization

### Database Optimizations

1. **Connection Pooling**
   - Pool size: 20 connections
   - Max overflow: 30 connections
   - Timeout: 30 seconds

2. **Query Optimization**
   - Eager loading relationships (selectinload)
   - Lazy loading for large collections
   - Database query analysis

3. **Indexing Strategy**
   - Indices on frequently queried columns
   - Composite indices for common filter combinations
   - Partial indices for sparse data

### Caching Strategy

1. **Multi-level Cache**
   - Redis for distributed cache
   - In-memory cache for hot data
   - HTTP cache headers

2. **Cache Invalidation**
   - Time-based (TTL)
   - Event-based
   - Dependency-based

### Async Performance

1. **Async Database Operations**
   - Non-blocking database queries
   - Connection pooling
   - Batch operations

2. **Concurrent Request Handling**
   - Async task scheduling
   - Worker pools for CPU-bound tasks
   - Rate limiting

## Scalability

### Horizontal Scaling

**Kubernetes Deployment:**
- Multiple replicas (default: 3)
- Horizontal Pod Autoscaler (HPA)
- Load balancing

**Configuration:**
```yaml
replicas: 3
autoscaling:
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilization: 70%
```

### Vertical Scaling

**Resource Limits:**
```yaml
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

### State Management

1. **Stateless API Servers**
   - All state in Redis/Database
   - Session tokens in headers
   - No server-side sessions

2. **Distributed Cache**
   - Redis cluster for cache
   - Cache replication
   - Cache consistency

## Security

### Authentication

1. **JWT Tokens**
   - Issued on login
   - 30-minute expiration
   - Refresh tokens for renewal

2. **Authorization**
   - Role-based access control (RBAC)
   - Scope-based permissions
   - Resource-level checks

### Data Protection

1. **Encryption**
   - HTTPS/TLS in transit
   - Password hashing (bcrypt)
   - Sensitive data encryption at rest

2. **Input Validation**
   - Pydantic schema validation
   - SQL injection prevention
   - XSS protection

### API Security

1. **Rate Limiting**
   - Per-user rate limits
   - Global rate limits
   - Token bucket algorithm

2. **CORS**
   - Whitelist allowed origins
   - Restrict methods and headers
   - Credentials handling

### Audit & Compliance

1. **Audit Logging**
   - All user actions logged
   - Immutable audit trail
   - Searchable logs

2. **Compliance**
   - GDPR data handling
   - Data retention policies
   - Privacy by design

## Deployment

### Docker

Multi-stage Dockerfile for optimized image:
- Builder stage: Install dependencies
- Runtime stage: Minimal production image
- Size: ~200MB

### Kubernetes

Production-ready K8s manifests:
- Deployment with rolling updates
- Service with load balancing
- HPA for autoscaling
- PDB for high availability

### CI/CD

GitHub Actions workflows:
- Test on push
- Build Docker image
- Push to registry
- Deploy to staging/production

## Monitoring

### Metrics

- Request latency
- Error rates
- Database query performance
- Cache hit rates
- Memory usage

### Logging

- Structured JSON logs
- Centralized log collection
- Log levels (DEBUG, INFO, WARN, ERROR)

### Health Checks

- Liveness probe (service running)
- Readiness probe (ready for traffic)
- Startup probe (initialization complete)

## References

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Redis Documentation](https://redis.io/documentation)
