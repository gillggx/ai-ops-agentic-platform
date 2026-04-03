"use client";

import { useEffect, useState } from "react";
import { useAppContext } from "@/context/AppContext";
import { OverviewDashboard } from "@/components/ontology/OverviewDashboard";
import { EquipmentDetail } from "@/components/ontology/EquipmentDetail";
import { AnalysisPanel } from "@/components/layout/AnalysisPanel";
import { AlarmCenter } from "@/components/operations/AlarmCenter";

type Tab = "alarms" | "overview";

export default function Home() {
  const {
    selectedEquipment, setSelectedEquipment,
    setTriggerMessage,
    contract, setContract,
    investigateMode, setInvestigateMode,
  } = useAppContext();

  const [tab, setTab] = useState<Tab>("alarms");
  const [activeCount, setActiveCount] = useState(0);

  // Fetch active alarm count to decide default tab + tab badge
  useEffect(() => {
    fetch("/api/admin/alarms/stats")
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d) setActiveCount(d.total_active ?? 0);
      })
      .catch(() => {});
  }, []);

  function handleAskAgent(message: string) {
    setTriggerMessage(message);
  }

  function handleHandoff(mcp: string, params?: Record<string, unknown>) {
    setTriggerMessage(`請執行 ${mcp}，參數：${JSON.stringify(params ?? {})}`);
  }

  if (investigateMode && contract) {
    return (
      <AnalysisPanel
        contract={contract}
        onClose={() => { setInvestigateMode(false); setContract(null); }}
        onAgentMessage={handleAskAgent}
        onHandoff={handleHandoff}
      />
    );
  }

  if (selectedEquipment) {
    return (
      <EquipmentDetail
        equipmentId={selectedEquipment.equipment_id}
        onBack={() => setSelectedEquipment(null)}
        onAskAgent={handleAskAgent}
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Tab bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 4,
        padding: "8px 16px 0",
        background: "#fff",
        borderBottom: "1px solid #e2e8f0",
        flexShrink: 0,
      }}>
        <TabButton
          label="🔔 告警中心"
          active={tab === "alarms"}
          badge={activeCount}
          onClick={() => setTab("alarms")}
        />
        <TabButton
          label="📊 設備總覽"
          active={tab === "overview"}
          onClick={() => setTab("overview")}
        />
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
        {tab === "alarms" ? (
          <AlarmCenter />
        ) : (
          <OverviewDashboard
            onSelectEquipment={(eq) => setSelectedEquipment(eq.equipment_id ? eq : null)}
            onAskAgent={handleAskAgent}
          />
        )}
      </div>
    </div>
  );
}

function TabButton({
  label, active, badge, onClick,
}: {
  label: string; active: boolean; badge?: number; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "8px 16px",
        border: "none", borderBottom: active ? "2px solid #2b6cb0" : "2px solid transparent",
        background: "transparent",
        color: active ? "#2b6cb0" : "#718096",
        fontWeight: active ? 700 : 400,
        fontSize: 13, cursor: "pointer",
        marginBottom: -1,
        transition: "color 0.1s",
      }}
    >
      {label}
      {badge != null && badge > 0 && (
        <span style={{
          background: "#e53e3e", color: "#fff",
          fontSize: 10, fontWeight: 700,
          padding: "1px 5px", borderRadius: 8, lineHeight: 1.4,
        }}>
          {badge}
        </span>
      )}
    </button>
  );
}
