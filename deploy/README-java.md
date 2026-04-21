# Java Migration — Deploy Runbook

## Topology

```
EC2 43.213.71.239

  :8000 — aiops-app  (Next.js)                     (unchanged)
  :8001 — fastapi-backend (Python, old)            (kept running during shadow + cutover)
  :8002 — aiops-java-api  (Spring Boot 3.5, NEW)   ← added by this deploy
  :8050 — aiops-python-sidecar (FastAPI, NEW)      ← added by this deploy
  :8012 — ontology-simulator                       (unchanged)

  + another project on this box — NOT TOUCHED
```

Throughout this runbook Java runs in **shadow mode** on `:8002` next to the old
Python on `:8001`. Nothing breaks Frontend until step §Cutover flips one env var.

## Files in this folder

| File | Purpose |
|---|---|
| `aiops-java-api.service` | systemd unit for Java API |
| `aiops-python-sidecar.service` | systemd unit for sidecar |
| `aiops-java-api.env.example` | template → `/opt/aiops/java-backend/.env` |
| `aiops-python-sidecar.env.example` | template → `/opt/aiops/python_ai_sidecar/.env` |
| `java-update.sh` | build + restart Java + sidecar in shadow mode |
| `java-rollback.sh` | stop Java + sidecar, ensure old Python is still serving |

## First-time install (on the EC2 box)

```bash
# SSH in
ssh -i ~/Desktop/aiops-ec2.pem ubuntu@43.213.71.239

cd /opt/aiops
git fetch origin
git checkout feat/java-api-rewrite
git pull

# Install JDK 21 (Temurin) — one-time.
sudo apt-get install -y wget gnupg
wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | sudo tee /etc/apt/trusted.gpg.d/adoptium.asc
echo "deb https://packages.adoptium.net/artifactory/deb $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/adoptium.list
sudo apt-get update && sudo apt-get install -y temurin-21-jdk

# Make a sidecar-specific venv (separate from fastapi-backend's).
sudo mkdir -p /opt/aiops/venv_sidecar /var/log/aiops
sudo chown -R ubuntu:ubuntu /opt/aiops /var/log/aiops

# Run the deploy (first invocation drops env templates for you to fill).
bash deploy/java-update.sh

# Edit real secrets into:
nano /opt/aiops/java-backend/.env
nano /opt/aiops/python_ai_sidecar/.env
# Important: PYTHON_SIDECAR_TOKEN in Java .env MUST EQUAL SERVICE_TOKEN in sidecar .env.
# Same for JAVA_INTERNAL_TOKEN <-> JAVA_INTERNAL_TOKEN.

# SHADOW-MODE EXTRAS (Python owns the schema while Java runs alongside):
# Add these to /opt/aiops/java-backend/.env:
#   AIOPS_PROFILE=local                   # OIDC-off, local BCrypt admin seeded
#   SPRING_JPA_HIBERNATE_DDL_AUTO=none    # don't validate Python's schema
#   SPRING_FLYWAY_ENABLED=false           # don't re-baseline
# Phase 7 flips these back once entity types are reconciled with Python's
# schema (user_id etc. are INT in Python, BIGINT in Java entities).

# CREATE audit_logs (Java-only table Python doesn't touch):
sudo -u postgres psql aiops_db -c "
CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  user_id BIGINT, username VARCHAR(150), roles VARCHAR(100),
  http_method VARCHAR(10) NOT NULL, endpoint VARCHAR(300) NOT NULL,
  status_code INTEGER, duration_ms BIGINT,
  remote_ip VARCHAR(45), user_agent VARCHAR(500),
  request_body TEXT, error_message TEXT);
ALTER TABLE audit_logs OWNER TO aiops;
GRANT ALL ON TABLE audit_logs TO aiops;
GRANT ALL ON SEQUENCE audit_logs_id_seq TO aiops;
CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id    ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_endpoint   ON audit_logs(endpoint);
"

# Re-run to pick up the real .env values.
bash deploy/java-update.sh
```

After this, both `aiops-java-api` and `aiops-python-sidecar` are running. The
old `fastapi-backend` is untouched. Frontend still points at `:8001`.

## Routine update

```bash
cd /opt/aiops
bash deploy/java-update.sh
```

No Frontend impact — Java restart on `:8002` doesn't affect traffic.

## Cutover (Java takes over Frontend traffic)

**Only do this after Phase 7** — Phase 5b ships a stub LLM, Phase 5c ships a
minimal pandas-free executor, so chat/build/execute semantics aren't yet at
parity with old Python. The cutover below is for when the real LLM +
pipeline_executor have been wired in `python_ai_sidecar/`.

```bash
# 1. Flip Frontend upstream.
sed -i 's|^FASTAPI_BASE_URL=.*|FASTAPI_BASE_URL=http://localhost:8002|' \
  /opt/aiops/aiops-app/.env.local

# 2. Restart Next.js.
sudo systemctl restart aiops-app.service

# 3. Smoke — should still be green.
curl -sf http://localhost:8000/
curl -sf http://localhost:8002/actuator/health

# 4. Watch journal for 30 minutes.
sudo journalctl -u aiops-java-api.service -f

# 5. Happy? Stop the old Python to free :8001.
sudo systemctl stop fastapi-backend.service
sudo systemctl disable fastapi-backend.service

# 6. (Optional) move Java from :8002 to :8001 — edit AIOPS_JAVA_PORT in .env,
#    update /api proxy in Frontend, restart both.
```

## Rollback (any time)

```bash
# 1. Flip Frontend back.
sed -i 's|^FASTAPI_BASE_URL=.*|FASTAPI_BASE_URL=http://localhost:8001|' \
  /opt/aiops/aiops-app/.env.local
sudo systemctl restart aiops-app.service

# 2. Stop Java stack, ensure old Python is up.
bash /opt/aiops/deploy/java-rollback.sh
```

## Observability

- `sudo journalctl -u aiops-java-api -f`
- `sudo journalctl -u aiops-python-sidecar -f`
- Java metrics: `curl http://localhost:8002/actuator/prometheus` (behind
  `IT_ADMIN` JWT for all non-health paths)
- Heap dump on OOM lands in `/var/log/aiops/java-heap-dump.hprof`

## Another project on this EC2

Do not touch. Our `java-update.sh` + `java-rollback.sh` only reference
`aiops-java-api` and `aiops-python-sidecar` systemd units. Nothing else.

## Cross-reference

- Phase 5a/5b/5c/5d/6 test reports: `docs/java_migration_qa/PHASE_*_TEST_REPORT.md`
- Main SPEC: `docs/SPEC_java_migration_v1.md`
