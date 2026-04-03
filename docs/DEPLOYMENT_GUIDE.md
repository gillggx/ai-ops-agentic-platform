# Deployment Guide

部署指南

## Table of Contents

- [Prerequisites](#prerequisites)
- [Local Development](#local-development)
- [Docker Deployment](#docker-deployment)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Production Checklist](#production-checklist)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### System Requirements

- Python 3.11+ or Docker
- PostgreSQL 13+
- Redis 6+
- Kubernetes 1.24+ (for K8s deployment)
- kubectl 1.24+
- Helm 3+

### Environment Setup

```bash
# Clone repository
git clone https://github.com/your-org/fastapi-backend.git
cd fastapi-backend

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -r requirements-dev.txt
```

## Local Development

### Setup Local Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with local configuration
# IMPORTANT: Change SECRET_KEY for production

# Initialize database
alembic upgrade head

# Create initial data
python scripts/init_data.py
```

### Run Local Server

```bash
# Method 1: Direct Python
python main.py

# Method 2: Using uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Method 3: Using Docker Compose
docker-compose up -d
```

### Access Local API

- **API Server**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## Docker Deployment

### Build Docker Image

```bash
# Build image
docker build -t fastapi-app:latest .

# Build with specific Python version
docker build --build-arg PYTHON_VERSION=3.14 -t fastapi-app:latest .

# Tag for registry
docker tag fastapi-app:latest ghcr.io/your-org/fastapi-app:latest
```

### Push to Registry

```bash
# Login to registry
docker login ghcr.io -u your-username -p your-token

# Push image
docker push ghcr.io/your-org/fastapi-app:latest
```

### Run Docker Container

```bash
# Single container (for development)
docker run -d \
  -p 8000:8000 \
  -e DATABASE_URL="postgresql://user:password@localhost/db" \
  -e REDIS_URL="redis://localhost:6379/0" \
  fastapi-app:latest

# Docker Compose (with all services)
docker-compose up -d

# Stop containers
docker-compose down
```

### Docker Compose Services

The `docker-compose.yml` includes:
- FastAPI application
- PostgreSQL database
- Redis cache
- RabbitMQ message queue
- Nginx reverse proxy
- Prometheus monitoring
- Grafana visualization

```bash
# View logs
docker-compose logs -f fastapi_app

# Enter container shell
docker-compose exec fastapi_app bash

# Run migrations
docker-compose exec fastapi_app alembic upgrade head
```

## Kubernetes Deployment

### Prerequisites

```bash
# Verify kubectl connection
kubectl cluster-info

# Check available contexts
kubectl config get-contexts

# Switch context if needed
kubectl config use-context your-cluster
```

### Create Namespace

```bash
# Create namespace
kubectl create namespace production

# Verify creation
kubectl get namespaces
```

### Create Secrets

```bash
# Create database secret
kubectl create secret generic fastapi-secrets \
  --from-literal=database-url="postgresql+asyncpg://user:pass@postgres:5432/db" \
  --from-literal=redis-url="redis://:password@redis:6379/0" \
  --from-literal=secret-key="your-secret-key" \
  -n production

# Verify secret
kubectl get secrets -n production
```

### Deploy with Helm

```bash
# Add Helm repository (if available)
helm repo add fastapi-app https://charts.example.com/fastapi-app
helm repo update

# Install using local chart
helm install fastapi-app ./deploy/helm \
  --namespace production \
  --values ./deploy/helm/values.yaml

# Upgrade deployment
helm upgrade fastapi-app ./deploy/helm \
  --namespace production \
  --values ./deploy/helm/values.yaml

# Verify installation
helm list -n production
```

### Deploy with kubectl

```bash
# Apply manifests
kubectl apply -f deploy/kubernetes/deployment.yaml \
              -f deploy/kubernetes/service.yaml \
              -n production

# Verify deployment
kubectl get deployments -n production
kubectl get pods -n production
kubectl get svc -n production
```

### Monitor Deployment

```bash
# Watch rollout status
kubectl rollout status deployment/fastapi-app -n production

# View pod logs
kubectl logs deployment/fastapi-app -n production -f

# Describe pod for events
kubectl describe pod <pod-name> -n production

# Get pod details
kubectl get pods -n production -o wide
```

### Scale Deployment

```bash
# Manual scaling
kubectl scale deployment fastapi-app --replicas=5 -n production

# Check HPA status
kubectl get hpa -n production

# View HPA metrics
kubectl describe hpa fastapi-app-hpa -n production
```

### Update Deployment

```bash
# Rolling update with new image
kubectl set image deployment/fastapi-app \
  fastapi-app=ghcr.io/your-org/fastapi-app:v2.1.0 \
  -n production

# Watch update progress
kubectl rollout status deployment/fastapi-app -n production

# Rollback if needed
kubectl rollout undo deployment/fastapi-app -n production
```

## Production Checklist

### Pre-Deployment

- [ ] All tests passing (`pytest tests/`)
- [ ] Code review completed
- [ ] Security scan passed
- [ ] Database migrations ready
- [ ] Environment variables configured
- [ ] SSL certificates prepared
- [ ] Monitoring configured
- [ ] Backup strategy defined
- [ ] Disaster recovery plan documented

### Deployment

- [ ] Database backups taken
- [ ] Health checks verified
- [ ] Load balancer configured
- [ ] DNS records updated
- [ ] SSL/TLS configured
- [ ] Rate limiting enabled
- [ ] CORS properly configured
- [ ] Monitoring alerts set up

### Post-Deployment

- [ ] Health checks passing
- [ ] Smoke tests successful
- [ ] Monitoring showing normal metrics
- [ ] Logs being collected
- [ ] Database replication working
- [ ] Cache warming complete
- [ ] Team notified of deployment
- [ ] Runbook updated

## Troubleshooting

### Common Issues

#### Application won't start

```bash
# Check logs
docker logs fastapi_app
# or
kubectl logs deployment/fastapi-app -n production

# Common causes:
# - Database not reachable
# - Invalid configuration
# - Missing dependencies
# - Port already in use
```

#### Database connection issues

```bash
# Test database connection
psql postgresql://user:password@host:5432/database

# Check PostgreSQL logs
docker logs fastapi_postgres

# Verify connection string
echo $DATABASE_URL
```

#### High memory usage

```bash
# Check memory usage
docker stats fastapi_app
# or
kubectl top pods -n production

# Causes:
# - Memory leak in code
# - Insufficient connection pooling
# - Large dataset operations
# - Cache memory issues
```

#### Slow API responses

```bash
# Check slow queries
psql -c "SELECT query, mean_time FROM pg_stat_statements ORDER BY mean_time DESC;"

# Check Redis performance
redis-cli --stat

# Check application logs for errors
docker logs -f fastapi_app
```

#### Pod CrashLoopBackOff

```bash
# Get pod events
kubectl describe pod <pod-name> -n production

# Check pod logs
kubectl logs <pod-name> -n production

# Common causes:
# - Readiness probe failing
# - Application crash on startup
# - Missing configuration
```

### Debug Commands

```bash
# Connect to running container
docker exec -it fastapi_app bash
# or
kubectl exec -it <pod-name> -n production -- bash

# Run Python interpreter
docker exec -it fastapi_app python

# Test database connection
docker exec -it fastapi_app \
  python -c "from app.core.database import DatabaseConfig; ..."

# View active connections
psql -c "SELECT * FROM pg_stat_activity;"

# Monitor query performance
watch -n 1 'psql -c "SELECT query, calls, mean_time FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;"'
```

## Performance Optimization

### Database

```bash
# Analyze table statistics
ANALYZE table_name;

# Reindex for performance
REINDEX TABLE table_name;

# Check index usage
SELECT schemaname, tablename, indexname, idx_scan 
FROM pg_stat_user_indexes 
ORDER BY idx_scan ASC;
```

### Cache

```bash
# Monitor Redis memory
redis-cli INFO memory

# Check eviction policy
redis-cli CONFIG GET maxmemory-policy

# Clear cache if needed
redis-cli FLUSHDB
```

### Application

```bash
# Check slow endpoints
curl http://localhost:8000/metrics | grep request_duration

# Monitor error rates
curl http://localhost:8000/metrics | grep errors

# Check cache hit rates
curl http://localhost:8000/metrics | grep cache_hits
```

## Scaling

### Horizontal Scaling

```bash
# Increase replicas
kubectl scale deployment fastapi-app --replicas=10 -n production

# Check HPA recommendations
kubectl get hpa -n production -o yaml
```

### Vertical Scaling

```bash
# Update resource limits
kubectl set resources deployment fastapi-app \
  --limits=cpu=1,memory=1Gi \
  --requests=cpu=500m,memory=512Mi \
  -n production
```

## Backup and Recovery

### Database Backup

```bash
# Backup PostgreSQL
pg_dump postgresql://user:password@host/database > backup.sql

# Backup with Docker
docker exec fastapi_postgres pg_dump -U appuser fastapi_db > backup.sql

# Restore backup
psql postgresql://user:password@host/database < backup.sql
```

### Redis Backup

```bash
# Backup Redis RDB
redis-cli BGSAVE

# Get backup location
redis-cli CONFIG GET dir
```

## References

- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)
- [Kubernetes Best Practices](https://kubernetes.io/docs/concepts/configuration/overview/)
- [Docker Documentation](https://docs.docker.com/)
- [Helm Documentation](https://helm.sh/docs/)
