"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Topbar } from "@/components/layout/Topbar";
// EquipmentNavigator removed from sidebar — now embedded in Dashboard
import { AICopilot } from "@/components/copilot/AICopilot";
import { AnalysisPanel } from "@/components/layout/AnalysisPanel";
import { AppProvider, useAppContext } from "@/context/AppContext";
import type { AIOpsReportContract } from "aiops-contract";

// ── Sidebar nav items ──────────────────────────────────────────────────────────

// ── Navigation structure ──────────────────────────────────────────────────────

const OPS_ITEMS = [
  { href: "/alarms",             label: "Alarm Center",     icon: "🔔" },
  { href: "/",                   label: "Dashboard",        icon: "📊" },
];

const KNOWLEDGE_ITEMS = [
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

function NavLink({ href, icon, label, active }: {
  href: string; icon: string; label: string; active: boolean;
}) {
  return (
    <Link href={href} style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "9px 12px", borderRadius: 6,
      color: active ? "#2b6cb0" : "#4a5568",
      background: active ? "#ebf4ff" : "transparent",
      textDecoration: "none", fontSize: 13,
      fontWeight: active ? 600 : 400, marginBottom: 2,
      transition: "background 0.1s",
    }}>
      <span style={{ fontSize: 14 }}>{icon}</span>
      {label}
    </Link>
  );
}

function SidebarSection({ title }: { title: string }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 600, color: "#a0aec0",
      padding: "8px 12px 4px", textTransform: "uppercase", letterSpacing: "0.5px",
    }}>
      {title}
    </div>
  );
}

// ── Left sidebar — changes content based on active tab ─────────────────────────

function ContextualSidebar() {
  const pathname = usePathname();

  const sidebarStyle: React.CSSProperties = {
    width: 220, flexShrink: 0,
    background: "#ffffff",
    borderRight: "1px solid #e2e8f0",
    display: "flex", flexDirection: "column",
    overflowY: "auto",
  };

  if (pathname.startsWith("/topology")) {
    return null;
  }

  // Unified sidebar for all pages (except topology)
  const isExact = (href: string) => href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <nav style={sidebarStyle}>
      <div style={{ padding: "8px", flex: 1 }}>
        <SidebarSection title="Operations Center" />
        {OPS_ITEMS.map(({ href, label, icon }) => (
          <NavLink key={href} href={href} icon={icon} label={label}
            active={isExact(href)} />
        ))}

        <SidebarSection title="Knowledge Studio" />
        {KNOWLEDGE_ITEMS.map(({ href, label, icon }) => (
          <NavLink key={href} href={href} icon={icon} label={label}
            active={isExact(href)} />
        ))}

        <SidebarSection title="Admin" />
        {ADMIN_ITEMS.map(({ href, label, icon }) => (
          <NavLink key={href} href={href} icon={icon} label={label}
            active={isExact(href)} />
        ))}
      </div>
    </nav>
  );
}

// ── Inner shell (needs context) ────────────────────────────────────────────────

function Shell({ children }: { children: React.ReactNode }) {
  const {
    selectedEquipment,
    triggerMessage, setTriggerMessage,
    setContract, setInvestigateMode,
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
      {/* Top navigation — always visible */}
      <Topbar />

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Left — contextual sidebar, never unmounts */}
        <ContextualSidebar />

        {/* Center — route content OR analysis panel overlay */}
        <main style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
          {investigateMode && contract ? (
            <AnalysisPanel
              contract={contract}
              onClose={() => { setInvestigateMode(false); setContract(null); }}
              onAgentMessage={(msg) => setTriggerMessage(msg)}
              onHandoff={handleHandoff}
            />
          ) : (
            children
          )}
        </main>

        {/* Right — AI Co-Pilot, never unmounts = messages persist */}
        <aside style={{
          width: 360, flexShrink: 0,
          display: "flex", flexDirection: "column",
          background: "#ffffff",
          borderLeft: "1px solid #e2e8f0",
          overflow: "hidden",
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

// ── Public export ──────────────────────────────────────────────────────────────

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AppProvider>
      <Shell>{children}</Shell>
    </AppProvider>
  );
}
