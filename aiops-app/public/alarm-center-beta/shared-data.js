// shared-data.js — single source of truth for all three modes
// Same EQP-04 story plays in Copilot stream, Machine cards, Alarm clusters.

window.SHIFT = {
  user: 'Mike Chen',
  team: 'APAC-A',
  start: '06:00',
  now: '06:55'
};

window.SHIFT_STATS = {
  received: 348,
  autoHandled: 341,
  assist: 1,
  needsYou: 1,
  trust: 96,
  timeSaved: '2h 22m',
  cost: '$48K',
  suppressed: 327
};

// Canonical machines
window.MACHINES = [
  {
    id: 'EQP-04', bay: 'BAY-A', status: 'takeover',
    summary: '<strong>Photo CD drift</strong> · STEP_007 + STEP_009 連續 OOC × 4',
    confidence: 62,
    rawAlarms: 36,
    meta: { uptime: '94.2%', lots: 8, lastIncident: '5 days ago' },
    spark: [14.2, 14.5, 14.8, 15.1, 15.7, 16.1, 16.5, 17.1, 17.4, 17.6],
    ucl: 17.5, lcl: 13.0, mid: 15.25,
    started: '06:51',
    done: [
      { text: '比對 chamber 群組 (EQP-07 相關度 0.86)', meta: '06:48' },
      { text: '抓取 APC 參數 + baseline 對比', meta: '06:42' },
      { text: '通知 owner KH (chamber 領域)', meta: '06:38' }
    ],
    needs: {
      kind: 'takeover',
      title: '我看過類似情境但這次 pattern 更廣',
      sub: '上次 (04-25) 只有 STEP_007，這次 <strong>STEP_007 + STEP_009</strong> 一起偏，gas flow 也 -1.8σ。信心 62% (門檻 75%)，請你選 recovery 策略。',
      options: [
        { key: 'A', recommended: true, text: '停 EQP-04 + 開深度診斷', sub: '影響 8 lot · 我同步準備 chamber clean' },
        { key: 'B', text: '只 hold 接下來 3 個 lot', sub: '影響 3 lot · 若是 chamber drift 可能會擴大' },
        { key: 'C', text: '繼續跑，OOC ×5 再叫我', sub: '影響 0 lot · 風險：可能再爛 1-2 wafer' }
      ]
    }
  },
  {
    id: 'EQP-07', bay: 'BAY-A', status: 'warn',
    summary: '與 EQP-04 同 chamber 群組，etch rate 偏移 +2.1σ',
    confidence: 78,
    rawAlarms: 11,
    meta: { uptime: '96.8%', lots: 11, lastIncident: '12 days ago' },
    spark: [22.8, 23.1, 23.4, 23.9, 24.3, 24.8, 25.2, 25.6, 25.9, 26.1],
    ucl: 26.0, lcl: 21.0, mid: 23.5,
    started: '06:48',
    done: [
      { text: '標記為 EQP-04 關聯機台', meta: '06:51' },
      { text: '暫停新 lot 派工 (queue depth 0)', meta: '06:48' }
    ],
    needs: {
      kind: 'warn',
      title: '建議跟 EQP-04 一起處理',
      sub: '我會在你選 EQP-04 策略 A 時，<strong>自動同步</strong>處理 EQP-07。或可單獨採取行動：',
      options: [
        { key: 'A', recommended: true, text: '同 EQP-04 一起停', sub: 'recommended · 同 chamber group' },
        { key: 'B', text: '只 hold 此機台', sub: 'EQP-04 繼續跑' }
      ]
    }
  },
  {
    id: 'EQP-15', bay: 'BAY-B', status: 'assist',
    summary: 'Photo recipe 比 MES 差一個 minor revision，已 stand-by 完成 rollback',
    confidence: 91,
    rawAlarms: 2,
    meta: { uptime: '98.1%', lots: 6, lastIncident: '30+ days ago' },
    spark: [44.8, 44.9, 45.0, 45.1, 45.0, 44.9, 45.2, 45.1, 45.0, 45.0],
    ucl: 46.0, lcl: 44.0, mid: 45.0,
    started: '06:38',
    done: [
      { text: '偵測 recipe v2.3.1 vs MES v2.3.0 差異', meta: '06:41' },
      { text: '產生 rollback plan (預跑通過)', meta: '06:40' },
      { text: '通知 Photo team', meta: '06:39' }
    ],
    needs: {
      kind: 'assist',
      title: '一鍵確認即可執行 rollback',
      sub: '腳本已備妥，預跑通過，<strong>0 lot</strong> 受影響（pre-process 抓到）。',
      options: [
        { key: 'A', recommended: true, text: '執行 rollback', sub: '預計 38 秒 · 我會在完成後回報' },
        { key: 'B', text: '我自己手動處理', sub: '我會把 plan 寄到你的信箱' }
      ]
    }
  },
  {
    id: 'EQP-09', bay: 'BAY-A', status: 'auto',
    summary: 'Sensor jitter 自動抑制 (Pattern #1102)，<strong>0 lot</strong> 受影響',
    confidence: 96,
    rawAlarms: 4,
    meta: { uptime: '99.4%', lots: 0, lastIncident: '今天' },
    spark: [40.1, 40.0, 40.2, 40.1, 40.0, 40.1, 40.2, 40.1, 40.0, 40.1],
    ucl: 41.0, lcl: 39.0, mid: 40.0,
    started: '06:32',
    done: [
      { text: '抑制 sensor jitter alarm × 4', meta: '06:32' },
      { text: '寫入 audit log #auto-2451', meta: '06:32' }
    ],
    needs: null
  },
  {
    id: 'EQP-21', bay: 'BAY-C', status: 'auto',
    summary: 'Temperature sensor 自動校正完成，Δ 0.8°C → 0.1°C',
    confidence: 95,
    rawAlarms: 4,
    meta: { uptime: '98.9%', lots: 5, lastIncident: '8 days ago' },
    spark: [80.4, 80.6, 80.8, 80.7, 80.5, 80.3, 80.1, 80.0, 80.1, 80.0],
    ucl: 81.0, lcl: 79.0, mid: 80.0,
    started: '06:42',
    done: [
      { text: '偵測 temperature delta 0.8°C', meta: '06:42' },
      { text: '執行 sensor recalibration (4m 12s)', meta: '06:44' },
      { text: '驗證偏差 < 0.2°C tolerance', meta: '06:48' }
    ],
    needs: null
  },
  {
    id: 'EQP-12', bay: 'BAY-B', status: 'auto',
    summary: 'Throughput 下降 12% — 在預期範圍內 (PM 排程前 24h)',
    confidence: 88,
    rawAlarms: 5,
    meta: { uptime: '97.3%', lots: 4, lastIncident: '24 days ago' },
    spark: [22, 21, 22, 21, 20, 20, 19, 19, 18, 19],
    ucl: 25, lcl: 15, mid: 20,
    started: '06:30',
    done: [
      { text: '預測下次 PM 在 22h 內排入', meta: '06:30' },
      { text: '更新 throughput 預期模型', meta: '06:35' }
    ],
    needs: null
  },
  {
    id: 'EQP-01', bay: 'BAY-A', status: 'auto',
    summary: '所有參數在 control 範圍內',
    confidence: 99,
    rawAlarms: 0,
    meta: { uptime: '99.1%', lots: 12, lastIncident: '30+ days ago' },
    spark: [15.0, 15.1, 15.0, 14.9, 15.0, 15.1, 15.0, 14.9, 15.0, 15.0],
    ucl: 17.5, lcl: 13.0, mid: 15.25,
    started: null,
    done: [{ text: '日常監看 · 0 異常', meta: 'now' }],
    needs: null
  },
  {
    id: 'EQP-02', bay: 'BAY-A', status: 'auto',
    summary: '所有參數在 control 範圍內',
    confidence: 99,
    rawAlarms: 0,
    meta: { uptime: '99.6%', lots: 14, lastIncident: '30+ days ago' },
    spark: [15.0, 15.0, 14.9, 15.1, 15.0, 14.9, 15.0, 15.1, 15.0, 14.9],
    ucl: 17.5, lcl: 13.0, mid: 15.25,
    started: null,
    done: [{ text: '日常監看 · 0 異常', meta: 'now' }],
    needs: null
  },
  {
    id: 'EQP-26', bay: 'BAY-C', status: 'idle',
    summary: 'Idle — 排定 14:00 PM 完成後恢復',
    confidence: null,
    rawAlarms: 0,
    meta: { uptime: '—', lots: 0, lastIncident: '—' },
    spark: null,
    started: null,
    done: [{ text: 'PM 工單 #PM-2026-0430-C26 進行中', meta: '13:20' }],
    needs: null
  }
];

// 30 tool floor map status (derived + extras)
window.FLOOR_MAP = (() => {
  const explicit = {};
  window.MACHINES.forEach(m => { explicit[m.id] = m; });
  const tools = [];
  for (let i = 1; i <= 30; i++) {
    const id = `EQP-${String(i).padStart(2,'0')}`;
    const bay = i <= 10 ? 'A' : i <= 20 ? 'B' : 'C';
    if (explicit[id]) {
      tools.push({ id, bay, status: explicit[id].status });
    } else {
      // most tools idle/auto
      const idle = i === 18 || i === 22 || i === 27;
      tools.push({ id, bay, status: idle ? 'idle' : 'auto' });
    }
  }
  return tools;
})();

// Copilot stream messages (same EQP-04 story)
window.COPILOT_MESSAGES = [
  { type: 'time-divider', label: 'Shift start · 06:00' },
  {
    type: 'ai', time: '06:00',
    text: '早安 Mike，APAC-A 班次接管成功。已啟用 <strong>Autopilot</strong>，正在監看 <strong>30 台機台</strong>、<strong>6 個 lot</strong>。預計 8 小時內可處理 ~98% 告警，會在需要你接手時提醒。'
  },
  { type: 'time-divider', label: '06:32' },
  {
    type: 'ai', time: '06:32',
    text: '剛剛把 <strong>EQP-09</strong> 的 sensor jitter 自動抑制了 — 過去 7 天命中相同 pattern <code>#1102</code> × 4 次，是已知 false alarm。',
    autoCard: {
      title: 'EQP-09 sensor jitter suppressed',
      sub: 'Pattern #1102 · 不影響任何 lot · 已寫入 audit log',
      meta: 'took 12s'
    }
  },
  {
    type: 'ai', time: '06:38',
    text: '<strong>EQP-15</strong> Photo recipe 比 MES 紀錄差了一個 minor revision，已準備好 rollback 腳本。'
  },
  {
    type: 'ai', time: '06:42',
    text: '剛幫 <strong>EQP-21</strong> chamber 2 的 temperature sensor 跑了自動校正，與 backup 偏離已從 0.8°C → 0.1°C。',
    autoCard: {
      title: 'EQP-21 temperature sensor re-calibrated',
      sub: 'Δ 0.8°C → 0.1°C · in tolerance',
      meta: 'took 4m 12s'
    }
  },
  { type: 'time-divider', label: '06:51 · Takeover request' },
  {
    type: 'takeover', time: '06:51',
    headline: '我看到了一個我沒看過的 pattern，需要你幫我決定。',
    body: '<strong>EQP-04</strong> 在 STEP_007 + STEP_009 都出現 OOC（過去 30 分鐘共 <strong>4 次</strong>）。我的相似度匹配目前只有 <strong>62%</strong>（門檻 75%），所以不敢自己決定。最近一次 EQP-04 出問題（04-25）只有 STEP_007，這次 pattern 更廣。',
    conf: 62,
    options: [
      { key: 'A', recommended: true, title: '停 EQP-04 + 開深度診斷', sub: '影響 8 lot · 同步準備 chamber clean' },
      { key: 'B', title: '只 hold 接下來 3 個 lot', sub: '影響 3 lot · 可能會擴大' },
      { key: 'C', title: '繼續跑，OOC ×5 再叫我', sub: '影響 0 lot · 風險：1-2 wafer 報廢' }
    ]
  },
  { type: 'time-divider', label: '06:55' },
  {
    type: 'user', time: '06:55',
    text: '為什麼這次和上次不一樣？04-25 也是 OOC ×4'
  },
  {
    type: 'ai', time: '06:55',
    text: '兩個關鍵差異：',
    dataBlock: '            04-25 (last)    今天 (now)\nSTEP_007    OOC ×4          OOC ×3\nSTEP_009    —               OOC ×1   ← new\nGas flow    nominal         -1.8σ    ← new\nEtch rate   +1.2σ           +2.4σ    ← worse',
    followup: '<strong>STEP_009 也偏了 + gas flow 跟著走</strong>，這通常代表問題在 chamber 本體不是 recipe。上次 chamber clean 處理掉是合理的。',
    chips: [
      { label: '看完整證據鏈' },
      { label: '比較其他類似事件' },
      { label: '選 A 並開診斷', kind: 'primary' }
    ]
  }
];

// 30 tool floor map status (derived + extras)
