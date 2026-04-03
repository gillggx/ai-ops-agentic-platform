"use client";

import { useEffect, useState, useCallback } from "react";

interface EquipmentItem {
  equipment_id: string;
  name: string;
  status: string;
}

interface Props {
  selectedId: string | null;
  onSelect: (eq: EquipmentItem) => void;
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

export function EquipmentNavigator({ selectedId, onSelect }: Props) {
  const [items, setItems] = useState<EquipmentItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchEquipment = useCallback(async () => {
    try {
      const res = await fetch("/api/ontology/equipment");
      if (!res.ok) return;
      const data = await res.json();
      setItems(data.items ?? []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEquipment();
    // Poll every 10s for live status
    const timer = setInterval(fetchEquipment, 10_000);
    return () => clearInterval(timer);
  }, [fetchEquipment]);

  const alarmCount = items.filter((i) => i.status === "alarm" || i.status === "down").length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Header */}
      <div style={{
        padding: "14px 16px 10px",
        borderBottom: "1px solid #e2e8f0",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "#718096", textTransform: "uppercase", letterSpacing: "0.5px" }}>
          設備狀態
        </span>
        {alarmCount > 0 && (
          <span style={{
            background: "#fed7d7",
            color: "#c53030",
            fontSize: 10,
            fontWeight: 700,
            padding: "2px 6px",
            borderRadius: 8,
          }}>
            {alarmCount} 告警
          </span>
        )}
      </div>

      {/* Equipment List */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {loading && (
          <div style={{ padding: "12px 16px", fontSize: 12, color: "#a0aec0" }}>載入中...</div>
        )}
        {items.map((item) => {
          const color = STATUS_COLOR[item.status] ?? "#a0aec0";
          const selected = selectedId === item.equipment_id;
          return (
            <button
              key={item.equipment_id}
              onClick={() => onSelect(item)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                width: "100%",
                padding: "10px 16px",
                background: selected ? "#ebf4ff" : "transparent",
                border: "none",
                borderLeft: selected ? "3px solid #2b6cb0" : "3px solid transparent",
                cursor: "pointer",
                textAlign: "left",
                transition: "background 0.12s",
              }}
            >
              <span style={{
                width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                background: color,
                boxShadow: item.status === "running" ? `0 0 6px ${color}60` : undefined,
              }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: selected ? 600 : 400, color: "#1a202c", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {item.name}
                </div>
                <div style={{ fontSize: 11, color }}>
                  {STATUS_LABEL[item.status] ?? item.status}
                </div>
              </div>
              <span style={{ fontSize: 10, color: "#a0aec0", fontFamily: "monospace" }}>
                {item.equipment_id}
              </span>
            </button>
          );
        })}
      </div>

      {/* Quick Actions */}
      <div style={{ padding: "12px 16px", borderTop: "1px solid #e2e8f0" }}>
        <div style={{ fontSize: 11, color: "#a0aec0", marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>
          快捷操作
        </div>
        <button
          onClick={() => onSelect({ equipment_id: "", name: "", status: "" })}
          style={{
            width: "100%",
            padding: "6px 10px",
            background: "transparent",
            border: "1px solid #e2e8f0",
            borderRadius: 6,
            fontSize: 12,
            color: "#718096",
            cursor: "pointer",
            textAlign: "left",
          }}
        >
          ← 返回總覽
        </button>
      </div>
    </div>
  );
}
