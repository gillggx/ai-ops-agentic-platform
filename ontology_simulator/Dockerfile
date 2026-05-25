# Dockerfile for ontology-simulator. Smaller than sidecar — no
# pandas/scipy, only fastapi + motor + nats.

FROM python:3.11-slim AS build
WORKDIR /build

COPY ontology_simulator/requirements.txt /build/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /build/requirements.txt

FROM python:3.11-slim
WORKDIR /app

RUN useradd -r -u 1001 -g root aiops

COPY --from=build /install /usr/local
COPY ontology_simulator /app
ENV PYTHONPATH=/app

USER 1001
EXPOSE 8080
ENV PORT=8080 \
    LOG_LEVEL=INFO

ENTRYPOINT ["sh","-c","exec uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
