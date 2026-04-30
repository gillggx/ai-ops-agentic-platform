"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { KpiStrip } from "./KpiStrip";
import { PulseStrip } from "./PulseStrip";
import { ClusterListPanel } from "./ClusterListPanel";
import { ClusterDetailPanel } from "./ClusterDetailPanel";
import { FocusedAgentPanel } from "./FocusedAgentPanel";
import type { Cluster, ClusterListResponse, Kpis } from "./types";
import type { Alarm } from "./AlarmDetailLegacy";

/** Tier 1+2 of the Alarm Center redesign. Owns:
 *   - cluster fetch (/api/admin/alarms/clusters)
 *   - kpi  fetch  (/api/admin/alarms/kpis)
 *   - per-cluster alarm-list fetch (existing /api/admin/alarms?status=...)
 *   - 60s polling for clusters + KPIs (matches PulseStrip note)
 *   - cross-pane selection state */
export function AlarmCenterShell() {
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [totalAlarms, setTotalAlarms] = useState(0);
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [loadingClusters, setLoadingClusters] = useState(false);

  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);
  const [sevFilter, setSevFilter] = useState<"all" | "high" | "med" | "low">("all");
  const [bayFilter, setBayFilter] = useState<"all" | "A" | "B" | "C">("all");

  // Per-cluster alarm cache: key=cluster_id → enriched alarms.
  const [alarmsByCluster, setAlarmsByCluster] = useState<Record<string, Alarm[]>>({});
  const [loadingAlarms, setLoadingAlarms] = useState(false);

  const refresh = useCallback(async () => {
    setLoadingClusters(true);
    try {
      const [clRes, kpiRes] = await Promise.all([
        fetch("/api/admin/alarms/clusters?since_hours=24&status=active"),
        fetch("/api/admin/alarms/kpis?since_hours=24"),
      ]);
      if (clRes.ok) {
        const data: ClusterListResponse = await clRes.json();
        setClusters(data.clusters || []);
        setTotalAlarms(data.total_alarms || 0);
      }
      if (kpiRes.ok) {
        const data: Kpis = await kpiRes.json();
        setKpis(data);
      }
    } finally { setLoadingClusters(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Refresh every 60s (PulseStrip already advertises this).
  useEffect(() => {
    const t = setInterval(refresh, 60_000);
    return () => clearInterval(t);
  }, [refresh]);

  // Auto-select the first cluster the first time data loads or after refresh
  // when the previous selection disappears.
  useEffect(() => {
    if (clusters.length === 0) { setSelectedClusterId(null); return; }
    if (selectedClusterId && clusters.some(c => c.cluster_id === selectedClusterId)) return;
    setSelectedClusterId(clusters[0].cluster_id);
  }, [clusters, selectedClusterId]);

  const selectedCluster = useMemo(
    () => clusters.find(c => c.cluster_id === selectedClusterId) ?? null,
    [clusters, selectedClusterId]
  );

  // Fetch per-cluster enriched alarms when selection changes (only if
  // not already cached for this cluster).
  useEffect(() => {
    const cl = selectedCluster;
    if (!cl) return;
    if (alarmsByCluster[cl.cluster_id]) return;
    setLoadingAlarms(true);
    (async () => {
      try {
        // We don't have an "ids=" endpoint yet; pull recent alarms and filter
        // by id locally. The alarm list endpoint is now fast (post hot-fix).
        const r = await fetch("/api/admin/alarms?status=active&days=7&limit=500");
        if (!r.ok) return;
        const d = await r.json();
        const all: Alarm[] = Array.isArray(d) ? d : (d?.data ?? []);
        const idSet = new Set(cl.alarm_ids);
        const matches = all.filter(a => idSet.has(a.id))
          .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        setAlarmsByCluster(prev => ({ ...prev, [cl.cluster_id]: matches }));
      } finally { setLoadingAlarms(false); }
    })();
  }, [selectedCluster?.cluster_id, alarmsByCluster, selectedCluster]);

  const onAcked = useCallback(() => {
    // Drop cache for this cluster + refresh the list/kpis so the count drops.
    if (selectedClusterId) {
      setAlarmsByCluster(prev => {
        const next = { ...prev };
        delete next[selectedClusterId];
        return next;
      });
    }
    refresh();
  }, [selectedClusterId, refresh]);

  const fullAlarms = selectedCluster ? (alarmsByCluster[selectedCluster.cluster_id] ?? []) : [];

  return (
    <div className="alarm-center">
      <KpiStrip kpis={kpis} />
      <PulseStrip kpis={kpis} />
      <ClusterListPanel
        clusters={clusters}
        totalAlarms={totalAlarms}
        sevFilter={sevFilter}
        setSevFilter={setSevFilter}
        bayFilter={bayFilter}
        setBayFilter={setBayFilter}
        selectedClusterId={selectedClusterId}
        onSelect={setSelectedClusterId}
        loading={loadingClusters}
      />
      <ClusterDetailPanel
        cluster={selectedCluster}
        fullAlarms={fullAlarms}
        loading={loadingAlarms}
      />
      <FocusedAgentPanel
        cluster={selectedCluster}
        fullAlarms={fullAlarms}
        onAcked={onAcked}
      />
      <style>{`@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }`}</style>
    </div>
  );
}
