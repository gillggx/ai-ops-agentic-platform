# Kubernetes Deployment

Manifests live in [`deploy/kubernetes/`](../deploy/kubernetes/). This guide
walks through bringing the platform up on any conformant K8s cluster
(minikube / kind / EKS / GKE / on-prem).

## Prerequisites

- K8s 1.27+ cluster with admin access (`kubectl` configured)
- `StorageClass` that supports `ReadWriteOnce` PVCs (default in all major clouds)
- Container images published to a registry your cluster can pull from
- For external access: an Ingress controller OR willingness to use NodePort

## 1. Build & push images

```bash
# From repo root:
docker build -f java-backend/Dockerfile         -t ghcr.io/gillggx/aiops-java-api:$(git rev-parse --short HEAD) .
docker build -f java-scheduler/Dockerfile       -t ghcr.io/gillggx/aiops-java-scheduler:$(git rev-parse --short HEAD) .
docker build -f python_ai_sidecar/Dockerfile    -t ghcr.io/gillggx/aiops-python-sidecar:$(git rev-parse --short HEAD) .
docker build -f ontology_simulator/Dockerfile   -t ghcr.io/gillggx/aiops-ontology-simulator:$(git rev-parse --short HEAD) .
# aiops-app needs the prod secrets as build-args (they bake into the bundle):
docker build -f aiops-app/Dockerfile \
  --build-arg INTERNAL_API_TOKEN=$INTERNAL_API_TOKEN \
  --build-arg NEXTAUTH_SECRET=$NEXTAUTH_SECRET \
  --build-arg FASTAPI_BASE_URL=http://aiops-java-api.aiops.svc.cluster.local \
  -t ghcr.io/gillggx/aiops-app:$(git rev-parse --short HEAD) .

# Push:
docker push ghcr.io/gillggx/aiops-java-api:...    # ... × 5
```

Update `deploy/kubernetes/components/*.yaml` to use your image tags
(replace `:latest` with the commit SHA).

## 2. Apply manifests

```bash
cd deploy/kubernetes

# Namespace + config
kubectl apply -f base/namespace.yaml
kubectl apply -f base/configmap.yaml

# Secrets (DO NOT commit real values; create directly):
kubectl -n aiops create secret generic aiops-secrets \
  --from-literal=INTERNAL_API_TOKEN=$(openssl rand -hex 32) \
  --from-literal=NEXTAUTH_SECRET=$(openssl rand -base64 32) \
  --from-literal=POSTGRES_PASSWORD=$(openssl rand -hex 16)
kubectl -n aiops create secret generic aiops-secrets-llm \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...

# Databases (StatefulSets — wait for Ready before continuing)
kubectl apply -f databases/
kubectl wait --for=condition=ready pod -l app=postgres -n aiops --timeout=180s
kubectl wait --for=condition=ready pod -l app=mongodb  -n aiops --timeout=180s
kubectl wait --for=condition=ready pod -l app=redis    -n aiops --timeout=60s

# Application services
kubectl apply -f components/

# Optional auto-scaling (stateless services only)
kubectl apply -f hpa/
```

## 3. Verify

```bash
kubectl get pods -n aiops
# Every pod Ready 1/1 (or 2/2 for the 2-replica deployments).

kubectl get svc -n aiops
# 5 service entries.

# Port-forward to the frontend:
kubectl port-forward -n aiops svc/aiops-app 8000:80
# → open http://localhost:8000
```

## 4. Scaling

```bash
# Stateless services scale freely:
kubectl scale -n aiops deploy/aiops-java-api --replicas=5
kubectl scale -n aiops deploy/aiops-python-sidecar --replicas=3

# Or use HPA (already configured for aiops-app):
kubectl get hpa -n aiops

# DO NOT scale aiops-java-scheduler beyond 1 unless you add leader
# election — see docs/scheduler-job-coordination.md.
```

## Exposing to users

The example uses `NodePort 30800` for aiops-app. For real prod:

```yaml
# Option A: LoadBalancer (cloud-managed)
apiVersion: v1
kind: Service
metadata:
  name: aiops-app
spec:
  type: LoadBalancer
  ports: [{port: 443, targetPort: 8080}]
  selector: {app: aiops-app}

# Option B: Ingress (with cert-manager / your TLS story)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: aiops-app
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  rules:
    - host: aiops.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: aiops-app
                port: {number: 80}
  tls:
    - hosts: [aiops.example.com]
      secretName: aiops-app-tls
```

Both omitted from this manifest set — cluster-specific.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Pods stuck `Pending` | No PVC binding / no storage class | `kubectl describe pod ...` — check events for `FailedScheduling` |
| `aiops-java-api` crashloops with `connection refused: postgres` | DB not yet Ready when api started | Restart: `kubectl rollout restart deploy/aiops-java-api -n aiops` |
| sidecar 401s | `INTERNAL_API_TOKEN` differs across pods | All envFrom references hit the same `aiops-secrets`; verify with `kubectl exec ... -- env \| grep INTERNAL` |
| `aiops-app` redirect loop | `NEXTAUTH_URL` env not matching public URL | Patch deployment env or rebuild image with new build-arg |
| HPA shows `<unknown>/70%` | Metrics-server not installed | `kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml` |
| Two scheduler pods running during rollout → duplicate cron firings | Default RollingUpdate strategy | Manifest uses `strategy: Recreate` to prevent this — verify it's still set if you edit |

## What's not covered (deferred)

- TLS / cert-manager
- Ingress controller install
- NetworkPolicy
- PodDisruptionBudgets
- Backup (Velero / native snapshots)
- Helm chart packaging
- Monitoring stack (Prometheus / Grafana / Loki / ELK)
- Multi-region / multi-cluster
