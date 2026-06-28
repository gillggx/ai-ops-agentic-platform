/**
 * 3-stage Skill Studio types (画面 A + 画面 B).
 *
 * Wire format is snake_case (Jackson default — feedback_jackson_snake_case_wire).
 */

export type StageKind = "detect" | "diagnose" | "recover";

export interface SkillStage {
  id: number;
  skill_doc_id: number;
  kind: StageKind;
  trigger_config: string;   // JSON text
  prose: string;
  compiled_rules: string;   // JSON text
  pipeline_id: number | null;
  status: "draft" | "stable";
  version: string;
  activated_at: string | null;
  activated_by: number | null;
  created_at: string;
  updated_at: string;
}

/** Compile output. Same shape returned by stub (Phase 2) and real LLM (Phase 5). */
export interface CompileResult {
  compiledRules: string;    // JSON text
  meta: Record<string, unknown>;
}

// ── Per-kind rule shapes ────────────────────────────────────────────────────

export interface DetectRule {
  id: string;               // "D1"
  when: string;
  for: string;
  if: string;
  then: string;
}

export interface DiagnoseRule {
  id: string;               // "A1" .. "A5"
  dim: "Tool" | "Lot" | "APC" | "Recipe" | "Step";
  title: string;
  operator: ">=";
  threshold: number;
}

export type Safety = "auto" | "approval" | "notify";

export interface RecoverRule {
  id: string;               // "P1" .. "P4"
  pattern: string;
  action: string;
  safety: Safety;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

export const KIND_ORDER: StageKind[] = ["detect", "diagnose", "recover"];

export const KIND_META: Record<StageKind, {
  zh: string; en: string; tagline: string;
  color: string; deep: string; tint: string;
  contractIn: string | null; contractOut: string;
}> = {
  detect:   {
    zh: "偵測", en: "DETECT",
    tagline: "監看訊號，達條件就觸發事件",
    color: "#b06d00", deep: "#8a5500", tint: "#fbf2e0",
    contractIn: "SPC 串流", contractOut: "Event",
  },
  diagnose: {
    zh: "診斷", en: "DIAGNOSE",
    tagline: "收到事件後多維度盤點成結構化 findings",
    color: "#3b5bdb", deep: "#2f49b0", tint: "#e9ecfd",
    contractIn: "Event", contractOut: "Findings[]",
  },
  recover:  {
    zh: "回復", en: "RECOVER",
    tagline: "命中 pattern 後採取動作",
    color: "#0f9d6e", deep: "#0b7a55", tint: "#e6f6f0",
    contractIn: "Findings[]", contractOut: "Action[]",
  },
};

export const SAFETY_META: Record<Safety, { label: string; color: string; bg: string }> = {
  auto:     { label: "自動",      color: "#0b7a55", bg: "#e6f6f0" },
  approval: { label: "需審批",    color: "#8a5500", bg: "#fbf2e0" },
  notify:   { label: "僅通知",    color: "#5b6470", bg: "#eef0f3" },
};
