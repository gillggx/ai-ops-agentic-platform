"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import { useTranslations } from "next-intl";
// Resizable panel via native CSS resize
import { ChatOpsAgentRail } from "@/components/chatops/ChatOpsAgentRail";
import type { DraftCardData } from "@/components/chatops/DraftCard";
import { MobileShell } from "@/components/mobile/MobileShell";
import { Topbar } from "@/components/layout/Topbar";
import HandoffListener from "@/components/shell/HandoffListener";
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
  /** ChatOps rail Console card (2026-07-10): stamped at push time. */
  ts?: string;
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
  /** v31.3 — on kind:"start" of an incremental build: the existing canvas
   *  to seed, so ops referencing pre-existing nodes apply cleanly. */
  base_pipeline?: unknown;
}

// ── Navigation structure ──────────────────────────────────────────────────────

// Role-based menu visibility (2026-04-25):
//   OPS_ITEMS      → all roles (ON_DUTY / PE / IT_ADMIN)
//   KNOWLEDGE      → PE + IT_ADMIN
//   ADMIN_ITEMS    → IT_ADMIN only
// RoleHierarchy in Java: IT_ADMIN > PE > ON_DUTY — a user with IT_ADMIN
// implicitly has PE + ON_DUTY authority server-side.

// labelKey → messages/<locale>/nav.json
const OPS_ITEMS = [
  { href: "/alarms",             labelKey: "alarmCenter",     icon: "🔔" },
  // 2026-06-27 — Patrol Activity: see "what happened between events and
  // the alarms that landed". Non-emoji icon per feedback_no_emoji rule;
  // legacy emojis above predate the rule and stay as-is.
  { href: "/patrol-activity",    labelKey: "patrolActivity",  icon: "○" },
  { href: "/dashboard",          labelKey: "dashboard",       icon: "📊" },
];

const KNOWLEDGE_ITEMS = [
  // Phase 11 v6 — Skill Library is the SINGLE knowledge-authoring entry
  // point. Pipeline Builder is no longer linked from the main nav; it
  // reachable only via Skill → Build/Refine → embed=skill (see
  // SkillEmbedBanner). Direct hits to /admin/pipeline-builder redirect
  // back to /skills.
  { href: "/skills",                  labelKey: "skillLibrary",        icon: "📖" },
  // 草稿暫存區 (V78) — chat-built pipelines auto-parked here (most-recent 10).
  { href: "/drafts",                  labelKey: "draftShelf",          icon: "▤" },
  // 2026-05-11: Agent Rules & Knowledge — user-owned prompt directives,
  // RAG facts, jargon lexicon, and few-shot examples that the chat
  // orchestrator's context_loader retrieves to enrich the system prompt.
  { href: "/agent-knowledge",         labelKey: "rulesKnowledge",      icon: "📓" },
  // Chart catalog — 18 chart components catalog + per-user style preference.
  { href: "/help/charts",             labelKey: "chartCatalog",        icon: "📚" },
];

const ADMIN_ITEMS = [
  { href: "/agent-activity",          labelKey: "agentActivity",    icon: "◎" },
  { href: "/supervisor",              labelKey: "supervisor",       icon: "◈" },
  // 2026-07-06 sunset — build traces superseded by /agent-activity（頁面保留不連）
  { href: "/admin/block-docs",        labelKey: "blockDocs",        icon: "📖" },
  { href: "/system/data-sources",     labelKey: "dataSources",      icon: "🗄️" },
  { href: "/system/event-registry",   labelKey: "eventRegistry",    icon: "📋" },
  { href: "/system/monitor",          labelKey: "systemMonitor",    icon: "🖥️" },
  { href: "/admin/simulator-health",  labelKey: "simulatorHealth",  icon: "💓" },
  { href: "/admin/mcp",               labelKey: "mcpRegistry",      icon: "⬢" },
  // V82 標準 Skill — agent 說明書管理 (non-emoji icon per feedback_no_emoji)
  { href: "/admin/agent-skills",      labelKey: "agentSkills",      icon: "▤" },
  { href: "/admin/users",             labelKey: "users",            icon: "👥" },
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
      color: active ? "#ffffff" : "#8b90a7",
      background: active ? "var(--navs, #274035)" : "transparent",
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
    return <div style={{ height: 1, background: "rgba(255,255,255,0.12)", margin: "8px 6px" }} />;
  }
  return (
    <div style={{
      fontSize: "var(--fs-xs)", fontWeight: 600, color: "#676d80",
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
  const t = useTranslations("nav");

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
      background: "var(--nav, #14211C)",
      borderRight: "1px solid rgba(255,255,255,0.08)",
      display: "flex", flexDirection: "column",
      overflowY: "auto", overflowX: "hidden",
      transition: "width 0.2s, min-width 0.2s",
    }}>
      {/* Header with collapse toggle */}
      <div style={{
        padding: collapsed ? "12px 0" : "10px 12px",
        borderBottom: "1px solid rgba(255,255,255,0.1)",
        display: "flex", alignItems: "center",
        justifyContent: collapsed ? "center" : "space-between",
        flexShrink: 0,
      }}>
        {!collapsed && <span style={{ fontSize: 14, fontWeight: 700, color: "#f0f2f5" }}>AIOps</span>}
        <button onClick={() => setCollapsed(c => !c)} title={collapsed ? t("expandMenu") : t("collapseMenu")} style={{
          background: "none", border: "none", cursor: "pointer",
          color: "#9aa1b5", fontSize: 12, padding: "4px",
        }}>
          {collapsed ? "▶" : "◀"}
        </button>
      </div>

      <div style={{ padding: collapsed ? "4px" : "8px", flex: 1 }}>
        {showOps && (
          <>
            <SidebarSection title={t("sectionOps")} collapsed={collapsed} />
            {OPS_ITEMS.map(({ href, labelKey, icon }) => (
              <NavLink key={href} href={href} icon={icon} label={t(labelKey)}
                active={isExact(href)} collapsed={collapsed} />
            ))}
          </>
        )}

        {showKnowledge && (
          <>
            <SidebarSection title={t("sectionKnowledge")} collapsed={collapsed} />
            {KNOWLEDGE_ITEMS.map(({ href, labelKey, icon }) => (
              <NavLink key={href} href={href} icon={icon} label={t(labelKey)}
                active={isExact(href)} collapsed={collapsed} />
            ))}
          </>
        )}

        {showAdmin && (
          <>
            <SidebarSection title={t("sectionAdmin")} collapsed={collapsed} />
            {ADMIN_ITEMS.map(({ href, labelKey, icon }) => (
              <NavLink key={href} href={href} icon={icon} label={t(labelKey)}
                active={isExact(href)} collapsed={collapsed} />
            ))}
          </>
        )}
      </div>
    </nav>
  );
}

// ── Inner shell ──────────────────────────────────────────────────────────────

function Shell({ children }: { children: React.ReactNode }) {
  const t = useTranslations("nav");
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
  // Phase B ChatOps (2026-07-10): /chatops renders the SAME panel as a
  // centered wide column + a conversation-history sidebar. One instance —
  // all Live-Canvas / glass wiring below keeps working unchanged.
  const pathname = usePathname() ?? "";
  const isChatOps = pathname === "/chatops";
  // Session 管理 (2026-07-12)：手機抽屜帳號列要顯示使用者＋登出。
  const { data: authSession } = useSession();
  // 手機版 (2026-07-11)：viewport ≤ 899px 自動切 MobileShell（底部 4 tab）。
  // SSR 先當桌機，client mount 後以 matchMedia 校正 — 手機首屏會有一次換版。
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 899px)");
    const apply = () => setIsMobile(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  const [chatOpsSess, setChatOpsSess] = useState<{
    id: string | null;
    messages: Array<{ role: string; content: string }>;
    nonce: number;
  }>({ id: null, messages: [], nonce: 0 });
  const [sessionsTick, setSessionsTick] = useState(0);
  // Session 管理 (2026-07-12)：預設開新 — 進 ChatOps／手機一律全新對話，
  // 不再自動接回上一個 session。舊對話從「對話紀錄」（桌機左欄／手機抽屜）
  // 或「進行中建構」banner 進：openChatSession(sid) 先併 server rich history
  // （V85 跨裝置）再抓文字輪次，最後 nonce 重掛面板還原。
  const [chatOpsHydrating, setChatOpsHydrating] = useState(false);
  const openChatSession = useCallback((sid: string) => {
    setChatOpsHydrating(true);
    const richMerge = fetch(
      `/api/agent/session/${encodeURIComponent(sid)}/rich-history`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => {
        const blob = (env?.data ?? env)?.rich_history as string | undefined;
        if (!blob) return;
        const key = `chatops:history:${sid}`;
        const serverAt = (JSON.parse(blob) as { at?: number }).at ?? 0;
        let localAt = 0;
        try {
          localAt = (JSON.parse(localStorage.getItem(key) || "{}") as { at?: number }).at ?? 0;
        } catch { /* corrupt local — overwrite */ }
        if (serverAt > localAt) localStorage.setItem(key, blob);
      })
      .catch(() => { /* server 備份 best-effort */ });
    Promise.resolve(richMerge).then(() =>
    fetch(`/api/agent/session/${encodeURIComponent(sid)}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((env) => {
        const row = (env?.data ?? env) as { messages?: unknown } | null;
        let msgs: Array<{ role: string; content: string }> = [];
        try {
          const parsed = typeof row?.messages === "string" ? JSON.parse(row.messages) : row?.messages;
          if (Array.isArray(parsed)) {
            msgs = parsed.filter((m): m is { role: string; content: string } =>
              !!m && typeof m.content === "string" && (m.role === "user" || m.role === "assistant"));
          }
        } catch { /* unparseable history — start visually empty, session id kept */ }
        setChatOpsSess((prev) => ({ id: sid, messages: msgs, nonce: prev.nonce + 1 }));
      })
      .catch(() => {
        // session gone (expired / deleted) — start fresh
        setChatOpsSess((prev) => (prev.id ? { id: null, messages: [], nonce: prev.nonce + 1 } : prev));
      })
      .finally(() => setChatOpsHydrating(false)));
  }, []);
  const newChatSession = useCallback(() => {
    try { localStorage.removeItem("chatops:session-id"); } catch { /* ignore */ }
    setChatOpsSess((prev) => ({ id: null, messages: [], nonce: prev.nonce + 1 }));
  }, []);
  // My Drafts (2026-07-12)：rail/抽屜點草稿 → 草稿卡插入當前對話。
  const [draftInsert, setDraftInsert] = useState<{ data: DraftCardData; nonce: number } | null>(null);
  const openDraft = useCallback((d: DraftCardData) => {
    setDraftInsert({ data: d, nonce: Date.now() });
  }, []);
  // 進行中背景工作（V85）— 預設開新後「回到進行中對話」的入口。
  const [runningTask, setRunningTask] = useState<{ chat_session_id: string; goal?: string } | null>(null);
  useEffect(() => {
    if (!isChatOps && !isMobile) return;
    let stop = false;
    const poll = () => fetch("/api/agent/tasks/running", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!stop) setRunningTask((d?.tasks ?? [])[0] ?? null); })
      .catch(() => { /* ambient */ });
    poll();
    const t = setInterval(poll, 30_000);
    return () => { stop = true; clearInterval(t); };
  }, [isChatOps, isMobile]);
  // ChatOps (2026-07-10): builds render INLINE in the conversation; the Lite
  // Canvas overlay never auto-opens there (it hid the chat = user couldn't
  // see progress). Events still stream into glassEvents so「↗ 展開 canvas」
  // can open the overlay on demand.
  const lastGlassStartRef = useRef<{ sessionId: string; goal?: string } | null>(null);
  // Remember the last non-ChatOps page so the Topbar Copilot pill returns there.
  useEffect(() => {
    if (!isChatOps) {
      try { localStorage.setItem("chatops:last-path", pathname); } catch { /* ignore */ }
    }
  }, [pathname, isChatOps]);
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
    e = { ...e, ts: new Date().toTimeString().slice(0, 8) };
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

  const agentPanelEl = (
              <AIAgentPanel
                key={(isChatOps || isMobile) ? `chatops-${chatOpsSess.nonce}` : "dock"}
                sessionId={(isChatOps || isMobile) ? (chatOpsSess.id ?? undefined) : undefined}
                initialMessages={(isChatOps || isMobile) ? chatOpsSess.messages : undefined}
                persistHistory={isChatOps || isMobile}
                insertDraft={(isChatOps || isMobile) ? draftInsert : null}
                onSessionResolved={(sid) => {
                  if (!isChatOps && !isMobile) return;
                  try { localStorage.setItem("chatops:session-id", sid); } catch { /* ignore */ }
                  setChatOpsSess((prev) => (prev.id === sid ? prev : { ...prev, id: sid }));
                  setSessionsTick((x) => x + 1);
                }}
                onPbPipelineExpand={(card) => {
                  // 手動「↗ 展開 canvas」— ChatOps 不自動開 overlay，想看才開。
                  // Loose cast: the union's published variant has no pipeline_json.
                  const c = card as unknown as {
                    pipeline_json?: Record<string, unknown>;
                    result_summary?: import("@/lib/pipeline-builder/types").PipelineResultSummary;
                    node_results?: Record<string, import("@/lib/pipeline-builder/types").NodeResult>;
                  };
                  if (glassEventsRef.current.length === 0 && c.pipeline_json) {
                    pushGlassEvent({ kind: "start", sessionId: "adhoc-expand", base_pipeline: c.pipeline_json });
                    pushGlassEvent({ kind: "done", status: "finished", pipeline_json: c.pipeline_json });
                  }
                  if (c.result_summary) {
                    setPipelineResult({ summary: c.result_summary, nodeResults: c.node_results ?? {} });
                    setRunPhase("done");
                  }
                  setGlassOverlay({
                    sessionId: lastGlassStartRef.current?.sessionId ?? "adhoc-expand",
                    goal: (c.pipeline_json as { name?: string } | undefined)?.name,
                    active: false,
                  });
                }}
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
                  // Reset prior state so the build paints from a clean canvas.
                  // ChatOps: keep the conversation visible — record the stream
                  // but do NOT auto-open the overlay (inline card shows progress).
                  resetOverlayState();
                  setRunPhase("building");
                  lastGlassStartRef.current = { sessionId: ev.session_id, goal: ev.goal };
                  if (!isChatOps && !isMobile) {
                    setGlassOverlay({
                      sessionId: ev.session_id,
                      goal: ev.goal,
                      active: true,
                    });
                  }
                  pushGlassEvent({ kind: "start", sessionId: ev.session_id, goal: ev.goal, base_pipeline: ev.base_pipeline });
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
                    setRunError(ev.summary ?? t("buildIncomplete", { status: ev.status }));
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
  );

  // 手機版：MobileShell 全螢幕接管（route children 保持 mounted 但隱藏，
  // 桌機 overlay / topbar / sidebar 全部不渲染）。
  if (isMobile) {
    return (
      <>
        <HandoffListener />
        <MobileShell
          agentPanel={chatOpsHydrating ? (
            <div style={{
              flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
              color: "#94a3b8", fontSize: 13,
            }}>
              正在載入對話…
            </div>
          ) : agentPanelEl}
          onNewChat={newChatSession}
          onOpenSession={openChatSession}
          onOpenDraft={openDraft}
          activeSessionId={chatOpsSess.id}
          runningTask={runningTask}
          userName={authSession?.user?.name ?? null}
          onLogout={() => void signOut({ callbackUrl: "/login" })}
        />
        <div style={{ display: "none" }}>{children}</div>
      </>
    );
  }

  return (
    <div style={{
      display: "flex", flexDirection: "column",
      height: "100vh", background: "var(--ws, #f7f8fc)", overflow: "hidden",
    }}>
      <Topbar />
      <HandoffListener />
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Sidebar + main + copilot toggle live in a relative container so
            LiveCanvasOverlay can position-absolute over them without also
            covering the right AI Agent rail. */}
        <div style={{
          flex: 1, display: "flex", overflow: "hidden",
          position: "relative", minWidth: 0,
        }}>
          <ContextualSidebar />
          {isChatOps ? (
            <>
              <ChatOpsAgentRail
                runPhase={runPhase}
                goal={lastGlassStartRef.current?.goal ?? null}
                events={glassEvents}
                onNew={newChatSession}
                onOpenSession={openChatSession}
                activeSessionId={chatOpsSess.id}
                onOpenDraft={openDraft}
              />
              <div style={{
                flex: 1, display: "flex", justifyContent: "center",
                overflow: "hidden", minWidth: 0, background: "var(--ws, #f7f8fc)",
              }}>
                <div style={{
                  width: "100%", maxWidth: 960,
                  display: "flex", flexDirection: "column", overflow: "hidden",
                  background: "var(--pn, #ffffff)",
                  borderLeft: "1px solid #e2e8f0", borderRight: "1px solid #e2e8f0",
                }}>
                  {runningTask && runningTask.chat_session_id !== chatOpsSess.id && (
                    <button onClick={() => openChatSession(runningTask.chat_session_id)} style={{
                      margin: "10px 14px 0", padding: "9px 14px", borderRadius: 10,
                      border: "1px solid #eadfc2", background: "#faf3df", color: "#8a6a1d",
                      fontSize: 12.5, fontWeight: 700, textAlign: "left", cursor: "pointer",
                    }}>
                      有進行中的建構{runningTask.goal ? `：${runningTask.goal.slice(0, 40)}…` : ""} — 點此回到該對話
                    </button>
                  )}
                  {chatOpsHydrating ? (
                    <div style={{
                      flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
                      color: "#94a3b8", fontSize: 13,
                    }}>
                      正在載入上次的對話…
                    </div>
                  ) : agentPanelEl}
                </div>
              </div>
              {/* keep the route's page mounted (it renders null) */}
              <div style={{ display: "none" }}>{children}</div>
            </>
          ) : (
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
          )}
          {/* Copilot toggle strip (hidden in ChatOps — the panel IS the page) */}
          {!isChatOps && <div
            onClick={() => setCopilotOpen(o => !o)}
            style={{
              width: 28, flexShrink: 0,
              display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", gap: 6,
              background: copilotOpen ? "var(--ws, #f7f8fc)" : "var(--pl, #ebf8ff)",
              borderLeft: "1px solid #e2e8f0",
              cursor: "pointer", userSelect: "none",
              transition: "background 0.15s",
            }}
            title={copilotOpen ? t("collapseCopilot") : t("expandCopilot")}
          >
            <span style={{ fontSize: 14 }}>{copilotOpen ? "▶" : "◀"}</span>
            <span style={{
              writingMode: "vertical-rl", fontSize: 11, fontWeight: 600,
              color: copilotOpen ? "#a0aec0" : "var(--p, #2b6cb0)", letterSpacing: "1px",
            }}>
              AI Agent
            </span>
          </div>}

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

        {/* AI Agent panel (collapsible; hidden in ChatOps — same instance renders center) */}
        {!isChatOps && copilotOpen && (
          <aside style={{
            width: 380, minWidth: 280, maxWidth: "50vw", flexShrink: 0,
            display: "flex", flexDirection: "column",
            background: "var(--pn, #ffffff)", borderLeft: "1px solid #e2e8f0", overflow: "hidden",
            resize: "horizontal", direction: "rtl",
          }}>
            <div style={{ direction: "ltr", display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
              {agentPanelEl}
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
  // Bare pages — no sidebar, no topbar, no copilot. Login + cowork handoff
  // surfaces (review / confirm) which launch standalone and fit the window.
  const isBare = pathname === "/login" || pathname.startsWith("/api/auth")
    || pathname.startsWith("/handoff");
  if (isBare) {
    return <>{children}</>;
  }
  return <Shell>{children}</Shell>;
}
