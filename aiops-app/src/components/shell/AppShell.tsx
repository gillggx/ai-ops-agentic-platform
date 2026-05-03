"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
// Resizable panel via native CSS resize
import { Topbar } from "@/components/layout/Topbar";
import { AIAgentPanel } from "@/components/copilot/AIAgentPanel";
import { AnalysisPanel } from "@/components/layout/AnalysisPanel";
import { DataExplorerPanel } from "@/components/layout/DataExplorerPanel";
import { AppProvider, useAppContext } from "@/context/AppContext";
import type { DataExplorerState } from "@/context/AppContext";
import type { AIOpsReportContract } from "aiops-contract";

// v1.6 Lite Canvas overlay — wraps BuilderProvider + DagCanvas (read-only)
// with two tabs (Canvas / 結果). Pop-up over sidebar+main, leaves the right
// AI Agent rail uncovered. Replaces the old LiveCanvasOverlay (full
// BuilderLayout) and the floating PipelineResultsPanel for chat-driven runs.
const LiteCanvasOverlay = dynamic(
  () => import("@/components/copilot/LiteCanvasOverlay"),
  { ssr: false },
);
type RunPhase = "idle" | "building" | "build_failed" | "running" | "done" | "error";

interface GlassEvent {
  kind: "start" | "op" | "chat" | "error" | "done" | "user";
  sessionId?: string;
  goal?: string;
  op?: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  content?: string;
  message?: string;
  status?: string;
  summary?: string;
  pipeline_json?: unknown;
}

// ── Navigation structure ──────────────────────────────────────────────────────

// Role-based menu visibility (2026-04-25):
//   OPS_ITEMS      → all roles (ON_DUTY / PE / IT_ADMIN)
//   KNOWLEDGE      → PE + IT_ADMIN
//   ADMIN_ITEMS    → IT_ADMIN only
// RoleHierarchy in Java: IT_ADMIN > PE > ON_DUTY — a user with IT_ADMIN
// implicitly has PE + ON_DUTY authority server-side.

const OPS_ITEMS = [
  { href: "/alarms",             label: "Alarm Center",     icon: "🔔" },
  { href: "/dashboard",          label: "Dashboard",        icon: "📊" },
];

const KNOWLEDGE_ITEMS = [
  // Option A UX consolidation (2026-04-23): Pipeline Builder is the single
  // entry point for building & publishing. Auto-Patrols / Auto-Check Rules /
  // Published Skills are reachable via Admin → Triggers Overview.
  { href: "/admin/pipeline-builder",  label: "Pipeline Builder",       icon: "🧩" },
];

// Help section — visible to all logged-in roles. Currently the chart
// component catalog (/help/charts); future: agent-prompt cookbook,
// keyboard shortcuts cheatsheet, etc.
const HELP_ITEMS = [
  { href: "/help/charts", label: "Chart Catalog", icon: "📚" },
];

const ADMIN_ITEMS = [
  { href: "/admin/triggers",        label: "Triggers Overview", icon: "🔔" },
  { href: "/system/skills",         label: "Skills",          icon: "⚙️" },
  { href: "/admin/memories",        label: "Agent Memory",    icon: "🧠" },
  { href: "/system/data-sources",   label: "Data Sources",    icon: "🗄️" },
  { href: "/system/event-registry", label: "Event Registry",  icon: "📋" },
  { href: "/system/monitor",        label: "System Monitor",  icon: "🖥️" },
  { href: "/admin/users",           label: "Users",           icon: "👥" },
];

function userCanSeeOps(_roles: string[]): boolean {
  return true;  // all roles
}
function userCanSeeKnowledge(roles: string[]): boolean {
  return roles.includes("PE") || roles.includes("IT_ADMIN");
}
function userCanSeeAdmin(roles: string[]): boolean {
  return roles.includes("IT_ADMIN");
}

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
  const session = useSession();

  if (pathname.startsWith("/topology")) return null;

  const isExact = (href: string) =>
    href === "/dashboard" ? (pathname === "/" || pathname === "/dashboard") : pathname.startsWith(href);

  // Role-based menu filter. Trust the NextAuth session — middleware blocks
  // unauthenticated visitors at /login, so by the time this renders the
  // session always carries real roles. Empty roles ⇒ render no sections
  // (a degraded but safe UX over the old "show everything" fallback).
  const roles: string[] = (session?.data as unknown as { roles?: string[] })?.roles ?? [];

  const showOps = userCanSeeOps(roles);
  const showKnowledge = userCanSeeKnowledge(roles);
  const showAdmin = userCanSeeAdmin(roles);

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
        {showOps && (
          <>
            <SidebarSection title="Operations Center" collapsed={collapsed} />
            {OPS_ITEMS.map(({ href, label, icon }) => (
              <NavLink key={href} href={href} icon={icon} label={label}
                active={isExact(href)} collapsed={collapsed} />
            ))}
          </>
        )}

        {showKnowledge && (
          <>
            <SidebarSection title="Knowledge Studio" collapsed={collapsed} />
            {KNOWLEDGE_ITEMS.map(({ href, label, icon }) => (
              <NavLink key={href} href={href} icon={icon} label={label}
                active={isExact(href)} collapsed={collapsed} />
            ))}
          </>
        )}

        {showAdmin && (
          <>
            <SidebarSection title="Admin" collapsed={collapsed} />
            {ADMIN_ITEMS.map(({ href, label, icon }) => (
              <NavLink key={href} href={href} icon={icon} label={label}
                active={isExact(href)} collapsed={collapsed} />
            ))}
          </>
        )}

        {/* Help — bottom section, all logged-in roles see it */}
        <SidebarSection title="Help" collapsed={collapsed} />
        {HELP_ITEMS.map(({ href, label, icon }) => (
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
  // Phase 5-UX-5: right-side AI Agent is the sole entry (Topbar reverted).
  // Open by default so users see the chat prompt immediately.
  const [copilotOpen, setCopilotOpen] = useState(true);
  // Phase 5-UX-6: Live Glass Box overlay.
  // When chat agent calls build_pipeline_live, the first pb_glass_start event
  // opens this overlay with an empty canvas; subsequent pb_glass_op events
  // stream into it (node-by-node), and pb_glass_done closes off the build.
  const [glassOverlay, setGlassOverlay] = useState<{
    sessionId: string;
    goal?: string;
    active: boolean;
  } | null>(null);
  // Live stream of glass events consumed by LiveCanvasOverlay. Stored in a ref
  // + mirrored to state so the overlay can re-render on each event.
  const [glassEvents, setGlassEvents] = useState<GlassEvent[]>([]);
  const glassEventsRef = useRef<GlassEvent[]>([]);
  // v1.4 Plan Panel — relayed from AIAgentPanel so LiveCanvasOverlay
  // can render the same checklist (overlay covers the AIAgentPanel).
  const [overlayPlanItems, setOverlayPlanItems] = useState<import("@/components/copilot/PlanRenderer").PlanItem[]>([]);
  // Auto-run lifecycle for the Lite Canvas overlay's Results tab.
  const [pipelineResult, setPipelineResult] = useState<{
    summary: import("@/lib/pipeline-builder/types").PipelineResultSummary;
    nodeResults: Record<string, import("@/lib/pipeline-builder/types").NodeResult>;
  } | null>(null);
  const [runPhase, setRunPhase] = useState<RunPhase>("idle");
  const [runError, setRunError] = useState<string | null>(null);
  const [durationMs, setDurationMs] = useState<number | null>(null);

  const pushGlassEvent = (e: GlassEvent) => {
    glassEventsRef.current = [...glassEventsRef.current, e];
    setGlassEvents(glassEventsRef.current);
  };

  const resetGlassStream = () => {
    glassEventsRef.current = [];
    setGlassEvents([]);
  };

  const resetOverlayState = () => {
    resetGlassStream();
    setPipelineResult(null);
    setRunPhase("idle");
    setRunError(null);
    setDurationMs(null);
  };

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
        {/* Sidebar + main + copilot toggle live in a relative container so
            LiveCanvasOverlay can position-absolute over them without also
            covering the right AI Agent rail. */}
        <div style={{
          flex: 1, display: "flex", overflow: "hidden",
          position: "relative", minWidth: 0,
        }}>
          <ContextualSidebar />
          <main style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
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
          {/* Copilot toggle strip (always visible) */}
          <div
            onClick={() => setCopilotOpen(o => !o)}
            style={{
              width: 28, flexShrink: 0,
              display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", gap: 6,
              background: copilotOpen ? "#f7f8fc" : "#ebf8ff",
              borderLeft: "1px solid #e2e8f0",
              cursor: "pointer", userSelect: "none",
              transition: "background 0.15s",
            }}
            title={copilotOpen ? "收合 Copilot" : "展開 Copilot"}
          >
            <span style={{ fontSize: 14 }}>{copilotOpen ? "▶" : "◀"}</span>
            <span style={{
              writingMode: "vertical-rl", fontSize: 11, fontWeight: 600,
              color: copilotOpen ? "#a0aec0" : "#2b6cb0", letterSpacing: "1px",
            }}>
              AI Agent
            </span>
          </div>

          {/* Lite Canvas overlay — auto-opens on pb_glass_start. Hosts a
              read-only DagCanvas + a "結果" tab that shows the auto-run
              ResultsBody. Sits as an absolute layer over sidebar+main, not
              over the right AI Agent rail. */}
          {glassOverlay && (
            <LiteCanvasOverlay
              sessionId={glassOverlay.sessionId}
              goal={glassOverlay.goal}
              active={glassOverlay.active}
              events={glassEvents}
              planItems={overlayPlanItems}
              runPhase={runPhase}
              runError={runError}
              durationMs={durationMs}
              summary={pipelineResult?.summary ?? null}
              nodeResults={pipelineResult?.nodeResults ?? {}}
              onClose={() => {
                setGlassOverlay(null);
                resetOverlayState();
              }}
            />
          )}
        </div>

        {/* AI Agent panel (collapsible) */}
        {copilotOpen && (
          <aside style={{
            width: 380, minWidth: 280, maxWidth: "50vw", flexShrink: 0,
            display: "flex", flexDirection: "column",
            background: "#ffffff", borderLeft: "1px solid #e2e8f0", overflow: "hidden",
            resize: "horizontal", direction: "rtl",
          }}>
            <div style={{ direction: "ltr", display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
              <AIAgentPanel
                onContract={handleContract}
                onDataExplorer={handleDataExplorer}
                triggerMessage={triggerMessage}
                onTriggerConsumed={() => setTriggerMessage(null)}
                contextEquipment={selectedEquipment?.name ?? null}
                onHandoff={handleHandoff}
                // Suppress in-chat pb_pipeline card while the Lite Canvas
                // overlay is mounted — its left-side surface already shows the
                // DAG + results, so a second inline copy would just be
                // duplicate visual noise.
                liteCanvasActive={!!glassOverlay}
                // Phase 5-UX-6: mirror every user message into the overlay
                // event stream so the chat-style panel shows user bubbles.
                onUserMessageSent={(text) => {
                  pushGlassEvent({ kind: "user", content: text });
                }}
                // Phase 5-UX-6: Glass Box event wiring — chat agent streams
                // its sub-agent's operations here; AppShell mounts the live
                // canvas overlay so the user watches node-by-node build.
                onGlassStart={(ev) => {
                  // Open the Lite Canvas overlay and reset prior state so the
                  // build paints from a clean canvas + Results tab is empty.
                  resetOverlayState();
                  setRunPhase("building");
                  setGlassOverlay({
                    sessionId: ev.session_id,
                    goal: ev.goal,
                    active: true,
                  });
                  pushGlassEvent({ kind: "start", sessionId: ev.session_id, goal: ev.goal });
                }}
                onGlassOp={(ev) => pushGlassEvent({
                  kind: "op",
                  op: ev.op,
                  args: ev.args,
                  result: ev.result,
                })}
                onGlassChat={(ev) => pushGlassEvent({ kind: "chat", content: ev.content })}
                onGlassError={(ev) => pushGlassEvent({ kind: "error", message: ev.message })}
                onGlassDone={(ev) => {
                  pushGlassEvent({
                    kind: "done",
                    status: ev.status,
                    summary: ev.summary,
                    pipeline_json: ev.pipeline_json,
                  });
                  // Build done. If the agent gave up (MAX_TURNS, etc.), mark
                  // the phase build_failed so the overlay flips to Results
                  // and shows a takeover card. Otherwise stay in "building"
                  // until pb_run_start flips us to "running".
                  if (ev.status && ev.status !== "finished" && ev.status !== "success") {
                    setRunPhase("build_failed");
                    setRunError(ev.summary ?? `建構未完成（status=${ev.status}）`);
                  }
                  setGlassOverlay((prev) => prev ? { ...prev, active: false } : prev);
                }}
                // Plan items are owned by AIAgentPanel; relay to overlay so the
                // live canvas can show the same checklist if it wants to.
                onPlanItemsChange={setOverlayPlanItems}
                onPipelineResult={(summary, nodeResults) => {
                  setPipelineResult({ summary, nodeResults });
                }}
                onAutoRunStart={() => {
                  setRunPhase("running");
                  setRunError(null);
                  setDurationMs(null);
                }}
                onAutoRunDone={(ms) => {
                  setRunPhase("done");
                  setDurationMs(ms ?? null);
                }}
                onAutoRunError={(msg) => {
                  setRunPhase("error");
                  setRunError(msg);
                }}
              />
            </div>
          </aside>
        )}
      </div>

      {/* v1.6: chat-driven results live inside LiteCanvasOverlay's "結果" tab.
          Manual Run Full inside BuilderLayout still uses its own
          PipelineResultsPanel — that mount lives there, not here. */}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AppProvider>
      <ShellGate>{children}</ShellGate>
    </AppProvider>
  );
}

/** Render the full shell for authenticated pages; bypass for /login etc. */
function ShellGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // Bare pages — no sidebar, no topbar, no copilot. Login etc.
  const isBare = pathname === "/login" || pathname.startsWith("/api/auth");
  if (isBare) {
    return <>{children}</>;
  }
  return <Shell>{children}</Shell>;
}
