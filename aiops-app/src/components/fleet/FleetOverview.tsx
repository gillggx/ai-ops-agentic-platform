"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { FleetBriefingHero } from "./FleetBriefingHero";
import { TopConcernsRow } from "./TopConcernsRow";
import { ToolList } from "./ToolList";
import type {
  FleetConcern, FleetConcernResponse,
  FleetEquipment, FleetEquipmentResponse,
  FleetStats,
} from "./types";

const FONT_LINK = "https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap";

/** Fleet Overview = the new Mode A of /dashboard. Replaces FabHeatmap +
 *  the legacy BriefingPanel. Mode B (?toolId=XX) is unaffected; the
 *  parent page.tsx switches between them based on the URL param.
 *
 *  Reference: docs/SPEC_dashboard_redesign_v1_phase1.md §2.2 */
export function FleetOverview({ onOpenTool }: { onOpenTool?: (id: string) => void }) {
  const router = useRouter();
  const [equipment, setEquipment] = useState<FleetEquipment[]>([]);
  const [concerns, setConcerns] = useState<FleetConcern[]>([]);
  const [stats, setStats] = useState<FleetStats | null>(null);
  const [loading, setLoading] = useState(false);

  // Lazy-load fonts only when this view mounts.
  useEffect(() => {
    const id = "fleet-overview-fonts";
    if (document.getElementById(id)) return;
    const link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    link.href = FONT_LINK;
    document.head.appendChild(link);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [eqRes, cnRes, stRes] = await Promise.all([
        fetch("/api/admin/fleet/equipment?since_hours=24"),
        fetch("/api/admin/fleet/concerns?since_hours=24"),
        fetch("/api/admin/fleet/stats?since_hours=24"),
      ]);
      if (eqRes.ok) {
        const j: FleetEquipmentResponse = await eqRes.json();
        setEquipment(j.equipment ?? []);
      }
      if (cnRes.ok) {
        const j: FleetConcernResponse = await cnRes.json();
        setConcerns(j.concerns ?? []);
      }
      if (stRes.ok) {
        const j: FleetStats = await stRes.json();
        setStats(j);
      }
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const t = setInterval(refresh, 5 * 60_000);
    return () => clearInterval(t);
  }, [refresh]);

  const openTool = (id: string) => {
    if (onOpenTool) onOpenTool(id);
    else router.push(`/dashboard?toolId=${id}`);
  };

  return (
    <div className="fleet-overview">
      <div className="fleet-overview__topbar">
        <div className="fleet-overview__title">全廠總覽</div>
        <div className="micro" style={{ color: "var(--c-ink-3)" }}>
          近 24 小時 · {stats ? `更新於 ${new Date(stats.as_of).toLocaleTimeString("zh-TW", { hour12: false })}` : "—"}
        </div>
      </div>

      <FleetBriefingHero stats={stats} equipment={equipment} concerns={concerns} />

      <TopConcernsRow
        concerns={concerns}
        onDrill={c => {
          if (c.tools.length > 0) openTool(c.tools[0]);
        }}
      />

      <ToolList tools={equipment} concerns={concerns} onOpenTool={openTool} />

      {loading && equipment.length === 0 && (
        <div className="fleet-overview__empty">載入中…</div>
      )}
      {!loading && equipment.length === 0 && (
        <div className="fleet-overview__empty">
          <div style={{ fontSize: 32, marginBottom: 8 }}>📡</div>
          <div>目前無機台資料 — 等 simulator 餵入</div>
        </div>
      )}
    </div>
  );
}
