"use client";

/**
 * Agent Rules & Knowledge — user-owned maintenance surface (V32, 2026-05-11).
 *
 * 4 tabs: Directives / Knowledge / Lexicon / Examples — each backed by
 * a /api/agent-* proxy that forwards to Java. Sidecar's context_loader
 * retrieves these at conversation start to enrich the system prompt.
 *
 * Adapted from /Users/gill/Downloads/agent-rules-standalone (mockup).
 */
import { useEffect, useMemo, useRef, useState } from "react";

type ScopeType = "global" | "skill" | "tool" | "recipe";
type Priority = "high" | "med" | "low";

interface Directive {
  id: number;
  scope_type: ScopeType;
  scope_value?: string | null;
  title: string;
  body: string;
  priority: Priority;
  active: boolean;
  source: string;
  created_at: string;
  updated_at: string;
  uses?: number;
}

type MemoClass = "domain" | "preference" | "presentation" | "correction" | "episodic" | "procedure";
type WrittenBy = "planner" | "builder" | "repair" | "human";

interface Knowledge extends Directive {
  uses: number;
  last_used_at?: string | null;
  memo_class?: MemoClass | null;
  written_by?: WrittenBy | null;
  applies_to?: "plan" | "execute" | "both" | null;
  always_on?: boolean;
}

interface DocMemo {
  id: number;
  block_id: string;
  param?: string | null;
  memo: string;
  status: string;
  from_episode?: string | null;
  created_at: string;
}

// agent provenance (who wrote the memory) — the core "分是誰的" dimension
const AGENT_META: Record<WrittenBy, { label: string; color: string; bg: string }> = {
  planner: { label: "Planner", color: "#1d4ed8", bg: "#eff6ff" },
  builder: { label: "Builder", color: "#047857", bg: "#ecfdf5" },
  repair:  { label: "Repair",  color: "#b45309", bg: "#fffbeb" },
  human:   { label: "Human",   color: "#475569", bg: "#f1f5f9" },
};
const MEMO_CLASS_COLOR: Record<MemoClass, string> = {
  domain: "#7c3aed", preference: "#0891b2", presentation: "#db2777",
  correction: "#dc2626", episodic: "#65a30d", procedure: "#ca8a04",
};

interface Lexicon {
  id: number;
  term: string;
  standard: string;
  note?: string | null;
  uses: number;
  created_at: string;
  updated_at: string;
}

interface Example {
  id: number;
  scope_type: ScopeType;
  scope_value?: string | null;
  title: string;
  input_text: string;
  output_text: string;
  uses: number;
  last_used_at?: string | null;
  created_at: string;
  updated_at: string;
}

const TABS = [
  { id: "directives", label: "Directives", desc: "always-on prompt rules" },
  { id: "knowledge",  label: "Knowledge",  desc: "RAG-retrievable domain facts" },
  { id: "lexicon",    label: "Lexicon",    desc: "your jargon → standard term" },
  { id: "examples",   label: "Examples",   desc: "few-shot pairs by intent" },
] as const;
type Tab = typeof TABS[number]["id"];

const PRIORITY_COLOR: Record<Priority, string> = {
  high: "#dc2626", med: "#d97706", low: "#94a3b8",
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  const j = await res.json();
  if (!res.ok || j?.ok === false) {
    throw new Error(j?.error?.message ?? `HTTP ${res.status}`);
  }
  return j.data as T;
}

export function AgentKnowledgePanel() {
  // Agent Console 教它入口 (2026-07-04): /agent-knowledge?prefill_block=…&
  // prefill_phase=…&prefill_instruction=… lands on the knowledge tab with a
  // draft pre-filled from the build step the user was looking at.
  const prefill = useMemo(() => {
    if (typeof window === "undefined") return null;
    const q = new URLSearchParams(window.location.search);
    const block = q.get("prefill_block");
    const phase = q.get("prefill_phase");
    const instruction = q.get("prefill_instruction");
    if (!block && !phase && !instruction) return null;
    return { block, phase, instruction };
  }, []);
  // Agent Console 記憶 chip (2026-07-05): /agent-knowledge?id=N 直接打開該筆
  // 的編輯器，而不是只落在列表頁。
  const openId = useMemo(() => {
    if (typeof window === "undefined") return null;
    const raw = new URLSearchParams(window.location.search).get("id");
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) ? n : null;
  }, []);
  const [tab, setTab] = useState<Tab>((prefill || openId != null) ? "knowledge" : "directives");

  return (
    <div style={{ padding: 24, maxWidth: 1280, margin: "0 auto", fontFamily: "system-ui, sans-serif" }}>
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600 }}>Rules &amp; Knowledge</h1>
        <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: 13 }}>
          Maintain what the agent knows about your domain. Each tab feeds a
          different prompt-injection surface — directives ride on every reply,
          knowledge is RAG-retrieved by relevance, lexicon rewrites jargon
          inline, examples teach response style.
        </p>
      </header>

      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e2e8f0", marginBottom: 18 }}>
        {TABS.map((t) => (
          <button key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: "10px 16px", border: "none", background: "none",
              borderBottom: tab === t.id ? "2px solid #2563eb" : "2px solid transparent",
              color: tab === t.id ? "#1e293b" : "#64748b",
              fontWeight: tab === t.id ? 600 : 400, fontSize: 13.5, cursor: "pointer",
            }}>
            {t.label}
          </button>
        ))}
        <span style={{ flex: 1 }}/>
        <span style={{ alignSelf: "center", fontSize: 12, color: "#94a3b8", paddingRight: 4 }}>
          {TABS.find((t) => t.id === tab)?.desc}
        </span>
      </div>

      {tab === "directives" && <DirectivesView />}
      {tab === "knowledge"  && <KnowledgeView prefill={prefill} openId={openId} />}
      {tab === "lexicon"    && <LexiconView />}
      {tab === "examples"   && <ExamplesView />}
    </div>
  );
}

// ── Directives tab ────────────────────────────────────────────────────

function DirectivesView() {
  const [items, setItems] = useState<Directive[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Directive | "new" | null>(null);

  const load = async () => {
    setLoading(true);
    try { setItems(await api<Directive[]>("/api/agent-directives")); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const onSave = async (d: Partial<Directive>, id?: number) => {
    if (id) await api(`/api/agent-directives/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    else await api("/api/agent-directives", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    setEditing(null);
    await load();
  };

  const onDelete = async (id: number) => {
    if (!confirm("Delete this directive?")) return;
    await api(`/api/agent-directives/${id}`, { method: "DELETE" });
    await load();
  };

  const onToggleActive = async (d: Directive) => {
    await api(`/api/agent-directives/${d.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active: !d.active }) });
    await load();
  };

  return (
    <div>
      <div style={{ display: "flex", marginBottom: 12 }}>
        <span style={{ flex: 1 }}/>
        <button onClick={() => setEditing("new")} style={btnStyle("primary")}>+ New directive</button>
      </div>
      {loading ? <p style={muted}>Loading…</p>
       : items.length === 0 ? <Empty message="No directives yet. Add one to bias every agent response."/>
       : <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
           {items.map((d) => (
             <ItemRow key={d.id} d={d} onEdit={() => setEditing(d)}
               onToggleActive={() => onToggleActive(d)}
               onDelete={() => onDelete(d.id)}/>
           ))}
         </div>}
      {editing && (
        <DirectiveEditor
          initial={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSave={onSave}/>
      )}
    </div>
  );
}

function ItemRow({ d, onEdit, onToggleActive, onDelete }: {
  d: Directive; onEdit: () => void; onToggleActive: () => void; onDelete: () => void;
}) {
  const scopeLabel = d.scope_value ? `${d.scope_type}:${d.scope_value}` : d.scope_type;
  return (
    <div style={{
      padding: "12px 16px", border: "1px solid #e2e8f0", borderRadius: 6,
      background: d.active ? "#fff" : "#f8fafc", opacity: d.active ? 1 : 0.6,
      display: "flex", alignItems: "flex-start", gap: 12,
    }}>
      <span style={{ width: 8, height: 8, borderRadius: 999, background: PRIORITY_COLOR[d.priority], marginTop: 6, flexShrink: 0 }}/>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 4 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "#1e293b" }}>{d.title}</span>
          <Pill>{scopeLabel}</Pill>
          <Pill>{d.priority}</Pill>
          {!d.active && <Pill color="#94a3b8">disabled</Pill>}
          {d.source === "auto-promoted" && <Pill color="#7c3aed" bg="#f3e8ff">✨ auto</Pill>}
        </div>
        <div style={{ fontSize: 12.5, color: "#64748b", lineHeight: 1.5 }}>{d.body}</div>
        {(d.uses ?? 0) > 0 && (
          <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>fired {d.uses} time(s)</div>
        )}
      </div>
      <div style={{ display: "flex", gap: 4 }}>
        <button onClick={onToggleActive} style={btnStyle("secondary")} title={d.active ? "disable" : "enable"}>
          {d.active ? "● on" : "○ off"}
        </button>
        <button onClick={onEdit} style={btnStyle("secondary")}>Edit</button>
        <button onClick={onDelete} style={btnStyle("danger")}>×</button>
      </div>
    </div>
  );
}

function DirectiveEditor({ initial, onClose, onSave }: {
  initial: Directive | null;
  onClose: () => void;
  onSave: (d: Partial<Directive>, id?: number) => Promise<void>;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [body, setBody] = useState(initial?.body ?? "");
  const [scopeType, setScopeType] = useState<ScopeType>(initial?.scope_type ?? "global");
  const [scopeValue, setScopeValue] = useState(initial?.scope_value ?? "");
  const [priority, setPriority] = useState<Priority>(initial?.priority ?? "med");
  const [busy, setBusy] = useState(false);
  return (
    <Modal onClose={onClose} title={initial ? "Edit directive" : "New directive"}>
      <Field label="Title">
        <input value={title} onChange={(e) => setTitle(e.target.value)} style={inputStyle}/>
      </Field>
      <Field label="Body (the actual rule)">
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5} style={{ ...inputStyle, fontFamily: "inherit", resize: "vertical" }}/>
      </Field>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr 1fr", gap: 10 }}>
        <Field label="Scope">
          <select value={scopeType} onChange={(e) => setScopeType(e.target.value as ScopeType)} style={inputStyle}>
            <option value="global">global</option>
            <option value="skill">skill</option>
            <option value="tool">tool</option>
            <option value="recipe">recipe</option>
          </select>
        </Field>
        <Field label={scopeType === "global" ? "(no value)" : "Scope value"}>
          <input value={scopeValue ?? ""} onChange={(e) => setScopeValue(e.target.value)}
            disabled={scopeType === "global"}
            placeholder={scopeType === "tool" ? "EQP-01" : scopeType === "skill" ? "skill-slug" : ""}
            style={inputStyle}/>
        </Field>
        <Field label="Priority">
          <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)} style={inputStyle}>
            <option value="high">high</option>
            <option value="med">med</option>
            <option value="low">low</option>
          </select>
        </Field>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button disabled={busy || !title.trim() || !body.trim()}
          onClick={async () => {
            setBusy(true);
            try {
              await onSave({
                title, body, scope_type: scopeType,
                scope_value: scopeType === "global" ? null : (scopeValue || null),
                priority,
              }, initial?.id);
            } finally { setBusy(false); }
          }}
          style={btnStyle(busy ? "secondary-disabled" : "primary")}>
          {busy ? "Saving…" : "Save"}
        </button>
        <button onClick={onClose} style={btnStyle("secondary")}>Cancel</button>
      </div>
    </Modal>
  );
}

// ── Knowledge tab (mostly mirrors Directives — same shape) ────────────

type AgentFilter = "all" | WrittenBy | "unclassified";
type ClassFilter = "all" | MemoClass;

function KnowledgeView({ prefill, openId }: {
  prefill?: { block: string | null; phase: string | null; instruction: string | null } | null;
  openId?: number | null;
}) {
  const [items, setItems] = useState<Knowledge[]>([]);
  const [docMemos, setDocMemos] = useState<DocMemo[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Knowledge | "new" | null>(null);
  // ?id=N：清單載入後自動打開該筆編輯器（只開一次）。
  const openedRef = useRef(false);
  useEffect(() => {
    if (openId == null || openedRef.current || items.length === 0) return;
    const hit = items.find((k) => k.id === openId);
    if (hit) {
      openedRef.current = true;
      setEditing(hit);
    }
  }, [openId, items]);
  const [agentF, setAgentF] = useState<AgentFilter>("all");
  const [classF, setClassF] = useState<ClassFilter>("all");

  // 教它 prefill: open the editor once with a draft carrying the build-step
  // context. No id → DirectiveEditor saves it as a CREATE.
  useEffect(() => {
    if (!prefill) return;
    const ctxLines = [
      prefill.block ? `工具/block：${prefill.block}` : null,
      prefill.phase ? `phase：${prefill.phase}` : null,
      prefill.instruction ? `原始指令：${prefill.instruction}` : null,
    ].filter(Boolean).join("\n");
    setEditing({
      title: `[教它] ${prefill.block ?? prefill.phase ?? "build 知識"}`,
      body: `${ctxLines}\n\n（描述正確做法）\n**Why:** \n**How to apply:** `,
      scope_type: "global", scope_value: null, priority: "med",
    } as unknown as Knowledge);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const [ks, dm] = await Promise.all([
        api<Knowledge[]>("/api/agent-knowledge"),
        api<DocMemo[]>("/api/agent-knowledge/doc-memos").catch(() => [] as DocMemo[]),
      ]);
      setItems(ks); setDocMemos(dm);
    } finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const onSave = async (d: Partial<Knowledge>, id?: number) => {
    if (id) await api(`/api/agent-knowledge/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    else await api("/api/agent-knowledge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    setEditing(null); await load();
  };
  const onDelete = async (id: number) => {
    if (!confirm("Delete?")) return;
    await api(`/api/agent-knowledge/${id}`, { method: "DELETE" }); await load();
  };
  const onToggleActive = async (d: Knowledge) => {
    await api(`/api/agent-knowledge/${d.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active: !d.active }) });
    await load();
  };

  // agent bucket for a row: written_by, or "unclassified" when null (legacy)
  const bucketOf = (d: Knowledge): AgentFilter => d.written_by ?? "unclassified";

  const showBuilder = agentF === "all" || agentF === "builder";
  const filtered = useMemo(() => items.filter((d) => {
    if (agentF !== "all" && bucketOf(d) !== agentF) return false;
    if (classF !== "all" && d.memo_class !== classF) return false;
    return true;
  }), [items, agentF, classF]);

  // per-agent counts for the filter chips (builder = doc-memo count)
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: items.length + docMemos.length, builder: docMemos.length };
    for (const d of items) { const b = bucketOf(d); c[b] = (c[b] ?? 0) + 1; }
    return c;
  }, [items, docMemos]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <FilterGroup label="誰寫的">
          {(["all", "planner", "builder", "repair", "human", "unclassified"] as AgentFilter[]).map((a) => (
            <FilterChip key={a} active={agentF === a} onClick={() => setAgentF(a)}
              color={a !== "all" && a !== "unclassified" ? AGENT_META[a as WrittenBy]?.color : "#475569"}>
              {a === "all" ? "全部" : a === "unclassified" ? "未分類" : AGENT_META[a as WrittenBy].label}
              {counts[a] != null && a !== "unclassified" ? ` ${counts[a]}` : ""}
            </FilterChip>
          ))}
        </FilterGroup>
        <FilterGroup label="類別">
          {(["all", "domain", "preference", "presentation", "correction", "episodic", "procedure"] as ClassFilter[]).map((c) => (
            <FilterChip key={c} active={classF === c} onClick={() => setClassF(c)}
              color={c !== "all" ? MEMO_CLASS_COLOR[c as MemoClass] : "#475569"}>
              {c === "all" ? "全部" : c}
            </FilterChip>
          ))}
        </FilterGroup>
        <span style={{ flex: 1 }}/>
        <button onClick={() => setEditing("new")} style={btnStyle("primary")}>+ New knowledge fact</button>
      </div>

      {loading ? <p style={muted}>Loading…</p> : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {filtered.map((d) => (
            <KnowledgeRow key={d.id} d={d} onEdit={() => setEditing(d)}
              onToggleActive={() => onToggleActive(d)} onDelete={() => onDelete(d.id)}/>
          ))}

          {/* Builder's memory lives in a separate table (block_doc_memos) —
              read-only review queue, shown when the agent filter includes it. */}
          {showBuilder && classF === "all" && docMemos.length > 0 && (
            <div style={{ marginTop: filtered.length ? 14 : 0 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: AGENT_META.builder.color, margin: "4px 2px 8px" }}>
                Builder 的文件備忘（block_doc_memos · 唯讀，Supervisor 審核後才回寫 block docs）
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {docMemos.map((m) => <DocMemoRow key={m.id} m={m}/>)}
              </div>
            </div>
          )}

          {filtered.length === 0 && !(showBuilder && classF === "all" && docMemos.length > 0) && (
            <Empty message="這個篩選條件下沒有 memory。調整「誰寫的 / 類別」或新增一筆。"/>
          )}
        </div>
      )}

      {editing && (
        <DirectiveEditor
          initial={editing === "new" ? null : (editing as unknown as Directive)}
          onClose={() => setEditing(null)}
          onSave={onSave as (d: Partial<Directive>, id?: number) => Promise<void>}/>
      )}
    </div>
  );
}

function KnowledgeRow({ d, onEdit, onToggleActive, onDelete }: {
  d: Knowledge; onEdit: () => void; onToggleActive: () => void; onDelete: () => void;
}) {
  const agent = d.written_by ? AGENT_META[d.written_by] : null;
  const draft = !d.active;
  return (
    <div style={{
      padding: "12px 16px", border: "1px solid #e2e8f0", borderRadius: 6,
      borderLeft: `3px solid ${agent?.color ?? "#cbd5e1"}`,
      background: draft ? "#fafafa" : "#fff", opacity: draft ? 0.75 : 1,
      display: "flex", alignItems: "flex-start", gap: 12,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 4 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "#1e293b" }}>{d.title}</span>
          {agent
            ? <Pill color={agent.color} bg={agent.bg}>{agent.label}</Pill>
            : <Pill color="#94a3b8">未分類</Pill>}
          {d.memo_class && (
            <Pill color={MEMO_CLASS_COLOR[d.memo_class]} bg="#fff">{d.memo_class}</Pill>
          )}
          {d.always_on && <Pill color="#7c3aed" bg="#f3e8ff">always-on</Pill>}
          {draft && <Pill color="#b45309" bg="#fffbeb">draft</Pill>}
          {d.applies_to && d.applies_to !== "both" && <Pill>{d.applies_to}</Pill>}
        </div>
        <div style={{ fontSize: 12.5, color: "#64748b", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{d.body}</div>
        {(d.uses ?? 0) > 0 && (
          <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>recalled {d.uses} time(s)</div>
        )}
      </div>
      <div style={{ display: "flex", gap: 4 }}>
        <button onClick={onToggleActive} style={btnStyle("secondary")} title={d.active ? "disable" : "enable"}>
          {d.active ? "● on" : "○ off"}
        </button>
        <button onClick={onEdit} style={btnStyle("secondary")}>Edit</button>
        <button onClick={onDelete} style={btnStyle("danger")}>×</button>
      </div>
    </div>
  );
}

function DocMemoRow({ m }: { m: DocMemo }) {
  return (
    <div style={{
      padding: "10px 14px", border: "1px solid #e2e8f0", borderRadius: 6,
      borderLeft: `3px solid ${AGENT_META.builder.color}`, background: "#fff",
    }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 3 }}>
        <Pill color={AGENT_META.builder.color} bg={AGENT_META.builder.bg}>Builder</Pill>
        <span style={{ fontFamily: "monospace", fontSize: 12.5, fontWeight: 600, color: "#1e293b" }}>{m.block_id}</span>
        {m.param && <Pill>{m.param}</Pill>}
        <Pill color={m.status === "pending" ? "#b45309" : "#475569"} bg={m.status === "pending" ? "#fffbeb" : "#f1f5f9"}>{m.status}</Pill>
      </div>
      <div style={{ fontSize: 12.5, color: "#64748b", lineHeight: 1.5 }}>{m.memo}</div>
      {m.from_episode && <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 3 }}>from episode {m.from_episode}</div>}
    </div>
  );
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <span style={{ fontSize: 11, color: "#94a3b8", fontWeight: 600, marginRight: 2 }}>{label}</span>
      {children}
    </div>
  );
}

function FilterChip({ active, onClick, color, children }: {
  active: boolean; onClick: () => void; color?: string; children: React.ReactNode;
}) {
  return (
    <button onClick={onClick} style={{
      padding: "3px 9px", borderRadius: 12, fontSize: 11.5, cursor: "pointer",
      border: `1px solid ${active ? (color ?? "#2563eb") : "#e2e8f0"}`,
      background: active ? (color ?? "#2563eb") : "#fff",
      color: active ? "#fff" : (color ?? "#475569"), fontWeight: active ? 600 : 500,
    }}>{children}</button>
  );
}

// ── Lexicon tab ───────────────────────────────────────────────────────

function LexiconView() {
  const [items, setItems] = useState<Lexicon[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Lexicon | "new" | null>(null);

  const load = async () => {
    setLoading(true);
    try { setItems(await api<Lexicon[]>("/api/agent-lexicon")); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const onSave = async (term: string, standard: string, note: string, id?: number) => {
    const body = { term, standard, note: note || null };
    if (id) await api(`/api/agent-lexicon/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    else await api("/api/agent-lexicon", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    setEditing(null); await load();
  };

  const onDelete = async (id: number) => {
    if (!confirm("Delete?")) return;
    await api(`/api/agent-lexicon/${id}`, { method: "DELETE" }); await load();
  };

  return (
    <div>
      <div style={{ display: "flex", marginBottom: 12 }}>
        <span style={{ flex: 1 }}/>
        <button onClick={() => setEditing("new")} style={btnStyle("primary")}>+ New lexicon entry</button>
      </div>
      {loading ? <p style={muted}>Loading…</p>
       : items.length === 0 ? <Empty message='No lexicon yet. Add jargon → standard pairs (e.g. "打點" → "OOC excursion").'/>
       : <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
           <thead><tr style={{ background: "#f8fafc" }}>
             <th style={th}>Your term</th><th style={th}>Standard term</th><th style={th}>Note</th>
             <th style={th}>Uses</th><th style={th}/>
           </tr></thead>
           <tbody>{items.map((l) => (
             <tr key={l.id} style={{ borderBottom: "1px solid #e2e8f0" }}>
               <td style={td}><span style={{ fontFamily: "monospace", fontWeight: 600 }}>{l.term}</span></td>
               <td style={td}>{l.standard}</td>
               <td style={{ ...td, color: "#94a3b8" }}>{l.note ?? "—"}</td>
               <td style={td}>{l.uses}</td>
               <td style={{ ...td, textAlign: "right" }}>
                 <button onClick={() => setEditing(l)} style={btnStyle("secondary")}>Edit</button>
                 <button onClick={() => onDelete(l.id)} style={btnStyle("danger")}>×</button>
               </td>
             </tr>))}
           </tbody>
         </table>}
      {editing && (
        <LexiconEditor initial={editing === "new" ? null : editing}
          onClose={() => setEditing(null)} onSave={onSave}/>
      )}
    </div>
  );
}

function LexiconEditor({ initial, onClose, onSave }: {
  initial: Lexicon | null; onClose: () => void;
  onSave: (term: string, standard: string, note: string, id?: number) => Promise<void>;
}) {
  const [term, setTerm] = useState(initial?.term ?? "");
  const [standard, setStandard] = useState(initial?.standard ?? "");
  const [note, setNote] = useState(initial?.note ?? "");
  return (
    <Modal onClose={onClose} title={initial ? "Edit lexicon" : "New lexicon entry"}>
      <Field label="Your term (jargon)"><input value={term} onChange={(e) => setTerm(e.target.value)} style={inputStyle} placeholder="e.g. 打點"/></Field>
      <Field label="Standard term (canonical)"><input value={standard} onChange={(e) => setStandard(e.target.value)} style={inputStyle} placeholder="e.g. OOC excursion"/></Field>
      <Field label="Note (optional)"><input value={note ?? ""} onChange={(e) => setNote(e.target.value)} style={inputStyle}/></Field>
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button disabled={!term.trim() || !standard.trim()} onClick={() => void onSave(term, standard, note, initial?.id)} style={btnStyle(!term.trim() || !standard.trim() ? "secondary-disabled" : "primary")}>Save</button>
        <button onClick={onClose} style={btnStyle("secondary")}>Cancel</button>
      </div>
    </Modal>
  );
}

// ── Examples tab ──────────────────────────────────────────────────────

function ExamplesView() {
  const [items, setItems] = useState<Example[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Example | "new" | null>(null);

  const load = async () => {
    setLoading(true);
    try { setItems(await api<Example[]>("/api/agent-examples")); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const onSave = async (d: Partial<Example>, id?: number) => {
    if (id) await api(`/api/agent-examples/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    else await api("/api/agent-examples", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    setEditing(null); await load();
  };
  const onDelete = async (id: number) => {
    if (!confirm("Delete?")) return;
    await api(`/api/agent-examples/${id}`, { method: "DELETE" }); await load();
  };

  return (
    <div>
      <div style={{ display: "flex", marginBottom: 12 }}>
        <span style={{ flex: 1 }}/>
        <button onClick={() => setEditing("new")} style={btnStyle("primary")}>+ New few-shot example</button>
      </div>
      {loading ? <p style={muted}>Loading…</p>
       : items.length === 0 ? <Empty message="No examples yet. Add input → desired-output pairs to teach response style."/>
       : <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
           {items.map((e) => (
             <div key={e.id} style={{ padding: "12px 16px", border: "1px solid #e2e8f0", borderRadius: 6, background: "#fff" }}>
               <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                 <span style={{ fontSize: 14, fontWeight: 600 }}>{e.title}</span>
                 <Pill>{e.scope_value ? `${e.scope_type}:${e.scope_value}` : e.scope_type}</Pill>
                 <span style={{ flex: 1 }}/>
                 <button onClick={() => setEditing(e)} style={btnStyle("secondary")}>Edit</button>
                 <button onClick={() => onDelete(e.id)} style={btnStyle("danger")}>×</button>
               </div>
               <div style={{ fontSize: 12, color: "#475569", whiteSpace: "pre-wrap", marginBottom: 6 }}><b>USER:</b> {e.input_text}</div>
               <div style={{ fontSize: 12, color: "#0f766e", whiteSpace: "pre-wrap" }}><b>IDEAL:</b> {e.output_text}</div>
             </div>
           ))}
         </div>}
      {editing && (
        <ExampleEditor initial={editing === "new" ? null : editing}
          onClose={() => setEditing(null)} onSave={onSave}/>
      )}
    </div>
  );
}

function ExampleEditor({ initial, onClose, onSave }: {
  initial: Example | null; onClose: () => void;
  onSave: (d: Partial<Example>, id?: number) => Promise<void>;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [scopeType, setScopeType] = useState<ScopeType>(initial?.scope_type ?? "global");
  const [scopeValue, setScopeValue] = useState(initial?.scope_value ?? "");
  const [inputText, setInputText] = useState(initial?.input_text ?? "");
  const [outputText, setOutputText] = useState(initial?.output_text ?? "");
  return (
    <Modal onClose={onClose} title={initial ? "Edit example" : "New example"}>
      <Field label="Title"><input value={title} onChange={(e) => setTitle(e.target.value)} style={inputStyle}/></Field>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 10 }}>
        <Field label="Scope">
          <select value={scopeType} onChange={(e) => setScopeType(e.target.value as ScopeType)} style={inputStyle}>
            <option value="global">global</option><option value="skill">skill</option>
            <option value="tool">tool</option><option value="recipe">recipe</option>
          </select>
        </Field>
        <Field label={scopeType === "global" ? "(no value)" : "Scope value"}>
          <input value={scopeValue ?? ""} onChange={(e) => setScopeValue(e.target.value)} disabled={scopeType === "global"} style={inputStyle}/>
        </Field>
      </div>
      <Field label="USER (input that triggers this style)"><textarea value={inputText} onChange={(e) => setInputText(e.target.value)} rows={4} style={{ ...inputStyle, fontFamily: "inherit", resize: "vertical" }}/></Field>
      <Field label="IDEAL RESPONSE (the agent should answer like this)"><textarea value={outputText} onChange={(e) => setOutputText(e.target.value)} rows={6} style={{ ...inputStyle, fontFamily: "inherit", resize: "vertical" }}/></Field>
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button disabled={!title.trim() || !inputText.trim() || !outputText.trim()}
          onClick={() => void onSave({
            title, scope_type: scopeType,
            scope_value: scopeType === "global" ? null : (scopeValue || null),
            input_text: inputText, output_text: outputText,
          }, initial?.id)}
          style={btnStyle(!title.trim() || !inputText.trim() || !outputText.trim() ? "secondary-disabled" : "primary")}>Save</button>
        <button onClick={onClose} style={btnStyle("secondary")}>Cancel</button>
      </div>
    </Modal>
  );
}

// ── Shared bits ───────────────────────────────────────────────────────

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div onClick={(e) => { if (e.target === e.currentTarget) onClose(); }} style={{
      position: "fixed", inset: 0, zIndex: 1000, padding: 24,
      background: "rgba(15,23,42,0.45)", display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        width: "min(640px, 100%)", maxHeight: "90vh", overflowY: "auto",
        background: "#fff", borderRadius: 8, padding: "20px 24px",
        boxShadow: "0 20px 50px rgba(0,0,0,0.25)",
      }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 14 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>{title}</h2>
          <span style={{ flex: 1 }}/>
          <button onClick={onClose} style={{ all: "unset", cursor: "pointer", padding: 4, fontSize: 18, color: "#94a3b8" }}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <label style={{ display: "block", fontSize: 11, color: "#64748b", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 }}>{label}</label>
      {children}
    </div>
  );
}

function Pill({ children, color, bg }: { children: React.ReactNode; color?: string; bg?: string }) {
  return <span style={{
    display: "inline-flex", padding: "1px 7px", borderRadius: 3,
    fontSize: 10.5, fontWeight: 600, letterSpacing: "0.04em",
    color: color ?? "#475569", background: bg ?? "#f1f5f9",
    border: "1px solid #e2e8f0", textTransform: "uppercase", whiteSpace: "nowrap",
  }}>{children}</span>;
}

function Empty({ message }: { message: string }) {
  return <div style={{ padding: "60px 28px", textAlign: "center", color: "#94a3b8", fontSize: 13 }}>{message}</div>;
}

const muted = { color: "#94a3b8", fontSize: 13, padding: 24, textAlign: "center" as const };
const inputStyle: React.CSSProperties = {
  width: "100%", padding: "6px 10px", fontSize: 13,
  border: "1px solid #cbd5e1", borderRadius: 4, outline: "none", background: "#fff",
};
const th: React.CSSProperties = { padding: "8px 12px", textAlign: "left", fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 600 };
const td: React.CSSProperties = { padding: "10px 12px" };

function btnStyle(kind: "primary" | "secondary" | "secondary-disabled" | "danger"): React.CSSProperties {
  const base: React.CSSProperties = { padding: "5px 11px", borderRadius: 4, fontSize: 12, fontWeight: 500, cursor: "pointer", border: "1px solid transparent", marginLeft: 4 };
  if (kind === "primary") return { ...base, background: "#2563eb", color: "#fff", borderColor: "#2563eb" };
  if (kind === "danger") return { ...base, background: "#fef2f2", color: "#dc2626", borderColor: "#fecaca" };
  if (kind === "secondary-disabled") return { ...base, background: "#f1f5f9", color: "#94a3b8", borderColor: "#e2e8f0", cursor: "not-allowed" };
  return { ...base, background: "#fff", color: "#475569", borderColor: "#cbd5e1" };
}
