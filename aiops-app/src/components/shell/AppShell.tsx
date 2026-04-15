"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Group, Panel, Separator } from "react-resizable-panels";
import { Topbar } from "@/components/layout/Topbar";
import { AICopilot } from "@/components/copilot/AICopilot";
import { AnalysisPanel } from "@/components/layout/AnalysisPanel";
import { DataExplorerPanel } from "@/components/layout/DataExplorerPanel";
import { AppProvider, useAppContext } from "@/context/AppContext";
import type { DataExplorerState } from "@/context/AppContext";
import type { AIOpsReportContract } from "aiops-contract";

// ── Navigation structure ──────────────────────────────────────────────────────

const OPS_ITEMS = [
  { href: "/alarms",             label: "Alarm Center",     icon: "🔔" },
  { href: "/dashboard",          label: "Dashboard",        icon: "📊" },
];

const KNOWLEDGE_ITEMS = [
  { href: "/admin/auto-patrols", label: "Auto-Patrols",     icon: "🔍" },
  { href: "/admin/skills",       label: "Diagnostic Rules", icon: "🔧" },
  { href: "/admin/my-skills",    label: "My Skills",        icon: "⭐" },
];

const ADMIN_ITEMS = [
  { href: "/system/skills",         label: "Skills",          icon: "⚙️" },
  { href: "/admin/memories",        label: "Agent Memory",    icon: "🧠" },
  { href: "/system/data-sources",   label: "Data Sources",    icon: "🗄️" },
  { href: "/system/event-registry", label: "Event Registry",  icon: "📋" },
  { href: "/system/monitor",        label: "System Monitor",  icon: "🖥️" },
];

function NavLink({ href, icon, label, active, collapsed }: {
  href: string; icon: string; label: string; active: boolean; collapsed: boolean;
}) {
  return (
    <Link href={href} title={collapsed ? label : undefined} style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: collapsed ? "var(--sp-md) 0" : "var(--sp-sm) var(--sp-md)",
      justifyContent: collapsed ? "center" : "flex-start",
      borderRadius: "var(--radius-md)",
      color: active ? "#2b6cb0" : "#4a5568",
      background: active ? "#ebf4ff" : "transparent",
      textDecoration: "none", fontSize: collapsed ? 18 : "var(--fs-sm)",
      fontWeight: active ? 600 : 400, marginBottom: 2,
      transition: "background 0.1s",
    }}>
      <span style={{ fontSize: collapsed ? 18 : 14, flexShrink: 0 }}>{icon}</span>
      {!collapsed && <span>{label}</span>}
    </Link>
  );
}

function SidebarSection({ title, collapsed }: { title: string; collapsed: boolean }) {
  if (collapsed) {
    return <div style={{ height: 1, background: "#e2e8f0", margin: "8px 6px" }} />;
  }
  return (
    <div style={{
      fontSize: "var(--fs-xs)", fontWeight: 600, color: "#a0aec0",
      padding: "var(--sp-sm) var(--sp-md) var(--sp-xs)", textTransform: "uppercase", letterSpacing: "0.5px",
    }}>
      {title}
    </div>
  );
}

// ── Left sidebar — collapsible VS Code style ─────────────────────────────────

function ContextualSidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(true);

  if (pathname.startsWith("/topology")) return null;

  const isExact = (href: string) =>
    href === "/dashboard" ? (pathname === "/" || pathname === "/dashboard") : pathname.startsWith(href);

  return (
    <nav style={{
      width: collapsed ? 48 : 200,
      minWidth: collapsed ? 48 : 200,
      flexShrink: 0,
      background: "#ffffff",
      borderRight: "1px solid #e2e8f0",
      display: "flex", flexDirection: "column",
      overflowY: "auto", overflowX: "hidden",
      transition: "width 0.2s, min-width 0.2s",
    }}>
      {/* Header with collapse toggle */}
      <div style={{
        padding: collapsed ? "12px 0" : "10px 12px",
        borderBottom: "1px solid #e2e8f0",
        display: "flex", alignItems: "center",
        justifyContent: collapsed ? "center" : "space-between",
        flexShrink: 0,
      }}>
        {!collapsed && <span style={{ fontSize: 14, fontWeight: 700, color: "#1a202c" }}>AIOps</span>}
        <button onClick={() => setCollapsed(c => !c)} title={collapsed ? "展開選單" : "收合選單"} style={{
          background: "none", border: "none", cursor: "pointer",
          color: "#718096", fontSize: 12, padding: "4px",
        }}>
          {collapsed ? "▶" : "◀"}
        </button>
      </div>

      <div style={{ padding: collapsed ? "4px" : "8px", flex: 1 }}>
        <SidebarSection title="Operations Center" collapsed={collapsed} />
        {OPS_ITEMS.map(({ href, label, icon }) => (
          <NavLink key={href} href={href} icon={icon} label={label}
            active={isExact(href)} collapsed={collapsed} />
        ))}

        <SidebarSection title="Knowledge Studio" collapsed={collapsed} />
        {KNOWLEDGE_ITEMS.map(({ href, label, icon }) => (
          <NavLink key={href} href={href} icon={icon} label={label}
            active={isExact(href)} collapsed={collapsed} />
        ))}

        <SidebarSection title="Admin" collapsed={collapsed} />
        {ADMIN_ITEMS.map(({ href, label, icon }) => (
          <NavLink key={href} href={href} icon={icon} label={label}
            active={isExact(href)} collapsed={collapsed} />
        ))}
      </div>
    </nav>
  );
}

// ── Inner shell ──────────────────────────────────────────────────────────────

function Shell({ children }: { children: React.ReactNode }) {
  const {
    triggerMessage, setTriggerMessage,
    contract, setContract,
    investigateMode, setInvestigateMode,
    selectedEquipment,
    dataExplorer, setDataExplorer,
  } = useAppContext();

  function handleContract(c: AIOpsReportContract) {
    setContract(c);
    setInvestigateMode(true);
  }

  function handleDataExplorer(de: DataExplorerState) {
    setDataExplorer(de);
    // Close investigate mode if open
    setInvestigateMode(false);
    setContract(null);
  }

  function handleHandoff(mcp: string, params?: Record<string, unknown>) {
    setTriggerMessage(`請執行 ${mcp}，參數：${JSON.stringify(params ?? {})}`);
  }

  return (
    <div style={{
      display: "flex", flexDirection: "column",
      height: "100vh", background: "#f7f8fc", overflow: "hidden",
    }}>
      <Topbar />
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <ContextualSidebar />
        <Group orientation="horizontal" style={{ flex: 1 }}>
          <Panel defaultSize={70} minSize={40}>
            <main style={{ height: "100%", overflowY: "auto", minWidth: 0 }}>
              {dataExplorer ? (
                <DataExplorerPanel
                  state={dataExplorer}
                  onClose={() => setDataExplorer(null)}
                />
              ) : investigateMode && contract ? (
                <AnalysisPanel
                  contract={contract}
                  onClose={() => { setInvestigateMode(false); setContract(null); }}
                  onAgentMessage={(msg) => setTriggerMessage(msg)}
                  onHandoff={handleHandoff}
                />
              ) : children}
            </main>
          </Panel>
          <Separator style={{
            width: 4, background: "#e2e8f0", cursor: "col-resize",
            transition: "background 0.15s",
          }} />
          <Panel defaultSize={30} minSize={20} maxSize={50}>
            <div style={{
              height: "100%", display: "flex", flexDirection: "column",
              background: "#ffffff", borderLeft: "1px solid #e2e8f0", overflow: "hidden",
            }}>
              <AICopilot
                onContract={handleContract}
                onDataExplorer={handleDataExplorer}
                triggerMessage={triggerMessage}
                onTriggerConsumed={() => setTriggerMessage(null)}
                contextEquipment={selectedEquipment?.name ?? null}
                onHandoff={handleHandoff}
              />
            </div>
          </Panel>
        </Group>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AppProvider>
      <Shell>{children}</Shell>
    </AppProvider>
  );
}
