import type { TourStep } from "../types";

/** Equipment Navigator / Fleet Overview onboarding (6 steps). */
export const FLEET_STEPS: TourStep[] = [
  {
    title: "歡迎使用設備導覽",
    body: "兩個視角：全廠 overview vs 單機台 deep dive。全廠看哪台/哪個 step 最差，單機台看 SPC/APC/DC/FDC/EC 五面 + 製程溯源。45 秒帶你看 5 個重點。",
    target: null,
    placement: "center",
  },
  {
    title: "① 全廠 OOC Heatmap",
    body: "x 軸 = 機台、y 軸 = step、顏色 = OOC rate。一眼看哪個 step × 機台組合最差。點任一 cell 直接跳到該機台 deep dive。",
    target: '[data-tour-id="fleet-heatmap"]',
    placement: "bottom",
  },
  {
    title: "② 機台清單 + 健康度",
    body: "左側列出所有機台，每台給一個 0-100 健康度分數（綜合 SPC + APC drift + FDC alarm + EC seasoning）。可以排序、filter status。",
    target: '[data-tour-id="fleet-equipment-list"]',
    placement: "right",
  },
  {
    title: "③ EQP detail — 5 面感測",
    body: "點機台進入詳情，上方 5 個 status card：SPC（pass/OOC）、APC（drift %）、FDC（fault class）、DC（sensor 異常）、EC（chamber age / wafers since PM）。一眼判斷介入優先級。",
    target: '[data-tour-id="eqp-status-cards"]',
    placement: "bottom",
  },
  {
    title: "④ 製程溯源 — 流程 / 參數 / 拓樸",
    body: "下方分頁：「流程溯源」看 lot 跑過哪幾個 step；「參數檢視」看 recipe / DC sensor 數值；「拓樸圖」用 React Flow 畫出 lot × step × tool × spc/apc/dc/ec 全 ontology 關係。",
    target: '[data-tour-id="eqp-lineage"]',
    placement: "top",
  },
  {
    title: "完成！",
    body: "隨時可按 ⌘K 跳到任何 equipment / alarm。機台異常時會自動產生 alarm 進 Alarm Center；那邊可以反向 trace 回這裡。",
    target: ".tour-help",
    placement: "right",
  },
];
