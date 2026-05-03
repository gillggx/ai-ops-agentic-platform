import type { TourStep } from "../types";

/** Fleet Overview (Mode A — /dashboard 沒帶 toolId) onboarding (6 steps).
 *
 *  All targets are elements that exist in Mode A. EQP detail's status
 *  cards / 製程溯源 live in EQP_DETAIL_STEPS (separate tour, fires
 *  when toolId is in the URL).
 */
export const FLEET_STEPS: TourStep[] = [
  {
    title: "歡迎使用設備導覽（全廠視角）",
    body: "這頁是全廠 overview。看 AI 摘要、最該介入的問題、所有機台健康度。45 秒帶你走 4 個重點。點任一機台可下鑽到 deep dive，那邊會有另一段導覽。",
    target: null,
    placement: "center",
  },
  {
    title: "① AI 簡報",
    body: "Sidecar 即時生成的全廠摘要 — 整合 24h KPI、active alarm、各機台 trend。右側列總體指標：active equipment / OOC count / wafers / health score。",
    target: '[data-tour-id="fleet-briefing"]',
    placement: "bottom",
  },
  {
    title: "② 最該關心的 3 件事",
    body: "AI 從所有 alarm + SPC + APC 訊號中挑出當下最該介入的 top 3，給排序理由 + 牽涉哪幾台機台。點任一卡片直接跳到對應機台 deep dive。",
    target: '[data-tour-id="fleet-concerns"]',
    placement: "top",
  },
  {
    title: "③ 機台清單 + 健康度",
    body: "所有機台列表，每台一個 0-100 健康度分數（綜合 SPC + APC drift + FDC alarm + EC seasoning）。卡片顯示近期 OOC count + alarm 數 + trend。可排序、filter。",
    target: '[data-tour-id="fleet-equipment-list"]',
    placement: "top",
  },
  {
    title: "④ ⌘K 跨頁面跳轉",
    body: "在任何頁面按 ⌘K（Windows 是 Ctrl+K），跨 surface 搜尋 pipeline / alarm / equipment — 一鍵跳轉。在這頁可以快速跳到任一機台 deep dive。",
    target: null,
    placement: "center",
  },
  {
    title: "完成！下一步：點機台進 deep dive",
    body: "點上方任一機台卡片進入 deep dive — 那邊有 5 面感測（SPC/APC/DC/FDC/EC）+ 製程溯源（流程 / 參數 / 拓樸圖），會有專屬的導覽出現。隨時可點左下角 ? 重看本導覽。",
    target: ".tour-help",
    placement: "right",
  },
];

/** EQP detail (Mode B — /dashboard?toolId=EQP-XX) onboarding (4 steps).
 *
 *  Fires when user enters Mode B for the first time. Targets are
 *  elements only present when EqpDetail is mounted.
 */
export const EQP_DETAIL_STEPS: TourStep[] = [
  {
    title: "EQP Deep Dive",
    body: "你進到單機台 deep dive 了。這頁有兩塊：上方 5 個 status card 一眼看健康狀態，下方分頁切換健康趨勢 / 製程溯源。30 秒帶你看 3 個重點。",
    target: null,
    placement: "center",
  },
  {
    title: "① 5 面感測 status cards",
    body: "SPC（pass/OOC）、APC（drift %）、FDC（fault class）、DC（sensor 異常）、EC（chamber age / wafers since PM）。一眼判斷介入優先級。顏色 = 該模組狀態。",
    target: '[data-tour-id="eqp-status-cards"]',
    placement: "bottom",
  },
  {
    title: "② 製程溯源（要先點上方「製程溯源」分頁）",
    body: "切到「製程溯源」分頁有 3 個 sub-tab：流程溯源（lot 走過哪幾個 step）、參數檢視（recipe / DC / APC 數值）、拓樸圖（用 React Flow 畫 lot × step × tool × ontology 全關係）。",
    target: '[data-tour-id="eqp-lineage"]',
    placement: "top",
  },
  {
    title: "完成！",
    body: "上方「全廠總覽」按鈕回 fleet overview。⌘K 跳到任何 equipment / alarm / pipeline。隨時可點 ? 重看導覽。",
    target: ".tour-help",
    placement: "right",
  },
];
