# Multi-stage Dockerfile for FastAPI Application
# FastAPI 应用程序的多阶段 Dockerfile

# Stage 1: Builder Stage
# 第一阶段：构建阶段
FROM python:3.14-slim as builder

LABEL maintainer="Glass Box AI Team"
LABEL version="2.0.0"
LABEL description="FastAPI Backend - Builder Stage"

# Set environment variables
# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies for building
# 安装系统依赖项
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
# 创建虚拟环境
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements
# 复制需求文件
COPY requirements.txt .

# Install Python dependencies
# 安装 Python 依赖项
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# Stage 2: Runtime Stage
# 第二阶段：运行时阶段
FROM python:3.14-slim

LABEL maintainer="Glass Box AI Team"
LABEL version="2.0.0"
LABEL description="FastAPI Backend - Runtime Stage"

# Set working directory
# 设置工作目录
WORKDIR /app

# Set environment variables for production
# 设置生产环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH" \
    ENVIRONMENT=production

# Install runtime dependencies only
# 仅安装运行时依赖项
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
# 从构建器复制虚拟环境
COPY --from=builder /opt/venv /opt/venv

# Copy application code
# 复制应用程序代码
COPY ./app /app/app
COPY ./main.py /app/main.py
COPY ./pyproject.toml /app/pyproject.toml
COPY ./.env.example /app/.env.example

# Create necessary directories
# 创建必要的目录
RUN mkdir -p /app/logs \
    && mkdir -p /app/data \
    && chmod 755 /app/logs \
    && chmod 755 /app/data

# Create non-root user for security
# 为安全起见创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set permissions
# 设置权限
RUN chown -R appuser:appuser /app

# Switch to non-root user
# 切换到非 root 用户
USER appuser

# Health check
# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
# 暴露端口
EXPOSE 8000

# Run application with proper signal handling
# 运行应用程序并进行正确的信号处理
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
