"use client";
import { useEffect, useRef } from "react";
import * as echarts from "echarts";

// ── Colour palette ────────────────────────────────────────────────────────────
const C = {
  events: "#7c3aed",   // violet
  apc:    "#0d9488",   // teal
  dc:     "#4f46e5",   // indigo
  spc:    "#d97706",   // amber
  recipe: "#0284c7",   // sky
  orphan: "#dc2626",   // red
};

const SUB_COLORS: Record<string, { main: string; light: string }> = {
  APC:    { main: C.apc,    light: "#5eead4" },
  DC:     { main: C.dc,     light: "#a5b4fc" },
  SPC:    { main: C.spc,    light: "#fcd34d" },
  RECIPE: { main: C.recipe, light: "#7dd3fc" },
};

// ── Types ─────────────────────────────────────────────────────────────────────
interface SubsystemStats {
  index_entries:    number;
  distinct_objects: number;
  compression_ratio: number | null;
}

export interface SankeyAuditData {
  subsystems:   Record<string, SubsystemStats>;
  event_fanout: { TOOL_EVENT: number; LOT_EVENT: number };
}

interface Props {
  audit:       SankeyAuditData;
  orphanCount: number;
}

// ── Build ECharts node/link arrays ────────────────────────────────────────────
function buildOption(audit: SankeyAuditData, orphanCount: number): echarts.EChartsOption {
  const totalEvents =
    (audit.event_fanout.TOOL_EVENT ?? 0) + (audit.event_fanout.LOT_EVENT ?? 0);

  const nodes: echarts.SankeySeriesOption["data"] = [
    { name: "Process Events", depth: 0, itemStyle: { color: C.events }, label: { color: "#c4b5fd" } },
  ];
  const links: echarts.SankeySeriesOption["links"] = [];

  for (const name of ["APC", "DC", "SPC", "RECIPE"]) {
    const stats = audit.subsystems[name];
    if (!stats) continue;
    const col = SUB_COLORS[name];

    nodes.push(
      { name: `${name} Index`,   depth: 1, itemStyle: { color: col.main  }, label: { color: "#e2e8f0" } },
      { name: `${name} Objects`, depth: 2, itemStyle: { color: col.light }, label: { color: "#cbd5e1" } },
    );

    // Process Events → Index
    links.push({
      source: "Process Events",
      target: `${name} Index`,
      value:  stats.index_entries,
      lineStyle: { color: col.main, opacity: 0.35 },
    });

    // Index → Objects (healthy)
    const healthyVal = stats.index_entries - orphanCount;
    links.push({
      source: `${name} Index`,
      target: `${name} Objects`,
      value:  Math.max(1, healthyVal),
      lineStyle: { color: col.light, opacity: 0.55 },
    });
  }

  // Orphan node + broken red links
  if (orphanCount > 0) {
    nodes.push({
      name: "⚡ Orphan",
      depth: 2,
      itemStyle: { color: C.orphan },
      label: { color: "#fca5a5", fontWeight: "bold" },
    });
    // Attach orphan link to first subsystem with data
    const firstSub = Object.keys(audit.subsystems)[0];
    if (firstSub) {
      links.push({
        source: `${firstSub} Index`,
        target: "⚡ Orphan",
        value:  orphanCount,
        lineStyle: { color: C.orphan, opacity: 0.85 },
      });
    }
  }

  return {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      triggerOn: "mousemove",
      backgroundColor: "#1e293b",
      borderColor: "#334155",
      textStyle: { color: "#e2e8f0", fontSize: 12 },
      formatter: (params: unknown) => {
        const p = params as { dataType?: string; name?: string; value?: number;
                               data?: { source?: string; target?: string; value?: number } };
        if (p.dataType === "edge") {
          const d = p.data!;
          return `<b>${d.source}</b> → <b>${d.target}</b><br/>Count: <b>${(d.value ?? 0).toLocaleString()}</b>`;
        }
        return `<b>${p.name}</b>`;
      },
    },
    series: [
      {
        type: "sankey",
        emphasis: { focus: "adjacency" },
        nodeGap: 20,
        nodeWidth: 18,
        left: "3%", right: "3%", top: "12%", bottom: "8%",
        label: {
          fontSize: 11,
          fontWeight: "bold",
          fontFamily: "'Inter', sans-serif",
        },
        lineStyle: { curveness: 0.48 },
        data:  nodes as echarts.SankeySeriesOption["data"],
        links: links as echarts.SankeySeriesOption["links"],
      },
    ],
  };
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function SankeyFlow({ audit, orphanCount }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current, null, { renderer: "canvas" });
    }
    chartRef.current.setOption(buildOption(audit, orphanCount), true);
  }, [audit, orphanCount]);

  // Responsive resize
  useEffect(() => {
    const obs = new ResizeObserver(() => chartRef.current?.resize());
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => { chartRef.current?.dispose(); chartRef.current = null; };
  }, []);

  return <div ref={containerRef} className="w-full h-full" />;
}
