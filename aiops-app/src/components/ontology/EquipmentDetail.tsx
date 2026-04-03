"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { VegaLiteChart } from "@/components/contract/visualizations/VegaLiteChart";

interface Equipment {
  equipment_id: string;
  name: string;
  status: string;
  chamber_count: number;
}

interface DcPoint {
  timestamp: string;
  value: number;
  is_ooc: boolean;
}

interface DcData {
  ucl: number;
  lcl: number;
  mean: number;
  data: DcPoint[];
}

interface EventItem {
  event_id: string;
  event_type: string;
  severity: string;
  description: string;
  timestamp: string;
}

interface Props {
  equipmentId: string;
  onBack: () => void;
  onAskAgent: (message: string) => void;
}

const STATUS_COLOR: Record<string, string> = {
  running: "#38a169", idle: "#d69e2e", alarm: "#e53e3e",
  maintenance: "#ed8936", down: "#e53e3e",
};
const STATUS_LABEL: Record<string, string> = {
  running: "運行中", idle: "閒置", alarm: "告警",
  maintenance: "維護", down: "停機",
};
const SEVERITY_COLOR: Record<string, string> = {
  critical: "#e53e3e", warning: "#d69e2e", info: "#718096",
};

function buildSpcSpec(dc: DcData): Record<string, unknown> {
  const ruleData = [
    { label: "UCL", y: dc.ucl, color: "#e53e3e" },
    { label: "Mean", y: dc.mean, color: "#718096" },
    { label: "LCL", y: dc.lcl, color: "#3182ce" },
  ];

  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    width: "container",
    height: 220,
    background: "transparent",
    layer: [
      // Control limit rules
      {
        data: { values: ruleData },
        mark: { type: "rule", strokeDash: [4, 3], strokeWidth: 1.5 },
        encoding: {
          y: { field: "y", type: "quantitative" },
          color: {
            field: "label",
            scale: { domain: ["UCL", "Mean", "LCL"], range: ["#e53e3e", "#a0aec0", "#3182ce"] },
            legend: { title: "Control Limits", orient: "bottom-right", labelFontSize: 10, titleFontSize: 10 },
          },
          strokeDash: { value: [4, 3] },
        },
      },
      // Main line
      {
        data: { values: dc.data },
        mark: { type: "line", color: "#3182ce", strokeWidth: 1.5 },
        encoding: {
          x: { field: "timestamp", type: "temporal", axis: { labelAngle: -30, labelFontSize: 10, title: null } },
          y: { field: "value", type: "quantitative", axis: { title: "Value", labelFontSize: 10, titleFontSize: 11 } },
        },
      },
      // OOC dots
      {
        data: { values: dc.data.filter((p) => p.is_ooc) },
        mark: { type: "point", filled: true, color: "#e53e3e", size: 60 },
        encoding: {
          x: { field: "timestamp", type: "temporal" },
          y: { field: "value", type: "quantitative" },
          tooltip: [
            { field: "timestamp", type: "temporal", title: "時間" },
            { field: "value", type: "quantitative", title: "數值" },
          ],
        },
      },
    ],
  };
}

export function EquipmentDetail({ equipmentId, onBack, onAskAgent }: Props) {
  const [equipment, setEquipment] = useState<Equipment | null>(null);
  const [dc, setDc] = useState<DcData | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    const now = new Date();
    const start = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    const fmt = (d: Date) => d.toISOString();

    try {
      const [eqRes, dcRes, evRes] = await Promise.all([
        fetch(`/api/ontology/equipment/${equipmentId}`),
        fetch(`/api/ontology/equipment/${equipmentId}/dc/timeseries?parameter=Temperature&start=${fmt(start)}&end=${fmt(now)}`),
        fetch(`/api/ontology/events?equipment_id=${equipmentId}&start=${fmt(start)}&end=${fmt(now)}`),
      ]);

      if (eqRes.ok) setEquipment(await eqRes.json());
      if (dcRes.ok) setDc(await dcRes.json());
      if (evRes.ok) {
        const evData = await evRes.json();
        setEvents((evData.items ?? []).slice(-20).reverse()); // latest first, max 20
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [equipmentId]);

  useEffect(() => {
    setLoading(true);
    setEquipment(null);
    setDc(null);
    setEvents([]);
    fetchAll();
  }, [fetchAll]);

  if (loading) {
    return (
      <div style={{ padding: 24, color: "#a0aec0", fontSize: 13 }}>
        載入 {equipmentId} 資料中...
      </div>
    );
  }

  const statusColor = STATUS_COLOR[equipment?.status ?? ""] ?? "#a0aec0";
  const oocCount = dc?.data.filter((p) => p.is_ooc).length ?? 0;
  const spcSpec = dc ? buildSpcSpec(dc) : null;

  return (
    <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button
          onClick={onBack}
          style={{
            background: "transparent",
            border: "1px solid #e2e8f0",
            borderRadius: 6,
            padding: "4px 10px",
            fontSize: 12,
            color: "#718096",
            cursor: "pointer",
          }}
        >
          ← 返回
        </button>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#1a202c" }}>
              {equipment?.name ?? equipmentId}
            </h2>
            <span style={{
              padding: "2px 8px",
              borderRadius: 12,
              fontSize: 11,
              fontWeight: 600,
              background: `${statusColor}20`,
              color: statusColor,
            }}>
              {STATUS_LABEL[equipment?.status ?? ""] ?? equipment?.status}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "#a0aec0", marginTop: 2 }}>
            {equipmentId} · Chamber: {equipment?.chamber_count ?? 1}
          </div>
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <Link
            href={`/topology?type=tool&id=${encodeURIComponent(equipmentId)}`}
            style={{
              padding: "6px 14px",
              background: "#f0fff4",
              border: "1px solid #c6f6d5",
              borderRadius: 6,
              fontSize: 12,
              color: "#276749",
              cursor: "pointer",
              fontWeight: 500,
              textDecoration: "none",
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            Topology
          </Link>
          <button
            onClick={() => onAskAgent(`${equipmentId} 最近有哪些異常？請分析根因。`)}
            style={{
              padding: "6px 14px",
              background: "#ebf4ff",
              border: "1px solid #bee3f8",
              borderRadius: 6,
              fontSize: 12,
              color: "#2b6cb0",
              cursor: "pointer",
              fontWeight: 500,
            }}
          >
            AI 診斷
          </button>
        </div>
      </div>

      {/* Stats Row */}
      <div style={{ display: "flex", gap: 12 }}>
        {[
          { label: "UCL",     value: dc?.ucl?.toFixed(2) ?? "—" },
          { label: "Mean",    value: dc?.mean?.toFixed(2) ?? "—" },
          { label: "LCL",     value: dc?.lcl?.toFixed(2) ?? "—" },
          { label: "OOC 次數", value: oocCount, color: oocCount > 0 ? "#e53e3e" : "#38a169" },
          { label: "事件數",   value: events.length },
        ].map(({ label, value, color }) => (
          <div key={label} style={{
            background: "#ffffff",
            border: "1px solid #e2e8f0",
            borderRadius: 8,
            padding: "10px 14px",
            flex: 1,
          }}>
            <div style={{ fontSize: 10, color: "#a0aec0", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.4px", marginBottom: 4 }}>
              {label}
            </div>
            <div style={{ fontSize: 20, fontWeight: 700, color: color ?? "#1a202c" }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      {/* SPC Chart */}
      <div style={{
        background: "#ffffff",
        border: "1px solid #e2e8f0",
        borderRadius: 10,
        padding: "16px 20px",
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#4a5568", marginBottom: 12 }}>
          Temperature SPC 管制圖（最近 24 小時）
        </div>
        {spcSpec ? (
          <VegaLiteChart spec={spcSpec} />
        ) : (
          <div style={{ height: 220, display: "flex", alignItems: "center", justifyContent: "center", color: "#a0aec0", fontSize: 12 }}>
            無 SPC 資料
          </div>
        )}
      </div>

      {/* Event Log */}
      <div style={{
        background: "#ffffff",
        border: "1px solid #e2e8f0",
        borderRadius: 10,
        padding: "16px 20px",
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#4a5568", marginBottom: 12 }}>
          事件紀錄（最近 24 小時，最新優先）
        </div>
        {events.length === 0 ? (
          <div style={{ color: "#a0aec0", fontSize: 12 }}>無事件</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {events.map((ev) => {
              const sevColor = SEVERITY_COLOR[ev.severity] ?? "#718096";
              return (
                <div key={ev.event_id} style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  padding: "8px 10px",
                  background: `${sevColor}08`,
                  borderRadius: 6,
                  borderLeft: `3px solid ${sevColor}`,
                }}>
                  <span style={{
                    padding: "1px 6px",
                    borderRadius: 4,
                    fontSize: 10,
                    fontWeight: 700,
                    background: `${sevColor}20`,
                    color: sevColor,
                    flexShrink: 0,
                    marginTop: 1,
                  }}>
                    {ev.severity.toUpperCase()}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, color: "#1a202c", fontWeight: 500 }}>
                      {ev.description}
                    </div>
                    <div style={{ fontSize: 11, color: "#a0aec0", marginTop: 2 }}>
                      {ev.event_type} · {new Date(ev.timestamp).toLocaleString("zh-TW", { hour12: false })}
                    </div>
                  </div>
                  <button
                    onClick={() => onAskAgent(`請分析 ${equipmentId} 的 ${ev.event_type} 事件 (${ev.description})`)}
                    style={{
                      padding: "3px 8px",
                      background: "transparent",
                      border: "1px solid #bee3f8",
                      borderRadius: 4,
                      fontSize: 10,
                      color: "#2b6cb0",
                      cursor: "pointer",
                      flexShrink: 0,
                    }}
                  >
                    診斷▸
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
