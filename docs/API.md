# API Documentation

API 文档

## Overview

The Glass Box AI Diagnostic Platform API provides RESTful endpoints for managing users, agents, data, and system operations. This document describes all available endpoints, request formats, and response schemas.

玻璃盒 AI 诊断平台 API 提供了用于管理用户、代理、数据和系统操作的 RESTful 端点。本文档描述了所有可用的端点、请求格式和响应架构。

**API Version:** 2.0.0  
**Base URL:** `/api/v1`  
**Authentication:** JWT Bearer Token  
**Response Format:** JSON  

## Table of Contents

- [Authentication](#authentication)
- [Common Patterns](#common-patterns)
- [Error Handling](#error-handling)
- [User Endpoints](#user-endpoints)
- [Agent Endpoints](#agent-endpoints)
- [Data Endpoints](#data-endpoints)
- [System Endpoints](#system-endpoints)
- [Rate Limiting](#rate-limiting)
- [Webhooks](#webhooks)

## Authentication

### JWT Authentication

All endpoints (except public ones) require Bearer token authentication.

所有端点（公共端点除外）都需要持有者令牌身份验证。

**Request Header:**
```
Authorization: Bearer <access_token>
```

**Token Endpoints:**

#### Login
```
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123"
}

Response: 200 OK
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

#### Refresh Token
```
POST /api/v1/auth/refresh
Content-Type: application/json

{
  "refresh_token": "eyJhbGc..."
}

Response: 200 OK
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

## Common Patterns

### Pagination

List endpoints support pagination:

```
GET /api/v1/users?page=1&limit=20&sort=-created_at

Response:
{
  "items": [...],
  "total": 100,
  "page": 1,
  "limit": 20,
  "pages": 5
}
```

**Parameters:**
- `page` (int): Page number (1-indexed)
- `limit` (int): Items per page (max 100)
- `sort` (string): Sort field with optional `-` prefix for descending

### Filtering

List endpoints support filtering:

```
GET /api/v1/users?status=active&role=admin

Query Parameters:
- status: User status (active, inactive, suspended)
- role: User role (admin, user, viewer)
```

### Timestamps

All timestamps are in ISO 8601 format (UTC):
```
2024-01-15T10:30:45.123456Z
```

## Error Handling

### Error Response Format

```json
{
  "detail": "Error message",
  "error_code": "RESOURCE_NOT_FOUND",
  "status_code": 404,
  "timestamp": "2024-01-15T10:30:45Z",
  "request_id": "req_12345abcde"
}
```

### Common Status Codes

| Code | Meaning | Description |
|------|---------|-------------|
| 200 | OK | Request successful |
| 201 | Created | Resource created successfully |
| 204 | No Content | Request successful, no content |
| 400 | Bad Request | Invalid request format |
| 401 | Unauthorized | Missing or invalid authentication |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource not found |
| 409 | Conflict | Resource conflict (e.g., duplicate) |
| 422 | Unprocessable Entity | Invalid request data |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Server Error | Internal server error |
| 503 | Service Unavailable | Service temporarily unavailable |

## User Endpoints

### List Users

```
GET /api/v1/users

Query Parameters:
- page: int (default: 1)
- limit: int (default: 20, max: 100)
- status: string (active, inactive, suspended)
- role: string (admin, user, viewer)

Response: 200 OK
{
  "items": [
    {
      "id": 1,
      "username": "john_doe",
      "email": "john@example.com",
      "status": "active",
      "role": "user",
      "created_at": "2024-01-15T10:00:00Z",
      "updated_at": "2024-01-15T10:00:00Z"
    }
  ],
  "total": 50,
  "page": 1,
  "limit": 20,
  "pages": 3
}
```

### Get User

```
GET /api/v1/users/{user_id}

Response: 200 OK
{
  "id": 1,
  "username": "john_doe",
  "email": "john@example.com",
  "status": "active",
  "role": "user",
  "profile": {
    "full_name": "John Doe",
    "avatar_url": "https://...",
    "bio": "Software engineer"
  },
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T10:00:00Z"
}
```

### Create User

```
POST /api/v1/users
Content-Type: application/json

{
  "username": "jane_doe",
  "email": "jane@example.com",
  "password": "SecurePassword123!",
  "role": "user"
}

Response: 201 Created
{
  "id": 2,
  "username": "jane_doe",
  "email": "jane@example.com",
  "status": "active",
  "role": "user",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

### Update User

```
PUT /api/v1/users/{user_id}
Content-Type: application/json

{
  "username": "jane_smith",
  "email": "jane.smith@example.com",
  "profile": {
    "full_name": "Jane Smith",
    "bio": "Updated bio"
  }
}

Response: 200 OK
{
  "id": 2,
  "username": "jane_smith",
  "email": "jane.smith@example.com",
  "...": "..."
}
```

### Delete User

```
DELETE /api/v1/users/{user_id}

Response: 204 No Content
```

## Agent Endpoints

### List Agents

```
GET /api/v1/agents

Query Parameters:
- page: int
- limit: int
- status: string (running, stopped, failed, idle)
- type: string (diagnostic, analysis, processing)

Response: 200 OK
{
  "items": [
    {
      "id": 1,
      "name": "Diagnostic Agent",
      "type": "diagnostic",
      "status": "running",
      "created_at": "2024-01-15T10:00:00Z"
    }
  ],
  "total": 10,
  "page": 1,
  "limit": 20
}
```

### Start Agent

```
POST /api/v1/agents/{agent_id}/start

Response: 202 Accepted
{
  "id": 1,
  "name": "Diagnostic Agent",
  "status": "running",
  "started_at": "2024-01-15T10:30:00Z"
}
```

### Stop Agent

```
POST /api/v1/agents/{agent_id}/stop

Response: 200 OK
{
  "id": 1,
  "name": "Diagnostic Agent",
  "status": "stopped",
  "stopped_at": "2024-01-15T10:35:00Z"
}
```

## Data Endpoints

### Import Data

```
POST /api/v1/data/import
Content-Type: multipart/form-data

Files:
- file: <binary file>

Response: 202 Accepted
{
  "import_id": "import_12345",
  "status": "processing",
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Get Import Status

```
GET /api/v1/data/imports/{import_id}

Response: 200 OK
{
  "import_id": "import_12345",
  "status": "completed",
  "records_imported": 1000,
  "records_skipped": 5,
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:45:00Z"
}
```

### Export Data

```
POST /api/v1/data/export
Content-Type: application/json

{
  "format": "csv",
  "filters": {
    "date_from": "2024-01-01",
    "date_to": "2024-01-31"
  }
}

Response: 202 Accepted
{
  "export_id": "export_12345",
  "status": "processing",
  "format": "csv"
}
```

## System Endpoints

### Health Check

```
GET /health

Response: 200 OK
{
  "overall": "healthy",
  "checks": {
    "database": true,
    "cache": true,
    "queue": true
  },
  "last_check": "2024-01-15T10:30:00Z"
}
```

### Metrics

```
GET /metrics

Response: 200 OK
{
  "uptime_seconds": 3600,
  "requests_total": 10000,
  "requests_per_second": 2.5,
  "error_rate": 0.001,
  "cache_hits": 5000,
  "cache_misses": 1000,
  "database_connections": 5,
  "memory_usage_mb": 256
}
```

### System Status

```
GET /api/v1/system/status

Response: 200 OK
{
  "status": "operational",
  "version": "2.0.0",
  "environment": "production",
  "uptime_seconds": 3600,
  "components": {
    "api": "healthy",
    "database": "healthy",
    "cache": "healthy",
    "queue": "healthy"
  }
}
```

## Rate Limiting

API requests are rate limited per user:

**Rate Limits:**
- Standard users: 1,000 requests/hour
- Premium users: 10,000 requests/hour
- Admin users: Unlimited

**Rate Limit Headers:**
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1705344600
```

**Rate Limit Exceeded:**
```
HTTP/1.1 429 Too Many Requests

{
  "detail": "Rate limit exceeded",
  "error_code": "RATE_LIMIT_EXCEEDED",
  "retry_after": 60
}
```

## Webhooks

### Register Webhook

```
POST /api/v1/webhooks

{
  "url": "https://example.com/webhook",
  "events": ["user.created", "agent.started"],
  "secret": "webhook_secret_key"
}

Response: 201 Created
{
  "id": "webhook_12345",
  "url": "https://example.com/webhook",
  "events": ["user.created", "agent.started"],
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Webhook Payload

```json
{
  "event_type": "user.created",
  "timestamp": "2024-01-15T10:30:00Z",
  "data": {
    "user_id": 1,
    "username": "john_doe",
    "email": "john@example.com"
  },
  "signature": "sha256=..."
}
```

### Webhook Verification

Verify webhook signature:
```python
import hmac
import hashlib

def verify_webhook(payload, signature, secret):
    computed = hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(computed, signature)
```

## SDK & Client Libraries

### Python

```python
from fastapi_client import Client

client = Client("https://api.example.com", token="access_token")

# Get user
user = client.users.get(1)

# Create user
new_user = client.users.create(
    username="jane_doe",
    email="jane@example.com",
    password="password123"
)
```

### JavaScript

```javascript
const client = new FastAPIClient("https://api.example.com", token);

// Get user
const user = await client.users.get(1);

// Create user
const newUser = await client.users.create({
  username: "jane_doe",
  email: "jane@example.com",
  password: "password123"
});
```

## Changelog

### Version 2.0.0 (Current)
- Added event sourcing
- Improved performance with caching
- Enhanced security with rate limiting
- Added comprehensive monitoring

### Version 1.0.0
- Initial release

## Support

For API support:
- Email: api-support@example.com
- Slack: #api-support
- Issues: https://github.com/your-org/fastapi-backend/issues
