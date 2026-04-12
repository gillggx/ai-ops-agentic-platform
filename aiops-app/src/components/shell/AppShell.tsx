"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Topbar } from "@/components/layout/Topbar";
import { AICopilot } from "@/components/copilot/AICopilot";
import { AnalysisPanel } from "@/components/layout/AnalysisPanel";
import { AppProvider, useAppContext } from "@/context/AppContext";
import type { AIOpsReportContract } from "aiops-contract";

// ── Navigation structure ──────────────────────────────────────────────────────

const OPS_ITEMS = [
  { href: "/alarms",             label: "Alarm Center",     icon: "🔔" },
  { href: "/dashboard",          label: "Dashboard",        icon: "📊" },
];

const KNOWLEDGE_ITEMS = [
  { href: "/admin/my-skills",    label: "My Skills",        icon: "⭐" },
  { href: "/admin/auto-patrols", label: "Auto-Patrols",     icon: "🔍" },
  { href: "/admin/skills",       label: "Diagnostic Rules", icon: "🔧" },
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
      padding: collapsed ? "10px 0" : "9px 12px",
      justifyContent: collapsed ? "center" : "flex-start",
      borderRadius: 6,
      color: active ? "#2b6cb0" : "#4a5568",
      background: active ? "#ebf4ff" : "transparent",
      textDecoration: "none", fontSize: collapsed ? 18 : 13,
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
      fontSize: 10, fontWeight: 600, color: "#a0aec0",
      padding: "8px 12px 4px", textTransform: "uppercase", letterSpacing: "0.5px",
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
  } = useAppContext();

  function handleContract(c: AIOpsReportContract) {
    setContract(c);
    setInvestigateMode(true);
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
        <main style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
          {investigateMode && contract ? (
            <AnalysisPanel
              contract={contract}
              onClose={() => { setInvestigateMode(false); setContract(null); }}
              onAgentMessage={(msg) => setTriggerMessage(msg)}
              onHandoff={handleHandoff}
            />
          ) : children}
        </main>
        <aside style={{
          width: 360, flexShrink: 0,
          display: "flex", flexDirection: "column",
          background: "#ffffff", borderLeft: "1px solid #e2e8f0", overflow: "hidden",
        }}>
          <AICopilot
            onContract={handleContract}
            triggerMessage={triggerMessage}
            onTriggerConsumed={() => setTriggerMessage(null)}
            contextEquipment={selectedEquipment?.name ?? null}
            onHandoff={handleHandoff}
          />
        </aside>
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
