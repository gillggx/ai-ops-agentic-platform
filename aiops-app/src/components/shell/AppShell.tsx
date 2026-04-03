"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Topbar } from "@/components/layout/Topbar";
import { EquipmentNavigator } from "@/components/ontology/EquipmentNavigator";
import { AICopilot } from "@/components/copilot/AICopilot";
import { AppProvider, useAppContext } from "@/context/AppContext";
import type { AIOpsReportContract } from "aiops-contract";

// ── Sidebar nav items ──────────────────────────────────────────────────────────

const STUDIO_ITEMS = [
  { href: "/admin/skills",       label: "Diagnostic Rules", icon: "🔧" },
  { href: "/admin/mcps",         label: "Analysis Views",   icon: "⚡" },
  { href: "/admin/auto-patrols", label: "Auto-Patrols",     icon: "🔍" },
];

const SYSTEM_ITEMS = [
  { href: "/system/data-sources",   label: "Data Sources",   icon: "🗄️" },
  { href: "/system/event-registry", label: "Event Registry", icon: "📋" },
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
  const { selectedEquipment, setSelectedEquipment } = useAppContext();

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

  if (pathname.startsWith("/admin")) {
    return (
      <nav style={sidebarStyle}>
        <div style={{ padding: "8px", flex: 1 }}>
          <SidebarSection title="Knowledge Studio" />
          {STUDIO_ITEMS.map(({ href, label, icon }) => (
            <NavLink key={href} href={href} icon={icon} label={label}
              active={pathname.startsWith(href)} />
          ))}
        </div>
      </nav>
    );
  }

  if (pathname.startsWith("/system")) {
    return (
      <nav style={sidebarStyle}>
        <div style={{ padding: "8px", flex: 1 }}>
          <SidebarSection title="System Admin" />
          {SYSTEM_ITEMS.map(({ href, label, icon }) => (
            <NavLink key={href} href={href} icon={icon} label={label}
              active={pathname.startsWith(href)} />
          ))}
        </div>
      </nav>
    );
  }

  // Operations Center — equipment navigator
  return (
    <aside style={sidebarStyle}>
      <EquipmentNavigator
        selectedId={selectedEquipment?.equipment_id ?? null}
        onSelect={(eq) => setSelectedEquipment(eq.equipment_id ? eq : null)}
      />
    </aside>
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

        {/* Center — route content */}
        <main style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
          {children}
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
