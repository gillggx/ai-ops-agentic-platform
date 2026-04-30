"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { KpiStrip } from "./KpiStrip";
import { PulseStrip } from "./PulseStrip";
import { ClusterListPanel } from "./ClusterListPanel";
import { ClusterDetailPanel } from "./ClusterDetailPanel";
import type { Cluster, ClusterListResponse, Kpis } from "./types";

/** Tier 1+2 of the Alarm Center redesign. 2-column shell:
 *   - Left: cluster rail
 *   - Right: cluster detail (cluster-level AI synthesis + drill-down rows)
 *  The previous "AI 助理" pane was removed (overlapped with the chat-side
 *  AI Agent); per-alarm details live on /alarms/[id] now. */
export function AlarmCenterShell() {
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [totalAlarms, setTotalAlarms] = useState(0);
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [loadingClusters, setLoadingClusters] = useState(false);

  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);
  const [sevFilter, setSevFilter] = useState<"all" | "high" | "med" | "low">("all");
  const [bayFilter, setBayFilter] = useState<"all" | "A" | "B" | "C">("all");

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
  useEffect(() => {
    const t = setInterval(refresh, 60_000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    if (clusters.length === 0) { setSelectedClusterId(null); return; }
    if (selectedClusterId && clusters.some(c => c.cluster_id === selectedClusterId)) return;
    setSelectedClusterId(clusters[0].cluster_id);
  }, [clusters, selectedClusterId]);

  const selectedCluster = useMemo(
    () => clusters.find(c => c.cluster_id === selectedClusterId) ?? null,
    [clusters, selectedClusterId]
  );

  const onAcked = useCallback(() => { refresh(); }, [refresh]);

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
        onAcked={onAcked}
      />
      <style>{`@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }`}</style>
    </div>
  );
}
