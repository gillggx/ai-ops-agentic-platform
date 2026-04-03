#!/bin/bash

# FastAPI Application Deployment Script
# FastAPI 应用程序部署脚本

set -e

# Color output
# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
# 配置
ENVIRONMENT=${1:-staging}
NAMESPACE=${2:-default}
IMAGE_TAG=${3:-latest}
HELM_RELEASE=${4:-fastapi-app}

# Logging functions
# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Check prerequisites
# 检查先决条件
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed"
    fi
    
    if ! command -v helm &> /dev/null; then
        log_error "helm is not installed"
    fi
    
    log_info "Prerequisites check passed"
}

# Create namespace if not exists
# 如果不存在，创建命名空间
create_namespace() {
    log_info "Creating namespace: $NAMESPACE"
    
    kubectl create namespace "$NAMESPACE" || log_warn "Namespace $NAMESPACE already exists"
}

# Create image pull secret
# 创建镜像拉取密钥
create_pull_secret() {
    log_info "Creating image pull secret..."
    
    local secret_name="ghcr-secret"
    local registry="ghcr.io"
    local username=${GHCR_USERNAME:-"your-username"}
    local token=${GHCR_TOKEN:-"your-token"}
    
    kubectl create secret docker-registry "$secret_name" \
        --docker-server="$registry" \
        --docker-username="$username" \
        --docker-password="$token" \
        -n "$NAMESPACE" || log_warn "Secret $secret_name already exists"
}

# Deploy with Helm
# 使用 Helm 部署
deploy_with_helm() {
    log_info "Deploying with Helm..."
    
    local chart_path="deploy/helm"
    local values_file="deploy/helm/values.yaml"
    
    if [ ! -f "$values_file" ]; then
        log_error "Values file not found: $values_file"
    fi
    
    helm upgrade --install "$HELM_RELEASE" "$chart_path" \
        --namespace "$NAMESPACE" \
        --values "$values_file" \
        --set image.tag="$IMAGE_TAG" \
        --set replicaCount=3 \
        --wait \
        --timeout 5m
    
    log_info "Helm deployment completed"
}

# Wait for deployment
# 等待部署
wait_for_deployment() {
    log_info "Waiting for deployment to be ready..."
    
    kubectl rollout status deployment/fastapi-app \
        -n "$NAMESPACE" \
        --timeout=10m
    
    log_info "Deployment is ready"
}

# Run smoke tests
# 运行冒烟测试
run_smoke_tests() {
    log_info "Running smoke tests..."
    
    local pod_name=$(kubectl get pods -n "$NAMESPACE" \
        -l app=fastapi-app \
        -o jsonpath='{.items[0].metadata.name}')
    
    if [ -z "$pod_name" ]; then
        log_error "No pods found for deployment"
    fi
    
    log_info "Testing pod: $pod_name"
    
    # Test health endpoint
    # 测试健康检查端点
    kubectl exec -it "$pod_name" -n "$NAMESPACE" \
        -- curl -f http://localhost:8000/health || log_error "Health check failed"
    
    # Test metrics endpoint
    # 测试指标端点
    kubectl exec -it "$pod_name" -n "$NAMESPACE" \
        -- curl -f http://localhost:8001/metrics || log_error "Metrics check failed"
    
    log_info "Smoke tests passed"
}

# Rollback deployment
# 回滚部署
rollback_deployment() {
    log_warn "Rolling back deployment..."
    
    helm rollback "$HELM_RELEASE" -n "$NAMESPACE"
    
    log_info "Rollback completed"
}

# Main deployment flow
# 主部署流程
main() {
    log_info "Starting deployment for $ENVIRONMENT environment"
    log_info "Namespace: $NAMESPACE"
    log_info "Image tag: $IMAGE_TAG"
    
    check_prerequisites
    create_namespace
    create_pull_secret
    deploy_with_helm
    wait_for_deployment
    
    if run_smoke_tests; then
        log_info "Deployment successful!"
    else
        log_error "Smoke tests failed, rolling back..."
        rollback_deployment
        log_error "Deployment failed"
    fi
}

# Error handling
# 错误处理
trap 'log_error "Deployment failed"; rollback_deployment' ERR

# Run main
# 运行主函数
main
