# Scheduler Job Coordination

How `aiops-java-scheduler` avoids duplicate execution under multi-host
deployment, and what limits to respect.

## Current implementation

The scheduler uses **Redis-backed distributed locking** via
[`DistributedLockService.java`](../java-scheduler/src/main/java/com/aiops/scheduler/lock/DistributedLockService.java).
Every cron-driven action follows this pattern:

```java
String lockKey = "scheduler:patrol:" + patrolId;
if (lockService.tryAcquire(lockKey, ttlSeconds)) {
    try {
        executePatrol(patrolId);
    } finally {
        lockService.release(lockKey);
    }
} else {
    log.debug("patrol {} already running on another instance — skip", patrolId);
}
```

Backed by Redis `SET key value NX EX ttl` — atomic, no race window.

## Why this matters

In K8s, a `Deployment` may briefly run multiple pods during a rollout
(unless `strategy: Recreate` is set). Without locking, two pods would
fire the same cron tick and produce duplicate alarms / pipeline runs.

## Deployment rules

| Requirement | Reason |
|---|---|
| **replicas = 1** by default | Redis lock prevents duplicate execution, but only one pod actively schedules — saves CPU. |
| **strategy: Recreate** | Avoids transient 2-pod overlap during deploys. |
| **No HPA on this Deployment** | Auto-scaling would create extra schedulers that compete for locks (wasted work + clutters logs). |
| **Single Redis instance** | Lock is only as durable as Redis. For real HA add Redis Sentinel / Cluster. |

These are all enforced in
[`deploy/kubernetes/components/aiops-java-scheduler.yaml`](../deploy/kubernetes/components/aiops-java-scheduler.yaml).

## When to add leader election

If job volume grows enough that a single scheduler pod becomes the bottleneck:

1. Add a K8s `Lease`-based leader election (Spring Cloud Kubernetes
   `LeaderInitiator` or a Bedrock-style implementation).
2. Run N replicas; only the leader executes the `@Scheduled` methods.
3. Other replicas remain warm — instant failover when the leader's
   Lease expires.
4. Keep the Redis lock as a second line of defense (cheap insurance).

This is **not implemented today** — single replica + Redis lock has been
sufficient at current job volume.

## Failure modes

| Scenario | Behaviour |
|---|---|
| Scheduler pod crashes mid-execution | Lock TTL expires (default 5 min); next pod or restart re-runs the job. Side effects already written to DB stay. |
| Redis unreachable | `tryAcquire` returns false → job skipped that tick. Cron will retry next tick. Errors are warn-logged, scheduler does not crash. |
| Two pods race during rollout | First to `SET NX` wins; second skips silently. No duplicate fire. |
| Long-running job exceeds TTL | Second pod may also acquire and run a duplicate. Tune TTL to be > 95-percentile job duration; consider lock-extension heartbeat for jobs > 5 min. |

## Metrics & observability

Not yet exported as Prometheus metrics. Today the signal is:

- `skill_runs.triggered_by = 'system_schedule'` in Postgres — per-run audit
- Scheduler stdout JSON logs (filter `service=aiops-java-scheduler`, look
  for `trace_id=task_<uuid>` clustering per cron tick)

Future work (separate issue):

- Prometheus `Counter`: `scheduler_jobs_total{result=...}`
- Prometheus `Histogram`: `scheduler_job_duration_seconds`
- Prometheus `Gauge`: `scheduler_lock_holders` (>1 would be a red flag)

## Graceful shutdown

The Deployment spec sets `terminationGracePeriodSeconds: 30` with a small
`preStop sleep 5` so:

1. Service endpoint stops routing new requests to the pod.
2. preStop sleep gives any in-flight `@Scheduled` invocation a chance to
   finish naturally.
3. SIGTERM → Spring graceful shutdown waits up to 30s for active threads.
4. SIGKILL if it overruns.

Cron jobs longer than 30 seconds should checkpoint their progress to the
DB so a SIGKILL doesn't lose work. Today no job exceeds this window.
