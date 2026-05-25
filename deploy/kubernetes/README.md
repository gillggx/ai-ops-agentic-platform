# Kubernetes Deployment

Minimum-viable manifest set for the AIOps platform. Apply in this order:

```bash
# 1. namespace + config + secrets
kubectl apply -f base/namespace.yaml
kubectl apply -f base/configmap.yaml
# Create real secrets (see base/secrets.example.yaml for the keys):
kubectl -n aiops create secret generic aiops-secrets \
  --from-literal=INTERNAL_API_TOKEN=$(openssl rand -hex 32) \
  --from-literal=NEXTAUTH_SECRET=$(openssl rand -base64 32) \
  --from-literal=POSTGRES_PASSWORD=$(openssl rand -hex 16)
kubectl -n aiops create secret generic aiops-secrets-llm \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...

# 2. databases (StatefulSet for postgres/mongodb; Deployment for redis)
kubectl apply -f databases/

# 3. application services (wait for DBs Ready first)
kubectl wait --for=condition=ready pod -l app=postgres -n aiops --timeout=180s
kubectl wait --for=condition=ready pod -l app=mongodb -n aiops --timeout=180s
kubectl wait --for=condition=ready pod -l app=redis -n aiops --timeout=60s

kubectl apply -f components/

# 4. optional autoscaling (stateless services only — never the scheduler)
kubectl apply -f hpa/
```

See `docs/deploy-kubernetes.md` for the full guide, troubleshooting,
and migration notes. Job coordination details for the scheduler live in
`docs/scheduler-job-coordination.md`.

## Out of scope (deferred)

- **Ingress / TLS / cert-manager** — cluster-specific. The example exposes
  aiops-app via NodePort 30800. Swap to your own Ingress controller for prod.
- **NetworkPolicy** — recommended but not included.
- **Helm chart** — manifests are plain YAML; Helm packaging can come later.
- **Logging / monitoring stack** — see `docs/logging-schema.md`. ELK / Fluent
  Bit setup is environment-specific.
