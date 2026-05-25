# Multi-stage Dockerfile for aiops-python-sidecar.
# Stage 1: install deps in a builder. Stage 2: copy installed packages
# into a slim runtime to keep the final image lean (~450MB).

FROM python:3.11-slim AS build
WORKDIR /build

# System libs needed by pandas/numpy/scipy + httpx.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY python_ai_sidecar/requirements.txt /build/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /build/requirements.txt

FROM python:3.11-slim
WORKDIR /app

# Runtime needs the C libs that pandas/scipy linked against.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 1001 -g root aiops

COPY --from=build /install /usr/local
COPY python_ai_sidecar /app/python_ai_sidecar
# aiops-contract Python types are imported by sidecar at runtime.
COPY aiops-contract/python /app/aiops-contract/python
ENV PYTHONPATH=/app:/app/aiops-contract/python

USER 1001
EXPOSE 8080
ENV PORT=8080 \
    LOG_LEVEL=INFO

ENTRYPOINT ["sh","-c","exec uvicorn python_ai_sidecar.main:app --host 0.0.0.0 --port ${PORT}"]
