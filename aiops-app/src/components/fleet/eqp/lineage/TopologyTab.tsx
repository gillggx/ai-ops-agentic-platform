"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { TopologySnapshot } from "@/components/ontology/TopologyCanvas";

const TopologyCanvas = dynamic(
  () => import("@/components/ontology/TopologyCanvas").then(m => ({ default: m.TopologyCanvas })),
  { ssr: false, loading: () => <div className="micro" style={{ padding: 24, textAlign: "center", color: "var(--c-ink-3)" }}>載入拓樸圖…</div> }
);

/** Fetches the most recent LOT for {toolId}, then pulls
 *  /api/ontology/topology?lot=... so the canvas centres on this tool's
 *  latest run. v1 — Phase 3 plan keeps the existing component intact. */
export function TopologyTab({ toolId }: { toolId: string }) {
  const [snapshot, setSnapshot] = useState<TopologySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    (async () => {
      try {
        const lineageRes = await fetch(`/api/admin/fleet/equipment/${toolId}/lineage`);
        if (!lineageRes.ok) throw new Error(`lineage HTTP ${lineageRes.status}`);
        const lineage = await lineageRes.json();
        const lotId = lineage?.selected?.lot?.lot_id ?? lineage?.lots?.[0]?.lot_id;
        if (!lotId) {
          if (!cancelled) {
            setErr("無 LOT 可供拓樸");
            setLoading(false);
          }
          return;
        }
        const url = `/api/ontology/topology?lot=${encodeURIComponent(lotId)}&tool=${encodeURIComponent(toolId)}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`topology HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) setSnapshot(data as TopologySnapshot);
      } catch (e) {
        if (!cancelled) setErr(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [toolId]);

  return (
    <div className="surface" style={{ padding: 16, minHeight: 480 }}>
      {loading && <div className="micro" style={{ color: "var(--c-ink-3)" }}>載入中…</div>}
      {err && <div className="small" style={{ color: "var(--c-crit)" }}>載入失敗：{err}</div>}
      {!loading && !err && <TopologyCanvas snapshot={snapshot} centerType="TOOL" />}
    </div>
  );
}
