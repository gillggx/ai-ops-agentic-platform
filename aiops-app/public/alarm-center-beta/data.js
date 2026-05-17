/* AIOps mock data — 半導體 fab alarm scenarios */

const NOW = new Date('2026-04-30T14:18:00');
const minsAgo = (n) => new Date(NOW.getTime() - n * 60000);
const fmtTime = (d) => d.toTimeString().slice(0, 5);
const fmtAgo = (d) => {
  const m = Math.floor((NOW - d) / 60000);
  if (m < 1) return 'now';
  if (m < 60) return `${m}m`;
  return `${Math.floor(m / 60)}h`;
};
const fmtFull = (d) => d.toISOString().replace('T', ' ').slice(0, 19);

// 50 alarms grouped into clusters (簡化展示)
const CLUSTERS = [
  {
    id: 'c1', tool: 'EQP-03', area: 'BAY-A',
    severity: 'high', count: 15, openCount: 15, ackCount: 0,
    title: '連續 OOC — STEP_007 SPC 異常',
    summary: '<strong>EQP-03</strong> 最近 5 次 Process 中有 3 次 <strong>OOC</strong>，xbar 持續逼近 UCL，疑似 chamber drift。',
    firstAt: minsAgo(48), lastAt: minsAgo(6),
    spark: [3, 5, 4, 7, 8, 11, 10, 14, 13, 15],
    assignee: null,
    cause: 'chamber drift',
    affectedLots: 8,
    rootcause_confidence: 0.86,
  },
  {
    id: 'c2', tool: 'EQP-07', area: 'BAY-A',
    severity: 'high', count: 11, openCount: 11, ackCount: 0,
    title: 'Etch rate 偏移 — Recipe ETCH_PR04',
    summary: '<strong>EQP-07</strong> 在連續 11 個 lot 上出現 etch rate 高出 baseline 2.3σ，與 EQP-03 同 chamber 群組。',
    firstAt: minsAgo(42), lastAt: minsAgo(11),
    spark: [2, 3, 5, 6, 8, 7, 9, 10, 11, 11],
    assignee: 'KH',
    cause: 'recipe drift',
    affectedLots: 11,
    rootcause_confidence: 0.74,
  },
  {
    id: 'c3', tool: 'EQP-06', area: 'BAY-A',
    severity: 'high', count: 9, openCount: 7, ackCount: 2,
    title: 'Particle excursion — POST-CMP',
    summary: '<strong>EQP-06</strong> 後段 CMP 量測出現 particle 數高於 spec，過去 2 小時累計 9 件。',
    firstAt: minsAgo(120), lastAt: minsAgo(9),
    spark: [1, 2, 1, 3, 4, 5, 6, 7, 8, 9],
    assignee: 'YT',
    cause: 'consumable wear',
    affectedLots: 6,
    rootcause_confidence: 0.62,
  },
  {
    id: 'c4', tool: 'EQP-12', area: 'BAY-B',
    severity: 'med', count: 5, openCount: 5, ackCount: 0,
    title: 'Throughput 下降 18%',
    summary: '<strong>EQP-12</strong> 最近 30 分鐘 throughput 較預期下降 18%，未觸發 hard alarm 但有趨勢風險。',
    firstAt: minsAgo(31), lastAt: minsAgo(2),
    spark: [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
    assignee: null,
    cause: 'mechanical',
  },
  {
    id: 'c5', tool: 'EQP-21', area: 'BAY-C',
    severity: 'med', count: 4, openCount: 4, ackCount: 0,
    title: 'Sensor drift — temperature',
    summary: '<strong>EQP-21</strong> chamber 2 temperature sensor 讀值與 backup 偏離 0.8°C。',
    firstAt: minsAgo(24), lastAt: minsAgo(15),
    spark: [1, 2, 2, 3, 3, 4, 4, 4, 4, 4],
    assignee: 'JL',
    cause: 'sensor',
  },
  {
    id: 'c6', tool: 'EQP-04', area: 'BAY-A',
    severity: 'low', count: 3, openCount: 1, ackCount: 2,
    title: 'PM 即將到期',
    summary: '<strong>EQP-04</strong> 預防保養剩餘 8 hr，建議排入下個 idle window。',
    firstAt: minsAgo(180), lastAt: minsAgo(45),
    spark: [1, 1, 1, 2, 2, 2, 3, 3, 3, 3],
    assignee: 'ML',
    cause: 'scheduled',
  },
  {
    id: 'c7', tool: 'EQP-15', area: 'BAY-B',
    severity: 'low', count: 2, openCount: 2, ackCount: 0,
    title: 'Recipe 版本不一致',
    summary: '<strong>EQP-15</strong> 載入 recipe 版本與 MES 紀錄差 1 個 minor revision。',
    firstAt: minsAgo(95), lastAt: minsAgo(60),
    spark: [1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
    assignee: null,
    cause: 'config',
  },
  {
    id: 'c8', tool: 'EQP-09', area: 'BAY-C',
    severity: 'low', count: 1, openCount: 0, ackCount: 1,
    title: 'Network jitter',
    summary: '<strong>EQP-09</strong> EAP 連線出現短暫 jitter，已自動恢復。',
    firstAt: minsAgo(75), lastAt: minsAgo(75),
    spark: [0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    assignee: 'auto',
    cause: 'network',
  },
];

// Floor map — 30 tools across 3 bays
const FLOORMAP = [
  // BAY-A (most problems)
  { id: 'EQP-01', bay: 'A', status: 'ok', util: 92 },
  { id: 'EQP-02', bay: 'A', status: 'ok', util: 88 },
  { id: 'EQP-03', bay: 'A', status: 'high', util: 76, count: 15 },
  { id: 'EQP-04', bay: 'A', status: 'low', util: 84, count: 1 },
  { id: 'EQP-05', bay: 'A', status: 'ok', util: 91 },
  { id: 'EQP-06', bay: 'A', status: 'high', util: 70, count: 7 },
  { id: 'EQP-07', bay: 'A', status: 'high', util: 68, count: 11 },
  { id: 'EQP-08', bay: 'A', status: 'ok', util: 90 },
  { id: 'EQP-09', bay: 'A', status: 'idle', util: 0 },
  { id: 'EQP-10', bay: 'A', status: 'ok', util: 87 },
  // BAY-B
  { id: 'EQP-11', bay: 'B', status: 'ok', util: 89 },
  { id: 'EQP-12', bay: 'B', status: 'med', util: 72, count: 5 },
  { id: 'EQP-13', bay: 'B', status: 'ok', util: 93 },
  { id: 'EQP-14', bay: 'B', status: 'ok', util: 86 },
  { id: 'EQP-15', bay: 'B', status: 'low', util: 84, count: 2 },
  { id: 'EQP-16', bay: 'B', status: 'ok', util: 88 },
  { id: 'EQP-17', bay: 'B', status: 'ok', util: 90 },
  { id: 'EQP-18', bay: 'B', status: 'idle', util: 0 },
  { id: 'EQP-19', bay: 'B', status: 'ok', util: 85 },
  { id: 'EQP-20', bay: 'B', status: 'ok', util: 92 },
  // BAY-C
  { id: 'EQP-21', bay: 'C', status: 'med', util: 79, count: 4 },
  { id: 'EQP-22', bay: 'C', status: 'ok', util: 88 },
  { id: 'EQP-23', bay: 'C', status: 'ok', util: 91 },
  { id: 'EQP-24', bay: 'C', status: 'ok', util: 87 },
  { id: 'EQP-25', bay: 'C', status: 'ok', util: 89 },
  { id: 'EQP-26', bay: 'C', status: 'idle', util: 0 },
  { id: 'EQP-27', bay: 'C', status: 'ok', util: 90 },
  { id: 'EQP-28', bay: 'C', status: 'ok', util: 86 },
  { id: 'EQP-29', bay: 'C', status: 'ok', util: 92 },
  { id: 'EQP-30', bay: 'C', status: 'ok', util: 88 },
];

// Detail data for the selected cluster (EQP-03)
const PROCESS_HISTORY = [
  { time: '2026-04-30 14:16:50', lot: 'LOT-0043', step: 'STEP_007', spc: 'OOC', value: 15.084, ucl: 17.500, bad: true },
  { time: '2026-04-30 14:14:07', lot: 'LOT-0036', step: 'STEP_007', spc: 'PASS', value: 13.615, ucl: 17.500 },
  { time: '2026-04-30 14:11:25', lot: 'LOT-0029', step: 'STEP_009', spc: 'OOC', value: 16.340, ucl: 17.500, bad: true },
  { time: '2026-04-30 14:09:08', lot: 'LOT-0019', step: 'STEP_007', spc: 'OOC', value: 15.879, ucl: 17.500, bad: true },
  { time: '2026-04-30 14:06:13', lot: 'LOT-0003', step: 'STEP_001', spc: 'PASS', value: 15.668, ucl: 17.500 },
];

const APC_PARAMS = [
  { name: 'convergence_idx', value: 0.329 },
  { name: 'etch_rate_pred', value: 32.413, bad: true },
  { name: 'etch_time_offset', value: 0.015 },
  { name: 'fb_alpha', value: 0.108 },
  { name: 'fb_correction', value: 0.498 },
  { name: 'ff_alpha', value: 0.418 },
  { name: 'ff_correction', value: 0.030 },
  { name: 'ff_weight', value: 0.215 },
  { name: 'gas_flow_comp', value: -1.835, bad: true },
  { name: 'lot_weight', value: 0.413 },
];

const PLAN_STEPS = [
  { id: 'p1', text: '解析 EQP-03 觸發條件', status: 'done' },
  { id: 'p2', text: '比對 5 次 Process 資料 + APC 參數', status: 'done' },
  { id: 'p3', text: '查詢 EQP-03 過去 24h 同類 OOC', status: 'done' },
  { id: 'p4', text: '交叉比對 EQP-07 是否同 root cause', status: 'active' },
  { id: 'p5', text: '產生派工建議與優先序', status: 'pending' },
];

window.MOCK = {
  NOW, minsAgo, fmtTime, fmtAgo, fmtFull,
  CLUSTERS, FLOORMAP, PROCESS_HISTORY, APC_PARAMS, PLAN_STEPS,
};
