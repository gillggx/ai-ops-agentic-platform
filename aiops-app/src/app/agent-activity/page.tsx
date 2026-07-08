"use client";

/**
 * Agent Activity page (spec MULTI_AGENT_ACTIVITY_UI_SPEC §4).
 *
 * Shows how OUR three build-plane agents (planner / builder / repair) behaved
 * on each build. The primary view (Tab A "Trace 明細") mirrors the original
 * build trace — multiple phases, the prompt each round ran, the LLM output —
 * but every round's prompt is annotated with WHICH memories it recalled
 * (memory_recall steps merged in by the Java rounds() endpoint). Tabs B/C are
 * an at-a-glance swim-lane and a scorecard over the same episode.
 *
 * Backend: GET /api/agent-activity/episodes | /episodes/{key} |
 * /episodes/{key}/rounds | /report — all proxy to Java (ApiResponse envelope,
 * unwrapped here via `.data`).
 */

import { useCallback, useEffect, useState } from "react";

// ── shared types (loose — read-only view) ──────────────────────────────
interface EpisodeRow {
  episode_key: string;
  instruction: string | null;
  status: string | null;
  divergence: boolean;
  step_count: number;
  cost: Record<string, unknown> | null;
  started_at: string | null;
}
interface RecalledMemory {
  id: number | null;
  memo_class: string | null;
  title: string | null;
  layer: string | null;
}
interface RoundRow {
  node: string | null;
  phase_id: string | null;
  round: number | null;
  user_msg: string | null;
  raw_response: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cache_read: number | null;
  finish_reason: string | null;
  recalled: RecalledMemory[];
}
interface StepRow {
  agent: string | null;
  phase_id: string | null;
  event_type: string | null;
  payload: Record<string, unknown> | null;
  ts: string | null;
}
interface Detail {
  episode_key: string;
  instruction: string | null;
  status: string | null;
  divergence: boolean;
  self_assessment: Record<string, unknown> | null;
  user_feedback: Array<Record<string, unknown>> | null;
  cost: Record<string, unknown> | null;
  plan: Array<Record<string, unknown>> | null;
  steps: StepRow[];
  // case-meta bar fields — Java ships these in a parallel workstream, so every
  // one may be missing on older episodes. Read defensively.
  user_id?: number | string | null;
  username?: string | null;
  trigger_source?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  phase_count?: number | null;
}

const AGENT_COLOR: Record<string, string> = {
  planner: "#2563eb",
  builder: "#059669",
  repair: "#d97706",
  verifier: "#6b7280",
};
const MEMO_COLOR: Record<string, string> = {
  domain: "#7c3aed",
  preference: "#0891b2",
  presentation: "#db2777",
  correction: "#dc2626",
  episodic: "#65a30d",
  procedure: "#ca8a04",
};

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body?.error as string) || `HTTP ${res.status}`);
  return (body?.data ?? body) as T;
}

// ── page ────────────────────────────────────────────────────────────────
type Tab = "trace" | "timeline" | "scorecard";

export default function AgentActivityPage() {
  const [episodes, setEpisodes] = useState<EpisodeRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("trace");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<EpisodeRow[]>("/api/agent-activity/episodes?limit=40")
      .then((rows) => {
        setEpisodes(rows);
        // ?episode= deep link（Supervisor 提案的來源紀錄 chip）優先
        const want = typeof window !== "undefined"
          ? new URLSearchParams(window.location.search).get("episode") : null;
        if (want && rows.some((r) => r.episode_key === want)) setSelected(want);
        else if (rows.length && !selected) setSelected(rows[0].episode_key);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div style={{ display: "flex", height: "100%", fontSize: 13, color: "#1f2937" }}>
      {/* left: episode picker */}
      <aside style={{ width: 320, borderRight: "1px solid #e5e7eb", overflowY: "auto", flexShrink: 0 }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid #e5e7eb" }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Agent Activity</div>
          <div style={{ color: "#6b7280", fontSize: 12, marginTop: 2 }}>
            planner / builder / repair 的建構軌跡與記憶引用
          </div>
        </div>
        {loading && <div style={{ padding: 16, color: "#6b7280" }}>載入中…</div>}
        {error && <div style={{ padding: 16, color: "#dc2626" }}>{error}</div>}
        {episodes.map((e) => (
          <button
            key={e.episode_key}
            onClick={() => setSelected(e.episode_key)}
            style={{
              display: "block", width: "100%", textAlign: "left", cursor: "pointer",
              padding: "10px 16px 10px 13px", border: "none",
              borderBottom: "1px solid #f3f4f6",
              borderLeft: e.episode_key === selected ? "3px solid #2563eb" : "3px solid transparent",
              background: e.episode_key === selected ? "#eff6ff" : "#fff",
              fontWeight: e.episode_key === selected ? 600 : 400,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <span style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {e.instruction || e.episode_key}
              </span>
              <StatusChip status={e.status} divergence={e.divergence} />
            </div>
            <div style={{ color: "#9ca3af", fontSize: 11, marginTop: 3 }}>
              {e.step_count} steps · {e.started_at ? new Date(e.started_at).toLocaleString() : "—"}
            </div>
          </button>
        ))}
        {!loading && !episodes.length && !error && (
          <div style={{ padding: 16, color: "#9ca3af" }}>
            尚無 episode。開啟 ENABLE_AGENT_EPISODES 並跑一次 build 後即會出現。
          </div>
        )}
      </aside>

      {/* right: tabs */}
      <main style={{ flex: 1, overflowY: "auto", padding: 0 }}>
        <div style={{ display: "flex", gap: 4, padding: "10px 20px 0", borderBottom: "1px solid #e5e7eb", position: "sticky", top: 0, background: "#fff", zIndex: 1 }}>
          {([["trace", "Trace 明細"], ["timeline", "時間軸概覽"], ["scorecard", "記分板"]] as [Tab, string][]).map(
            ([t, label]) => (
              <button key={t} onClick={() => setTab(t)} style={tabStyle(tab === t)}>{label}</button>
            )
          )}
        </div>
        {/* key 必須加前綴：MetaBar 與 Tab 是同層 siblings，先前兩者都用裸
            `selected` 當 key —— sibling 重複 key 讓 React reconciler 在切換
            episode 時不拆舊 MetaBar，meta 列一條條累積（bug 修 3 次的根因，
            prod 無警告靜默壞）。 */}
        {selected && <MetaBar key={`meta-${selected}`} episodeKey={selected} />}
        {!selected ? (
          <div style={{ padding: 40, color: "#9ca3af" }}>左側選一個 build。</div>
        ) : tab === "trace" ? (
          <TraceTab key={`tab-${selected}`} episodeKey={selected} />
        ) : tab === "timeline" ? (
          <TimelineTab key={`tab-${selected}`} episodeKey={selected} />
        ) : (
          <ScorecardTab key={`tab-${selected}`} episodeKey={selected} />
        )}
      </main>
    </div>
  );
}

// ── case-meta bar (spec item #2 「一個 case 要有基本 meta」) ──────────────
// NOTE: this page is not yet i18n'd — its strings are inline CJK like the rest
// of the file. Migrating agent-activity to next-intl is a separate follow-up;
// the new meta-bar strings below intentionally match the page's existing style.

/** ms → "2m 14s" / "47s" / "1h 03m". null/negative → null (caller shows 進行中). */
function humanizeDuration(ms: number | null | undefined): string | null {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return null;
  const totalSec = Math.round(ms / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

/** Best-effort 觸發來源 from the instruction prefix. Only "[resume:<kind>]"
 *  gives a real source; "[intent_confirmed:…]" is stripped (the underlying
 *  chat-vs-builder origin is not persisted), everything else → "—". */
const TRIGGER_LABEL: Record<string, string> = {
  chat: "對話", builder: "Builder", skill: "Skill", schedule: "排程",
};
/** 觸發來源：優先用 episode 記錄的 trigger_source（V76）；舊 episode 無值時
 *  退回 instruction 前綴推導（resume:… 才有意義）。 */
function deriveTrigger(d: { trigger_source?: string | null; instruction?: string | null }): string {
  const src = (d.trigger_source ?? "").trim();
  if (src) return TRIGGER_LABEL[src] ?? src;
  const inst = d.instruction ?? "";
  const resume = inst.match(/^\s*\[resume:([^\]]+)\]/);
  if (resume) return `resume · ${resume[1].trim()}`;
  return "—";
}

function metaResult(status: string | null | undefined): { label: string; fg: string; bg: string } {
  const s = (status ?? "").toLowerCase();
  if (s === "finished" || s === "success" || s === "done")
    return { label: "成功", fg: "#059669", bg: "#ecfdf5" };
  if (s === "failed" || s === "error" || s === "handover" || s === "aborted")
    return { label: "失敗", fg: "#dc2626", bg: "#fef2f2" };
  // interrupted = janitor swept an orphaned 'running' row (sidecar died
  // mid-build). Distinct from 失敗 — the build never got to fail, it was cut.
  if (s === "interrupted")
    return { label: "中斷", fg: "#92400e", bg: "#fffbeb" };
  if (s === "running" || s === "in_progress")
    return { label: "進行中", fg: "#b45309", bg: "#fffbeb" };
  return { label: status ?? "—", fg: "#6b7280", bg: "#f3f4f6" };
}

/** Aggregate LLM-call stats across agents from cost_json. calls comes from the
 *  recorder's per-agent rollup; latency_ms is the summed per-call latency, so
 *  avg = total latency / calls. Returns null avg when there were no calls. */
function llmStats(cost: Record<string, unknown> | null): { calls: number; avgMs: number | null } {
  if (!cost || typeof cost !== "object") return { calls: 0, avgMs: null };
  let calls = 0, latency = 0;
  for (const v of Object.values(cost)) {
    if (v && typeof v === "object") {
      calls += Number((v as Record<string, unknown>).calls ?? 0);
      latency += Number((v as Record<string, unknown>).latency_ms ?? 0);
    }
  }
  return { calls, avgMs: calls > 0 ? latency / calls : null };
}

function MetaBar({ episodeKey }: { episodeKey: string }) {
  const [d, setD] = useState<Detail | null>(null);
  useEffect(() => {
    let alive = true;            // 忽略過期回應：切換 episode 後舊 fetch 不覆蓋
    setD(null);                  // 立即清空，避免上一筆 meta 疊到下一筆
    getJson<Detail>(`/api/agent-activity/episodes/${encodeURIComponent(episodeKey)}`)
      .then((r) => { if (alive) setD(r); })
      .catch(() => { if (alive) setD(null); });
    return () => { alive = false; };
  }, [episodeKey]);
  // 載入中顯示骨架列（而非整條消失）→ 給「已選取、正在載入」的提示
  if (!d) {
    return (
      <div style={{ padding: "12px 20px", borderBottom: "1px solid #e5e7eb",
                    background: "#fafafa", color: "#9ca3af", fontSize: 12.5 }}>
        載入 case 詳情…
      </div>
    );
  }

  const who = d.username?.trim()
    || (d.user_id != null && String(d.user_id) !== "" ? `#${d.user_id}` : null)
    || "—";
  const when = d.started_at ? new Date(d.started_at).toLocaleString() : "—";
  const dur = humanizeDuration(d.duration_ms);
  const running = (d.status ?? "").toLowerCase() === "running" || (!dur && !d.finished_at);
  const duration = dur ?? (running ? "進行中" : "—");
  const result = metaResult(d.status);
  const phases = d.phase_count != null ? String(d.phase_count) : "—";
  const trigger = deriveTrigger(d);
  const { calls, avgMs } = llmStats(d.cost);
  // Topic = the user's original prompt. Resume rounds carry a technical
  // "[resume:…]" instruction — strip it so the topic reads like what the
  // user actually typed (the original instruction is first-write-wins on
  // the episode, so this is mostly a legacy-row safety net).
  const rawTopic = (d.instruction ?? "").trim();
  const topic = rawTopic.replace(/^\[resume:[^\]]*\]\s*/, "").trim();

  return (
    <div style={{ borderBottom: "1px solid #e5e7eb", background: "#fafafa" }}>
      <div style={{ padding: "14px 20px 0" }}>
        {/* user first (使用者要求「下 prompt 的 user 顯示在第 1 個」) */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{
            fontSize: 12, fontWeight: 700, color: "#1e40af", background: "#eff6ff",
            border: "1px solid #bfdbfe", borderRadius: 999, padding: "1px 10px",
          }}>{who}</span>
          <span style={{ fontSize: 10.5, color: "#9ca3af" }}>的原始指令</span>
        </div>
        <div style={{
          fontSize: 15, fontWeight: 700, color: "#111827", lineHeight: 1.5,
          whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}>
          {topic || "（無指令內容 — 例如由排程觸發）"}
        </div>
      </div>
      <div style={{
        display: "flex", flexWrap: "wrap", gap: 8, padding: "10px 20px 12px",
      }}>
      <MetaCell label="誰觸發" value={who} />
      <MetaCell label="何時" value={when} />
      <MetaCell label="花費多久" value={duration} />
      <MetaCell label="結果">
        <span style={{
          fontSize: 12, fontWeight: 600, color: result.fg, background: result.bg,
          borderRadius: 999, padding: "1px 10px",
        }}>{result.label}</span>
      </MetaCell>
      <MetaCell label="階段數" value={phases} />
      <MetaCell label="觸發來源" value={trigger} />
      <MetaCell label="LLM 呼叫" value={calls > 0 ? `${calls} 次` : "—"} />
      <MetaCell label="平均每次耗時"
        value={avgMs != null ? `${(avgMs / 1000).toFixed(1)}s` : "—"} />
      </div>
    </div>
  );
}

function MetaCell({ label, value, children }: { label: string; value?: string; children?: React.ReactNode }) {
  return (
    <div style={{
      border: "1px solid #e5e7eb", borderRadius: 8, background: "#fff",
      padding: "6px 12px", minWidth: 96,
    }}>
      <div style={{ fontSize: 10.5, color: "#9ca3af", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "#1f2937" }}>
        {children ?? value ?? "—"}
      </div>
    </div>
  );
}

// ── Tab A: Trace 明細 (primary — mirrors build trace + memory refs) ──────
function TraceTab({ episodeKey }: { episodeKey: string }) {
  const [rounds, setRounds] = useState<RoundRow[] | null>(null);
  const [available, setAvailable] = useState(true);
  const [reason, setReason] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getJson<{ available: boolean; rounds?: RoundRow[]; reason?: string }>(
      `/api/agent-activity/episodes/${encodeURIComponent(episodeKey)}/rounds`
    )
      .then((d) => {
        setAvailable(d.available);
        setReason(d.reason ?? null);
        setRounds(d.rounds ?? []);
      })
      .catch((e) => setErr(String(e.message || e)));
  }, [episodeKey]);

  if (err) return <div style={{ padding: 24, color: "#dc2626" }}>{err}</div>;
  if (rounds === null) return <div style={{ padding: 24, color: "#6b7280" }}>載入 trace…</div>;
  if (!available)
    return (
      <div style={{ padding: 24 }}>
        <div style={{ color: "#b45309", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 8, padding: 14 }}>
          此 build 沒有可讀的 trace 檔案（BuildTracer 未寫入或已輪替），無法顯示逐輪 prompt/output。
          <div style={{ color: "#92400e", fontSize: 12, marginTop: 6 }}>{reason}</div>
          <div style={{ marginTop: 8, fontSize: 12 }}>可切換到「時間軸概覽」用 step 事件流檢視。</div>
        </div>
      </div>
    );

  // group rounds by phase, preserving order
  const phases: { phase: string; rows: RoundRow[] }[] = [];
  for (const r of rounds) {
    const ph = r.phase_id || "(plan)";
    let g = phases.find((x) => x.phase === ph);
    if (!g) { g = { phase: ph, rows: [] }; phases.push(g); }
    g.rows.push(r);
  }

  return (
    <div style={{ padding: "18px 20px 60px" }}>
      {phases.map((g) => (
        <section key={g.phase} style={{ marginBottom: 22 }}>
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ background: "#111827", color: "#fff", borderRadius: 6, padding: "2px 10px", fontSize: 12 }}>
              {g.phase}
            </span>
            <span style={{ color: "#9ca3af", fontWeight: 400, fontSize: 12 }}>{g.rows.length} round(s)</span>
          </div>
          {g.rows.map((r, i) => <RoundCard key={i} r={r} />)}
        </section>
      ))}
      {!phases.length && <div style={{ color: "#9ca3af" }}>此 trace 沒有 LLM 呼叫記錄。</div>}
    </div>
  );
}

function RoundCard({ r }: { r: RoundRow }) {
  const [open, setOpen] = useState(false);
  const agent = r.node?.includes("goal_plan") ? "planner"
    : r.node?.includes("revise") || r.node?.includes("repair") ? "repair"
    : "builder";
  const color = AGENT_COLOR[agent] ?? "#374151";
  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 8, marginBottom: 10, overflow: "hidden" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left", cursor: "pointer", padding: "8px 12px", border: "none", background: "#fafafa" }}
      >
        <span style={{ width: 8, height: 8, borderRadius: 8, background: color, flexShrink: 0 }} />
        <span style={{ fontWeight: 600, color }}>{agent}</span>
        <span style={{ color: "#6b7280", fontSize: 12 }}>round {r.round ?? "—"} · {r.node}</span>
        <span style={{ flex: 1 }} />
        {r.recalled?.length > 0 && (
          <span title="此輪引用的記憶條數" style={{ fontSize: 11, color: "#7c3aed", background: "#f5f3ff", borderRadius: 10, padding: "1px 8px" }}>
            ◎ {r.recalled.length} memory
          </span>
        )}
        <span style={{ fontSize: 11, color: "#9ca3af" }}>
          in {r.input_tokens ?? "—"} / out {r.output_tokens ?? "—"}
          {r.cache_read ? ` · cache ${r.cache_read}` : ""}
        </span>
        <span style={{ color: "#9ca3af" }}>{open ? "▲" : "▼"}</span>
      </button>

      {/* memory refs — always visible when present (U3 core requirement) */}
      {r.recalled?.length > 0 && (
        <div style={{ padding: "8px 12px", background: "#faf5ff", borderTop: "1px solid #f3e8ff", display: "flex", flexWrap: "wrap", gap: 6 }}>
          <span style={{ fontSize: 11, color: "#6b21a8", fontWeight: 600 }}>此輪 prompt 引用記憶：</span>
          {r.recalled.map((m, i) => (
            <span key={i} style={{ fontSize: 11, border: `1px solid ${MEMO_COLOR[m.memo_class ?? ""] ?? "#c4b5fd"}`, color: MEMO_COLOR[m.memo_class ?? ""] ?? "#6b21a8", borderRadius: 6, padding: "1px 7px", background: "#fff" }}>
              <b>{m.memo_class ?? "?"}</b>
              {m.layer ? ` · ${m.layer}` : ""} · {m.title || `#${m.id}`}
            </span>
          ))}
        </div>
      )}

      {open && (
        <div style={{ padding: 12 }}>
          <Labelled label="Prompt (user_msg)">
            <Pre text={r.user_msg} />
          </Labelled>
          <Labelled label={`Output (raw_response)${r.finish_reason ? ` · finish=${r.finish_reason}` : ""}`}>
            <Pre text={r.raw_response} />
          </Labelled>
        </div>
      )}
    </div>
  );
}

// ── Tab B: 時間軸概覽 (swim-lane over step events) ───────────────────────

/** 事件 → 人話。回傳 [動作標籤, 細節說明]。未知型別原樣顯示（誠實）。 */
function describeStep(s: StepRow): [string, string] {
  const p = (s.payload ?? {}) as Record<string, unknown>;
  const str = (k: string) => String(p[k] ?? "").trim();
  switch (s.event_type ?? "") {
    case "phase_started": return ["開始階段", ""];
    case "phase_done": {
      const r = p["rounds_used"];
      return ["階段完成", r != null ? `用了 ${r} 輪` : ""];
    }
    case "block_picked": return ["選用 block", str("block")];
    case "tool_action": {
      const t = str("tool");
      const err = str("error");
      const suffix = err ? `（失敗：${err.slice(0, 60)}）` : "";
      switch (t) {
        case "inspect_block_doc": return ["查閱文件", `${str("block")}${suffix}`];
        case "inspect_node_output": return ["檢視節點輸出", `${str("node")}${suffix}`];
        case "add_node": return ["加入節點", `${str("block")}${p["node"] ? ` → ${str("node")}` : ""}${suffix}`];
        case "commit_pick": return ["決定用 block", `${str("block")}${suffix}`];
        case "set_param": return ["調整參數", `${str("node")}.${str("param")}${suffix}`];
        case "connect": return ["連接節點", `${str("from")} → ${str("to")}${suffix}`];
        case "remove_node": return ["移除節點", `${str("node")}${suffix}`];
        case "abort_node": return ["放棄此節點", `${str("node")}${suffix}`];
        case "run_verifier": return ["請求驗證", suffix];
        case "phase_complete": return ["宣告階段完成", suffix];
        case "abort_phase": return ["放棄此階段", suffix];
        default: return [t || "動作", suffix];
      }
    }
    case "llm_usage": {
      const tok = Number(p["output_tokens"] ?? 0) + Number(p["input_tokens"] ?? 0);
      return ["LLM 思考", tok ? `${tok} tokens` : ""];
    }
    case "memory_recall": {
      const n = Array.isArray(p["recalled"]) ? (p["recalled"] as unknown[]).length : 0;
      return ["引用記憶", n ? `${n} 筆` : "無命中"];
    }
    case "memory_write": return ["寫入記憶", str("title")];
    case "verifier_reject": {
      const why = str("result") || str("error_message");
      return ["驗證未通過", `${str("block_id")}${why ? ` — ${why.slice(0, 70)}` : ""}`];
    }
    case "param_reject_fix": return ["參數修正後通過", ""];
    case "stuck_escalated": return ["卡住，升級處理", ""];
    case "repair_triggered": return ["觸發修復 agent", ""];
    case "repair_outcome": {
      const r = str("result");
      return ["修復結果", r === "retry" ? "重試成功路徑" : r === "handover" ? "交回使用者決定" : r];
    }
    case "plan_proposed": return ["提出建置計畫", ""];
    case "plan_confirmed": return ["計畫已確認", ""];
    case "plan_user_edited": return ["使用者修改了計畫", ""];
    case "replan": return ["重新規劃", ""];
    case "work_order": {
      const ops = Array.isArray(p["ops"]) ? (p["ops"] as unknown[]).join("、") : "";
      const failed = str("failed_op");
      return ["修理工單", `[${str("kind")}] ${str("diagnosis").slice(0, 60)} → ${ops}${failed ? `（中斷於 ${failed.slice(0, 40)}）` : ""}`];
    }
    case "plan_patch": {
      const ops = Array.isArray(p["ops"]) ? (p["ops"] as Array<Record<string, unknown>>) : [];
      const kept = Array.isArray(p["preserved"]) ? (p["preserved"] as unknown[]).join(",") : "";
      const opsTxt = ops.map((o) => `${o["op"] === "remove_phase" ? "移除" : "改寫"} ${o["id"]}`).join("、");
      return ["計畫修訂", `${opsTxt}${kept ? `（保留 ${kept}）` : ""}`];
    }
    case "source_cache_stats": {
      const h = Number(p["hits"] ?? 0), f = Number(p["fetches"] ?? 0);
      return ["資料重用統計", `實際取資料 ${f} 次、重用 ${h} 次`];
    }
    case "situation_report": {
      const nodes = Array.isArray(p["nodes"]) ? (p["nodes"] as Array<Record<string, unknown>>) : [];
      const withCols = nodes.filter((n) => Array.isArray(n["output_columns"]) && (n["output_columns"] as unknown[]).length);
      const cols = withCols.map((n) => `${n["id"]}: ${(n["output_columns"] as string[]).slice(0, 6).join("/")}`).join("；");
      return ["看現況（交給 Planner）", `${str("route")}｜${nodes.length} 節點${cols ? `｜欄位 ${cols.slice(0, 120)}` : ""}`];
    }
    case "modify_plan": {
      const ops = Array.isArray(p["ops"]) ? (p["ops"] as Array<Record<string, unknown>>) : [];
      const opsTxt = ops.map((o) => `${o["node"]}: ${Object.keys((o["params"] as Record<string, unknown>) ?? {}).join(",")}`).join("、");
      const mode = str("mode");
      return ["微調計畫", `${mode === "delta" ? "增量" : mode}｜${opsTxt || str("reason").slice(0, 60)}`];
    }
    default: return [s.event_type ?? "—", ""];
  }
}

function TimelineTab({ episodeKey }: { episodeKey: string }) {
  const [d, setD] = useState<Detail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    getJson<Detail>(`/api/agent-activity/episodes/${encodeURIComponent(episodeKey)}`)
      .then(setD).catch((e) => setErr(String(e.message || e)));
  }, [episodeKey]);
  if (err) return <div style={{ padding: 24, color: "#dc2626" }}>{err}</div>;
  if (!d) return <div style={{ padding: 24, color: "#6b7280" }}>載入…</div>;

  return (
    <div style={{ padding: "18px 20px 60px" }}>
      <div style={{ color: "#6b7280", marginBottom: 12 }}>{d.steps.length} 個事件，依時間排序。memory_recall 用紫色標示。</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {d.steps.map((s, i) => {
          const color = AGENT_COLOR[s.agent ?? ""] ?? "#374151";
          const isRecall = s.event_type === "memory_recall";
          const isReject = s.event_type === "verifier_reject";
          const isMilestone = s.event_type === "phase_done" || s.event_type === "phase_started";
          const [label, detail] = describeStep(s);
          return (
            <div key={i} style={{
              display: "flex", alignItems: "center", gap: 10, padding: "5px 8px",
              borderRadius: 6,
              background: isRecall ? "#faf5ff" : isReject ? "#fff7f5" : "transparent",
            }}>
              <span style={{ width: 64, fontSize: 11, color: "#9ca3af", flexShrink: 0 }}>
                {s.ts ? new Date(s.ts).toLocaleTimeString() : "—"}
              </span>
              <span style={{ width: 70, fontWeight: 600, color, fontSize: 12, flexShrink: 0 }}>{s.agent ?? "—"}</span>
              {s.phase_id && <span style={{ fontSize: 11, color: "#9ca3af", flexShrink: 0 }}>[{s.phase_id}]</span>}
              <span style={{
                fontSize: 12.5, flexShrink: 0,
                fontWeight: isMilestone ? 700 : 500,
                color: isReject ? "#b42318" : isRecall ? "#7c3aed" : "#1f2937",
              }}>
                {label}
              </span>
              {detail && (
                <span style={{ fontSize: 12, color: "#6b7280", fontFamily: "ui-monospace,monospace",
                               overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {detail}
                </span>
              )}
            </div>
          );
        })}
        {!d.steps.length && <div style={{ color: "#9ca3af" }}>此 build 無 step 事件。</div>}
      </div>
    </div>
  );
}

// ── Tab C: 記分板 (episode scorecard) ───────────────────────────────────
function ScorecardTab({ episodeKey }: { episodeKey: string }) {
  const [d, setD] = useState<Detail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    getJson<Detail>(`/api/agent-activity/episodes/${encodeURIComponent(episodeKey)}`)
      .then(setD).catch((e) => setErr(String(e.message || e)));
  }, [episodeKey]);
  if (err) return <div style={{ padding: 24, color: "#dc2626" }}>{err}</div>;
  if (!d) return <div style={{ padding: 24, color: "#6b7280" }}>載入…</div>;

  const recallCount = d.steps.filter((s) => s.event_type === "memory_recall").length;
  const byAgent: Record<string, number> = {};
  for (const s of d.steps) byAgent[s.agent ?? "—"] = (byAgent[s.agent ?? "—"] ?? 0) + 1;

  return (
    <div style={{ padding: "18px 20px 60px", maxWidth: 720 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(150px,1fr))", gap: 12, marginBottom: 20 }}>
        <Stat label="狀態" value={d.status ?? "—"} accent={d.status === "success" ? "#059669" : d.status === "error" ? "#dc2626" : "#6b7280"} />
        <Stat label="Divergence" value={d.divergence ? "是（自評OK但被拒）" : "否"} accent={d.divergence ? "#dc2626" : "#059669"} />
        <Stat label="記憶引用次數" value={String(recallCount)} accent="#7c3aed" />
        <Stat label="事件總數" value={String(d.steps.length)} />
      </div>

      <Section title="Instruction">{d.instruction || "—"}</Section>

      <Section title="每個 agent 的事件數">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {Object.entries(byAgent).map(([a, n]) => (
            <span key={a} style={{ border: "1px solid #e5e7eb", borderRadius: 6, padding: "3px 10px" }}>
              <b style={{ color: AGENT_COLOR[a] ?? "#374151" }}>{a}</b> · {n}
            </span>
          ))}
        </div>
      </Section>

      <Section title="Plan">
        {d.plan?.length ? (
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            {d.plan.map((p, i) => (
              <li key={i} style={{ marginBottom: 3 }}>
                {String((p as Record<string, unknown>).id ?? i)}: {String((p as Record<string, unknown>).text ?? (p as Record<string, unknown>).goal ?? JSON.stringify(p))}
              </li>
            ))}
          </ol>
        ) : "—"}
      </Section>

      <Section title="Self assessment">
        <Pre text={d.self_assessment ? JSON.stringify(d.self_assessment, null, 2) : null} />
      </Section>

      {d.user_feedback && d.user_feedback.length > 0 && (
        <Section title="User feedback">
          <Pre text={JSON.stringify(d.user_feedback, null, 2)} />
        </Section>
      )}

      <Section title="Cost">
        <Pre text={d.cost ? JSON.stringify(d.cost, null, 2) : null} />
      </Section>
    </div>
  );
}

// ── small presentational helpers ─────────────────────────────────────────
function StatusChip({ status, divergence }: { status: string | null; divergence: boolean }) {
  const bg = divergence ? "#fef2f2" : status === "success" ? "#ecfdf5" : status === "error" ? "#fef2f2" : "#f3f4f6";
  const fg = divergence ? "#dc2626" : status === "success" ? "#059669" : status === "error" ? "#dc2626" : "#6b7280";
  return (
    <span style={{ fontSize: 10, background: bg, color: fg, borderRadius: 10, padding: "1px 7px", flexShrink: 0, whiteSpace: "nowrap" }}>
      {divergence ? "diverge" : status ?? "?"}
    </span>
  );
}
function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: "10px 12px" }}>
      <div style={{ fontSize: 11, color: "#9ca3af" }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: accent ?? "#111827", marginTop: 2 }}>{value}</div>
    </div>
  );
}
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>{title}</div>
      <div>{children}</div>
    </div>
  );
}
function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 11, color: "#6b7280", fontWeight: 600, marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}
function Pre({ text }: { text: string | null | undefined }) {
  return (
    <pre style={{ margin: 0, background: "#0f172a", color: "#e2e8f0", padding: 12, borderRadius: 6, fontSize: 12, lineHeight: 1.5, overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 360, overflowY: "auto" }}>
      {text || "（空）"}
    </pre>
  );
}
function tabStyle(active: boolean): React.CSSProperties {
  return {
    padding: "8px 16px", cursor: "pointer", border: "none", background: "transparent",
    fontWeight: active ? 700 : 500, color: active ? "#111827" : "#6b7280",
    borderBottom: active ? "2px solid #111827" : "2px solid transparent", marginBottom: -1,
  };
}
