/**
 * Kind + trigger → suggested pipeline inputs.
 *
 * Each suggestion maps to a PipelineInput the user can toggle on/off in the
 * wizard step 3. Suggestions are DB-less heuristics based on what typically
 * flows into each kind of pipeline at runtime:
 *
 *   auto_patrol + event     → fields from the event payload
 *   auto_patrol + schedule  → tool_id (for target_scope fan-out)
 *   auto_patrol + once      → tool_id (same, or specific literal)
 *   auto_check              → alarm attributes
 *   skill                   → common query params (Agent supplies at call time)
 *
 * Extending: add entries here. Descriptions become the PipelineInput.description
 * (shown in Inspector and Run Dialog), so keep them human-friendly.
 */

import type { PipelineInput, PipelineInputType } from "@/lib/pipeline-builder/types";

export type WizardKind = "auto_patrol" | "auto_check" | "skill";
export type WizardTriggerMode = "event" | "schedule" | "once" | null;
/** Subset of TargetScope.type that's relevant to the input suggester — only
 *  schedule/once-mode patrols carry a non-event scope, and only by_step
 *  changes which inputs the runtime expects (it injects $loop.step in
 *  addition to $loop.tool_id). Others can pass undefined. */
export type WizardScopeType =
  | "all_equipment"
  | "specific_equipment"
  | "by_step"
  | undefined;

export interface InputSuggestion {
  name: string;
  type: PipelineInputType;
  required: boolean;
  description: string;
  /** Pre-checked so the common case auto-selects. User can still uncheck. */
  preChecked: boolean;
  /** Marked as load-bearing for the kind's key runtime behavior (e.g. tool_id
   *  enables Auto-Patrol target_scope=all_equipment fan-out). Rendered with a
   *  badge so users understand why it matters. */
  critical?: boolean;
  /** Preview value used by Auto-Run on the canvas + Inspector placeholder.
   *  Without this, an Auto-Run with empty inputs resolves $name → null →
   *  block fails MISSING_PARAM (e.g. process_history "三選一" rule). At
   *  runtime the real value comes from event payload / patrol fan-out
   *  / user input, so example is purely for preview. */
  example?: string | number | boolean;
}

export function getInputSuggestions(
  kind: WizardKind,
  triggerMode: WizardTriggerMode,
  scopeType?: WizardScopeType,
): InputSuggestion[] {
  if (kind === "auto_patrol") {
    if (triggerMode === "event") {
      return [
        {
          name: "equipment_id",
          type: "string",
          required: true,
          preChecked: true,
          example: "EQP-01",
          description: "從 event payload 取得發生事件的機台 ID（常見於 OOC/APC_drift 等 event）",
        },
        {
          name: "lot_id",
          type: "string",
          required: false,
          preChecked: false,
          example: "LOT-12345",
          description: "從 event payload 取得批次 ID（lot 級事件才需要）",
        },
        {
          name: "step",
          type: "string",
          required: false,
          preChecked: false,
          example: "STEP_001",
          description: "製程站點，例如 STEP_013（step 級事件才需要）",
        },
        {
          name: "event_time",
          type: "string",
          required: false,
          preChecked: false,
          example: "2026-04-30T00:00:00Z",
          description: "事件發生時間（ISO 8601 字串）",
        },
      ];
    }
    // schedule or once — no event payload, fan-out is the key concern.
    // When scopeType=by_step the runtime injects $loop.step too, so step
    // becomes critical in that case (still optional for the other scopes).
    const stepRequired = scopeType === "by_step";
    return [
      {
        name: "tool_id",
        type: "string",
        required: true,
        preChecked: true,
        critical: true,
        example: "EQP-01",
        description:
          "綁 target_scope=all_equipment 時 Auto-Patrol Service 會在 runtime 為每台機台注入一次此值做 fan-out。強烈建議宣告，否則只能寫死 EQP-ID。",
      },
      {
        name: "step",
        type: "string",
        required: stepRequired,
        preChecked: stepRequired,
        critical: stepRequired,
        example: "STEP_001",
        description: stepRequired
          ? "目標範圍 = 指定站點 → runtime 會注入 $loop.step 給 pipeline。必填。"
          : "選擇性：如果 pipeline 需要區分製程站點，宣告這個。",
      },
      {
        name: "time_range",
        type: "string",
        required: false,
        preChecked: false,
        example: "24h",
        description: "預設時間窗，例如 24h / 7d（pipeline 裡的 block_process_history 可以綁這個）",
      },
    ];
  }
  if (kind === "auto_check") {
    return [
      {
        name: "equipment_id",
        type: "string",
        required: true,
        preChecked: true,
        critical: true,
        example: "EQP-01",
        description: "Alarm 發生在哪台機台（alarm payload 會自動填入）",
      },
      {
        name: "lot_id",
        type: "string",
        required: false,
        preChecked: false,
        example: "LOT-12345",
        description: "Alarm 對應的批次 ID",
      },
      {
        name: "step",
        type: "string",
        required: false,
        preChecked: false,
        example: "STEP_001",
        description: "Alarm 發生時的製程站點",
      },
      {
        name: "event_time",
        type: "string",
        required: false,
        preChecked: false,
        example: "2026-04-30T00:00:00Z",
        description: "Alarm 產生時間（ISO 8601）",
      },
      {
        name: "trigger_event",
        type: "string",
        required: false,
        preChecked: false,
        example: "OOC",
        description: "觸發這個 alarm 的 event_type 名稱（例如 OOC）",
      },
      {
        name: "severity",
        type: "string",
        required: false,
        preChecked: false,
        example: "HIGH",
        description: "Alarm 嚴重度（LOW / MEDIUM / HIGH / CRITICAL）",
      },
      {
        name: "summary",
        type: "string",
        required: false,
        preChecked: false,
        example: "範例：SPC 連續 2 次 OOC 觸發告警",
        description: "Alarm 摘要訊息（人類可讀）",
      },
      {
        name: "patrol_id",
        type: "integer",
        required: false,
        preChecked: false,
        example: 1,
        description: "Alarm 是由哪個 Auto-Patrol 產生（可用於 filter / trace）",
      },
    ];
  }
  // skill — Agent supplies these at call time; no critical default.
  return [
    {
      name: "tool_id",
      type: "string",
      required: true,
      preChecked: true,
      example: "EQP-01",
      description: "Agent 要查哪台機台時傳入（大多數 skill 用到）",
    },
    {
      name: "lot_id",
      type: "string",
      required: false,
      preChecked: false,
      example: "LOT-12345",
      description: "Agent 要查特定批次時傳入",
    },
    {
      name: "step",
      type: "string",
      required: false,
      preChecked: false,
      example: "STEP_001",
      description: "Agent 要鎖在特定 step 時傳入",
    },
    {
      name: "time_range",
      type: "string",
      required: false,
      preChecked: false,
      example: "24h",
      description: "查詢時間窗，例如 24h / 7d",
    },
    {
      name: "limit",
      type: "integer",
      required: false,
      preChecked: false,
      example: 100,
      description: "回傳筆數上限",
    },
  ];
}

/**
 * Convert a selected InputSuggestion into a PipelineInput (drop wizard-only
 * fields like preChecked / critical).
 */
export function suggestionToInput(s: InputSuggestion): PipelineInput {
  return {
    name: s.name,
    type: s.type,
    required: s.required,
    description: s.description,
    // Carry the example so Auto-Run on the canvas resolves $name without a
    // user-supplied value. Empty string and missing both fall through.
    ...(s.example !== undefined ? { example: s.example } : {}),
  };
}

/** Human-friendly kind label used across the wizard. */
export function kindLabel(kind: WizardKind): string {
  switch (kind) {
    case "auto_patrol": return "Auto Patrol";
    case "auto_check":  return "Auto-Check (診斷規則)";
    case "skill":       return "Skill";
  }
}

/** Short banner copy explaining WHY this kind needs inputs. */
export function kindInputRationale(kind: WizardKind, triggerMode: WizardTriggerMode): string {
  if (kind === "auto_patrol") {
    if (triggerMode === "event") {
      return "事件觸發時，event payload 的欄位會**依名稱**自動填入這裡宣告的 inputs。勾對應的欄位，pipeline 才拿得到觸發事件的資訊。";
    }
    return "排程 / 指定時間觸發時，Auto-Patrol Service 會在 runtime 為每台機台注入 tool_id 做 fan-out。沒定 tool_id 就只能寫死 EQP-ID，新機台上線不會被納入。";
  }
  if (kind === "auto_check") {
    return "Alarm 觸發時，**alarm payload 會依欄位名稱自動填入這裡宣告的 inputs**。沒宣告 → pipeline 拿不到 alarm 的任何資訊，整條變 hardcode 查詢。";
  }
  return "Agent 呼叫這個 skill 時會根據宣告的 inputs 傳入參數。沒宣告 → 每次呼叫都是同樣的固定查詢，失去客製化能力。";
}
