/**
 * Supervisor workbench — shared model + design tokens.
 *
 * Data source: GET /api/supervisor/proposals (Java SupervisorCurationService.toDto):
 *   { id, action_type: MERGE|CORRECT|PRUNE|PROMOTE|DOC_REVISE, target_ids[],
 *     proposal{}, rationale, status: proposed|approved|rejected,
 *     proposer_meta, created_at, reviewed_by, reviewed_at, commit_result }
 *
 * Visual tokens are copied 1:1 from docs-design/supervisor-design.dc.html
 * (section 1a) — do not "improve" them ad hoc; change the design doc first.
 */

// ── design tokens (section 1a) ──────────────────────────────────────────
export const TOK = {
  ink: "#211f1c",
  paper: "#fbfbf9",
  card: "#fff",
  cardFoot: "#fcfbf7",
  border: "#e7e3d9",
  borderSub: "#efece3",
  borderRow: "#f2efe7",
  muted: "#8a857c",
  faint: "#a49e91",
  fainter: "#b6b0a4",
  body: "#3d3a34",
  secondary: "#54504a",
  btnBorder: "#ddd8cb",
  mono: "ui-monospace, Menlo, monospace",
  font: "-apple-system, 'Segoe UI', 'Noto Sans TC', sans-serif",
  amber: "#9a6700", amberBg: "#faf3e2", amberBd: "#ecd9a8",
  purple: "#6d28d9", purpleBg: "#f3effc", purpleBd: "#ded2f3",
  cyan: "#0e7490", cyanBg: "#e9f5f8", cyanBd: "#bfe0e9",
  green: "#1a7f4e", greenBg: "#eaf5ee", greenBd: "#bfe0cd",
  red: "#b42318", redBg: "#fdf0ee", redBd: "#f3c6bf", redBtnBd: "#f0c1b8",
  slate: "#475569", slateBg: "#f1f5f9", slateBd: "#d7dee7",
  lifeBg: "#f0f6f8", lifeBd: "#cbe2ea", lifeConn: "#9cc2cf",
  blue: "#1d4ed8",
} as const;

export interface ChipStyle { fg: string; bg: string; bd: string }

/** Type chip palette — knowledge curation = purple, doc curation = amber,
 *  anything else (future config-type proposals) = cyan per design. */
export function typeChip(actionType: string): ChipStyle {
  switch (actionType) {
    case "MERGE":
    case "CORRECT":
    case "PRUNE":
    case "PROMOTE":
      return { fg: TOK.purple, bg: TOK.purpleBg, bd: TOK.purpleBd };
    case "DOC_REVISE":
      return { fg: TOK.amber, bg: TOK.amberBg, bd: TOK.amberBd };
    default:
      return { fg: TOK.cyan, bg: TOK.cyanBg, bd: TOK.cyanBd };
  }
}

export function statusChip(status: string): ChipStyle {
  switch (status) {
    case "proposed": return { fg: TOK.amber, bg: TOK.amberBg, bd: TOK.amberBd };
    case "approved": return { fg: TOK.green, bg: TOK.greenBg, bd: TOK.greenBd };
    case "rejected": return { fg: TOK.red, bg: TOK.redBg, bd: TOK.redBd };
    default:         return { fg: TOK.muted, bg: "#f4f2ec", bd: TOK.btnBorder }; // expired / superseded
  }
}

/** Evidence row styling — ▣ system fact (solid) / △ agent self-report
 *  (dashed) / ◆ memory. Marks live in JSX, never in i18n strings. */
export type EvidenceKind = "sys" | "self" | "mem";
export const EV_STYLE: Record<EvidenceKind, { sig: string; fg: string; bd: string; bg: string; line: "solid" | "dashed" }> = {
  sys:  { sig: "▣", fg: TOK.slate,  bd: TOK.slateBd,  bg: "#fff",    line: "solid" },
  self: { sig: "△", fg: TOK.amber,  bd: TOK.amberBd,  bg: "#fffdf6", line: "dashed" },
  mem:  { sig: "◆", fg: TOK.purple, bd: TOK.purpleBd, bg: "#faf8ff", line: "solid" },
};

export type LifeState = "done" | "current" | "todo";
export const LIFE_STYLE: Record<LifeState, { mark: string; fg: string }> = {
  done:    { mark: "✓", fg: TOK.green },
  current: { mark: "●", fg: TOK.cyan },
  todo:    { mark: "○", fg: TOK.muted },
};

// ── wire types ──────────────────────────────────────────────────────────

/** 案情四段 narrative (W2) — every field may be missing on old rows. */
export interface NarrativeSubject {
  kind?: string | null;   // block | knowledge | preference | cfg | …
  id?: string | null;
  label?: string | null;
}
export interface Narrative {
  happened?: string | null;
  observed?: string | null;
  subject?: NarrativeSubject | null;
  action?: string | null;
}

export interface Proposal {
  id: number;
  action_type: string;
  target_ids: unknown[];
  proposal: Record<string, unknown> | null;
  rationale?: string | null;
  status: string;
  proposer_meta?: Record<string, unknown> | null;
  created_at?: string | null;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
  commit_result?: Record<string, unknown> | null;
  // W2 additions — Java ships in a parallel workstream, all optional:
  narrative?: Narrative | null;
  reject_reason?: string | null;
  landed_at?: string | null;
  landed_by?: string | number | null;
  verify_result?: string | null;
  verify_at?: string | null;
  superseded_by?: number | null;
}

/** Defensive narrative accessor — returns null unless at least one of the
 *  four sections carries real text (old rows / partial writes → fallback
 *  to the legacy 提案/為什麼/依據 layout). */
export function narrativeOf(p: Proposal): Narrative | null {
  const n = p.narrative;
  if (!n || typeof n !== "object") return null;
  const has = (v: unknown) => typeof v === "string" && v.trim() !== "";
  if (has(n.happened) || has(n.observed) || has(n.action)) return n;
  return null;
}

/** GET /api/supervisor/metrics/llm-daily row — defensive, all optional. */
export interface LlmDailyRow {
  day?: string | null;
  model?: string | null;
  calls?: number | null;
  empty_calls?: number | null;
  error_calls?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cache_read?: number | null;
}

// ── role / signer mapping ───────────────────────────────────────────────
// 2026-07-06 政策：document（block 文件 = 系統的一部份）→ IT_ADMIN；
// knowledge（PRUNE/PROMOTE/MERGE/CORRECT 操作 agent_knowledge）→ PE。
const PE_SIGNED = new Set(["PRUNE", "PROMOTE", "MERGE", "CORRECT"]);

export function signerOf(p: Proposal): "PE" | "IT_ADMIN" {
  return PE_SIGNED.has(p.action_type) ? "PE" : "IT_ADMIN";
}

export function canSign(p: Proposal, roles: string[]): boolean {
  return roles.includes(signerOf(p));
}

// ── proposal JSON parsing (defensive — every field may be missing) ──────
const obj = (p: Proposal): Record<string, unknown> => p.proposal ?? {};
const str = (v: unknown): string | null =>
  typeof v === "string" && v.trim() !== "" ? v : null;

export function proposalTitle(p: Proposal): string {
  // display_title = 掃讀用短標題（2026-07-06 UX 回饋：原標題太長抓不到重點）；
  // 沒有時退回語意 title / rationale。
  return str(obj(p).display_title) ?? str(obj(p).title) ?? str(p.rationale) ?? `${p.action_type} #${p.id}`;
}

/** 提案來源：Supervisor 查案（forensics）vs 策展（curation）。 */
export function metaSource(p: Proposal): "forensics" | "curation" {
  const m = p.proposer_meta as unknown;
  const raw = m && typeof m === "object" ? JSON.stringify(m) : String(m ?? "");
  return raw.includes("forensics") ? "forensics" : "curation";
}

/** curation（Agent 提出）提案的來源 agents（主要在前）；forensics 不帶。 */
export function agentsOf(p: Proposal): string[] {
  const m = p.proposer_meta as unknown;
  const meta = m && typeof m === "object" ? m as Record<string, unknown>
    : (() => { try { return JSON.parse(String(m ?? "{}")); } catch { return {}; } })();
  const a = meta.agents;
  return Array.isArray(a) ? a.map(String) : [];
}

/** "為什麼" — proposal.why, else rationale unless it was already the title. */
export function proposalWhy(p: Proposal): string | null {
  const explicit = str(obj(p).why);
  if (explicit) return explicit;
  if (str(obj(p).title)) return str(p.rationale);
  return null; // rationale already consumed as the title
}

/** A "提案" bullet — either an i18n descriptor or a raw literal line. */
export type WhatLine = { key: string; params?: Record<string, string | number> } | { text: string };

function fmtIds(v: unknown): string {
  if (Array.isArray(v) && v.length > 0) return v.map((x) => `#${String(x)}`).join(" · ");
  return "—";
}

export function whatLines(p: Proposal): WhatLine[] {
  const b = obj(p);
  const s = (v: unknown) => str(v) ?? "—";
  switch (p.action_type) {
    case "MERGE": {
      const out: WhatLine[] = [
        { key: "what.mergeKeep", params: { id: b.keep_id == null ? "—" : String(b.keep_id) } },
        { key: "what.mergeRemove", params: { ids: fmtIds(b.remove_ids) } },
      ];
      if (str(b.merged_body)) out.push({ key: "what.mergeBody" });
      return out;
    }
    case "CORRECT": {
      const out: WhatLine[] = [
        { key: "what.correctRewrite", params: { id: b.target_id == null ? "—" : String(b.target_id) } },
      ];
      if (str(b.new_title)) out.push({ key: "what.correctTitle", params: { title: s(b.new_title) } });
      const promote = b.promote === true || String(b.promote) === "true";
      out.push({ key: promote ? "what.correctPromote" : "what.correctDraft" });
      return out;
    }
    case "PRUNE":
      return [{ key: "what.pruneTargets", params: { ids: fmtIds(b.target_ids ?? p.target_ids) } }];
    case "PROMOTE":
      return [
        { key: "what.promoteNew", params: { cls: s(b.memo_class), title: s(b.title) } },
        { key: "what.promoteApplies", params: { applies: s(b.applies_to) } },
      ];
    case "DOC_REVISE": {
      const memoIds = Array.isArray(b.memo_ids) ? b.memo_ids.length : 0;
      const out: WhatLine[] = [
        { key: "what.docBlock", params: { block: s(b.block_id) } },
        { key: "what.docMemos", params: { count: memoIds } },
      ];
      // 草稿內容改由 DocRevisePreview 呈現（可展開文件對照），此處不再放 what 行
      return out;
    }
    default: {
      const json = compactJson(b);
      return json ? [{ text: json }] : [{ text: "—" }];
    }
  }
}

// ── target ids (purple ◆ chips → /agent-knowledge?id=N) ────────────────
export interface TargetChip { id: string; short?: string; numeric: boolean }

export function targetChips(p: Proposal): TargetChip[] {
  const raw = Array.isArray(p.target_ids) ? p.target_ids : [];
  // optional { targets: [{id, short}] } enrichment in the proposal JSON
  const enrich = new Map<string, string>();
  const t = obj(p).targets;
  if (Array.isArray(t)) {
    for (const e of t) {
      if (e && typeof e === "object" && "id" in e) {
        const short = str((e as Record<string, unknown>).short) ?? str((e as Record<string, unknown>).title);
        if (short) enrich.set(String((e as Record<string, unknown>).id), short);
      }
    }
  }
  return raw.map((v) => {
    const id = String(v);
    return { id, short: enrich.get(id), numeric: /^\d+$/.test(id) };
  });
}

// ── evidence rows ───────────────────────────────────────────────────────
export interface EvidenceRow {
  kind: EvidenceKind;
  label: string | null;   // literal label from the proposal JSON
  labelKey?: string;      // i18n fallback label ("evidence.raw")
  detail: string;
}

function evidenceKind(v: unknown): EvidenceKind {
  const k = String(v ?? "").toLowerCase();
  if (k === "self" || k === "agent" || k === "selfreport") return "self";
  if (k === "mem" || k === "memory") return "mem";
  return "sys";
}

export function compactJson(v: unknown, max = 400): string {
  try {
    const s = JSON.stringify(v);
    if (!s || s === "{}" || s === "[]" || s === "null") return "";
    return s.length > max ? `${s.slice(0, max)}…` : s;
  } catch {
    return "";
  }
}

export function evidenceRows(p: Proposal): EvidenceRow[] {
  const ev = obj(p).evidence;
  if (Array.isArray(ev) && ev.length > 0) {
    return ev.map((e) => {
      const r = (e && typeof e === "object" ? e : {}) as Record<string, unknown>;
      return {
        kind: evidenceKind(r.k ?? r.kind ?? r.type),
        label: str(r.label) ?? str(r.source),
        detail: str(r.detail) ?? str(r.text) ?? str(r.summary) ?? compactJson(r),
      } as EvidenceRow;
    });
  }
  // no structured evidence — render the raw proposal fields as one ▣ row
  const rest: Record<string, unknown> = {};
  // display_title/revised_doc_draft/trace_refs 已由標題與 DocRevisePreview
  // 呈現，evidence 原始 dump 不重複列。
  const skip = new Set(["title", "display_title", "why", "evidence", "targets", "revised_doc_draft", "trace_refs"]);
  for (const [k, v] of Object.entries(obj(p))) if (!skip.has(k)) rest[k] = v;
  return [{ kind: "sys", label: null, labelKey: "evidence.raw", detail: compactJson(rest) || "—" }];
}

// ── supersede detection ─────────────────────────────────────────────────
export function isSuperseded(p: Proposal): boolean {
  if (p.status === "expired" || p.status === "superseded") return true;
  if (p.superseded_by != null) return true;   // W2 top-level column
  const b = obj(p);
  return b.superseded === true || b.superseded_by != null || b.superseded_by_id != null;
}

export function supersededBy(p: Proposal): number | null {
  const b = obj(p);
  // W2 top-level column wins; legacy proposal-JSON fields as fallback
  const v = p.superseded_by ?? b.superseded_by ?? b.superseded_by_id;
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

// ── misc ────────────────────────────────────────────────────────────────
export function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

/** Shared fetch helper for the Java ApiResponse envelope { ok, data }. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  const j = await res.json().catch(() => ({}));
  if (!res.ok || j?.ok === false) {
    throw new Error(j?.error?.message ?? j?.error ?? `HTTP ${res.status}`);
  }
  return (j?.data ?? j) as T;
}
