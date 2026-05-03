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
        const lot = lineage?.selected?.lot ?? lineage?.lots?.[0];
        const lotId = lot?.lot_id;
        const step = lot?.latest_step;
        const eventTime = lot?.latest_event_time;
        if (!lotId || !step || !eventTime) {
          if (!cancelled) {
            setErr("缺少 LOT / step / eventTime — 無法查詢拓樸");
            setLoading(false);
          }
          return;
        }
        // /api/ontology/topology requires lot + step + eventTime (otherwise 400).
        const url = `/api/ontology/topology?lot=${encodeURIComponent(lotId)}`
          + `&step=${encodeURIComponent(step)}`
          + `&eventTime=${encodeURIComponent(eventTime)}`;
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

  // .surface (background + border-radius) needs to be a flex column so
  // TopologyCanvas's outer `display: flex; flex: 1` can claim height.
  // Without this the canvas collapses to 0 effective height and renders
  // empty — the bug user reported when 拓樸圖 sub-tab shows blank.
  return (
    <div
      className="surface"
      style={{ minHeight: 600, height: 600, display: "flex", flexDirection: "column", overflow: "hidden" }}
    >
      {loading && (
        <div className="micro" style={{ padding: 16, color: "var(--c-ink-3)" }}>載入中…</div>
      )}
      {err && (
        <div className="small" style={{ padding: 16, color: "var(--c-crit)" }}>載入失敗：{err}</div>
      )}
      {!loading && !err && <TopologyCanvas snapshot={snapshot} centerType="TOOL" />}
    </div>
  );
}
