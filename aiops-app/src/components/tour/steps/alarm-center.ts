import type { TourStep } from "../types";

/** Alarm Center onboarding (5 steps).
 *
 *  Step 3 (深度診斷面板) targets the cluster detail panel which shows an
 *  empty state if no cluster is selected — the spotlight still works
 *  because the <main> wrapper exists either way; the empty state guides
 *  the user to "點 cluster 進入". Step 4 (DR 報告) only renders inside
 *  the cluster detail content, so we use the <main> as anchor + tell the
 *  user to click a cluster first if they haven't.
 */
export const ALARM_CENTER_STEPS: TourStep[] = [
  {
    title: "歡迎使用 Alarm Center",
    body: "這裡是廠房異常的單一入口。所有 SPC OOC、APC drift、FDC fault、auto patrol 觸發的告警都在這集中處理。30 秒帶你看 4 個重點。",
    target: null,
    placement: "center",
  },
  {
    title: "① Alarm Cluster 列表",
    body: "Alarm 自動依機台 + alarm type 聚類成 cluster。依 severity（HIGH / MEDIUM / LOW）排序。紅色 = 立即介入，黃色 = 觀察。點任一 cluster 進入深度診斷。",
    target: '[data-tour-id="alarm-list"]',
    placement: "right",
  },
  {
    title: "② 深度診斷面板",
    body: "（如果你還沒點 cluster，會看到「左側選擇 cluster 開始」） 點 cluster 後右側 panel 會展開：機台 ID、severity、時間範圍、cause、所有 alarm 事件清單 + 逐筆深度診斷。",
    target: '[data-tour-id="alarm-detail"]',
    placement: "left",
  },
  {
    title: "③ AI 診斷報告（要先點任一 cluster 才看得到）",
    body: "Sidecar 跑完整個 cluster 的 root cause 分析，整合 SPC + APC + FDC 上下文，給結論 + 建議 action。底下還有每筆 alarm 的個別深度診斷可以展開。",
    target: '[data-tour-id="alarm-dr"]',
    placement: "left",
  },
  {
    title: "完成！",
    body: "三個 action：✓ Acknowledge（看到了）、✓ Resolve（已處理）、↑ Escalate（升級給上層）。⌘K 隨時跳到任何 equipment / pipeline。隨時點 ? 重看本導覽。",
    target: ".tour-help",
    placement: "right",
  },
];
