"use client";

import { useEffect, useState, useCallback } from "react";

interface EquipmentItem {
  equipment_id: string;
  name: string;
  status: string;
  chamber_count: number;
}

interface Props {
  onSelectEquipment: (eq: EquipmentItem) => void;
  onAskAgent: (message: string) => void;
}

const STATUS_COLOR: Record<string, string> = {
  running:     "#38a169",
  idle:        "#d69e2e",
  alarm:       "#e53e3e",
  maintenance: "#ed8936",
  down:        "#e53e3e",
};

const STATUS_LABEL: Record<string, string> = {
  running:     "運行中",
  idle:        "閒置",
  alarm:       "告警",
  maintenance: "維護",
  down:        "停機",
};

const STATUS_BG: Record<string, string> = {
  running:     "#f0fff4",
  idle:        "#fffff0",
  alarm:       "#fff5f5",
  maintenance: "#fffaf0",
  down:        "#fff5f5",
};

function KpiCard({ label, value, unit, color }: { label: string; value: string | number; unit?: string; color?: string }) {
  return (
    <div style={{
      background: "#ffffff",
      border: "1px solid #e2e8f0",
      borderRadius: 10,
      padding: "16px 20px",
      flex: 1,
    }}>
      <div style={{ fontSize: 11, color: "#718096", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
        <span style={{ fontSize: 28, fontWeight: 700, color: color ?? "#1a202c", lineHeight: 1 }}>
          {value}
        </span>
        {unit && <span style={{ fontSize: 12, color: "#718096" }}>{unit}</span>}
      </div>
    </div>
  );
}

export function OverviewDashboard({ onSelectEquipment, onAskAgent }: Props) {
  const [equipment, setEquipment] = useState<EquipmentItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchEquipment = useCallback(async () => {
    try {
      const res = await fetch("/api/ontology/equipment");
      if (!res.ok) return;
      const data = await res.json();
      setEquipment(data.items ?? []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEquipment();
    const timer = setInterval(fetchEquipment, 10_000);
    return () => clearInterval(timer);
  }, [fetchEquipment]);

  // Derived KPIs
  const total      = equipment.length;
  const running    = equipment.filter((e) => e.status === "running").length;
  const alarms     = equipment.filter((e) => e.status === "alarm" || e.status === "down").length;
  const maintenance = equipment.filter((e) => e.status === "maintenance").length;
  const utilization = total > 0 ? Math.round((running / total) * 100) : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Title */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#1a202c" }}>設備總覽</h2>
        {!loading && (
          <span style={{ fontSize: 12, color: "#a0aec0" }}>
            共 {total} 台 · 每 10 秒更新
          </span>
        )}
      </div>

      {/* KPI Row */}
      <div style={{ display: "flex", gap: 12 }}>
        <KpiCard label="設備稼動率"    value={`${utilization}`}  unit="%"  color={utilization >= 70 ? "#38a169" : "#d69e2e"} />
        <KpiCard label="運行中設備"    value={running}            unit="台"  color="var(--p, #2b6cb0)" />
        <KpiCard label="告警 / 停機"   value={alarms}             unit="台"  color={alarms > 0 ? "#e53e3e" : "#38a169"} />
        <KpiCard label="維護中"        value={maintenance}        unit="台"  color={maintenance > 0 ? "#ed8936" : "#718096"} />
      </div>

      {/* Equipment Grid */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#4a5568", marginBottom: 10 }}>設備狀態一覽</div>
        {loading ? (
          <div style={{ color: "#a0aec0", fontSize: 13 }}>載入中...</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
            {equipment.map((eq) => {
              const color = STATUS_COLOR[eq.status] ?? "#a0aec0";
              const bg    = STATUS_BG[eq.status]    ?? "var(--ws, #f7f8fc)";
              return (
                <button
                  key={eq.equipment_id}
                  onClick={() => onSelectEquipment(eq)}
                  style={{
                    background: bg,
                    border: `1px solid ${color}40`,
                    borderRadius: 10,
                    padding: "14px 16px",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "transform 0.12s, box-shadow 0.12s",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.boxShadow = "0 4px 12px rgba(0,0,0,0.08)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "none"; }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, flexShrink: 0 }} />
                    <span style={{ fontSize: 11, color, fontWeight: 600 }}>
                      {STATUS_LABEL[eq.status] ?? eq.status}
                    </span>
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#1a202c", marginBottom: 2 }}>
                    {eq.name}
                  </div>
                  <div style={{ fontSize: 11, color: "#718096" }}>
                    {eq.equipment_id} · {eq.chamber_count ?? 1} chamber
                  </div>
                  <div style={{
                    marginTop: 8,
                    fontSize: 11,
                    color: "var(--p, #2b6cb0)",
                    fontWeight: 500,
                  }}>
                    查看詳情 →
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

    </div>
  );
}
