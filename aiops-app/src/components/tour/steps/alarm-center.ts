import type { TourStep } from "../types";

/** Alarm Center onboarding (5 steps). */
export const ALARM_CENTER_STEPS: TourStep[] = [
  {
    title: "歡迎使用 Alarm Center",
    body: "這裡是廠房異常的單一入口。所有 SPC OOC、APC drift、FDC fault、自動 patrol 觸發的告警都在這裡集中處理。30 秒帶你看 4 個重點。",
    target: null,
    placement: "center",
  },
  {
    title: "① Alarm 列表",
    body: "依 severity（CRITICAL / HIGH / MEDIUM）、OOC type、發生時間排序。紅色 = 立即介入，黃色 = 觀察。點 alarm 進入深度診斷。",
    target: '[data-tour-id="alarm-list"]',
    placement: "right",
  },
  {
    title: "② 深度診斷面板",
    body: "點任一 alarm 開啟。包含 SPC chart 上下文 + DR pipeline 自動跑出的 root cause + 相關歷史趨勢。Agent 已自動跑完分析。",
    target: '[data-tour-id="alarm-detail"]',
    placement: "left",
  },
  {
    title: "③ DR Pipeline（誰決定要這樣分析）",
    body: "每條 alarm 綁一條 DR pipeline，由 PE 在 Pipeline Builder 用 auto_check 模式建立、綁 alarm attribute（如「STEP_007 CD OOC 就跑 root cause 分析」）。透明可審計。",
    target: '[data-tour-id="alarm-dr"]',
    placement: "top",
  },
  {
    title: "完成！",
    body: "三個動作可選：✓ Acknowledge（看到了）、✓ Resolve（已處理）、↑ Escalate（升級給上層）。隨時可按 ⌘K 跳到任何 equipment / pipeline 對照分析。",
    target: ".tour-help",
    placement: "right",
  },
];
