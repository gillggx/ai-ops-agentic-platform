"use client";

/**
 * AgentConsole — the AI Agent panel's second tab (agent 視角).
 *
 * Replaces the dead 9-Stage PipelineConsole. Renders the multi-agent build's
 * internal behaviour from a single `events[]` array (everything else is
 * derived — per design handoff README "State Management"). Four fixed
 * sections: agent status bar → activity stream (mini-timeline density) →
 * memory effect → cost footer.
 *
 * Fed by BOTH surfaces (chat AIAgentPanel + builder AgentBuilderPanelV30)
 * through normalizeConsoleEvent() so the two modes stay identical.
 *
 * Design source: design_handoff_agent_panel (2026-07-04), fidelity: high.
 * NOTE: the handoff's "⚠ agent 自述" chip is rendered as "△ 自述" — U+26A0
 * renders as emoji on some platforms and the product bans emoji.
 */

import React, { useEffect, useMemo, useReducer, useRef } from "react";
import { useTranslations } from "next-intl";

// ── design tokens (README "Design Tokens" — canonical values) ─────────────
const M = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace";
const AGD: Record<string, { name: string; c: string; bg: string; br: string }> = {
  planner:  { name: "Planner",  c: "#2563eb", bg: "#eef4fe", br: "#c7d9fa" },
  builder:  { name: "Builder",  c: "#059669", bg: "#eafaf3", br: "#bfe8d6" },
  repair:   { name: "Repair",   c: "#d97706", bg: "#fdf5e7", br: "#f0dcb4" },
  verifier: { name: "Verifier", c: "#6b7280", bg: "#f3f4f5", br: "#dcdee2" },
  // NOTE: memory's display name is localised in the component via
  // t("console.agents.memory") — `name` here is a non-rendered fallback.
  memory:   { name: "記憶", c: "#7c3aed", bg: "#f6f2fe", br: "#ddd0f7" }, // i18n-exempt: 顯示層走 agentName()
};
const AMB = "#b45309";
const AMB_TXT = "#8a5a06";
const AMB_BG = "#fbf5e9";
const GREEN = "#047857";

// ── event model ────────────────────────────────────────────────────────────
export type ConsoleAgent = "planner" | "builder" | "repair" | "verifier" | "memory";

export type ConsoleEventKind =
  | "phase_start" | "tool" | "submit" | "verdict_pass" | "verdict_reject"
  | "escalate" | "repair_start" | "repair_out" | "recall" | "write"
  | "phase_done" | "confirm" | "final" | "info";

export interface RecalledMem {
  id: string | number;
  memo_class?: string;
  title?: string;
  how_apply?: string;
  written_by?: string;
}

export interface ConsoleEvent {
  kind: ConsoleEventKind;
  agent: ConsoleAgent;
  /** phase id (p1…pN); "plan" for planning, "fin" for finalize */
  phaseId: string;
  round?: number;
  /** mono event code column (add_node / ADVANCED / memory_recall / W1 …) */
  code: string;
  /** one-line title (the 決定 for tool steps) */
  title: string;
  /** i18n: when set, render shows t("console." + titleKey) instead of `title`
   *  (`title` stays the zh-TW fallback for non-render consumers) */
  titleKey?: string;
  titleParams?: Record<string, string | number>;
  /** 理由 — from the tool call's reason field (B3); absent → row has no 理由 line */
  reason?: string;
  /** evidences (依據): sys = 系統事實 (▣), cite = 引用 (◈ + how_apply);
   *  textKey/textParams: i18n override for composed `text` (same rule as titleKey) */
  evidences?: {
    lv: "sys" | "cite"; id?: string; text: string;
    textKey?: string; textParams?: Record<string, string | number>;
  }[];
  /** 結果 — measured outcome (▣ n rows) */
  result?: string;
  /** recall events: which memories */
  mems?: RecalledMem[];
  /** write events: W-code payload; statusKey: i18n override for the composed status label */
  write?: { code: string; wcls: string; title: string; status: string; statusKey?: string };
  /** recall came back empty on a tool step → teach moment */
  teach?: { blockId?: string; phaseId?: string };
}

export interface ConsoleUsage {
  agent: string;
  inputTokens: number;
  outputTokens: number;
  cacheRead: number;
}

// ── reducer state (owned by the host panel via useConsoleStore) ────────────
export interface ConsoleState {
  events: ConsoleEvent[];
  usage: ConsoleUsage[];
  phases: { id: string; goal: string }[];
  building: boolean;
  done: boolean;
  doneStatus: string;
}

const EMPTY_STATE: ConsoleState = {
  events: [], usage: [], phases: [], building: false, done: false, doneStatus: "",
};

export type ConsoleAction =
  | { t: "reset" }
  | { t: "start"; phases?: { id: string; goal: string }[] }
  | { t: "phases"; phases: { id: string; goal: string }[] }
  | { t: "event"; ev: ConsoleEvent }
  | { t: "usage"; u: ConsoleUsage }
  | { t: "done"; status: string };

export function consoleReducer(s: ConsoleState, a: ConsoleAction): ConsoleState {
  switch (a.t) {
    case "reset": return EMPTY_STATE;
    case "start": return { ...EMPTY_STATE, building: true, phases: a.phases ?? [] };
    case "phases": return { ...s, phases: a.phases };
    case "event": return { ...s, events: [...s.events, a.ev] };
    case "usage": return { ...s, usage: [...s.usage, a.u] };
    case "done": return { ...s, building: false, done: true, doneStatus: a.status };
  }
}

export function useConsoleStore(): [ConsoleState, React.Dispatch<ConsoleAction>] {
  return useReducer(consoleReducer, EMPTY_STATE);
}

// ── SSE → ConsoleEvent/action normalisation (shared by both surfaces) ─────
/** Map one SSE payload (chat pb_glass_* shape OR builder raw shape) to
 *  console actions. Returns [] when the event carries no console signal. */
// i18n note: the zh-TW `title` / `evidences[].text` / write-status strings set
// below are FALLBACKS only (kept so non-render consumers of ConsoleEvent stay
// stable). Every one also carries titleKey/textKey/statusKey + params, and the
// render side translates via the "console" namespace — hence the per-line
// i18n-exempt markers.
export function normalizeConsoleEvent(ev: Record<string, unknown>): ConsoleAction[] {
  const t = String(ev.type ?? "");
  const out: ConsoleAction[] = [];

  // chat surface attaches structured fields to pb_glass_chat payloads —
  // handle them regardless of the outer type so both surfaces normalise
  // to the same console actions.
  const planField = ev.plan as { phases?: { id?: string; goal?: string }[] } | undefined;
  if (planField?.phases?.length) {
    out.push({ t: "phases", phases: planField.phases.map((p) => ({
      id: String(p.id ?? "?"), goal: String(p.goal ?? "") })) });
    out.push({ t: "event", ev: {
      kind: "tool", agent: "planner", phaseId: "plan", code: "plan_proposed",
      title: `提出 ${planField.phases.length} 個 phase`, // i18n-exempt: fallback, render uses titleKey
      titleKey: "events.planProposed", titleParams: { n: planField.phases.length },
    }});
  }
  if (ev.plan_confirmed) {
    out.push({ t: "event", ev: {
      kind: "confirm", agent: "planner", phaseId: "plan", code: "plan_confirmed",
      title: "計畫確認 — 萃取驗收 contract", // i18n-exempt: fallback, render uses titleKey
      titleKey: "events.planConfirmed",
    }});
  }
  const puField = ev.phase_update as Record<string, unknown> | undefined;
  if (puField && String(puField.status) === "completed") {
    const pid = String(puField.phase_id ?? "?");
    const rationale = puField.rationale != null ? String(puField.rationale) : "";
    out.push({ t: "event", ev: {
      kind: "verdict_pass", agent: "verifier", phaseId: pid, code: "ADVANCED",
      title: (rationale || "驗收通過").slice(0, 120), // i18n-exempt: fallback, render uses titleKey
      ...(rationale ? {} : { titleKey: "events.verdictPassDefault" }),
    }});
    out.push({ t: "event", ev: {
      kind: "phase_done", agent: "builder", phaseId: pid, code: "phase_done",
      title: `${pid} 完成`, // i18n-exempt: fallback, render uses titleKey
      titleKey: "events.phaseDone", titleParams: { pid },
    }});
  }
  const ffField = ev.ff_update as { phase_ids?: unknown[]; advanced_by_block?: string } | undefined;
  if (ffField?.phase_ids?.length) {
    ffField.phase_ids.forEach((pidRaw) => {
      const pid = String(pidRaw ?? "?");
      const block = String(ffField.advanced_by_block ?? "");
      out.push({ t: "event", ev: {
        kind: "phase_done", agent: "builder", phaseId: pid, code: "fast_forward",
        title: `${pid} 完成（ff: ${block}）`, // i18n-exempt: fallback, render uses titleKey
        titleKey: "events.phaseDoneFf", titleParams: { pid, block },
      }});
    });
  }
  if (out.length) return out;

  // side-channel behavioural events (agent_console) — same on both surfaces
  if (t === "agent_console") {
    const kind = String(ev.kind ?? "");
    const agent = (String(ev.agent ?? "") || "builder") as ConsoleAgent;
    const pid = String(ev.phase_id ?? "") || "plan";
    const p = (ev.payload ?? {}) as Record<string, unknown>;
    if (kind === "llm_usage") {
      out.push({ t: "usage", u: {
        agent,
        inputTokens: Number(ev.input_tokens ?? 0),
        outputTokens: Number(ev.output_tokens ?? 0),
        cacheRead: Number(ev.cache_read ?? 0),
      }});
    } else if (kind === "memory_recall") {
      const mems = Array.isArray(p.recalled) ? (p.recalled as RecalledMem[]) : [];
      // Subject inline (F-1 2026-07-05): show what was recalled without a
      // click — first memory title + "+n" for the rest.
      const first = String(mems[0]?.title ?? "").slice(0, 40);
      const subject = first
        ? `「${first}」${mems.length > 1 ? ` +${mems.length - 1}` : ""}`
        : `（layer=${String(p.layer ?? "?")}）`;
      out.push({ t: "event", ev: {
        kind: "recall", agent: "memory", phaseId: pid,
        round: p.round != null ? Number(p.round) : undefined,
        code: "memory_recall",
        title: `召回 ${mems.length} 筆 · ${subject}`, // i18n-exempt: fallback, render uses titleKey
        titleKey: "events.recall", titleParams: { n: mems.length, subject },
        mems,
      }});
    } else if (kind === "memory_write") {
      const w = {
        code: String(p.code ?? "W?"), wcls: String(p.memo_class ?? ""),
        title: String(p.title ?? ""), status: String(p.status ?? ""),
      };
      const statusMeta: Record<string, { label: string; key: string }> = {
        active: { label: "active · 立即生效", key: "writeStatus.active" }, // i18n-exempt: fallback, render uses statusKey
        review_queue: { label: "review queue · 不直接改 block_docs", key: "writeStatus.review_queue" }, // i18n-exempt: fallback, render uses statusKey
        draft: { label: "draft · 待 Supervisor 轉正", key: "writeStatus.draft" }, // i18n-exempt: fallback, render uses statusKey
      };
      const meta = statusMeta[w.status];
      out.push({ t: "event", ev: {
        kind: "write", agent: "memory", phaseId: pid, code: w.code,
        title: w.title,
        write: { ...w, status: meta?.label ?? w.status, statusKey: meta?.key },
      }});
    } else if (kind === "verifier_reject") {
      const rawReason = p.judge_reject_reason ?? p.reason ?? p.missing_for_phase;
      const reason = rawReason != null ? String(rawReason) : "";
      const blk = p.block_id ? ` [${String(p.block_id)}]` : "";
      const json = JSON.stringify(p).slice(0, 200);
      out.push({ t: "event", ev: {
        kind: "verdict_reject", agent: "verifier", phaseId: pid,
        code: "REJECTED",
        title: `${(reason || "驗收未過").slice(0, 120)}${blk}`, // i18n-exempt: fallback, render uses titleKey
        ...(reason ? {} : { titleKey: "events.rejectDefault", titleParams: { blk } }),
        evidences: [{
          lv: "sys",
          text: `結構化拒因：${json}`, // i18n-exempt: fallback, render uses textKey
          textKey: "evidence.structuredReject", textParams: { json },
        }],
      }});
    } else if (kind === "stuck_escalated") {
      const round = String(p.round ?? "?");
      out.push({ t: "event", ev: {
        kind: "escalate", agent: "builder", phaseId: pid, code: "stuck_escalated",
        round: p.round != null ? Number(p.round) : undefined,
        title: `r${round} 修正未果 — 升級 Repair`, // i18n-exempt: fallback, render uses titleKey
        titleKey: "events.stuckEscalated", titleParams: { round },
      }});
    } else if (kind === "repair_triggered") {
      out.push({ t: "event", ev: {
        kind: "repair_start", agent: "repair", phaseId: pid, code: "repair_triggered",
        title: "Repair 介入 — 三路對齊診斷（需求 × canvas × 拒因）", // i18n-exempt: fallback, render uses titleKey
        titleKey: "events.repairTriggered",
      }});
    } else if (kind === "repair_outcome") {
      const r = String(p.result ?? "?");
      out.push({ t: "event", ev: {
        kind: "repair_out", agent: "repair", phaseId: pid, code: "repair_outcome",
        title: r === "retry" ? "修復成功 — 交回 Builder 續跑" : "修復失敗 — handover 交棒", // i18n-exempt: fallback, render uses titleKey
        titleKey: r === "retry" ? "events.repairRetry" : "events.repairHandover",
      }});
    }
    return out;
  }

  // tool steps — chat surface: pb_glass_op with _phase_id/_round in args
  if (t === "pb_glass_op") {
    const args = (ev.args ?? {}) as Record<string, unknown>;
    const result = (ev.result ?? {}) as Record<string, unknown>;
    const pid = String(args._phase_id ?? "") || "plan";
    const round = args._round != null && args._round !== "?" ? Number(args._round) : undefined;
    const op = String(ev.op ?? "?");
    const summary = String(args._args_summary ?? "");
    const resSummary = String(result._summary ?? "");
    const reason = typeof args.reason === "string" ? args.reason : undefined;
    out.push({ t: "event", ev: {
      kind: "tool", agent: "builder", phaseId: pid, round,
      code: op, title: summary || op, reason,
      result: resSummary || undefined,
    }});
    return out;
  }

  // builder surface: phase_action carries the same payload pre-wrap
  if (t === "phase_action") {
    const pid = String(ev.phase_id ?? "") || "plan";
    const round = ev.round != null ? Number(ev.round) : undefined;
    const rawArgs = (ev.tool_args_raw ?? {}) as Record<string, unknown>;
    const reason = typeof rawArgs.reason === "string" ? rawArgs.reason : undefined;
    out.push({ t: "event", ev: {
      kind: "tool", agent: "builder", phaseId: pid, round,
      code: String(ev.tool ?? "?"),
      title: String(ev.args_summary ?? ev.tool ?? "?"),
      reason,
      result: ev.result_summary ? String(ev.result_summary) : undefined,
    }});
    return out;
  }

  // phase lifecycle — both surfaces
  if (t === "phase_started") {
    const pid = String(ev.phase_id ?? "");
    out.push({ t: "event", ev: {
      kind: "phase_start", agent: "builder",
      phaseId: pid || "plan",
      code: "phase_started",
      title: `開始 ${pid}`, // i18n-exempt: fallback, render uses titleKey
      titleKey: "events.phaseStart", titleParams: { pid },
    }});
    return out;
  }
  if (t === "phase_completed") {
    const pid = String(ev.phase_id ?? "") || "?";
    const rationale = ev.rationale != null ? String(ev.rationale) : "";
    out.push({ t: "event", ev: {
      kind: "verdict_pass", agent: "verifier", phaseId: pid, code: "ADVANCED",
      title: (rationale || "驗收通過").slice(0, 120), // i18n-exempt: fallback, render uses titleKey
      ...(rationale ? {} : { titleKey: "events.verdictPassDefault" }),
    }});
    out.push({ t: "event", ev: {
      kind: "phase_done", agent: "builder", phaseId: pid, code: "phase_done",
      title: `${pid} 完成`, // i18n-exempt: fallback, render uses titleKey
      titleKey: "events.phaseDone", titleParams: { pid },
    }});
    return out;
  }
  if (t === "phase_update") {
    // chat surface structured phase status (wrap of phase_completed etc.)
    const pu = ev as unknown as { phase_update?: Record<string, unknown> };
    const u = pu.phase_update;
    if (u && String(u.status) === "completed") {
      const pid = String(u.phase_id ?? "?");
      const rationale = u.rationale != null ? String(u.rationale) : "";
      out.push({ t: "event", ev: {
        kind: "verdict_pass", agent: "verifier", phaseId: pid, code: "ADVANCED",
        title: (rationale || "驗收通過").slice(0, 120), // i18n-exempt: fallback, render uses titleKey
        ...(rationale ? {} : { titleKey: "events.verdictPassDefault" }),
      }});
      out.push({ t: "event", ev: {
        kind: "phase_done", agent: "builder", phaseId: pid, code: "phase_done",
        title: `${pid} 完成`, // i18n-exempt: fallback, render uses titleKey
        titleKey: "events.phaseDone", titleParams: { pid },
      }});
    }
    return out;
  }
  if (t === "goal_plan_proposed") {
    const phases = Array.isArray(ev.phases) ? ev.phases as { id?: string; goal?: string }[] : [];
    out.push({ t: "phases", phases: phases.map((p) => ({
      id: String(p.id ?? "?"), goal: String(p.goal ?? "") })) });
    out.push({ t: "event", ev: {
      kind: "tool", agent: "planner", phaseId: "plan", code: "plan_proposed",
      title: `提出 ${phases.length} 個 phase`, // i18n-exempt: fallback, render uses titleKey
      titleKey: "events.planProposed", titleParams: { n: phases.length },
    }});
    return out;
  }
  if (t === "goal_plan_confirmed") {
    out.push({ t: "event", ev: {
      kind: "confirm", agent: "planner", phaseId: "plan", code: "plan_confirmed",
      title: "計畫確認 — 萃取驗收 contract", // i18n-exempt: fallback, render uses titleKey
      titleKey: "events.planConfirmed",
    }});
    return out;
  }
  return out;
}

// ── derived helpers ─────────────────────────────────────────────────────────
const PHASE_LABEL = (
  pid: string,
  phases: { id: string; goal: string }[],
  labels: { plan: string; fin: string },
): string => {
  if (pid === "plan") return labels.plan;
  if (pid === "fin") return labels.fin;
  const p = phases.find((x) => x.id === pid);
  return p ? `${pid} ${p.goal.slice(0, 24)}` : pid;
};

interface Group {
  id: string;
  label: string;
  rows: { ev: ConsoleEvent; idx: number }[];
  rejects: number;
  repair: boolean;
  rounds: number;
  done: boolean;
  active: boolean;
}

function buildGroups(
  events: ConsoleEvent[], phases: { id: string; goal: string }[], finished: boolean,
  labels: { plan: string; fin: string },
): Group[] {
  const by = new Map<string, Group>();
  const gs: Group[] = [];
  events.forEach((e, idx) => {
    let g = by.get(e.phaseId);
    if (!g) {
      g = { id: e.phaseId, label: PHASE_LABEL(e.phaseId, phases, labels), rows: [],
            rejects: 0, repair: false, rounds: 0, done: false, active: false };
      by.set(e.phaseId, g); gs.push(g);
    }
    g.rows.push({ ev: e, idx });
    if (e.kind === "verdict_reject") g.rejects++;
    if (e.agent === "repair") g.repair = true;
    if (e.round && e.round > g.rounds) g.rounds = e.round;
    if (e.kind === "phase_done" || e.kind === "final" || e.kind === "confirm") g.done = true;
  });
  gs.forEach((g, i) => { g.active = !finished && i === gs.length - 1; });
  return gs;
}

const chipS = (bg: string, c: string, br?: string, dashed?: boolean): React.CSSProperties => ({
  display: "inline-block", padding: "1px 6px", borderRadius: 4, fontSize: 9.5,
  fontFamily: M, fontWeight: 600, background: bg, color: c,
  border: `1px ${dashed ? "dashed" : "solid"} ${br ?? "transparent"}`,
  whiteSpace: "nowrap", flex: "none",
});

const MARKS: Record<ConsoleEventKind, { mark: string; color?: string; bg?: string }> = {
  phase_start:    { mark: "○" },
  tool:           { mark: "▪" },
  submit:         { mark: "▸" },
  verdict_pass:   { mark: "✓", color: "#059669" },
  verdict_reject: { mark: "✕", color: AMB, bg: AMB_BG },
  escalate:       { mark: "▲", color: AMB, bg: AMB_BG },
  repair_start:   { mark: "▲", color: "#d97706", bg: "#fdf5e7" },
  repair_out:     { mark: "✓", color: "#d97706", bg: "#fdf5e7" },
  recall:         { mark: "◆", color: "#7c3aed", bg: "#f9f6fe" },
  write:          { mark: "◆", color: "#7c3aed", bg: "#f9f6fe" },
  phase_done:     { mark: "✓" },
  confirm:        { mark: "✓" },
  final:          { mark: "■" },
  info:           { mark: "·" },
};

// GLM/token pricing is provider-dependent; per-1k blended estimate only.
const USD_PER_TOKEN = 0.0000023;

// ── component ───────────────────────────────────────────────────────────────
export function AgentConsole({
  state,
  onTeach,
  onOpenMemory,
  memoryEditable = false,
}: {
  state: ConsoleState;
  /** open /agent-knowledge with prefilled context (teach moment) */
  onTeach?: (ctx: { blockId?: string; phaseId?: string }) => void;
  /** jump to /agent-knowledge?id=… */
  onOpenMemory?: (id: string | number) => void;
  /** 稿 1d（2026-07-06）：PE/IT_ADMIN 點記憶 chip 進工房該筆；
   *  其他角色（ON_DUTY）開唯讀浮卡，不離開 Console。 */
  memoryEditable?: boolean;
}) {
  const t = useTranslations("console");
  const tm = useTranslations("mem");
  const { events, usage, phases, building, done, doneStatus } = state;
  const [expanded, setExpanded] = React.useState<Record<number, boolean>>({});
  const [costOpen, setCostOpen] = React.useState(false);
  const [readonlyMem, setReadonlyMem] = React.useState<RecalledMem | null>(null);
  const [reportSent, setReportSent] = React.useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const followRef = useRef(true);

  /** AGD keeps visual tokens; the memory agent's display name is localised. */
  const agentName = (k: string) => (k === "memory" ? t("agents.memory") : AGD[k].name);
  const groupLabels = useMemo(
    () => ({ plan: t("group.plan"), fin: t("group.fin") }), [t]);

  const gs = useMemo(
    () => buildGroups(events, phases, done, groupLabels),
    [events, phases, done, groupLabels]);
  const isIdle = events.length === 0 && !building;
  const last = events[events.length - 1];
  const totalRejects = events.filter((e) => e.kind === "verdict_reject").length;
  const repairUsed = events.some((e) => e.agent === "repair");

  // teach detection: a tool step whose phase+round had a recall with 0 mems,
  // OR no recall at all in that phase before it. Simple deterministic rule:
  // mark tool rows in phases where the latest recall before them was empty.
  const teachIdx = useMemo(() => {
    const set = new Set<number>();
    const lastRecallEmpty = new Map<string, boolean>();
    events.forEach((e, i) => {
      if (e.kind === "recall") lastRecallEmpty.set(e.phaseId, (e.mems ?? []).length === 0);
      if (e.kind === "tool" && e.agent === "builder" && lastRecallEmpty.get(e.phaseId) === true) {
        set.add(i);
      }
    });
    return set;
  }, [events]);

  // ── status line ──
  let statusLine = t("status.idle");
  let statusColor = "#a09d95";
  let phaseRound = "";
  if (done && last) {
    statusLine = doneStatus === "failed"
      ? t("status.buildFailed", { n: totalRejects })
      : t("status.buildDone", {
          phases: phases.length || gs.filter(g => g.id !== "plan" && g.id !== "fin").length,
          rejects: totalRejects,
        }) + (repairUsed ? " · Repair ×1" : "");
    statusColor = doneStatus === "failed" ? AMB : GREEN;
    phaseRound = "session done";
  } else if (last) {
    let activeAgent: ConsoleAgent = last.agent;
    if (activeAgent === "memory") {
      for (let i = events.length - 2; i >= 0; i--) {
        if (events[i].agent !== "memory") { activeAgent = events[i].agent; break; }
      }
    }
    const modeMap: Record<ConsoleEventKind, string> = {
      phase_start: t("mode.phase_start"), tool: t("mode.tool"), submit: t("mode.submit"),
      verdict_pass: t("mode.verdict_pass"), verdict_reject: t("mode.verdict_reject"),
      escalate: t("mode.escalate"), repair_start: t("mode.repair_start"),
      repair_out: t("mode.repair_out"),
      recall: t("mode.recall"), write: t("mode.write"), phase_done: t("mode.phase_done"),
      confirm: t("mode.confirm"), final: t("mode.final"), info: "",
    };
    statusLine = `${agentName(activeAgent)} ${last.agent === "memory" ? modeMap[last.kind] : (modeMap[last.kind] || t("mode.tool"))}`;
    statusColor = AGD[activeAgent].c;
    const g = gs[gs.length - 1];
    if (g && g.id !== "plan" && g.id !== "fin") {
      phaseRound = [g.id, g.rounds ? `r${g.rounds}/32` : null,
                    g.rejects ? t("status.rejectCount", { n: g.rejects }) : null]
        .filter(Boolean).join(" · ");
    } else if (g) {
      phaseRound = g.id === "plan" ? t("status.planning") : t("status.finalizing");
    }
  }
  const memActive = last?.agent === "memory";
  const activeAgentKey: string | null = (() => {
    if (!last || done) return null;
    if (last.agent !== "memory") return last.agent;
    for (let i = events.length - 2; i >= 0; i--) {
      if (events[i].agent !== "memory") return events[i].agent;
    }
    return null;
  })();

  // ── phase ticks ──
  const realPhases = phases.length
    ? phases.map((p) => p.id)
    : gs.filter((g) => g.id !== "plan" && g.id !== "fin").map((g) => g.id);
  const byPh = new Map(gs.map((g) => [g.id, g]));

  // ── memory aggregation ──
  const recAgg = useMemo(() => {
    const m = new Map<string, { mem: RecalledMem; n: number }>();
    events.forEach((e) => {
      if (e.kind !== "recall") return;
      (e.mems ?? []).forEach((r) => {
        const key = String(r.id ?? r.title ?? "?");
        const cur = m.get(key);
        if (cur) cur.n++;
        else m.set(key, { mem: r, n: 1 });
      });
    });
    return Array.from(m.entries());
  }, [events]);
  const writes = useMemo(
    () => events.filter((e) => e.kind === "write" && e.write).map((e) => e.write!),
    [events]);

  // ── cost ──
  const cost = useMemo(() => {
    const per: Record<string, { tok: number; cache: number }> = {};
    let total = 0, cacheHit = 0, cacheDen = 0;
    usage.forEach((u) => {
      const k = u.agent in AGD ? u.agent : "builder";
      const p = per[k] ?? (per[k] = { tok: 0, cache: 0 });
      const t = u.inputTokens + u.outputTokens;
      p.tok += t; p.cache += u.cacheRead;
      total += t; cacheHit += u.cacheRead; cacheDen += u.inputTokens;
    });
    // cache_read tokens are NOT included in input_tokens (provider
    // convention) — the hit rate denominator is fresh + cached input.
    const den = cacheHit + cacheDen;
    return { per, total, cachePct: den > 0 ? Math.round((cacheHit / den) * 100) : 0 };
  }, [usage]);

  // auto-scroll (pause when user scrolled up)
  useEffect(() => {
    const el = scrollRef.current;
    if (el && followRef.current) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  const anchorTo = (domId: string) => {
    const el = document.getElementById(domId);
    const sc = scrollRef.current;
    if (el && sc) sc.scrollTop += el.getBoundingClientRect().top - sc.getBoundingClientRect().top - 30;
  };

  const gMeta = (g: Group) =>
    [g.rounds ? `r${g.rounds}/32` : null,
     g.rejects ? t("status.rejectCount", { n: g.rejects }) : null,
     g.repair ? "REP" : null, `${g.rows.length}ev`].filter(Boolean).join(" · ")
    + (g.done ? " · ✓" : g.active ? ` · ${t("status.inProgress")}` : "");

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column",
                  background: "#fbfbf9", color: "#211f1c", position: "relative" }}>
      <style>{`
        @keyframes acPulse{0%,100%{opacity:1}50%{opacity:.3}}
        @keyframes acIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
        @media (prefers-reduced-motion: reduce){.ac-anim{animation:none !important;transition:none !important}}
      `}</style>
      {/* 稿 1d — 記憶唯讀浮卡（非 PE 角色點 chip 開啟，不離開 Console） */}
      {readonlyMem && (
        <>
          <div onClick={() => setReadonlyMem(null)}
               style={{ position: "absolute", inset: 0, zIndex: 40, background: "rgba(33,31,28,.18)" }} />
          <div style={{ position: "absolute", left: 10, right: 10, bottom: 96, zIndex: 41,
                        background: "#fff", border: "1px solid #ddd6fe", borderRadius: 10,
                        boxShadow: "0 8px 26px rgba(109,40,217,.13)", overflow: "hidden" }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "11px 14px",
                          borderBottom: "1px solid #f0edfb" }}>
              <span style={{ fontFamily: M, fontWeight: 700, fontSize: 12, color: "#6d28d9" }}>
                ◆ #{String(readonlyMem.id ?? "?")}
              </span>
              {readonlyMem.memo_class && (
                <span style={{ fontSize: 9.5, fontWeight: 700, padding: "1px 6px", borderRadius: 3,
                               border: "1px solid #c4b5fd", color: "#6d28d9" }}>
                  {readonlyMem.memo_class}
                </span>
              )}
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 10, color: "#8a877e", border: "1px solid #e9e7e2",
                             borderRadius: 4, padding: "1px 6px" }}>{tm("readonly")}</span>
              <span onClick={() => setReadonlyMem(null)}
                    style={{ cursor: "pointer", color: "#8a877e", fontSize: 12, padding: "0 2px" }}
                    title={tm("close")}>✕</span>
            </div>
            <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 9 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.55 }}>
                {readonlyMem.title || tm("removed")}
              </div>
              {readonlyMem.how_apply && (
                <div style={{ fontSize: 11.5, color: "#3d3a34", lineHeight: 1.65,
                              background: "#faf9f6", borderRadius: 6, padding: "8px 10px" }}>
                  <b style={{ fontSize: 10, color: "#8a877e" }}>{tm("howApply")}</b><br />
                  {readonlyMem.how_apply}
                </div>
              )}
              <div style={{ fontSize: 10.5, color: "#8a877e" }}>
                {tm("source")}{" "}
                {readonlyMem.written_by && ["planner", "builder", "repair", "supervisor"].includes(readonlyMem.written_by)
                  ? tm("sourceAgent")
                  : readonlyMem.written_by === "teach" ? tm("sourceTeach") : tm("sourceHuman")}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "10px 14px",
                          borderTop: "1px solid #f0edfb", background: "#fcfbf7" }}>
              <span style={{ fontSize: 10.5, color: "#8a877e", flex: 1 }}>{tm("footerNote")}</span>
              <button
                disabled={reportSent}
                onClick={() => {
                  const m = readonlyMem;
                  if (!m) return;
                  void fetch("/api/agent-knowledge", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      scope_type: "global",
                      priority: "med",
                      memo_class: m.memo_class || "domain",
                      title: `[回報] #${String(m.id ?? "?")} ${String(m.title ?? "").slice(0, 120)}`, // i18n-exempt: 存 DB 的 draft 標題 marker（同 [教它] 慣例）
                      body: `${tm("reportBody")}\n\n**Why:** \n**How to apply:** `,
                    }),
                  }).catch(() => {});
                  setReportSent(true);
                }}
                style={{ border: "1px solid #dcdad4",
                         background: reportSent ? "#eafaf3" : "#fff",
                         color: reportSent ? "#047857" : "#55534d",
                         borderRadius: 6, fontSize: 11, padding: "4px 10px",
                         cursor: reportSent ? "default" : "pointer",
                         fontFamily: "inherit" }}>
                {reportSent ? tm("reportSent") : tm("reportIssue")}
              </button>
            </div>
          </div>
        </>
      )}

      {/* ── 3.1 agent status bar ── */}
      <div style={{ padding: "10px 12px 9px", borderBottom: "1px solid #e9e7e2",
                    background: "#fff", flex: "none" }}>
        <div style={{ display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
          {(["planner", "builder", "repair", "verifier", "memory"] as const).map((k) => {
            const a = AGD[k];
            const act = k === "memory" ? memActive : (k === activeAgentKey && !memActive);
            return (
              <div key={k} style={act
                ? { display: "flex", alignItems: "center", gap: 5, padding: "3px 8px",
                    borderRadius: 6, background: a.bg, border: `1px solid ${a.br}`,
                    color: a.c, fontWeight: 600, fontSize: 10.5 }
                : { display: "flex", alignItems: "center", gap: 5, padding: "3px 8px",
                    borderRadius: 6, border: "1px solid transparent", color: "#a09d95",
                    fontSize: 10.5 }}>
                <span className="ac-anim" style={{
                  width: 6, height: 6, flex: "none",
                  borderRadius: k === "memory" ? 1 : "50%",
                  transform: k === "memory" ? "rotate(45deg)" : "none",
                  background: act ? a.c : "#d6d4cf",
                  animation: act && building ? "acPulse 1.2s ease-in-out infinite" : "none",
                }} />
                <span>{agentName(k)}</span>
              </div>
            );
          })}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "baseline", marginTop: 8, gap: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: statusColor, minWidth: 0,
                         overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {statusLine}
          </span>
          <span style={{ fontFamily: M, fontSize: 10, color: "#8a877e", whiteSpace: "nowrap" }}>
            {phaseRound}
          </span>
        </div>
        {realPhases.length > 0 && (
          <div style={{ display: "flex", gap: 3, marginTop: 6 }}>
            {realPhases.map((pid) => {
              const g = byPh.get(pid);
              let background = "#e6e4df";
              let anim = "none";
              if (g) {
                if (g.done) {
                  background = g.repair
                    ? "linear-gradient(90deg,#059669 65%,#d97706 65%)" : "#059669";
                } else if (g.active) {
                  background = g.repair ? "#d97706" : "#059669";
                  anim = building ? "acPulse 1.2s ease-in-out infinite" : "none";
                }
              }
              return <div key={pid} className="ac-anim" style={{
                flex: 1, height: 4, borderRadius: 2, background, animation: anim }} />;
            })}
          </div>
        )}
      </div>

      {/* ── 3.2 activity stream ── */}
      <div ref={scrollRef}
           onScroll={(e) => {
             const el = e.currentTarget;
             followRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
           }}
           style={{ flex: 1, overflowY: "auto", overflowX: "hidden", position: "relative" }}>
        <div style={{ position: "sticky", top: 0, zIndex: 3, display: "flex", gap: 4,
                      padding: "6px 10px", background: "rgba(251,251,249,.96)",
                      borderBottom: "1px solid #efede8" }}>
          {isIdle && <span style={{ fontSize: 10, color: "#a09d95" }}>{t("stream.idle")}</span>}
          {gs.map((g) => (
            <span key={g.id} onClick={() => anchorTo(`acg-${g.id}`)} style={{
              padding: "1px 8px", borderRadius: 10, fontSize: 9.5, fontFamily: M,
              cursor: "pointer",
              background: g.active ? "#211f1c" : "#efede8",
              color: g.active ? "#fff" : (g.rejects || g.repair ? "#a5680a" : "#6d6a62"),
              border: g.repair && !g.active ? "1px solid #f0dcb4" : "1px solid transparent",
            }}>
              {g.id === "plan" ? t("group.plan") : g.id === "fin" ? t("group.fin") : g.id}
            </span>
          ))}
        </div>
        {isIdle && (
          <div style={{ padding: "24px 14px", fontSize: 11, color: "#a09d95",
                        textAlign: "center" }}>
            {t("stream.idleHint")}
          </div>
        )}
        {gs.map((g) => (
          <div key={g.id} id={`acg-${g.id}`}>
            <div style={{ position: "sticky", top: 29, zIndex: 2, display: "flex",
                          justifyContent: "space-between", gap: 8, padding: "4px 10px",
                          background: "#f4f2ec", borderBottom: "1px solid #eceae4",
                          borderTop: "1px solid #eceae4", fontSize: 10, fontWeight: 700,
                          color: "#55534d" }}>
              <span style={{ whiteSpace: "nowrap", overflow: "hidden",
                             textOverflow: "ellipsis" }}>{g.label}</span>
              <span style={{ fontFamily: M, fontWeight: 400, color: "#8a877e",
                             whiteSpace: "nowrap" }}>{gMeta(g)}</span>
            </div>
            {g.rows.map(({ ev, idx }) => {
              const mk = MARKS[ev.kind];
              const isMem = ev.kind === "recall" || ev.kind === "write";
              const isTeach = teachIdx.has(idx);
              const open = !!expanded[idx];
              const agentColor = AGD[ev.agent]?.c ?? "#3d3b36";
              const bg = isTeach ? "#f6f2fe"
                : mk.bg ?? (ev.agent === "repair" ? "#fdf5e7" : "transparent");
              // detail lines (三段式)
              const parts: React.ReactNode[] = [];
              if (ev.reason) {
                parts.push(
                  <span key="why">{t("stream.reason", { reason: ev.reason })}
                    <span style={chipS("#fdf9ee", AMB_TXT, "#d3ab5e", true)}>△ {t("stream.selfReported")}</span>
                  </span>);
              }
              (ev.evidences ?? []).forEach((e2, i2) => {
                const txt = e2.textKey ? t(e2.textKey, e2.textParams) : e2.text;
                parts.push(e2.lv === "sys"
                  ? <span key={`ev${i2}`}><span style={chipS("#fff", "#3d3b36", "#b3b0a8")}>▣</span> {txt}</span>
                  : <span key={`ev${i2}`}><span style={chipS("#efe8fc", "#6d28d9", "#ddd0f7")}>◈ {e2.id ?? ""}</span> {txt}</span>);
              });
              if (ev.kind === "tool" && !(ev.evidences ?? []).length && isTeach) {
                parts.push(<span key="no-recall" style={{ color: "#7c3aed" }}>✕ {t("stream.noRecall")}</span>);
              }
              if (ev.result) {
                parts.push(<span key="res"><span style={chipS("#fff", "#3d3b36", "#b3b0a8")}>▣</span> {ev.result}</span>);
              }
              (ev.mems ?? []).forEach((m2, i2) => {
                parts.push(
                  <span key={`m${i2}`} style={{ color: "#6d28d9" }}>
                    ◆ #{String(m2.id ?? "?")} {m2.memo_class ?? ""} — {m2.how_apply || m2.title || ""}
                  </span>);
              });
              if (ev.write) {
                parts.push(
                  <span key="w" style={{ color: "#6d28d9" }}>
                    {ev.write.statusKey ? t(ev.write.statusKey) : ev.write.status}
                  </span>);
              }
              const hasDetail = parts.length > 0;
              return (
                <React.Fragment key={idx}>
                  <div className="ac-anim"
                       onClick={() => hasDetail && setExpanded((s) => ({ ...s, [idx]: !s[idx] }))}
                       style={{ display: "flex", alignItems: "center", gap: 6,
                                padding: "2.5px 12px 2.5px 10px",
                                cursor: hasDetail ? "pointer" : "default",
                                background: bg, animation: "acIn .2s ease" }}>
                    <span style={{ color: mk.color ?? agentColor, fontSize: 9, width: 10,
                                   textAlign: "center", flex: "none" }}>{mk.mark}</span>
                    <span style={{ fontFamily: M, fontSize: 9,
                                   color: ev.kind === "verdict_reject" ? AMB_TXT
                                     : isMem ? "#6d28d9" : isTeach ? "#7c3aed" : "#a09d95",
                                   flex: "none", width: 96, overflow: "hidden",
                                   textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {ev.code}
                    </span>
                    <span style={{ flex: 1, minWidth: 0, fontSize: 10.5,
                                   color: isMem ? "#4c1d95" : "#3d3b36",
                                   whiteSpace: "nowrap", overflow: "hidden",
                                   textOverflow: "ellipsis" }}>
                      {ev.titleKey ? t(ev.titleKey, ev.titleParams) : ev.title}
                    </span>
                    {(isTeach || !!ev.round) && (
                      <span style={{ fontFamily: M, fontSize: 9, color: isTeach ? "#7c3aed" : "#a09d95",
                                     flex: "none" }}>
                        {isTeach ? "✕0" : `r${ev.round}`}
                      </span>
                    )}
                  </div>
                  {open && hasDetail && (
                    <div style={{ padding: "2px 12px 6px 36px", fontSize: 10, color: "#8a877e",
                                  lineHeight: 1.55, background: "#fdfdfc",
                                  borderBottom: "1px solid #f2f0eb", display: "flex",
                                  flexDirection: "column", gap: 3 }}>
                      {parts}
                    </div>
                  )}
                  {open && isTeach && (
                    <div style={{ margin: "0 12px 6px 36px", border: "1px dashed #c9b3f2",
                                  borderRadius: 7, background: "#fbfaff", padding: "7px 9px" }}>
                      <div style={{ fontSize: 10.5, color: "#5b21b6", fontWeight: 600 }}>
                        {t("teach.title")}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                        <span style={{ fontSize: 10, color: "#8a877e", flex: 1 }}>
                          {t("teach.question")}
                        </span>
                        <button
                          onClick={(e) => { e.stopPropagation();
                            onTeach?.({ blockId: ev.code, phaseId: ev.phaseId }); }}
                          style={{ border: "1px solid #7c3aed", background: "#7c3aed",
                                   color: "#fff", fontSize: 10, fontWeight: 600,
                                   padding: "3px 10px", borderRadius: 5, cursor: "pointer" }}>
                          {t("teach.button")} →
                        </button>
                      </div>
                      <div style={{ marginTop: 5, fontSize: 9.5, lineHeight: 1.6,
                                    color: "#8b7bb8" }}>
                        {t("teach.autofill", { code: ev.code, phaseId: ev.phaseId })}
                      </div>
                    </div>
                  )}
                </React.Fragment>
              );
            })}
          </div>
        ))}
      </div>

      {/* ── 3.3 memory effect ── */}
      <div className="ac-anim" style={{
        borderTop: "1px solid #e9e7e2", padding: "8px 12px",
        background: memActive ? "#fdfbff" : "#fff",
        boxShadow: memActive ? "inset 3px 0 0 #7c3aed" : "none",
        transition: "all .4s ease", flex: "none" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".08em",
                         color: "#7c3aed" }}>{t("memory.title")}</span>
          <span style={{ fontSize: 10, color: "#8a877e" }}>
            {t("memory.counts", { recalls: recAgg.length, writes: writes.length })}
          </span>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6,
                      alignItems: "center" }}>
          <span style={{ fontSize: 10, color: "#8a877e", width: 26, flex: "none" }}>{t("memory.recall")}</span>
          {recAgg.length === 0 && <span style={{ fontSize: 10, color: "#c9c6bf" }}>—</span>}
          {recAgg.map(([key, { mem, n }]) => {
            const isNew = mem.written_by === "supervisor";
            return (
              <span key={key}
                    title={`${mem.memo_class ?? ""} — ${mem.how_apply || mem.title || ""}`}
                    onClick={() => {
                      if (mem.id == null) return;
                      // 稿 1d：非 PE 開唯讀浮卡（不離開 Console）；PE 進工房該筆
                      if (memoryEditable) onOpenMemory?.(mem.id);
                      else { setReadonlyMem(mem); setReportSent(false); }
                    }}
                    style={{ ...(isNew ? chipS("#7c3aed", "#fff")
                             : chipS("#efe8fc", "#6d28d9", "#ddd0f7")),
                             cursor: "pointer" }}>
                #{String(mem.id ?? "?")}{n > 1 ? ` ×${n}` : ""}{isNew ? ` ${t("memory.new")}` : ""}
              </span>
            );
          })}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4,
                      alignItems: "center" }}>
          <span style={{ fontSize: 10, color: "#8a877e", width: 26, flex: "none" }}>{t("memory.write")}</span>
          {writes.length === 0 && <span style={{ fontSize: 10, color: "#c9c6bf" }}>—</span>}
          {writes.map((w, i) => {
            const statusText = w.statusKey ? t(w.statusKey) : w.status;
            const isDraft = w.statusKey
              ? w.statusKey === "writeStatus.draft" : w.status.startsWith("draft");
            return (
              <span key={i} title={`${w.title}（${statusText}）`}
                    style={isDraft
                      ? chipS("#f9f6fe", "#6d28d9", "#c9b3f2")
                      : chipS("#7c3aed", "#fff")}>
                {w.code} {w.wcls}
              </span>
            );
          })}
        </div>
      </div>

      {/* ── 3.4 cost footer ── */}
      <div style={{ borderTop: "1px solid #e9e7e2", background: "#fff", flex: "none" }}>
        <div onClick={() => setCostOpen((v) => !v)}
             style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 12px",
                      cursor: "pointer" }}>
          <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".08em",
                         color: "#8a877e", flex: "none" }}>{t("cost.title")}</span>
          <div style={{ flex: 1, height: 5, borderRadius: 3, background: "#efede8",
                        overflow: "hidden", display: "flex" }}>
            {(["planner", "builder", "repair"] as const).map((k) => (
              <div key={k} className="ac-anim" style={{
                width: cost.total ? `${((cost.per[k]?.tok ?? 0) / cost.total) * 100}%` : 0,
                background: AGD[k].c, height: "100%", transition: "width .4s ease" }} />
            ))}
          </div>
          <span style={{ fontFamily: M, fontSize: 10, color: "#55534d", whiteSpace: "nowrap" }}>
            {(cost.total / 1000).toFixed(1)}k tok · ${(cost.total * USD_PER_TOKEN).toFixed(3)}
            {cost.cachePct > 0 ? ` · cache ${cost.cachePct}%` : ""}
          </span>
          <span style={{ fontSize: 9, color: "#b3b0a8" }}>{costOpen ? "▴" : "▾"}</span>
        </div>
        {costOpen && (
          <div style={{ padding: "2px 12px 9px", display: "flex", flexDirection: "column",
                        gap: 3 }}>
            {(["planner", "builder", "repair"] as const).map((k) => (
              <div key={k} style={{ display: "flex", alignItems: "center", gap: 6,
                                    fontSize: 10.5, color: "#55534d" }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%",
                               background: AGD[k].c, flex: "none" }} />
                <span style={{ width: 56, flex: "none" }}>{AGD[k].name}</span>
                <span style={{ fontFamily: M, fontSize: 10 }}>
                  {((cost.per[k]?.tok ?? 0) / 1000).toFixed(1)}k tok
                </span>
                <span style={{ flex: 1 }} />
                <span style={{ fontFamily: M, fontSize: 10 }}>
                  ${((cost.per[k]?.tok ?? 0) * USD_PER_TOKEN).toFixed(3)}
                </span>
              </div>
            ))}
            <div style={{ fontSize: 9.5, color: "#a09d95", marginTop: 2 }}>
              {t("cost.note")}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default AgentConsole;
