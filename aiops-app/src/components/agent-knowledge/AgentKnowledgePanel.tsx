"use client";

/**
 * 知識工房 /agent-knowledge — redesign per docs-design/supervisor-design.dc.html §1c
 * (2026-07-06).
 *
 * Information architecture:
 *  - 手冊（top, white table）= truths in effect. Pill switcher Knowledge /
 *    Lexicon / Examples, search, + 新增條目. Row click opens the existing
 *    editor modal (PE editing preserved).
 *  - 收件匣（bottom, beige panel）= pending review queue. W2 doc memos
 *    (block_doc_memos) rendered as three-段式 cards (提案 / 為什麼 / 依據).
 *
 * NOTE: the Directives tab was REMOVED from this page — directives moved to
 * the Supervisor workbench governance area (admin-only surface). The old
 * DirectivesView / ItemRow components were deleted (nothing else imported
 * them); /api/agent-directives routes are untouched for the new surface.
 *
 * NOTE: doc-memo approve — java-backend only exposes
 * GET /api/v1/agent-knowledge/doc-memos (AgentKnowledgeController). There is
 * no per-memo approve endpoint yet (memos are only promoted indirectly via
 * Supervisor DOC_REVISE proposals). Card actions render disabled with a
 * "W2 波後端接入" tooltip until that endpoint ships.
 *
 * W2 收件匣 upgrade (2026-07):
 *  - Supervisor 提案 cards — PE-signed proposal types (MERGE/CORRECT/PRUNE/
 *    PROMOTE/DOC_REVISE, status proposed) fetched from /api/supervisor/
 *    proposals, rendered via the shared NarrativeCard (compact) with real
 *    核准 / 駁回（必填理由）actions on the existing approve/reject proxies.
 *  - ON_DUTY 草稿 cards — knowledge rows with status === "draft".
 *    核准入庫 → POST /api/agent-knowledge/{id}/approve;
 *    退回刪除 → DELETE with confirm.
 *  - 手冊 table gains status chip / review_at / subject columns (all W2
 *    columns may be missing on old rows → derived / "—" fallbacks).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useSession } from "next-auth/react";
import { Proposal, proposalTitle, signerOf } from "@/components/supervisor/model";
import { NarrativeCard } from "@/components/supervisor/NarrativeCard";

// ── Types (wire shapes unchanged — snake_case per Java Jackson config) ──

type ScopeType = "global" | "skill" | "tool" | "recipe";
type Priority = "high" | "med" | "low";
type MemoClass = "domain" | "preference" | "presentation" | "correction" | "episodic" | "procedure";

interface Knowledge {
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
  uses: number;
  last_used_at?: string | null;
  memo_class?: MemoClass | null;
  written_by?: string | null; // planner|builder|repair|supervisor|human|null
  applies_to?: "plan" | "execute" | "both" | null;
  always_on?: boolean;
  // W2 governance columns — may be missing on old rows (Java parallel work):
  status?: KnowledgeStatus | string | null; // draft|active|stale|archived
  subject_kind?: string | null;
  subject_id?: string | null;
  review_at?: string | null;
}

type KnowledgeStatus = "draft" | "active" | "stale" | "archived";

/** W2 status with pre-W2 fallback: rows without the column derive from
 *  the legacy active flag so the chip column stays informative. */
function statusOf(k: Knowledge): KnowledgeStatus {
  const s = String(k.status ?? "").toLowerCase();
  if (s === "draft" || s === "active" || s === "stale" || s === "archived") return s;
  return k.active ? "active" : "archived";
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

type Pill = "knowledge" | "lexicon" | "examples";

// ── Design tokens (docs-design §1c) ─────────────────────────────────────

const C = {
  ink: "#211f1c",
  paper: "#fbfbf9",
  panelBorder: "#dedacf",
  line: "#e7e3d9",
  lineSoft: "#f2efe7",
  headBg: "#f7f5ef",
  cardHeadLine: "#efece3",
  cardFoot: "#fcfbf7",
  mutedStrong: "#54504a",
  bodyInk: "#3d3a34",
  muted: "#8a857c",
  faint: "#a49e91",
  ghost: "#b6b0a4",
  purple: "#6d28d9",
  purpleBg: "#f3effc",
  purpleBorder: "#ded2f3",
  purpleChipBorder: "#c4b5fd",
  purpleSoftBg: "#ede9fe",
  beige: "#f6f2e8",
  beigeBorder: "#e8dfc8",
  amber: "#9a6700",
  amberBg: "#faf3e2",
  amberBorder: "#ecd9a8",
  green: "#1a7f4e",
  greenBg: "#eaf5ee",
  greenBorder: "#bfe0cd",
  red: "#b42318",
  redBg: "#fdf0ee",
  redBorder: "#f0c1b8",
  inputBorder: "#ddd8cb",
  pillTrack: "#efece3",
  evidenceInk: "#475569",
  evidenceBorder: "#d7dee7",
} as const;

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

// grid template for the Knowledge manual table (per design; W2 adds
// 狀態 + 複審 columns and folds 來源+subject into one column for width)
const KB_GRID = "56px 84px 1fr 76px 64px 70px 70px 150px";
const LEX_GRID = "64px 1fr 1fr 1fr 90px";
const EX_GRID = "64px 1fr 110px 90px";

// W2 status chip palette — draft amber / active green / stale grey / archived dim
const STATUS_CHIP: Record<KnowledgeStatus, { fg: string; bg: string; bd: string; dim?: boolean }> = {
  draft:    { fg: C.amber, bg: C.amberBg, bd: C.amberBorder },
  active:   { fg: C.green, bg: C.greenBg, bd: C.greenBorder },
  stale:    { fg: C.mutedStrong, bg: C.headBg, bd: C.line },
  archived: { fg: C.ghost, bg: "transparent", bd: C.lineSoft, dim: true },
};

// PE-signed Supervisor proposal types surfaced in the workshop inbox
// (mirrors signerOf() in supervisor/model.ts — filter client-side)
function isPeProposal(p: Proposal): boolean {
  return p.status === "proposed" && signerOf(p) === "PE";
}

// written_by values that count as「Supervisor 蒸餾」
const DISTILLED_WRITERS = new Set(["planner", "builder", "repair", "supervisor"]);
// teach-drafts are created via the Console 教它 prefill — title carries the marker
const TEACH_TITLE_MARKERS = ["[教它]", "[Teach it]", "[教える]"];

type SrcKind = "human" | "distilled" | "teach";
function srcKindOf(k: Knowledge): SrcKind {
  if (TEACH_TITLE_MARKERS.some((m) => k.title?.startsWith(m))) return "teach";
  if (k.written_by && DISTILLED_WRITERS.has(k.written_by)) return "distilled";
  return "human"; // null / "human" / anything unknown → 人工
}

function fmtShortDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${mm}-${dd}`;
}

function firstLine(text: string): string {
  return text?.split("\n").map((l) => l.trim()).find(Boolean) ?? "";
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  const j = await res.json();
  if (!res.ok || j?.ok === false) {
    throw new Error(j?.error?.message ?? `HTTP ${res.status}`);
  }
  return j.data as T;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

// ── Main component ──────────────────────────────────────────────────────

export function AgentKnowledgePanel() {
  const t = useTranslations("kb");
  const { data: session } = useSession();

  // Agent Console 教它入口 (2026-07-04): ?prefill_block=…&prefill_phase=…&
  // prefill_instruction=… lands on Knowledge with a pre-filled draft editor.
  const prefill = useMemo(() => {
    if (typeof window === "undefined") return null;
    const q = new URLSearchParams(window.location.search);
    const block = q.get("prefill_block");
    const phase = q.get("prefill_phase");
    const instruction = q.get("prefill_instruction");
    if (!block && !phase && !instruction) return null;
    return { block, phase, instruction };
  }, []);
  // Agent Console 記憶 chip (2026-07-05): ?id=N opens that entry's editor.
  const openId = useMemo(() => {
    if (typeof window === "undefined") return null;
    const raw = new URLSearchParams(window.location.search).get("id");
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) ? n : null;
  }, []);

  const [pill, setPill] = useState<Pill>("knowledge");
  const [search, setSearch] = useState("");

  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [lexicon, setLexicon] = useState<Lexicon[]>([]);
  const [examples, setExamples] = useState<Example[]>([]);
  const [docMemos, setDocMemos] = useState<DocMemo[]>([]);
  const [supProposals, setSupProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [inboxBusy, setInboxBusy] = useState(false);
  const [inboxErr, setInboxErr] = useState<string | null>(null);

  const [editingK, setEditingK] = useState<Knowledge | "new" | null>(null);
  const [editingL, setEditingL] = useState<Lexicon | "new" | null>(null);
  const [editingE, setEditingE] = useState<Example | "new" | null>(null);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [ks, ls, es, dm, sp, dr] = await Promise.all([
        api<Knowledge[]>("/api/agent-knowledge"),
        api<Lexicon[]>("/api/agent-lexicon").catch(() => [] as Lexicon[]),
        api<Example[]>("/api/agent-examples").catch(() => [] as Example[]),
        api<DocMemo[]>("/api/agent-knowledge/doc-memos").catch(() => [] as DocMemo[]),
        // Supervisor proposals — endpoint is admin/PE surface; fail-open so
        // the manual tables never break when it 403s / is unreachable.
        api<Proposal[]>("/api/supervisor/proposals").catch(() => [] as Proposal[]),
        // W2 — cross-user drafts（PE/IT_ADMIN 收件匣）；ON_DUTY 403 → fail-open。
        api<Knowledge[]>("/api/agent-knowledge/drafts").catch(() => [] as Knowledge[]),
      ]);
      setKnowledge(ks); setLexicon(ls); setExamples(es); setDocMemos(dm);
      setSupProposals(Array.isArray(sp) ? sp.filter(isPeProposal) : []);
      setCrossDrafts(Array.isArray(dr) ? dr : []);
    } finally { setLoading(false); }
  };
  useEffect(() => { void loadAll(); }, []);

  // ON_DUTY 草稿 — W2 起走跨 user 端點 /api/agent-knowledge/drafts
  // （PE/IT_ADMIN 才 200；ON_DUTY 403 → crossDrafts 為空）。與 caller-scoped
  // 清單裡自己的 draft 去重合併。
  const [crossDrafts, setCrossDrafts] = useState<Knowledge[]>([]);
  const drafts = useMemo(() => {
    const own = knowledge.filter((k) => String(k.status ?? "").toLowerCase() === "draft");
    const seen = new Set(crossDrafts.map((k) => k.id));
    return [...crossDrafts, ...own.filter((k) => !seen.has(k.id))];
  }, [knowledge, crossDrafts]);

  // ── 收件匣 actions (Supervisor proposals + ON_DUTY drafts) ───────────
  const inboxAct = async (fn: () => Promise<unknown>) => {
    setInboxBusy(true);
    setInboxErr(null);
    try {
      await fn();
      await loadAll();
    } catch (e) {
      setInboxErr(t("inbox.actionError", { msg: String((e as Error).message || e) }));
    } finally { setInboxBusy(false); }
  };
  const approveProposal = (id: number) =>
    inboxAct(() => api(`/api/supervisor/proposals/${id}/approve`, { method: "POST" }));
  const rejectProposal = (id: number, reason: string) =>
    inboxAct(() => api(`/api/supervisor/proposals/${id}/reject`, {
      method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ reason }),
    }));
  const approveDraft = (id: number) =>
    inboxAct(() => api(`/api/agent-knowledge/${id}/approve`, { method: "POST" }));
  const returnDraft = (id: number) => {
    if (!confirm(t("inbox.returnConfirm"))) return;
    void inboxAct(() => api(`/api/agent-knowledge/${id}`, { method: "DELETE" }));
  };

  // ?id=N — auto-open that entry's editor once the list is in.
  const openedRef = useRef(false);
  useEffect(() => {
    if (openId == null || openedRef.current || knowledge.length === 0) return;
    const hit = knowledge.find((k) => k.id === openId);
    if (hit) { openedRef.current = true; setEditingK(hit); }
  }, [openId, knowledge]);

  // 教它 prefill — open the editor once with a draft carrying build-step
  // context. No id → the editor saves it as a CREATE.
  useEffect(() => {
    if (!prefill) return;
    const ctxLines = [
      prefill.block ? t("teach.block", { value: prefill.block }) : null,
      prefill.phase ? t("teach.phase", { value: prefill.phase }) : null,
      prefill.instruction ? t("teach.instruction", { value: prefill.instruction }) : null,
    ].filter(Boolean).join("\n");
    setEditingK({
      title: t("teach.titlePrefix", { name: prefill.block ?? prefill.phase ?? "build" }),
      body: `${ctxLines}\n\n${t("teach.bodyHint")}\n**Why:** \n**How to apply:** `,
      scope_type: "global", scope_value: null, priority: "med",
    } as unknown as Knowledge);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── CRUD (existing /api proxies reused) ──────────────────────────────
  const saveKnowledge = async (d: Partial<Knowledge>, id?: number) => {
    if (id) await api(`/api/agent-knowledge/${id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(d) });
    else await api("/api/agent-knowledge", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(d) });
    setEditingK(null); await loadAll();
  };
  const deleteKnowledge = async (id: number) => {
    if (!confirm(t("editor.deleteConfirm"))) return;
    await api(`/api/agent-knowledge/${id}`, { method: "DELETE" });
    setEditingK(null); await loadAll();
  };
  const toggleKnowledge = async (d: Knowledge) => {
    await api(`/api/agent-knowledge/${d.id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ active: !d.active }) });
    setEditingK(null); await loadAll();
  };
  const saveLexicon = async (term: string, standard: string, note: string, id?: number) => {
    const body = { term, standard, note: note || null };
    if (id) await api(`/api/agent-lexicon/${id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body) });
    else await api("/api/agent-lexicon", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
    setEditingL(null); await loadAll();
  };
  const deleteLexicon = async (id: number) => {
    if (!confirm(t("editor.deleteConfirm"))) return;
    await api(`/api/agent-lexicon/${id}`, { method: "DELETE" });
    setEditingL(null); await loadAll();
  };
  const saveExample = async (d: Partial<Example>, id?: number) => {
    if (id) await api(`/api/agent-examples/${id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(d) });
    else await api("/api/agent-examples", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(d) });
    setEditingE(null); await loadAll();
  };
  const deleteExample = async (id: number) => {
    if (!confirm(t("editor.deleteConfirm"))) return;
    await api(`/api/agent-examples/${id}`, { method: "DELETE" });
    setEditingE(null); await loadAll();
  };

  // ── Role chip (design top bar: PE purple chip) ───────────────────────
  const roles = (session as unknown as { roles?: string[] } | null)?.roles ?? [];
  const username = session?.user?.name ?? session?.user?.email ?? "";
  const topRole =
    roles.includes("IT_ADMIN") ? "IT_ADMIN" :
    roles.includes("PE") ? "PE" :
    roles.includes("ON_DUTY") ? "ON_DUTY" : null;

  // ── search filtering per pill ────────────────────────────────────────
  const q = search.trim().toLowerCase();
  const filteredK = useMemo(() => !q ? knowledge : knowledge.filter((k) =>
    k.title?.toLowerCase().includes(q) || k.body?.toLowerCase().includes(q)), [knowledge, q]);
  const filteredL = useMemo(() => !q ? lexicon : lexicon.filter((l) =>
    l.term?.toLowerCase().includes(q) || l.standard?.toLowerCase().includes(q) || (l.note ?? "").toLowerCase().includes(q)), [lexicon, q]);
  const filteredE = useMemo(() => !q ? examples : examples.filter((e) =>
    e.title?.toLowerCase().includes(q) || e.input_text?.toLowerCase().includes(q) || e.output_text?.toLowerCase().includes(q)), [examples, q]);

  const onAdd = () => {
    if (pill === "knowledge") setEditingK("new");
    else if (pill === "lexicon") setEditingL("new");
    else setEditingE("new");
  };

  return (
    <div style={{ padding: 24, maxWidth: 1380, margin: "0 auto", fontFamily: "system-ui, sans-serif", color: C.ink }}>
      <div style={{
        background: C.paper, border: `1px solid ${C.panelBorder}`, borderRadius: 12,
        overflow: "hidden", boxShadow: "0 2px 10px rgba(33,31,28,.07)",
      }}>
        {/* top bar — brand + path + role chip (design §1c header) */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 20px", borderBottom: `1px solid ${C.line}`, background: "#fff" }}>
          <span style={{ font: `700 13px ${MONO}`, letterSpacing: ".06em" }}>AIOPS</span>
          <span style={{ fontSize: 12.5, color: C.muted }}>{t("header.path")}</span>
          <span style={{ flex: 1 }}/>
          {topRole && (
            <span style={{
              font: `600 11px ${MONO}`, color: C.purple, background: C.purpleBg,
              border: `1px solid ${C.purpleBorder}`, borderRadius: 6, padding: "3px 10px",
            }}>
              {topRole}{username ? ` · ${username}` : ""}
            </span>
          )}
        </div>

        <div style={{ padding: "18px 24px 24px" }}>
          {/* ── 手冊區 header ── */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>{t("manual.title")}</span>
            <div style={{ display: "flex", gap: 2, background: C.pillTrack, borderRadius: 7, padding: 2, marginLeft: 6 }}>
              <PillButton active={pill === "knowledge"} onClick={() => setPill("knowledge")}>
                {t("manual.tabKnowledge", { count: knowledge.length })}
              </PillButton>
              <PillButton active={pill === "lexicon"} onClick={() => setPill("lexicon")}>
                {t("manual.tabLexicon", { count: lexicon.length })}
              </PillButton>
              <PillButton active={pill === "examples"} onClick={() => setPill("examples")}>
                {t("manual.tabExamples", { count: examples.length })}
              </PillButton>
            </div>
            <span style={{ flex: 1 }}/>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("manual.searchPlaceholder")}
              style={{
                border: `1px solid ${C.inputBorder}`, borderRadius: 7, padding: "6px 12px",
                fontSize: 11.5, width: 220, background: "#fff", fontFamily: "inherit", outline: "none",
              }}/>
            <button onClick={onAdd} style={{
              background: C.ink, color: C.paper, border: "none", borderRadius: 7,
              padding: "6px 14px", fontSize: 11.5, fontWeight: 600, cursor: "pointer",
            }}>{t("manual.add")}</button>
          </div>

          {/* ── 手冊 white table ── */}
          <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 10, overflow: "hidden", marginBottom: 24 }}>
            {loading ? (
              <div style={{ padding: "28px 16px", textAlign: "center", fontSize: 12, color: C.faint }}>{t("loading")}</div>
            ) : pill === "knowledge" ? (
              <KnowledgeTable t={t} items={filteredK} onRowClick={setEditingK}/>
            ) : pill === "lexicon" ? (
              <LexiconTable t={t} items={filteredL} onRowClick={setEditingL}/>
            ) : (
              <ExamplesTable t={t} items={filteredE} onRowClick={setEditingE}/>
            )}
            <div style={{ padding: "8px 16px", fontSize: 10.5, color: C.faint, borderTop: `1px solid ${C.lineSoft}` }}>
              {t("manual.directivesMoved")}
            </div>
          </div>

          {/* ── 收件匣（beige review queue）── */}
          <div style={{ background: C.beige, border: `1px solid ${C.beigeBorder}`, borderRadius: 12, padding: "16px 18px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
              <span style={{ fontSize: 13, fontWeight: 700 }}>{t("inbox.title")}</span>
              <span style={{
                font: `700 11px ${MONO}`, color: C.amber, background: C.amberBg,
                border: `1px solid ${C.amberBorder}`, borderRadius: 999, padding: "1px 9px",
              }}>{supProposals.length + drafts.length + docMemos.length}</span>
              <span style={{ fontSize: 11, color: C.muted }}>
                {t("inbox.breakdown3", { sup: supProposals.length, draft: drafts.length, memo: docMemos.length })}
              </span>
              <span style={{ flex: 1 }}/>
            </div>

            {inboxErr && (
              <div style={{
                marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 12,
                color: C.red, background: C.redBg, border: `1px solid ${C.redBorder}`,
              }}>{inboxErr}</div>
            )}

            {supProposals.length + drafts.length + docMemos.length === 0 ? (
              <div style={{ padding: "22px 0", textAlign: "center", fontSize: 12, color: C.faint }}>
                {loading ? t("loading") : t("inbox.empty")}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                {supProposals.length > 0 && (
                  <InboxSection label={t("inbox.secSup")}>
                    {supProposals.map((p) => (
                      <SupProposalCard key={p.id} t={t} p={p} busy={inboxBusy}
                        onApprove={approveProposal} onReject={rejectProposal}/>
                    ))}
                  </InboxSection>
                )}
                {/* drafts by other users may be invisible (caller-scoped list,
                    Java follow-up) — only render the section when non-empty */}
                {drafts.length > 0 && (
                  <InboxSection label={t("inbox.secDrafts")}>
                    {drafts.map((k) => (
                      <DraftCard key={k.id} t={t} k={k} busy={inboxBusy}
                        onApprove={approveDraft} onReturn={returnDraft}/>
                    ))}
                  </InboxSection>
                )}
                {docMemos.length > 0 && (
                  <InboxSection label={t("inbox.secMemos")}>
                    {docMemos.map((m) => <DocMemoCard key={m.id} t={t} m={m}/>)}
                  </InboxSection>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── editors (existing modals, PE editing preserved) ── */}
      {editingK && (
        <KnowledgeEditor
          initial={editingK === "new" ? null : editingK}
          onClose={() => setEditingK(null)}
          onSave={saveKnowledge}
          onDelete={deleteKnowledge}
          onToggleActive={toggleKnowledge}/>
      )}
      {editingL && (
        <LexiconEditor
          initial={editingL === "new" ? null : editingL}
          onClose={() => setEditingL(null)}
          onSave={saveLexicon}
          onDelete={deleteLexicon}/>
      )}
      {editingE && (
        <ExampleEditor
          initial={editingE === "new" ? null : editingE}
          onClose={() => setEditingE(null)}
          onSave={saveExample}
          onDelete={deleteExample}/>
      )}
    </div>
  );
}

type Translator = ReturnType<typeof useTranslations<"kb">>;

// ── 手冊 tables ─────────────────────────────────────────────────────────

function PillButton({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button onClick={onClick} style={{
      border: "none", cursor: "pointer", borderRadius: 5, padding: "4px 12px",
      fontSize: 11.5, fontFamily: "inherit",
      background: active ? "#fff" : "transparent",
      color: active ? C.ink : C.muted,
      fontWeight: active ? 700 : 400,
      boxShadow: active ? "0 1px 2px rgba(33,31,28,.1)" : "none",
    }}>{children}</button>
  );
}

function TableHead({ grid, cols }: { grid: string; cols: React.ReactNode[] }) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: grid, padding: "8px 16px",
      background: C.headBg, borderBottom: `1px solid ${C.line}`,
      font: `600 10.5px ${MONO}`, color: C.faint, letterSpacing: ".06em",
    }}>
      {cols.map((c, i) => <span key={i}>{c}</span>)}
    </div>
  );
}

function EmptyRow({ text }: { text: string }) {
  return <div style={{ padding: "36px 16px", textAlign: "center", fontSize: 12, color: C.faint }}>{text}</div>;
}

function KnowledgeTable({ t, items, onRowClick }: {
  t: Translator; items: Knowledge[]; onRowClick: (k: Knowledge) => void;
}) {
  return (
    <div>
      <TableHead grid={KB_GRID} cols={[
        t("manual.colId"), t("manual.colClass"), t("manual.colText"),
        t("manual.colStatus"), t("manual.colUsesShort"), t("manual.colLast"),
        t("manual.colReview"), t("manual.colSrcSub"),
      ]}/>
      {items.length === 0 && <EmptyRow text={t("manual.empty")}/>}
      {items.map((k) => {
        const src = srcKindOf(k);
        const st = statusOf(k);
        const chip = STATUS_CHIP[st];
        // subject (W2) — kind:id in mono, "—" when the columns are missing
        const subject = k.subject_kind || k.subject_id
          ? [k.subject_kind, k.subject_id].filter(Boolean).join(":")
          : null;
        return (
          <div key={k.id}
            onClick={() => onRowClick(k)}
            style={{
              display: "grid", gridTemplateColumns: KB_GRID, padding: "9px 16px",
              borderBottom: `1px solid ${C.lineSoft}`, alignItems: "center",
              background: "#fff", cursor: "pointer",
              opacity: chip.dim || !k.active ? 0.55 : 1,
            }}>
            <span style={{ font: `700 11px ${MONO}`, color: C.purple }}>◆ #{k.id}</span>
            <span>
              {k.memo_class ? (
                <span style={{
                  fontSize: 9.5, fontWeight: 700, padding: "1px 6px", borderRadius: 3,
                  border: `1px solid ${C.purpleChipBorder}`, color: C.purple,
                }}>{k.memo_class}</span>
              ) : <span style={{ fontSize: 11, color: C.ghost }}>—</span>}
            </span>
            <span style={{ fontSize: 12, paddingRight: 16 }} title={firstLine(k.body)}>
              {k.title}
              {src === "distilled" && k.uses === 0 && (
                <span style={{
                  fontSize: 9.5, fontWeight: 700, padding: "1px 6px", borderRadius: 3,
                  background: C.purpleSoftBg, color: C.purple, marginLeft: 6,
                }}>{t("manual.newDistilled")}</span>
              )}
              {!k.active && (
                <span style={{
                  fontSize: 9.5, fontWeight: 700, padding: "1px 6px", borderRadius: 3,
                  background: C.headBg, color: C.faint, marginLeft: 6,
                }}>{t("manual.disabled")}</span>
              )}
            </span>
            {/* status chip values are wire tokens — kept English, not i18n */}
            <span>
              <span style={{
                font: `700 9.5px ${MONO}`, padding: "1px 7px", borderRadius: 999,
                color: chip.fg, background: chip.bg, border: `1px solid ${chip.bd}`,
              }}>{st}</span>
            </span>
            <span style={{ font: `600 12px ${MONO}`, color: (k.uses ?? 0) > 0 ? C.ink : C.ghost }}>
              {k.uses ?? 0}
            </span>
            <span style={{ font: `500 11px ${MONO}`, color: C.muted }}>{fmtShortDate(k.last_used_at)}</span>
            <span style={{ font: `500 11px ${MONO}`, color: C.muted }}>{fmtShortDate(k.review_at)}</span>
            <span style={{ fontSize: 11, color: C.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {t(`src.${src}`)}
              {subject && (
                <span style={{ font: `500 10px ${MONO}`, color: C.faint, marginLeft: 6 }} title={subject}>
                  {subject}
                </span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function LexiconTable({ t, items, onRowClick }: {
  t: Translator; items: Lexicon[]; onRowClick: (l: Lexicon) => void;
}) {
  return (
    <div>
      <TableHead grid={LEX_GRID} cols={[
        t("manual.colId"), t("manual.lexColTerm"), t("manual.lexColStandard"),
        t("manual.lexColNote"), t("manual.colUsesShort"),
      ]}/>
      {items.length === 0 && <EmptyRow text={t("manual.empty")}/>}
      {items.map((l) => (
        <div key={l.id}
          onClick={() => onRowClick(l)}
          style={{
            display: "grid", gridTemplateColumns: LEX_GRID, padding: "9px 16px",
            borderBottom: `1px solid ${C.lineSoft}`, alignItems: "center",
            background: "#fff", cursor: "pointer",
          }}>
          <span style={{ font: `700 11px ${MONO}`, color: C.purple }}>◆ #{l.id}</span>
          <span style={{ font: `600 12px ${MONO}` }}>{l.term}</span>
          <span style={{ fontSize: 12 }}>{l.standard}</span>
          <span style={{ fontSize: 11.5, color: C.muted }}>{l.note ?? "—"}</span>
          <span style={{ font: `600 12px ${MONO}`, color: (l.uses ?? 0) > 0 ? C.ink : C.ghost }}>{l.uses ?? 0}</span>
        </div>
      ))}
    </div>
  );
}

function ExamplesTable({ t, items, onRowClick }: {
  t: Translator; items: Example[]; onRowClick: (e: Example) => void;
}) {
  return (
    <div>
      <TableHead grid={EX_GRID} cols={[
        t("manual.colId"), t("manual.exColTitle"), "scope", t("manual.colUsesShort"),
      ]}/>
      {items.length === 0 && <EmptyRow text={t("manual.empty")}/>}
      {items.map((e) => (
        <div key={e.id}
          onClick={() => onRowClick(e)}
          style={{
            display: "grid", gridTemplateColumns: EX_GRID, padding: "9px 16px",
            borderBottom: `1px solid ${C.lineSoft}`, alignItems: "center",
            background: "#fff", cursor: "pointer",
          }}>
          <span style={{ font: `700 11px ${MONO}`, color: C.purple }}>◆ #{e.id}</span>
          <span style={{ fontSize: 12, paddingRight: 16 }} title={firstLine(e.input_text)}>{e.title}</span>
          <span style={{ font: `500 11px ${MONO}`, color: C.muted }}>
            {e.scope_value ? `${e.scope_type}:${e.scope_value}` : e.scope_type}
          </span>
          <span style={{ font: `600 12px ${MONO}`, color: (e.uses ?? 0) > 0 ? C.ink : C.ghost }}>{e.uses ?? 0}</span>
        </div>
      ))}
    </div>
  );
}

// ── 收件匣 sections + cards ─────────────────────────────────────────────

function InboxSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{
        font: `700 10.5px ${MONO}`, color: C.mutedStrong, letterSpacing: ".05em",
        marginBottom: 8,
      }}>{label}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 12 }}>
        {children}
      </div>
    </div>
  );
}

/** Supervisor 提案 card — PE-signed proposal rendered via the shared
 *  NarrativeCard (compact). 核准 / 駁回（必填理由）hit the existing
 *  supervisor approve/reject proxies; the page reloads on success. */
function SupProposalCard({ t, p, busy, onApprove, onReject }: {
  t: Translator; p: Proposal; busy: boolean;
  onApprove: (id: number) => void;
  onReject: (id: number, reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [reasonErr, setReasonErr] = useState(false);
  const submitReject = () => {
    if (reason.trim() === "") { setReasonErr(true); return; }
    setReasonErr(false);
    onReject(p.id, reason.trim());
  };
  return (
    <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 10, display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "11px 14px 9px", borderBottom: `1px solid ${C.cardHeadLine}` }}>
        <div style={{ display: "flex", gap: 7, alignItems: "center", marginBottom: 5 }}>
          <span style={{
            font: `700 10.5px ${MONO}`, color: C.purple, background: C.purpleBg,
            border: `1px solid ${C.purpleBorder}`, borderRadius: 4, padding: "1px 6px",
          }}>{t("inbox.chipSup")}</span>
          <span style={{ font: `700 10.5px ${MONO}`, color: C.purple }}>{p.action_type}</span>
          <span style={{ font: `600 11px ${MONO}`, color: C.faint }}>#{p.id}</span>
          <span style={{ flex: 1 }}/>
          <span style={{
            font: `600 10.5px ${MONO}`, borderRadius: 999, padding: "1px 8px",
            color: C.amber, background: C.amberBg, border: `1px solid ${C.amberBorder}`,
          }}>{t("inbox.pending")}</span>
        </div>
        <div style={{ fontSize: 12.5, fontWeight: 700, lineHeight: 1.45 }}>{proposalTitle(p)}</div>
      </div>

      <div style={{ padding: "10px 14px", flex: 1 }}>
        <NarrativeCard p={p} compact/>
      </div>

      <div style={{
        display: "flex", gap: 6, padding: "9px 14px", borderTop: `1px solid ${C.cardHeadLine}`,
        background: C.cardFoot, borderRadius: "0 0 10px 10px", flexWrap: "wrap", alignItems: "center",
      }}>
        <button disabled={busy} onClick={() => onApprove(p.id)} style={{
          background: C.ink, color: C.paper, border: "none", borderRadius: 6,
          padding: "6px 14px", fontSize: 11.5, fontWeight: 700,
          cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
        }}>{busy ? t("inbox.working") : t("inbox.approve")}</button>
        <input
          value={reason}
          onChange={(e) => { setReason(e.target.value); if (reasonErr) setReasonErr(false); }}
          placeholder={reasonErr ? t("inbox.rejectReasonRequired") : t("inbox.rejectPlaceholder")}
          style={{
            border: `1px solid ${reasonErr ? C.redBorder : C.inputBorder}`,
            borderRadius: 6, padding: "5px 10px", fontSize: 11, flex: 1, minWidth: 120,
            background: "#fff", color: C.ink, fontFamily: "inherit", outline: "none",
          }}/>
        <button disabled={busy} onClick={submitReject} style={{
          background: "#fff", color: C.red, border: `1px solid ${C.redBorder}`, borderRadius: 6,
          padding: "6px 12px", fontSize: 11.5, fontWeight: 600,
          cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
        }}>{t("inbox.reject")}</button>
      </div>
    </div>
  );
}

/** ON_DUTY 草稿 card — knowledge row with status "draft".
 *  核准入庫 → POST /api/agent-knowledge/{id}/approve (draft → active);
 *  退回刪除 → DELETE with confirm (simplest reject path today). */
function DraftCard({ t, k, busy, onApprove, onReturn }: {
  t: Translator; k: Knowledge; busy: boolean;
  onApprove: (id: number) => void;
  onReturn: (id: number) => void;
}) {
  return (
    <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 10, display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "11px 14px 9px", borderBottom: `1px solid ${C.cardHeadLine}` }}>
        <div style={{ display: "flex", gap: 7, alignItems: "center", marginBottom: 5 }}>
          <span style={{
            font: `700 10.5px ${MONO}`, color: C.amber, background: C.amberBg,
            border: `1px solid ${C.amberBorder}`, borderRadius: 4, padding: "1px 6px",
          }}>{t("inbox.chipDraft")}</span>
          <span style={{ font: `600 11px ${MONO}`, color: C.faint }}>◆ #{k.id}</span>
          <span style={{ flex: 1 }}/>
          <span style={{ font: `500 10px ${MONO}`, color: C.ghost }}>
            {k.scope_value ? `${k.scope_type}:${k.scope_value}` : k.scope_type} · {fmtShortDate(k.created_at)}
          </span>
        </div>
        <div style={{ fontSize: 12.5, fontWeight: 700, lineHeight: 1.45 }}>{k.title}</div>
      </div>

      <div style={{ padding: "10px 14px", fontSize: 11.5, lineHeight: 1.6, color: C.bodyInk, flex: 1, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {k.body}
      </div>

      <div style={{
        display: "flex", gap: 6, padding: "9px 14px", borderTop: `1px solid ${C.cardHeadLine}`,
        background: C.cardFoot, borderRadius: "0 0 10px 10px", alignItems: "center",
      }}>
        <button disabled={busy} onClick={() => onApprove(k.id)} style={{
          background: C.ink, color: C.paper, border: "none", borderRadius: 6,
          padding: "6px 14px", fontSize: 11.5, fontWeight: 700,
          cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
        }}>{busy ? t("inbox.working") : t("inbox.approveStore")}</button>
        <button disabled={busy} onClick={() => onReturn(k.id)} style={{
          background: "#fff", color: C.red, border: `1px solid ${C.redBorder}`, borderRadius: 6,
          padding: "6px 12px", fontSize: 11.5, fontWeight: 600,
          cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
        }}>{t("inbox.returnDelete")}</button>
        <span style={{ flex: 1 }}/>
        <span style={{ fontSize: 10, color: C.faint }}>{t("inbox.signNote")}</span>
      </div>
    </div>
  );
}

// ── 收件匣 doc-memo card（三段式，design §1c W2 card）─────────────────────

function DocMemoCard({ t, m }: { t: Translator; m: DocMemo }) {
  const pending = m.status === "pending";
  // No approve endpoint on java-backend yet (checked AgentKnowledgeController:
  // GET /agent-knowledge/doc-memos only) — actions stay disabled until the W2
  // wave ships the write path.
  const disabledBtn: React.CSSProperties = { opacity: 0.45, cursor: "not-allowed" };
  return (
    <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 10, display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "11px 14px 9px", borderBottom: `1px solid ${C.cardHeadLine}` }}>
        <div style={{ display: "flex", gap: 7, alignItems: "center", marginBottom: 5 }}>
          <span style={{
            font: `700 10.5px ${MONO}`, color: C.amber, background: C.amberBg,
            border: `1px solid ${C.amberBorder}`, borderRadius: 4, padding: "1px 6px",
          }}>{t("inbox.chipW2")}</span>
          <span style={{ font: `600 11px ${MONO}`, color: C.faint }}>#m-{m.id}</span>
          <span style={{ flex: 1 }}/>
          <span style={{
            font: `600 10.5px ${MONO}`, borderRadius: 999, padding: "1px 8px",
            color: pending ? C.amber : C.mutedStrong,
            background: pending ? C.amberBg : C.headBg,
            border: `1px solid ${pending ? C.amberBorder : C.line}`,
          }}>{pending ? t("inbox.pending") : m.status}</span>
        </div>
        <div style={{ fontSize: 12.5, fontWeight: 700, lineHeight: 1.45, fontFamily: MONO }}>
          {m.block_id}{m.param ? ` · ${m.param}` : ""}
        </div>
      </div>

      <div style={{
        padding: "10px 14px", display: "grid", gridTemplateColumns: "48px 1fr",
        rowGap: 8, columnGap: 10, fontSize: 11.5, lineHeight: 1.6, flex: 1,
      }}>
        <div style={{ font: `700 10px ${MONO}`, color: C.muted }}>{t("inbox.proposal")}</div>
        <div>{m.memo}</div>
        <div style={{ font: `700 10px ${MONO}`, color: C.muted }}>{t("inbox.why")}</div>
        <div style={{ color: C.bodyInk }}>—</div>
        <div style={{ font: `700 10px ${MONO}`, color: C.muted }}>{t("inbox.evidence")}</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {m.from_episode ? (
            <span style={{
              font: `600 10px ${MONO}`, color: C.evidenceInk,
              border: `1px solid ${C.evidenceBorder}`, borderRadius: 4, padding: "1px 6px",
            }}>{t("inbox.episode", { id: m.from_episode })}</span>
          ) : <span style={{ color: C.ghost }}>—</span>}
        </div>
      </div>

      <div style={{
        display: "flex", gap: 6, padding: "9px 14px", borderTop: `1px solid ${C.cardHeadLine}`,
        background: C.cardFoot, borderRadius: "0 0 10px 10px",
      }}>
        <button disabled title={t("inbox.disabledTip")} style={{
          background: C.ink, color: C.paper, border: "none", borderRadius: 6,
          padding: "6px 14px", fontSize: 11.5, fontWeight: 700, ...disabledBtn,
        }}>{t("inbox.approve")}</button>
        <button disabled title={t("inbox.disabledTip")} style={{
          background: "#fff", color: C.red, border: `1px solid ${C.redBorder}`, borderRadius: 6,
          padding: "6px 12px", fontSize: 11.5, ...disabledBtn,
        }}>{t("inbox.reject")}</button>
        <span style={{ flex: 1 }}/>
        <span style={{ fontSize: 10, color: C.faint, alignSelf: "center" }}>{t("inbox.signNote")}</span>
      </div>
    </div>
  );
}

// ── Editors (pre-redesign modals, restyled to the §1c palette) ──────────

function KnowledgeEditor({ initial, onClose, onSave, onDelete, onToggleActive }: {
  initial: Knowledge | null;
  onClose: () => void;
  onSave: (d: Partial<Knowledge>, id?: number) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onToggleActive: (d: Knowledge) => Promise<void>;
}) {
  const t = useTranslations("kb");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [body, setBody] = useState(initial?.body ?? "");
  const [scopeType, setScopeType] = useState<ScopeType>(initial?.scope_type ?? "global");
  const [scopeValue, setScopeValue] = useState(initial?.scope_value ?? "");
  const [priority, setPriority] = useState<Priority>(initial?.priority ?? "med");
  const [busy, setBusy] = useState(false);
  // prefill drafts arrive without id — treat as CREATE
  const existingId = initial?.id;
  return (
    <Modal onClose={onClose} title={existingId ? t("editor.editEntry") : t("editor.newEntry")}>
      <Field label={t("editor.fieldTitle")}>
        <input value={title} onChange={(e) => setTitle(e.target.value)} style={inputStyle}/>
      </Field>
      <Field label={t("editor.fieldBody")}>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5} style={{ ...inputStyle, fontFamily: "inherit", resize: "vertical" }}/>
      </Field>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr 1fr", gap: 10 }}>
        <Field label={t("editor.fieldScope")}>
          <select value={scopeType} onChange={(e) => setScopeType(e.target.value as ScopeType)} style={inputStyle}>
            <option value="global">global</option>
            <option value="skill">skill</option>
            <option value="tool">tool</option>
            <option value="recipe">recipe</option>
          </select>
        </Field>
        <Field label={scopeType === "global" ? t("editor.fieldScopeNone") : t("editor.fieldScopeValue")}>
          <input value={scopeValue ?? ""} onChange={(e) => setScopeValue(e.target.value)}
            disabled={scopeType === "global"}
            placeholder={scopeType === "tool" ? "EQP-01" : scopeType === "skill" ? "skill-slug" : ""}
            style={inputStyle}/>
        </Field>
        <Field label={t("editor.fieldPriority")}>
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
              }, existingId);
            } finally { setBusy(false); }
          }}
          style={btnStyle(busy || !title.trim() || !body.trim() ? "disabled" : "primary")}>
          {busy ? t("editor.saving") : t("editor.save")}
        </button>
        <button onClick={onClose} style={btnStyle("secondary")}>{t("editor.cancel")}</button>
        <span style={{ flex: 1 }}/>
        {existingId != null && initial && (
          <>
            <button onClick={() => void onToggleActive(initial)} style={btnStyle("secondary")}>
              {initial.active ? t("editor.disable") : t("editor.enable")}
            </button>
            <button onClick={() => void onDelete(existingId)} style={btnStyle("danger")}>
              {t("editor.delete")}
            </button>
          </>
        )}
      </div>
    </Modal>
  );
}

function LexiconEditor({ initial, onClose, onSave, onDelete }: {
  initial: Lexicon | null; onClose: () => void;
  onSave: (term: string, standard: string, note: string, id?: number) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  const t = useTranslations("kb");
  const [term, setTerm] = useState(initial?.term ?? "");
  const [standard, setStandard] = useState(initial?.standard ?? "");
  const [note, setNote] = useState(initial?.note ?? "");
  return (
    <Modal onClose={onClose} title={initial ? t("editor.lexEdit") : t("editor.lexNew")}>
      <Field label={t("editor.fieldTerm")}><input value={term} onChange={(e) => setTerm(e.target.value)} style={inputStyle}/></Field>
      <Field label={t("editor.fieldStandard")}><input value={standard} onChange={(e) => setStandard(e.target.value)} style={inputStyle}/></Field>
      <Field label={t("editor.fieldNote")}><input value={note ?? ""} onChange={(e) => setNote(e.target.value)} style={inputStyle}/></Field>
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button disabled={!term.trim() || !standard.trim()}
          onClick={() => void onSave(term, standard, note, initial?.id)}
          style={btnStyle(!term.trim() || !standard.trim() ? "disabled" : "primary")}>{t("editor.save")}</button>
        <button onClick={onClose} style={btnStyle("secondary")}>{t("editor.cancel")}</button>
        <span style={{ flex: 1 }}/>
        {initial && (
          <button onClick={() => void onDelete(initial.id)} style={btnStyle("danger")}>{t("editor.delete")}</button>
        )}
      </div>
    </Modal>
  );
}

function ExampleEditor({ initial, onClose, onSave, onDelete }: {
  initial: Example | null; onClose: () => void;
  onSave: (d: Partial<Example>, id?: number) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  const t = useTranslations("kb");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [scopeType, setScopeType] = useState<ScopeType>(initial?.scope_type ?? "global");
  const [scopeValue, setScopeValue] = useState(initial?.scope_value ?? "");
  const [inputText, setInputText] = useState(initial?.input_text ?? "");
  const [outputText, setOutputText] = useState(initial?.output_text ?? "");
  const invalid = !title.trim() || !inputText.trim() || !outputText.trim();
  return (
    <Modal onClose={onClose} title={initial ? t("editor.exEdit") : t("editor.exNew")}>
      <Field label={t("editor.fieldTitle")}><input value={title} onChange={(e) => setTitle(e.target.value)} style={inputStyle}/></Field>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 10 }}>
        <Field label={t("editor.fieldScope")}>
          <select value={scopeType} onChange={(e) => setScopeType(e.target.value as ScopeType)} style={inputStyle}>
            <option value="global">global</option><option value="skill">skill</option>
            <option value="tool">tool</option><option value="recipe">recipe</option>
          </select>
        </Field>
        <Field label={scopeType === "global" ? t("editor.fieldScopeNone") : t("editor.fieldScopeValue")}>
          <input value={scopeValue ?? ""} onChange={(e) => setScopeValue(e.target.value)} disabled={scopeType === "global"} style={inputStyle}/>
        </Field>
      </div>
      <Field label={t("editor.fieldUser")}><textarea value={inputText} onChange={(e) => setInputText(e.target.value)} rows={4} style={{ ...inputStyle, fontFamily: "inherit", resize: "vertical" }}/></Field>
      <Field label={t("editor.fieldIdeal")}><textarea value={outputText} onChange={(e) => setOutputText(e.target.value)} rows={6} style={{ ...inputStyle, fontFamily: "inherit", resize: "vertical" }}/></Field>
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button disabled={invalid}
          onClick={() => void onSave({
            title, scope_type: scopeType,
            scope_value: scopeType === "global" ? null : (scopeValue || null),
            input_text: inputText, output_text: outputText,
          }, initial?.id)}
          style={btnStyle(invalid ? "disabled" : "primary")}>{t("editor.save")}</button>
        <button onClick={onClose} style={btnStyle("secondary")}>{t("editor.cancel")}</button>
        <span style={{ flex: 1 }}/>
        {initial && (
          <button onClick={() => void onDelete(initial.id)} style={btnStyle("danger")}>{t("editor.delete")}</button>
        )}
      </div>
    </Modal>
  );
}

// ── Shared bits ─────────────────────────────────────────────────────────

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div onClick={(e) => { if (e.target === e.currentTarget) onClose(); }} style={{
      position: "fixed", inset: 0, zIndex: 1000, padding: 24,
      background: "rgba(33,31,28,0.45)", display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        width: "min(640px, 100%)", maxHeight: "90vh", overflowY: "auto",
        background: C.paper, border: `1px solid ${C.panelBorder}`,
        borderRadius: 10, padding: "20px 24px",
        boxShadow: "0 20px 50px rgba(33,31,28,0.25)",
      }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 14 }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: C.ink }}>{title}</h2>
          <span style={{ flex: 1 }}/>
          <button onClick={onClose} style={{ all: "unset", cursor: "pointer", padding: 4, fontSize: 18, color: C.faint }}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <label style={{
        display: "block", font: `600 10px ${MONO}`, color: C.muted,
        textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4,
      }}>{label}</label>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "6px 10px", fontSize: 13,
  border: `1px solid ${C.inputBorder}`, borderRadius: 6, outline: "none", background: "#fff",
};

function btnStyle(kind: "primary" | "secondary" | "disabled" | "danger"): React.CSSProperties {
  const base: React.CSSProperties = {
    padding: "6px 14px", borderRadius: 6, fontSize: 11.5, fontWeight: 600,
    cursor: "pointer", border: "1px solid transparent",
  };
  if (kind === "primary") return { ...base, background: C.ink, color: C.paper, fontWeight: 700 };
  if (kind === "danger") return { ...base, background: "#fff", color: C.red, borderColor: C.redBorder };
  if (kind === "disabled") return { ...base, background: C.headBg, color: C.ghost, borderColor: C.line, cursor: "not-allowed" };
  return { ...base, background: "#fff", color: C.mutedStrong, borderColor: C.inputBorder };
}
