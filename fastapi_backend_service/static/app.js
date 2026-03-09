/**
 * AI Ops — Frontend Application
 *
 * Architecture
 * ─────────────
 *  Auth      : JWT stored in localStorage; login via POST /api/v1/auth/login
 *  Diagnose  : POST /api/v1/diagnose/ with Bearer token → ReadableStream SSE
 *  SSE       : Custom parser (Fetch API — EventSource doesn't support auth headers)
 *  Tabs      : Dynamic tabs created per tool_call event; updated on tool_result
 *  Chat      : Bubbles added for session_start, tool notifications, report, done, error
 *  Markdown  : rendered with marked.js (loaded via CDN)
 *  i18n      : Simple zh/en toggle via _t(key) + data-i18n attributes
 *  Report    : Right panel slides in on first tool_call
 */

'use strict';

// ══════════════════════════════════════════════════════════════
// State
// ══════════════════════════════════════════════════════════════
let _token       = localStorage.getItem('glassbox_token');
let _isStreaming = false;
let _toolTabs    = {};  // key: toolName → { tabEl, panelEl } (legacy non-streaming flow)

// Phase 9.1 — Multi-Tab Workspace state
let _workspaceTabs = {};   // { tabId: {btn, panel} }
let _activeTabId   = null;

// Phase 10 — Mobile responsive state
let _mobileView = 'chat';  // 'chat' | 'workspace'

// Phase 9 — Copilot state
let _slotContext     = {};     // accumulated params for current slot-filling session
let _slotToolId      = null;   // tool_id being filled
let _slotToolType    = null;   // 'mcp' | 'skill'
let _copilotHistory  = [];     // [{role, content}] conversation history
let _slashMenuVisible = false;
let _slashMenuItems  = null;   // cached {mcps, skills} for slash menu

// ── v13 Agent state ─────────────────────────────────────────────
let _v13Mode      = true;    // default to v13 Agent (real agentic loop)
let _v13SessionId = null;    // persist session_id across turns

// ── Help Chat global state ──────────────────────────────────────
let _helpPanelOpen     = false;
let _helpWelcomeShown  = false;   // guard: show welcome bubble only once per session
let _helpHistory       = [];      // [{role, content}] — preserved across open/close
let _helpStreaming      = false;

// ══════════════════════════════════════════════════════════════
// i18n
// ══════════════════════════════════════════════════════════════
let _currentLang = localStorage.getItem('aiops_lang') || 'zh';

const _i18nData = {
  zh: {
    'brand':             'AI Ops',
    'brand-sub':         'AI 診斷智能體 · AIOps',
    'login-btn':         '登入',
    'paste-token':       '或直接貼上 JWT Token',
    'use-token':         '使用',
    'no-account':        '未有帳號？請先透過',
    'create-user':       '建立使用者。',
    'logout':            '登出',
    'chat-assistant':    '對話助手',
    'sim-trigger':       '⚡ 模擬觸發：TETCH01 PM2 發生 SPC OOC',
    'send-hint':         'Ctrl + Enter 送出',
    'summary-tab':       '總結報告',
    'report-placeholder':'診斷完成後，AI 報告將呈現在此',
    'ds-title':          'Data Subject 管理',
    'ds-sub':            '定義資料源與 API 連線設定 (IT Admin)',
    'ds-add':            '+ 新增 Data Subject',
    'et-title':          'Event Type Builder',
    'et-sub':            '定義異常事件與屬性 (Expert/PE)',
    'et-add':            '+ 新增 Event Type',
    'mcp-title':         'MCP Builder',
    'mcp-sub':           '資料加工與視覺化建構器 (Expert/PE)',
    'mcp-add':           '+ 新增 MCP',
    'skill-title':       'Skill Builder',
    'skill-sub':         '決策大腦：Event → MCP → 診斷邏輯 (Expert/PE)',
    'skill-add':         '+ 新增 Skill',
    'settings-title':    '系統大腦調校 (Prompt Settings)',
    'settings-sub':      'IT Admin 維護 LLM Prompt 設定',
    'settings-reload':   '↺ 重新載入',
    'mobile-chat':       '對話',
    'mobile-workspace':  '報告',
  },
  en: {
    'brand':             'AI Ops',
    'brand-sub':         'AI Diagnostic Agent · AIOps',
    'login-btn':         'Login',
    'paste-token':       'Or paste JWT Token directly',
    'use-token':         'Use',
    'no-account':        'No account? Create one via',
    'create-user':       '',
    'logout':            'Logout',
    'chat-assistant':    'Chat Assistant',
    'sim-trigger':       '⚡ Simulate: TETCH01 PM2 SPC OOC Triggered',
    'send-hint':         'Ctrl + Enter to send',
    'summary-tab':       'Summary Report',
    'report-placeholder':'AI report will appear here after diagnosis',
    'ds-title':          'Data Subject Management',
    'ds-sub':            'Define data sources & API connections (IT Admin)',
    'ds-add':            '+ Add Data Subject',
    'et-title':          'Event Type Builder',
    'et-sub':            'Define anomaly events & attributes (Expert/PE)',
    'et-add':            '+ Add Event Type',
    'mcp-title':         'MCP Builder',
    'mcp-sub':           'Data processing & visualization builder (Expert/PE)',
    'mcp-add':           '+ Add MCP',
    'skill-title':       'Skill Builder',
    'skill-sub':         'Decision brain: Event → MCP → Diagnosis (Expert/PE)',
    'skill-add':         '+ Add Skill',
    'settings-title':    'Brain Tuning (Prompt Settings)',
    'settings-sub':      'IT Admin maintains LLM prompt settings',
    'settings-reload':   '↺ Reload',
    'mobile-chat':       'Chat',
    'mobile-workspace':  'Report',
  },
};

function _t(key) {
  return (_i18nData[_currentLang] || _i18nData['zh'])[key] || key;
}

function _applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const text = _t(key);
    if (text !== undefined) el.textContent = text;
  });
  // Update lang button label
  const langBtn = document.getElementById('lang-btn');
  if (langBtn) langBtn.textContent = _currentLang === 'zh' ? 'EN' : '中';
}

function _toggleLang() {
  _currentLang = _currentLang === 'zh' ? 'en' : 'zh';
  localStorage.setItem('aiops_lang', _currentLang);
  _applyI18n();
}

// ══════════════════════════════════════════════════════════════
// Report Panel
// ══════════════════════════════════════════════════════════════

function _showReportPanel() {
  // Report panel is always visible (70% layout); nothing to animate.
}

function _hideReportPanel() {
  // Report panel stays visible; just reset its content on new session.
}

// ══════════════════════════════════════════════════════════════
// Event-Driven Trigger — shows alert card instead of sending chat text
// ══════════════════════════════════════════════════════════════

// Mock event definition for the SPC OOC trigger
const _SPC_OOC_EVENT = {
  event_type:  'SPC_OOC_Etch_CD',
  event_id:    `EVT-${Date.now()}`,
  timestamp:   new Date().toLocaleString('zh-TW', { hour12: false }),
  params: {
    lot_id:           'L12345',
    tool_id:          'TETCH01',
    chamber_id:       'CH1',
    operation_number: '3200',
    ooc_parameter:    'CD_Mean',
    SPC_CHART:        'CD',
  },
};

function _simulateTrigger(/* text — kept for signature compat */) {
  if (_isStreaming) return;

  // Stamp a fresh event ID & timestamp each click
  _SPC_OOC_EVENT.event_id  = `EVT-${Date.now()}`;
  _SPC_OOC_EVENT.timestamp = new Date().toLocaleString('zh-TW', { hour12: false });
  window._pendingEventPayload = { ..._SPC_OOC_EVENT };

  const paramsHtml = Object.entries(_SPC_OOC_EVENT.params)
    .map(([k, v]) => `
      <div class="flex justify-between text-sm">
        <span class="text-slate-500">${_escapeHtml(k)}</span>
        <span class="text-slate-800 font-medium font-mono">${_escapeHtml(v)}</span>
      </div>`)
    .join('');

  const cardHtml = `
    <div class="bg-white border border-slate-200 rounded-lg shadow-sm w-full max-w-sm font-sans overflow-hidden">
      <div class="flex items-center justify-between px-4 py-3 border-b border-slate-100 bg-slate-50">
        <div class="flex items-center space-x-2">
          <svg class="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <span class="text-slate-700 font-semibold text-sm">系統通知</span>
        </div>
        <span class="text-slate-400 text-xs">${_escapeHtml(_SPC_OOC_EVENT.timestamp)}</span>
      </div>
      <div class="p-4">
        <div class="mb-4">
          <h3 class="text-lg font-bold text-slate-800">${_escapeHtml(_SPC_OOC_EVENT.event_type)}</h3>
          <p class="text-xs text-slate-400 font-mono mt-1"># ${_escapeHtml(_SPC_OOC_EVENT.event_id)}</p>
        </div>
        <div class="space-y-2 mb-5 bg-slate-50 p-3 rounded-md border border-slate-100">
          ${paramsHtml}
        </div>
        <button onclick="_launchEventDiagnosis()"
          class="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 px-4 rounded-md
                 transition-colors flex items-center justify-center space-x-2">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
          <span>啟動診斷分析</span>
        </button>
      </div>
    </div>`;

  _addChatBubble('event-alert', cardHtml);
}

// ══════════════════════════════════════════════════════════════
// Event-Driven Full Pipeline  (_launchEventDiagnosis)
// ══════════════════════════════════════════════════════════════

async function _launchEventDiagnosis() {
  const payload = window._pendingEventPayload;
  if (!payload || _isStreaming) return;

  _isStreaming = true;
  _setInputLocked(true);
  _setStatus('streaming');

  // Initialise the report panel header, clear old cards
  _initReportPanel(payload);
  _addChatBubble('agent', `🔍 已啟動診斷分析：<strong>${_escapeHtml(payload.event_type)}</strong>`);

  // Per-skill chat bubble references so we can update them in-place
  const skillBubbles = {};
  const collectedSkills = [];   // accumulated for summary rendering
  let totalSkills = 0;
  let doneCount = 0;

  try {
    const res = await fetch('/api/v1/diagnose/event-driven-stream', {
      method:  'POST',
      headers: {
        'Content-Type':  'application/json',
        'Authorization': `Bearer ${_token}`,
      },
      body: JSON.stringify({
        event_type: payload.event_type,
        event_id:   payload.event_id,
        params:     payload.params,
      }),
    });

    if (res.status === 401) { logout(); return; }
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { const err = await res.json(); msg = err.message || msg; } catch { /**/ }
      _addChatBubble('error', `❌ 診斷管線失敗：${msg}`);
      _renderPipelineError(msg);
      return;
    }

    // ── Read SSE stream ──
    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop();

      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;
        // Parse SSE line: "data: {...}"
        const dataLine = trimmed.split('\n').find(l => l.startsWith('data:'));
        if (!dataLine) continue;
        let evt;
        try { evt = JSON.parse(dataLine.slice(5).trim()); } catch { continue; }

        if (evt.type === 'error') {
          _diagLogLine('✗', evt.message, '#f87171');
          _addChatBubble('error', `⚠️ ${_escapeHtml(evt.message)}`);
          _renderPipelineError(evt.message);

        } else if (evt.type === 'start') {
          totalSkills = evt.skill_count || 0;
          _diagLogLine('▶', `診斷管線啟動 — ${totalSkills} 個 Skill`);
          _addChatBubble('agent', `📋 共找到 <strong>${totalSkills}</strong> 個 Skill，逐一執行中...`);

        } else if (evt.type === 'skill_start') {
          const bubbleId = `skill-bubble-${evt.index}`;
          _diagLogLine('⏳', `執行 Skill：${evt.skill_name}`);
          _addChatBubble('agent', `⏳ 正在執行 <strong>${_escapeHtml(evt.skill_name)}</strong>...`, bubbleId);
          skillBubbles[evt.index] = document.getElementById(bubbleId);

        } else if (evt.type === 'skill_done') {
          console.log('【1. SSE 收到原始 Payload】skill_done', JSON.parse(JSON.stringify(evt)));
          const doneIcon = evt.error ? '✗' : (evt.status === 'NORMAL' ? '✓' : '⚠');
          const doneColor = evt.error ? '#f87171' : (evt.status === 'NORMAL' ? '#34d399' : '#fbbf24');
          _diagLogLine(doneIcon, `${evt.skill_name} → ${evt.error ? '錯誤' : (evt.status || '完成')}${evt.error ? '：' + evt.error : ''}`, doneColor);
          doneCount++;
          collectedSkills.push(evt);
          // Update chat bubble
          const bubble = skillBubbles[evt.index];
          if (bubble) {
            const icon = evt.status === 'NORMAL' ? '✅' : (evt.error ? '❌' : '⚠️');
            bubble.innerHTML = `${icon} <strong>${_escapeHtml(evt.skill_name)}</strong> ${evt.error ? '失敗' : (evt.status === 'NORMAL' ? '正常' : '異常')}`;
          }
          // Append skill tab + card to report panel
          _appendSkillCard(evt);

        } else if (evt.type === 'done') {
          // Render summary bar above tabs
          _renderDiagnosisSummary(collectedSkills);
          const abnormal = collectedSkills.filter(s => !s.error && s.status !== 'NORMAL').length;
          if (totalSkills === 0) {
            _diagLogLine('⚠', '未找到綁定此 Event 的 Skill', '#fbbf24');
            _addChatBubble('agent', '⚠️ 未找到綁定此 Event 的 Skill，請先在 Skill Builder 建立。');
          } else if (abnormal > 0) {
            _diagLogLine('✓', `診斷完成 — ${abnormal}/${totalSkills} 異常`, '#fbbf24');
            _addChatBubble('agent', `🚨 診斷完成：${totalSkills} 個 Skill 中有 <strong>${abnormal}</strong> 個檢測到異常，請查看右側報告。`);
          } else {
            _diagLogLine('✓', `診斷完成 — 全部 ${totalSkills} 個正常`, '#34d399');
            _addChatBubble('agent', `✅ 診斷完成：全部 ${totalSkills} 個 Skill 正常。`);
          }
          _setStatus('ready');
        }
      }
    }

  } catch (err) {
    _addChatBubble('error', `❌ 連線錯誤：${err.message}`);
    _renderPipelineError(err.message);
  } finally {
    _isStreaming = false;
    _setInputLocked(false);
  }
}

/**
 * Initialise the report panel with a header for the triggering event.
 * Clears previous skill cards; returns the cards container element.
 */
function _initReportPanel(payload) {
  const tabId  = 'evt-current';
  const evtId  = payload.event_id || 'Event';

  // Replace any existing event tab (re-trigger resets the tab)
  if (_workspaceTabs[tabId]) {
    _workspaceTabs[tabId].btn.remove();
    _workspaceTabs[tabId].panel.remove();
    delete _workspaceTabs[tabId];
  }

  const paramsChips = Object.entries(payload.params || {}).map(([k, v]) =>
    `<span class="inline-flex items-center gap-1 bg-red-50 border border-red-200
                  rounded px-2 py-0.5 font-mono text-xs text-red-800">
      <span class="text-red-500">${_escapeHtml(k)}:</span>${_escapeHtml(String(v))}
    </span>`).join('');

  const contentHtml = `
    <div class="flex flex-col h-full overflow-hidden">
      <div class="px-6 pt-5 pb-3 border-b border-slate-200 flex-shrink-0 bg-slate-50">
        <div class="flex items-center gap-3 mb-2">
          <span class="text-base font-bold text-red-700">🚨 ${_escapeHtml(payload.event_type || '')}</span>
          <span class="text-xs font-mono text-slate-400">${_escapeHtml(evtId)}</span>
        </div>
        <div class="flex gap-2 flex-wrap">${paramsChips}</div>
      </div>
      <div id="skill-tab-bar"
           class="flex flex-shrink-0 border-b border-slate-200 bg-white overflow-x-auto px-2 pt-1 min-h-[42px]"></div>
      <div id="skill-tab-panels" class="flex-1 overflow-y-auto"></div>
    </div>`;

  _createWorkspaceTab(tabId, `🚨 ${evtId}`, contentHtml);
  _showReportPanel();
}

function _renderPipelineError(msg) {
  // Append error into the active event workspace tab
  const panels = document.getElementById('skill-tab-panels');
  if (panels) {
    panels.insertAdjacentHTML('beforeend',
      `<div class="m-4 p-4 text-red-600 bg-red-50 border border-red-200 rounded-lg text-sm">❌ 管線執行失敗：${_escapeHtml(msg)}</div>`);
  }
}

/**
 * Append one skill result as a tab + panel (called as each SSE skill_done arrives).
 */
function _appendSkillCard(s) {
  const tabBar = document.getElementById('skill-tab-bar');
  const panels = document.getElementById('skill-tab-panels');
  if (!tabBar || !panels) return;

  const idx    = tabBar.querySelectorAll('.skill-tab-btn').length;
  const isFirst = idx === 0;
  const icon   = s.error ? '❌' : (s.status === 'NORMAL' ? '✅' : '⚠️');
  const panelId = `skill-panel-${idx}`;

  // ── Tab button ──────────────────────────────────────────────
  const btn = document.createElement('button');
  btn.className = `skill-tab-btn${isFirst ? ' active' : ''}`;
  btn.title     = s.skill_name;
  btn.innerHTML = `${icon} ${_escapeHtml(s.skill_name)}`;
  btn.onclick   = () => _switchSkillTab(idx);
  tabBar.appendChild(btn);

  // ── Panel ────────────────────────────────────────────────────
  const panel = document.createElement('div');
  panel.id        = panelId;
  panel.className = `skill-tab-panel p-4${isFirst ? '' : ' hidden'}`;
  panel.innerHTML = _renderSkillBlock(s);
  panels.appendChild(panel);

  // Defer Plotly init one frame so the browser completes layout before measuring container
  requestAnimationFrame(() => _initChartsInCard(panel));
}

/** Switch active skill tab. */
function _switchSkillTab(idx) {
  document.querySelectorAll('.skill-tab-btn').forEach((btn, i) => {
    btn.classList.toggle('active', i === idx);
  });
  document.querySelectorAll('.skill-tab-panel').forEach((panel, i) => {
    panel.classList.toggle('hidden', i !== idx);
  });
}

/**
 * Render diagnosis summary as a tab (called after all skills complete).
 * Creates a "📊 總覽" tab at the end of the skill tab bar and switches to it.
 */
function _renderDiagnosisSummary(skills) {
  const tabBar = document.getElementById('skill-tab-bar');
  const panels = document.getElementById('skill-tab-panels');
  if (!tabBar || !panels || skills.length === 0) return;

  const summaryIdx = tabBar.querySelectorAll('.skill-tab-btn').length;

  // ── Tab button ──────────────────────────────────────────────
  const btn = document.createElement('button');
  btn.className = 'skill-tab-btn summary-tab-btn';
  btn.title     = '診斷總覽';
  btn.innerHTML = '📊 總覽';
  btn.onclick   = () => _switchSkillTab(summaryIdx);
  tabBar.appendChild(btn);

  // ── Panel content ────────────────────────────────────────────
  const headerCols = `
    <div class="summary-row" style="font-weight:600;color:#1e3a8a;font-size:11px;text-transform:uppercase;letter-spacing:.05em;padding-bottom:4px;border-bottom:1px solid #bfdbfe;">
      <span>Skill</span><span>診斷結論</span><span>建議動作</span>
    </div>`;

  const rows = skills.map(s => {
    const badge = s.error
      ? `<span class="inline-block px-2 py-0.5 rounded-full text-xs font-bold bg-red-100 text-red-700">ERROR</span>`
      : s.status === 'NORMAL'
        ? `<span class="inline-block px-2 py-0.5 rounded-full text-xs font-bold bg-green-100 text-green-700">正常</span>`
        : `<span class="inline-block px-2 py-0.5 rounded-full text-xs font-bold bg-orange-100 text-orange-700">異常</span>`;
    return `
      <div class="summary-row">
        <div class="flex items-start gap-1.5 flex-col">
          ${badge}
          <span class="text-slate-700 text-xs leading-snug">${_escapeHtml(s.skill_name)}</span>
        </div>
        <span class="text-slate-600 text-xs leading-relaxed">${_escapeHtml(s.conclusion || s.error || '')}</span>
        <span class="text-blue-800 text-xs leading-relaxed italic">${s.status !== 'NORMAL' ? _escapeHtml(s.human_recommendation || '—') : '—'}</span>
      </div>`;
  }).join('');

  // ── Panel element ────────────────────────────────────────────
  const panel = document.createElement('div');
  panel.className = 'skill-tab-panel p-4 hidden';
  panel.innerHTML = `
    <div class="text-xs font-bold text-blue-900 uppercase tracking-wider mb-3">📊 診斷總覽</div>
    <div class="diagnosis-summary-bar">${headerCols}${rows}</div>`;
  panels.appendChild(panel);

  // Switch to summary tab
  _switchSkillTab(summaryIdx);
}

/**
 * Initialise Plotly charts embedded in a skill card.
 * Robust: handles spec.data, spec.traces, empty data, and missing Plotly.
 */
function _initChartsInCard(cardEl) {
  if (!cardEl) return;
  cardEl.querySelectorAll('.evidence-chart[data-chart]').forEach(div => {
    const raw = div.dataset.chart;
    if (!raw) return;
    try {
      if (raw.startsWith('{')) {
        const spec    = JSON.parse(raw);
        const traces  = spec.data || spec.traces || [];
        if (window.Plotly) {
          const specLayout = spec.layout || {};
          // Deep-merge margin so spec can adjust individual sides without clobbering defaults
          const mergedMargin = Object.assign({ t: 40, b: 40, l: 50, r: 20 }, specLayout.margin || {});
          if (specLayout.title && mergedMargin.t < 55) mergedMargin.t = 55;
          const hasHorizLegend = specLayout.legend?.orientation === 'h';
          if (hasHorizLegend && mergedMargin.b < 100) mergedMargin.b = 100;
          const legendOverride = hasHorizLegend ? { legend: { ...specLayout.legend, y: -0.28, x: 0, xanchor: 'left' } } : {};
          const layout = Object.assign({
            height: 360,
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor:  '#f8fafc',
            font: { color: '#374151', size: 11 },
          }, specLayout, { margin: mergedMargin }, legendOverride);
          Plotly.newPlot(div, traces, layout, { responsive: true, displayModeBar: false });
        } else {
          // Plotly not loaded — hide wrapper so no blank space remains
          (div.closest('.evidence-chart-wrapper') || div).style.display = 'none';
        }
      } else if (raw.startsWith('data:image/')) {
        div.innerHTML = `<img src="${raw}" style="max-width:100%;border-radius:6px">`;
      } else {
        // Unknown format — hide wrapper
        (div.closest('.evidence-chart-wrapper') || div).style.display = 'none';
      }
    } catch (e) {
      // Hide entire wrapper on error so no blank space remains
      (div.closest('.evidence-chart-wrapper') || div).style.display = 'none';
    }
  });
}

/**
 * Open a chart in a fullscreen overlay.
 * On mobile portrait the inner container is CSS-rotated 90° to fill the
 * landscape dimensions — no native screen-lock API required.
 */
function _openChartFullscreen(chartData) {
  const modal  = document.getElementById('chart-fullscreen-modal');
  const target = document.getElementById('chart-fullscreen-target');
  if (!modal || !target || !chartData) return;

  target.innerHTML = '';
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';

  if (chartData.startsWith('{')) {
    // Plotly JSON spec — re-render at full size
    requestAnimationFrame(() => {
      try {
        const spec   = JSON.parse(chartData);
        const traces = spec.data || spec.traces || [];
        const layout = Object.assign({
          margin:          { t: 44, b: 52, l: 58, r: 26 },
          paper_bgcolor:   'rgba(0,0,0,0)',
          plot_bgcolor:    '#1e293b',
          font:            { color: '#e2e8f0', size: 13 },
          autosize:        true,
        }, spec.layout || {});
        if (window.Plotly) {
          Plotly.newPlot(target, traces, layout, { responsive: true, displayModeBar: true });
        }
      } catch (_) {
        target.innerHTML = '<p style="color:#e2e8f0;padding:24px">圖表載入失敗</p>';
      }
    });
  } else if (chartData.startsWith('data:image/')) {
    // Base64 PNG
    target.innerHTML = `<img src="${chartData}"
      style="max-width:100%;max-height:100%;object-fit:contain;display:block;margin:auto">`;
  }
}

/** Close chart fullscreen overlay and purge Plotly instance. */
function closeChartFullscreen() {
  const modal  = document.getElementById('chart-fullscreen-modal');
  const target = document.getElementById('chart-fullscreen-target');
  if (!modal) return;
  modal.classList.add('hidden');
  document.body.style.overflow = '';
  if (target) {
    if (window.Plotly) { try { Plotly.purge(target); } catch (_) {} }
    target.innerHTML = '';
  }
}

/** Legacy: kept so old non-streaming code paths don't break */
function _renderPipelineResults(result) {
  _initReportPanel(result.event || {});
  (result.skills || []).forEach(s => _appendSkillCard(s));
}

/**
 * Render a problem_object value as inline badges / key-value rows.
 * Handles scalar, array, and object shapes.
 */
function _renderProblemObjectInline(obj) {
  if (obj === null || obj === undefined) return '';
  if (typeof obj === 'string' || typeof obj === 'number' || typeof obj === 'boolean') {
    return `<span class="inline-block text-xs font-semibold bg-yellow-100 text-yellow-800 border border-yellow-300 rounded px-2 py-0.5">${_escapeHtml(String(obj))}</span>`;
  }
  if (Array.isArray(obj)) {
    if (!obj.length) return '';
    if (obj.every(v => typeof v !== 'object' || v === null)) {
      return `<div class="flex flex-wrap gap-1">${obj.map(v =>
        `<span class="text-xs font-semibold bg-yellow-100 text-yellow-800 border border-yellow-300 rounded px-2 py-0.5">${_escapeHtml(String(v))}</span>`
      ).join('')}</div>`;
    }
    return `<pre class="bg-amber-50 border border-amber-200 text-amber-900 text-xs rounded px-2 py-2 overflow-x-auto max-h-24">${_escapeHtml(JSON.stringify(obj, null, 2))}</pre>`;
  }
  if (typeof obj === 'object') {
    const entries = Object.entries(obj);
    if (!entries.length) return '';
    const rows = entries.map(([k, v]) => {
      let cell;
      if (v === null || v === undefined) {
        cell = '<span class="text-slate-400">—</span>';
      } else if (Array.isArray(v) && v.every(x => typeof x !== 'object' || x === null)) {
        cell = `<div class="flex flex-wrap gap-0.5">${v.map(x =>
          `<span class="inline-block bg-yellow-100 text-yellow-800 border border-yellow-300 rounded px-1.5 text-xs">${_escapeHtml(String(x))}</span>`
        ).join('')}</div>`;
      } else {
        cell = `<span class="text-amber-800 font-semibold text-xs">${_escapeHtml(typeof v === 'object' ? JSON.stringify(v) : String(v))}</span>`;
      }
      return `<tr>
        <td class="py-0.5 pr-3 text-slate-500 font-medium text-xs whitespace-nowrap align-top">${_escapeHtml(k)}</td>
        <td class="py-0.5 align-top">${cell}</td>
      </tr>`;
    }).join('');
    return `<table class="text-xs border-collapse w-full">${rows}</table>`;
  }
  return `<span class="text-xs font-semibold bg-yellow-100 text-yellow-800 border border-yellow-300 rounded px-2 py-0.5">${_escapeHtml(String(obj))}</span>`;
}

/**
 * Switch the active tab in an evidence section.
 * @param {string} uid   - Unique suffix for this evidence block
 * @param {string} tabId - ID of the tab to activate (e.g. 'chart-0', 'summary', 'raw')
 */
function _switchEvidenceTab(uid, tabId) {
  const section = document.getElementById(`ev-section-${uid}`);
  if (!section) return;

  // Hide all panels, deactivate all buttons
  section.querySelectorAll('.evidence-tab-panel').forEach(p => p.classList.add('hidden'));
  section.querySelectorAll('.evidence-tab-btn').forEach(b => b.classList.remove('active'));

  // Show requested panel + activate its button
  const panel = document.getElementById(`ev-panel-${tabId}-${uid}`);
  const btn   = document.getElementById(`ev-btn-${tabId}-${uid}`);
  if (panel) {
    panel.classList.remove('hidden');
    // Re-trigger Plotly render for chart tabs that were hidden during initial render
    if (tabId.startsWith('chart')) requestAnimationFrame(() => _initChartsInCard(panel));
  }
  if (btn) btn.classList.add('active');
}

function _renderSkillBlock(s) {
  if (s.error) {
    return `
      <div class="pipeline-report-block">
        <div class="pipeline-block-header">
          <span class="text-sm font-semibold text-slate-700">⚙️ ${_escapeHtml(s.skill_name)}</span>
          <span class="text-xs text-slate-400 ml-2 font-mono">${_escapeHtml(s.mcp_name)}</span>
          <span class="pipeline-block-status error">ERROR</span>
        </div>
        <div class="pipeline-block-body text-red-600 text-sm">⚠️ ${_escapeHtml(s.error)}</div>
      </div>`;
  }

  const statusClass = s.status === 'NORMAL' ? 'normal' : 'abnormal';
  const statusLabel = s.status === 'NORMAL' ? '✓ NORMAL' : '⚠ ABNORMAL';

  // 1. LLM-generated summary (primary narrative)
  const summaryHtml = s.summary
    ? `<p class="text-sm text-slate-800 mb-2">${_escapeHtml(s.summary)}</p>`
    : (s.conclusion ? `<p class="text-sm text-slate-800 mb-2">${_escapeHtml(s.conclusion)}</p>` : '');

  // 2. Identified abnormal object (from Python result)
  const probObj = s.problem_object;
  const hasProbObj = probObj && (
    (typeof probObj === 'string' && probObj !== '') ||
    (Array.isArray(probObj) && probObj.length > 0) ||
    (typeof probObj === 'object' && !Array.isArray(probObj) && Object.keys(probObj).length > 0)
  );
  const problemHtml = hasProbObj ? `
    <div class="skill-problem-object mt-2 mb-1">
      <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">🎯 異常物件</div>
      ${_renderProblemObjectInline(probObj)}
    </div>` : '';

  // 3. Expert recommendation (only shown when ABNORMAL)
  const recommendHtml = s.human_recommendation && s.status !== 'NORMAL'
    ? `<div class="pipeline-recommendation">💡 <strong>建議動作：</strong>${_escapeHtml(s.human_recommendation)}</div>`
    : '';

  // 4. MCP evidence tabs (Charting + Summary Data)
  const tabSuffix = Math.random().toString(36).slice(2, 7);
  const evidenceTabsHtml = _renderMcpEvidence(s.mcp_output, tabSuffix);

  return `
    <div class="pipeline-report-block">
      <div class="pipeline-block-header">
        <span class="text-sm font-semibold text-slate-700">⚙️ ${_escapeHtml(s.skill_name)}</span>
        <span class="text-xs text-slate-400 ml-2 font-mono">${_escapeHtml(s.mcp_name)}</span>
        <span class="pipeline-block-status ${statusClass}">${statusLabel}</span>
      </div>
      <div class="pipeline-block-body">
        ${summaryHtml}
        ${problemHtml}
        ${recommendHtml}
        ${evidenceTabsHtml}
      </div>
    </div>`;
}

/**
 * Render MCP output evidence: call params header + tabbed Charting / Summary Data / Raw Data.
 *
 * Tab logic:
 *   - "📊 Charting" (or "📊 Chart N" for multiples) → one tab per chart in ui_render.charts[]
 *   - "📋 Summary Data" → dataset exists AND _is_processed=true
 *   - "📄 Raw Data"     → _raw_dataset exists (original DS API response)
 *
 * @param {Object} mcpOutput  - Standard Payload {ui_render, dataset, _call_params, _raw_dataset}
 * @param {string} [suffix]   - Unique suffix for tab IDs (auto-generated if omitted)
 */
function _renderMcpEvidence(mcpOutput, suffix) {
  if (!mcpOutput) return '';
  console.log('【2. 準備渲染圖表，檢查紙箱】 charts:', (mcpOutput.ui_render || {}).charts, 'chart_data:', (mcpOutput.ui_render || {}).chart_data, '_is_processed:', mcpOutput._is_processed, '_raw_dataset rows:', Array.isArray(mcpOutput._raw_dataset) ? mcpOutput._raw_dataset.length : mcpOutput._raw_dataset);

  const uid        = suffix || Math.random().toString(36).slice(2, 7);
  const uiRender   = mcpOutput.ui_render || {};
  const callParams = mcpOutput._call_params || {};

  // ── Call parameters header ─────────────────────────────────
  const paramEntries = Object.entries(callParams).filter(([, v]) => v != null && v !== '');
  const paramsHtml = paramEntries.length > 0 ? `
    <div class="mcp-call-params">
      ${paramEntries.map(([k, v]) =>
        `<span class="mcp-param-chip"><span class="mcp-param-key">${_escapeHtml(k)}</span><span class="mcp-param-sep">:</span><span class="mcp-param-val">${_escapeHtml(String(v))}</span></span>`
      ).join('')}
    </div>` : '';

  // ── Build tabs array: [{id, label, html}] ─────────────────
  const tabs = [];

  // Chart tabs — prefer charts[] array; fall back to chart_data for old/auto-chart payloads
  const chartsArr = Array.isArray(uiRender.charts) ? uiRender.charts.filter(Boolean) : [];
  const charts = chartsArr.length > 0 ? chartsArr
    : (uiRender.chart_data ? [uiRender.chart_data] : []);

  charts.forEach((chartData, i) => {
    const tabId = `chart-${i}`;
    const label = charts.length === 1 ? '📊 Charting' : `📊 Chart ${i + 1}`;
    const cd = typeof chartData === 'string' ? chartData : JSON.stringify(chartData);
    const escaped = cd.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    tabs.push({
      id: tabId,
      label,
      html: `
        <div class="evidence-chart-wrapper">
          <div class="evidence-chart" data-chart="${escaped}"></div>
          <button class="chart-expand-btn"
                  onclick="_openChartFullscreen(this.previousElementSibling.dataset.chart)">
            ⛶ 全螢幕查看
          </button>
        </div>`,
    });
  });

  // Summary Data tab — processed dataset
  const summaryRows = Array.isArray(mcpOutput.dataset) ? mcpOutput.dataset.slice(0, 20) : [];
  if (summaryRows.length > 0 && mcpOutput._is_processed !== false) {
    tabs.push({ id: 'summary', label: '📋 Summary Data', html: _buildTableHtml(summaryRows) });
  }

  // Raw Data tab — original DS API response
  const rawRows = Array.isArray(mcpOutput._raw_dataset) ? mcpOutput._raw_dataset.slice(0, 20) : [];
  if (rawRows.length > 0) {
    tabs.push({ id: 'raw', label: '📄 Raw Data', html: _buildTableHtml(rawRows) });
  }

  if (tabs.length === 0) return paramsHtml;

  // Single tab — show as titled section without tab bar
  if (tabs.length === 1) {
    return `${paramsHtml}
      <div class="evidence-chart-section">
        <div class="evidence-chart-title">${tabs[0].label}</div>
        ${tabs[0].html}
      </div>`;
  }

  // Multiple tabs — render tab bar
  const firstTab = tabs[0].id;
  const tabBtns  = tabs.map((t, i) => `
    <button id="ev-btn-${t.id}-${uid}" class="evidence-tab-btn${i === 0 ? ' active' : ''}"
            onclick="_switchEvidenceTab('${uid}', '${t.id}')">${t.label}</button>`).join('');
  const tabPanels = tabs.map((t, i) => `
    <div id="ev-panel-${t.id}-${uid}" class="evidence-tab-panel${i !== 0 ? ' hidden' : ''}">
      ${t.html}
    </div>`).join('');

  return `${paramsHtml}
    <div id="ev-section-${uid}" class="evidence-chart-section">
      <div class="evidence-tab-bar">${tabBtns}</div>
      ${tabPanels}
    </div>`;
}

/** Build an HTML table from an array of row objects. */
function _buildTableHtml(rows) {
  if (!rows || !rows.length) return '';
  const cols      = Object.keys(rows[0]);
  const headerRow = cols.map(c => `<th>${_escapeHtml(String(c))}</th>`).join('');
  const bodyRows  = rows.map(r =>
    `<tr>${cols.map(c => `<td>${_escapeHtml(String(r[c] ?? ''))}</td>`).join('')}</tr>`
  ).join('');
  return `
    <div style="overflow-x:auto">
      <table class="evidence-table">
        <thead><tr>${headerRow}</tr></thead>
        <tbody>${bodyRows}</tbody>
      </table>
    </div>`;
}

// ══════════════════════════════════════════════════════════════
// Auth helpers
// ══════════════════════════════════════════════════════════════

/** Returns true if JWT token is missing, malformed, or past its exp claim. */
function _isTokenExpired(token) {
  if (!token) return true;
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return !payload.exp || payload.exp < Math.floor(Date.now() / 1000);
  } catch(_) {
    return true; // malformed token → treat as expired
  }
}

/** Clear all in-memory conversation histories and DOM chat containers on login. */
function _clearConversationHistory() {
  _copilotHistory = [];
  _helpHistory    = [];
  _helpWelcomeShown = false;
  const chatEl = document.getElementById('chat-history');
  if (chatEl) chatEl.innerHTML = '';
  const helpEl = document.getElementById('help-chat-history');
  if (helpEl) helpEl.innerHTML = '';
}

async function loginWithCredentials() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const btn      = document.getElementById('login-btn');
  const errEl    = document.getElementById('login-error');

  if (!username || !password) {
    _showLoginError('請輸入帳號與密碼');
    return;
  }

  btn.disabled    = true;
  btn.textContent = '登入中...';
  errEl.classList.add('hidden');

  try {
    const res  = await fetch('/api/v1/auth/login', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ username, password }),
    });
    const json = await res.json();

    if (!res.ok) {
      throw new Error(json.message || `HTTP ${res.status}`);
    }

    _token = json.data?.access_token;
    if (!_token) throw new Error('回應中未包含 access_token');

    localStorage.setItem('glassbox_token', _token);
    _clearConversationHistory();
    // Reset token counter on every fresh login
    const _lb = document.getElementById('v13-token-badge');
    if (_lb) { _lb.textContent = ''; _lb.classList.add('hidden'); delete _lb._totalIn; delete _lb._totalOut; }
    _showMainApp(username);

  } catch (err) {
    _showLoginError(err.message);
  } finally {
    btn.disabled    = false;
    btn.textContent = _t('login-btn');
  }
}

function loginWithToken() {
  const t = document.getElementById('token-input').value.trim();
  if (!t) { _showLoginError('請輸入 Token'); return; }
  _token = t;
  localStorage.setItem('glassbox_token', _token);
  _clearConversationHistory();
  const _lb2 = document.getElementById('v13-token-badge');
  if (_lb2) { _lb2.textContent = ''; _lb2.classList.add('hidden'); delete _lb2._totalIn; delete _lb2._totalOut; }
  _showMainApp('Token User');
}

function logout() {
  localStorage.removeItem('glassbox_token');
  _token = null;
  document.getElementById('main-app').classList.add('hidden');
  document.getElementById('login-screen').classList.remove('hidden');
  // Clear the password field for security
  document.getElementById('login-password').value = '';
}

function _showLoginError(msg) {
  const el = document.getElementById('login-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}

function _showMainApp(username) {
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('main-app').classList.remove('hidden');
  const badge = document.getElementById('user-badge');
  if (username) {
    badge.textContent = `👤 ${username}`;
    badge.classList.remove('hidden');
  }
  _applyI18n();

  // default to Diagnose (診斷站) — guard for script load order
  if (typeof switchView === 'function') switchView('diagnose');

  // Default to v13 Agent mode — set button highlight
  _setChatMode('v13');

  // Phase 10: init mobile layout + swipe after DOM is visible
  _initMobileLayout();
  _initSwipeGesture();

  // Keep layout correct when user rotates device or resizes window
  window.addEventListener('resize', _initMobileLayout, { passive: true });
}

// ══════════════════════════════════════════════════════════════
// Tab management
// ══════════════════════════════════════════════════════════════

function switchTab(name) {
  // Try workspace tab first (Phase 9.1)
  if (_workspaceTabs[name]) { _activateWorkspaceTab(name); return; }

  // Fallback: legacy element-based switching (for _createToolTab / old SSE flow)
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active-tab'));
  document.querySelectorAll('.tab-panel').forEach(el => el.classList.add('hidden'));
  const tabEl   = document.getElementById(`tab-btn-${name}`);
  const panelEl = document.getElementById(`panel-${name}`);
  if (tabEl)   tabEl.classList.add('active-tab');
  if (panelEl) panelEl.classList.remove('hidden');
}

function _createToolTab(toolName) {
  if (_toolTabs[toolName]) return; // already exists

  // Show report panel on first tool call
  _showReportPanel();

  const tabBar     = document.getElementById('tab-bar');
  const contentDiv = document.getElementById('tab-content');

  // ── Tab button ──
  const tab = document.createElement('button');
  tab.id        = `tab-btn-${toolName}`;
  tab.className = 'tab-btn whitespace-nowrap';
  tab.onclick   = () => switchTab(toolName);

  const shortName = toolName.replace('mcp_', '').replace(/_/g, ' ');
  tab.innerHTML = `
    <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path stroke-linecap="round" stroke-linejoin="round"
        d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066
           c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35
           a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065
           c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37
           a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573
           c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
    <span>${shortName}</span>
    <span class="tab-spinner"></span>
  `;
  tabBar.appendChild(tab);

  // ── Panel ──
  const panel = document.createElement('div');
  panel.id        = `panel-${toolName}`;
  panel.className = 'tab-panel hidden';
  contentDiv.appendChild(panel);

  _toolTabs[toolName] = { tab, panel };

  // Auto-switch to new tool tab
  switchTab(toolName);
}

function _markTabDone(toolName, isError) {
  const { tab } = _toolTabs[toolName] || {};
  if (!tab) return;

  const spinnerEl = tab.querySelector('.tab-spinner');
  if (!spinnerEl) return;

  spinnerEl.className = `tab-done ${isError ? 'text-red-400' : 'text-green-400'}`;
  spinnerEl.textContent = isError ? '✗' : '✓';
}

// ══════════════════════════════════════════════════════════════
// SSE Parsing  (Fetch-based — supports Authorization header)
// ══════════════════════════════════════════════════════════════

function _parseSSEChunk(text) {
  let eventType = null;
  let dataStr   = null;

  for (const line of text.split('\n')) {
    if (line.startsWith('event: '))      eventType = line.slice(7).trim();
    else if (line.startsWith('data: ')) dataStr   = line.slice(6).trim();
  }

  if (!eventType || !dataStr) return null;

  try {
    return { type: eventType, data: JSON.parse(dataStr) };
  } catch {
    return null;
  }
}

// ══════════════════════════════════════════════════════════════
// SSE Event Handlers
// ══════════════════════════════════════════════════════════════

function _handleSSEEvent({ type, data }) {
  switch (type) {

    case 'session_start':
      _addChatBubble('agent', '🔍 診斷開始，正在分析症狀...');
      break;

    case 'tool_call':
      _createToolTab(data.tool_name);
      _renderToolCallInput(data.tool_name, data.tool_input);
      _addChatBubble('tool',
        `<svg class="w-3.5 h-3.5 inline mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path stroke-linecap="round" d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4"/></svg>呼叫工具：<code>${data.tool_name}</code>`);
      break;

    case 'tool_result':
      _renderToolResult(data.tool_name, data.tool_result, data.is_error);
      _markTabDone(data.tool_name, data.is_error);
      break;

    case 'report':
      _renderSummaryReport(data.content, data.total_turns, data.tools_invoked);
      _showReportPanel();
      _addChatBubble('agent', '📋 診斷報告已生成，請查看右側「總結報告」頁籤。');
      break;

    case 'error':
      _addChatBubble('error', `❌ 診斷錯誤：${data.message || '未知錯誤'}`);
      break;

    case 'done':
      _addChatBubble('agent', '✅ 診斷完成。');
      _setStatus('ready');
      break;
  }
}

// ── Render tool call input (in tab panel) ──────────────────────
function _renderToolCallInput(toolName, toolInput) {
  const { panel } = _toolTabs[toolName] || {};
  if (!panel) return;

  panel.innerHTML = `
    <div class="tool-card">
      <div class="tool-title">
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="3"/>
          <path stroke-linecap="round" d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83"/>
        </svg>
        <span>${toolName}</span>
      </div>
      <div class="section-label">輸入參數</div>
      <pre class="code-block">${_escapeHtml(JSON.stringify(toolInput, null, 2))}</pre>
      <div class="section-label">執行中</div>
      <div class="loading-bar"><div class="loading-bar-inner"></div></div>
    </div>
  `;
}

// ── Render tool result (appended into existing tab panel) ──────
function _renderToolResult(toolName, result, isError) {
  const { panel } = _toolTabs[toolName] || {};
  if (!panel) return;

  // Remove loading bar
  panel.querySelector('.loading-bar')?.remove();
  const toolCard = panel.querySelector('.tool-card');
  if (!toolCard) return;

  const labelClass = isError ? 'text-red-400' : 'text-green-400';
  const labelText  = isError ? '❌ 執行失敗' : '✅ 執行結果';

  const resultDiv = document.createElement('div');
  resultDiv.innerHTML = `
    <div class="section-label ${labelClass}">${labelText}</div>
    ${_renderResultContent(toolName, result)}
  `;
  toolCard.appendChild(resultDiv);
}

// ── Smart result rendering (Event Object vs generic JSON) ──────
function _renderResultContent(toolName, result) {
  if (toolName === 'mcp_event_triage' && result?.event_type) {
    return _renderEventObject(result);
  }
  return `<pre class="code-block">${_escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
}

function _renderEventObject(obj) {
  const urgency   = obj.attributes?.urgency || 'low';
  const symptom   = _escapeHtml(obj.attributes?.symptom || '');
  const skills    = (obj.recommended_skills || [])
    .map(s => `<span class="skill-tag">${_escapeHtml(s)}</span>`)
    .join('');

  return `
    <div class="event-object">
      <div class="event-header">
        <span class="event-id">${_escapeHtml(obj.event_id || '')}</span>
        <span class="event-type-badge">${_escapeHtml(obj.event_type || '')}</span>
      </div>
      <div class="event-body">
        <div class="event-field">
          <span class="field-label">症狀</span>
          <span class="field-value">${symptom}</span>
        </div>
        <div class="event-field">
          <span class="field-label">緊急程度</span>
          <span class="urgency-badge urgency-${urgency}">${urgency}</span>
        </div>
        <div class="event-field">
          <span class="field-label">建議技能</span>
          <div class="skills-list">${skills}</div>
        </div>
      </div>
    </div>
  `;
}

// ── Render markdown summary into report panel ────────────────────
function _renderSummaryReport(content, totalTurns, toolsInvoked) {
  document.getElementById('summary-placeholder').classList.add('hidden');

  const summaryContent = document.getElementById('summary-content');
  summaryContent.classList.remove('hidden');
  summaryContent.innerHTML = marked.parse(content || '');

  const meta = document.createElement('div');
  meta.className = 'report-meta';
  meta.innerHTML = `
    <span>🔄 ${totalTurns || 0} 輪對話</span>
    <span>🛠 ${(toolsInvoked || []).length} 個工具</span>
  `;
  summaryContent.appendChild(meta);

  switchTab('summary');
}

// ══════════════════════════════════════════════════════════════
// Chat helpers
// ══════════════════════════════════════════════════════════════

function _addChatBubble(type, html, bubbleId) {
  const container = document.getElementById('chat-history');

  const wrapper = document.createElement('div');
  wrapper.className = type === 'user' ? 'flex justify-end' : 'flex justify-start';

  const bubble = document.createElement('div');

  switch (type) {
    case 'user':        bubble.className = 'chat-bubble chat-user';  break;
    case 'agent':       bubble.className = 'chat-bubble chat-agent'; break;
    case 'tool':        bubble.className = 'chat-tool';              break;
    case 'error':       bubble.className = 'chat-error';             break;
    case 'event-alert': bubble.className = 'chat-event-alert';       break;
    default:            bubble.className = 'chat-bubble chat-agent'; break;
  }

  if (bubbleId) bubble.id = bubbleId;
  bubble.innerHTML = html;
  wrapper.appendChild(bubble);
  container.appendChild(wrapper);
  container.scrollTop = container.scrollHeight;
}

function _addChatDivider(text) {
  const container = document.getElementById('chat-history');
  const el = document.createElement('div');
  el.className   = 'chat-divider';
  el.textContent = text;
  container.appendChild(el);
}

// ══════════════════════════════════════════════════════════════
// Main diagnosis flow
// ══════════════════════════════════════════════════════════════

async function sendDiagnosis() {
  if (_isStreaming) return;

  const input  = document.getElementById('issue-input');
  const issue  = input.value.trim();

  if (!issue) return;
  if (issue.length < 5) {
    _addChatBubble('error', '⚠️ 問題描述至少需要 5 個字元');
    return;
  }

  input.value     = '';
  _isStreaming    = true;
  _setInputLocked(true);
  _setStatus('streaming');

  _resetSession();
  _addChatBubble('user', _escapeHtml(issue));

  try {
    const response = await fetch('/api/v1/diagnose/', {
      method:  'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${_token}`,
      },
      body: JSON.stringify({ issue_description: issue }),
    });

    // Handle non-stream errors
    if (response.status === 401) {
      logout();
      return;
    }
    if (!response.ok) {
      let msg = `HTTP ${response.status}`;
      try {
        const err = await response.json();
        msg = err.message || msg;
      } catch { /* ignore */ }
      _addChatBubble('error', `❌ 請求失敗：${msg}`);
      return;
    }

    // ── Read SSE stream ──
    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split on the SSE double-newline separator
      const parts = buffer.split('\n\n');
      buffer = parts.pop();  // keep potentially incomplete last chunk

      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;
        const event = _parseSSEChunk(trimmed);
        if (event) _handleSSEEvent(event);
      }
    }

    // Flush any remaining buffer
    if (buffer.trim()) {
      const event = _parseSSEChunk(buffer.trim());
      if (event) _handleSSEEvent(event);
    }

  } catch (err) {
    _addChatBubble('error', `❌ 連線錯誤：${err.message}`);
    _setStatus('ready');
  } finally {
    _isStreaming = false;
    _setInputLocked(false);
  }
}

// ══════════════════════════════════════════════════════════════
// Multi-Tab Workspace management (right 70% panel)
// ══════════════════════════════════════════════════════════════

/**
 * Create a new workspace tab + panel and auto-activate it.
 * tabId     : unique string key (e.g. 'evt-current', 'mcp-1715000000')
 * title     : HTML-safe display string for the tab label
 * contentHtml : inner HTML for the panel (already escaped where needed)
 * Returns { btn, panel }.
 */
/**
 * Split-screen workspace tab manager.
 * Tabs live inside #ws-data-pane (left 70%).  Each result gets a slim tab button in
 * #ws-data-tab-bar and a panel stored in _workspaceTabs.  Only one panel is shown at
 * a time inside #ws-data-content.  The tab bar is hidden when there is ≤1 result.
 */
function _createWorkspaceTab(tabId, title, contentHtml) {
  document.getElementById('workspace-placeholder')?.classList.add('hidden');

  const tabBar = document.getElementById('ws-data-tab-bar');
  const content = document.getElementById('ws-data-content');
  if (!content) return { btn: null, panel: null };

  // ── Tab button ────────────────────────────────────────────────
  const btn = document.createElement('button');
  btn.id        = `ws-tab-btn-${tabId}`;
  btn.className = 'ws-inner-tab whitespace-nowrap text-xs px-3 py-1 rounded-md border border-transparent text-slate-500 hover:text-slate-700 transition-colors';
  btn.innerHTML =
    `<span>${title}</span>` +
    `<span class="ml-1.5 text-slate-400 hover:text-red-400 cursor-pointer"
          onclick="_closeWorkspaceTab('${tabId.replace(/'/g,"\\'")}');event.stopPropagation()">×</span>`;
  btn.onclick = () => _activateWorkspaceTab(tabId);
  tabBar?.appendChild(btn);

  // ── Panel (hidden by default, appended to content area) ───────
  const panel = document.createElement('div');
  panel.id        = `ws-panel-${tabId}`;
  panel.className = 'hidden h-full';
  panel.innerHTML = contentHtml;
  content.appendChild(panel);

  _workspaceTabs[tabId] = { btn, panel };
  _activateWorkspaceTab(tabId);

  // Show tab bar only when there are multiple results
  if (tabBar) tabBar.classList.toggle('hidden', Object.keys(_workspaceTabs).length < 2);
  if (_isMobile()) _switchMobileView('workspace');

  return { btn, panel };
}

/** Activate a workspace tab. */
function _activateWorkspaceTab(tabId) {
  Object.values(_workspaceTabs).forEach(({ btn, panel }) => {
    btn?.classList.remove('active-ws-tab');
    panel?.classList.add('hidden');
  });
  const entry = _workspaceTabs[tabId];
  if (!entry) return;
  entry.btn?.classList.add('active-ws-tab');
  entry.panel?.classList.remove('hidden');
  _activeTabId = tabId;
  // Resize Plotly charts that became visible (Plotly doesn't auto-resize on un-hide)
  requestAnimationFrame(() => {
    entry.panel?.querySelectorAll('.evidence-chart[data-chart]').forEach(div => {
      if (window.Plotly && div._fullLayout) Plotly.Plots.resize(div);
    });
  });
}

/** Close a workspace tab. */
function _closeWorkspaceTab(tabId) {
  const entry = _workspaceTabs[tabId];
  if (!entry) return;
  const wasActive = _activeTabId === tabId;
  entry.btn?.remove();
  entry.panel?.remove();
  delete _workspaceTabs[tabId];

  const remaining = Object.keys(_workspaceTabs);
  const tabBar = document.getElementById('ws-data-tab-bar');
  if (remaining.length === 0) {
    _activeTabId = null;
    document.getElementById('workspace-placeholder')?.classList.remove('hidden');
    tabBar?.classList.add('hidden');
  } else {
    if (tabBar) tabBar.classList.toggle('hidden', remaining.length < 2);
    if (wasActive) _activateWorkspaceTab(remaining[remaining.length - 1]);
  }
}

// ══════════════════════════════════════════════════════════════
// Session reset (before each new diagnosis)
// ══════════════════════════════════════════════════════════════

function _resetSession() {
  // Clear all workspace tabs
  Object.keys(_workspaceTabs).forEach(id => {
    _workspaceTabs[id].btn.remove();
    _workspaceTabs[id].panel.remove();
  });
  _workspaceTabs = {};
  _activeTabId   = null;
  _toolTabs      = {};

  // Clear tab bar
  const tabBar = document.getElementById('ws-data-tab-bar');
  if (tabBar) { tabBar.innerHTML = ''; tabBar.classList.add('hidden'); }

  // Reset data pane to placeholder
  const dataPaneContent = document.getElementById('ws-data-content');
  if (dataPaneContent) {
    dataPaneContent.innerHTML = `
      <div id="workspace-placeholder"
        class="flex flex-col items-center justify-center h-full text-slate-400 py-16">
        <svg class="w-14 h-14 mb-4 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1"
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586
               a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
        </svg>
        <p class="text-sm">診斷完成後，AI 報告將呈現在此</p>
      </div>`;
  }
  // Reset analysis pane to placeholder
  const analysisPaneContent = document.getElementById('ws-analysis-content');
  if (analysisPaneContent) {
    analysisPaneContent.innerHTML = `
      <div id="ws-analysis-placeholder"
        class="flex flex-col items-center justify-center h-full text-slate-400 py-16 px-4 text-center">
        <svg class="w-10 h-10 mb-3 opacity-25" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1"
            d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3
               m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547
               A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531
               c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
        </svg>
        <p class="text-xs text-slate-400">AI 深度分析將顯示於此</p>
      </div>`;
  }

  // Reset copilot slot state (keep history for context continuity)
  _slotContext  = {};
  _slotToolId   = null;
  _slotToolType = null;
  _clearSlashTool();

  // Phase 10: reset mobile view to chat panel for new diagnosis
  if (_isMobile()) _switchMobileView('chat');

  // Hide report panel for new diagnosis
  _hideReportPanel();

  // Add visual separator in chat
  _addChatDivider('── 新診斷開始 ──');
}

// ══════════════════════════════════════════════════════════════
// Phase 10 — Mobile Responsive Helpers
// ══════════════════════════════════════════════════════════════

function _isMobile() {
  return window.innerWidth <= 768;
}

/**
 * Switch mobile view between 'chat' and 'workspace'.
 * On desktop this is a no-op (panels are always both visible).
 */
function _switchMobileView(view) {
  _mobileView = view;
  const panels = document.getElementById('diagnose-panels');
  const chatBtn = document.getElementById('mobile-chat-btn');
  const wsBtn   = document.getElementById('mobile-ws-btn');
  if (!panels) return;

  panels.classList.toggle('mobile-chat',      view === 'chat');
  panels.classList.toggle('mobile-workspace', view === 'workspace');

  if (chatBtn) {
    chatBtn.classList.toggle('mobile-toggle-active', view === 'chat');
    chatBtn.classList.remove(view === 'chat' ? 'text-slate-600' : 'text-indigo-700');
  }
  if (wsBtn) {
    wsBtn.classList.toggle('mobile-toggle-active', view === 'workspace');
    wsBtn.classList.remove(view === 'workspace' ? 'text-slate-600' : 'text-indigo-700');
  }
}

/**
 * Initialise mobile layout on app boot and on window resize.
 * Sets the initial CSS state so panels are correctly positioned.
 */
function _initMobileLayout() {
  const panels = document.getElementById('diagnose-panels');
  if (!panels) return;
  if (_isMobile()) {
    // Default: show chat panel
    panels.classList.add('mobile-chat');
    panels.classList.remove('mobile-workspace');
  } else {
    // Desktop: remove mobile state classes entirely
    panels.classList.remove('mobile-chat', 'mobile-workspace');
  }
}

/**
 * Attach swipe gesture listeners to #diagnose-panels.
 * Swipe left  → switch to workspace
 * Swipe right → switch to chat
 */
function _initSwipeGesture() {
  const el = document.getElementById('diagnose-panels');
  if (!el) return;

  let startX = 0;
  let startY = 0;

  el.addEventListener('touchstart', (e) => {
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
  }, { passive: true });

  el.addEventListener('touchend', (e) => {
    if (!_isMobile()) return;
    const dx = e.changedTouches[0].clientX - startX;
    const dy = e.changedTouches[0].clientY - startY;
    // Only count horizontal swipes (dx must be dominant + min 50px)
    if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    if (dx < 0 && _mobileView === 'chat')      _switchMobileView('workspace'); // left
    if (dx > 0 && _mobileView === 'workspace') _switchMobileView('chat');      // right
  }, { passive: true });
}

// ══════════════════════════════════════════════════════════════
// UI helpers
// ══════════════════════════════════════════════════════════════

function _setInputLocked(locked) {
  const btn   = document.getElementById('send-btn');
  const input = document.getElementById('issue-input');
  btn.disabled   = locked;
  input.disabled = locked;
}

function _setStatus(state) {
  const label = document.querySelector('#status-indicator');

  if (state === 'streaming') {
    if (label) label.innerHTML = `<span class="w-1.5 h-1.5 rounded-full inline-block" style="background:#f59e0b;animation:pulse-dot 1s ease-in-out infinite"></span> <span class="text-amber-400">診斷中...</span>`;
  } else {
    if (label) label.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-green-400 inline-block"></span> <span>Ready</span>`;
  }
}

function handleInputKey(event) {
  if (event.ctrlKey && event.key === 'Enter') {
    event.preventDefault();
    _sendCopilotMessage();
  }
  // Close slash menu on Escape
  if (event.key === 'Escape') {
    _hideSlashMenu();
  }
}

// ── Agent Console (bottom-right of Diagnose page) ────────────────────────────
let _diagConsoleOpen      = false;
let _diagConsoleDotTimer  = null;

function _diagConsoleExpand() {
  const el = document.getElementById('diag-console');
  if (!el) return;
  el.style.height = '218px';   // header(34) + lines(184)
  _diagConsoleOpen = true;
  const ch = document.getElementById('diag-console-chevron');
  if (ch) ch.style.transform = 'rotate(180deg)';
}

function _diagConsoleCollapse() {
  const el = document.getElementById('diag-console');
  if (!el) return;
  el.style.height = '34px';    // just the header visible
  _diagConsoleOpen = false;
  const ch = document.getElementById('diag-console-chevron');
  if (ch) ch.style.transform = '';
}

function _diagConsoleToggle() {
  if (_diagConsoleOpen) _diagConsoleCollapse();
  else _diagConsoleExpand();
}

function _diagConsoleClear() {
  const lines = document.getElementById('diag-console-lines');
  if (lines) lines.innerHTML = '';
}

function _diagLogLine(icon, text, color = '#94a3b8') {
  const lines = document.getElementById('diag-console-lines');
  if (!lines) return;
  if (!_diagConsoleOpen) _diagConsoleExpand();
  const ts = new Date().toLocaleTimeString('zh-TW', { hour12: false });
  const row = document.createElement('div');
  row.className = 'flex items-start gap-2 py-0.5';
  row.innerHTML = `<span style="color:#475569;flex-shrink:0;">${ts}</span>`
                + `<span style="color:${color};">${icon} ${_escapeHtml(String(text))}</span>`;
  lines.appendChild(row);
  lines.scrollTop = lines.scrollHeight;
  // Pulse dot
  const dot = document.getElementById('diag-console-dot');
  if (dot) {
    dot.classList.remove('hidden');
    clearTimeout(_diagConsoleDotTimer);
    _diagConsoleDotTimer = setTimeout(() => dot.classList.add('hidden'), 2000);
  }
}

function _escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ══════════════════════════════════════════════════════════════
// v12 — Agent Draft: open editor with pre-filled draft data

async function _openDraftEditor(draftId, draftType, tabId) {
  if (!draftId) return;
  try {
    const resp = await fetch(`/api/v1/agent/draft/${draftId}`, {
      headers: { 'Authorization': `Bearer ${_token}` }
    });
    if (!resp.ok) { alert('無法取得草稿資料'); return; }
    const json = await resp.json();
    const payload = Object.assign({}, json.data?.payload || json.payload || {});
    payload._draft_id = draftId;

    // Close the draft workspace tab now that we're opening the editor
    if (tabId && typeof _closeWorkspaceTab === 'function') _closeWorkspaceTab(tabId);

    // Remember current view so "← 返回" can go back to chat
    window._draftReturnView = 'diagnose';

    if (draftType === 'skill') {
      if (typeof switchView === 'function') switchView('skill-builder');
      setTimeout(() => {
        if (typeof _skOpenEditor === 'function') _skOpenEditor(null, payload);
        document.getElementById('sk-back-btn') && (document.getElementById('sk-back-btn').textContent = '← 返回對話');
      }, 200);
    } else if (draftType === 'mcp') {
      if (typeof switchView === 'function') switchView('mcp-builder');
      // Wait for _loadMcpDefs() to complete (it loads _dataSubjects needed for dropdown)
      // Poll until _dataSubjects is populated or timeout after 3s
      const waitForDs = () => new Promise(resolve => {
        let attempts = 0;
        const check = () => {
          if ((typeof _dataSubjects !== 'undefined' && _dataSubjects.length > 0) || attempts >= 15) { resolve(); return; }
          attempts++;
          setTimeout(check, 200);
        };
        check();
      });
      await waitForDs();
      if (typeof _mcpOpenEditor === 'function') _mcpOpenEditor(null, payload);
      document.getElementById('mcp-back-btn') && (document.getElementById('mcp-back-btn').textContent = '← 返回對話');
    } else if (draftType === 'routine_check') {
      if (typeof switchView === 'function') switchView('nested-builder');
      setTimeout(async () => {
        if (typeof _nbPreFillFromDraft === 'function') await _nbPreFillFromDraft(payload);
      }, 300);
    } else if (draftType === 'event_skill_link') {
      if (typeof switchView === 'function') switchView('event-link-builder');
      setTimeout(async () => {
        if (typeof _elPreFillFromDraft === 'function') await _elPreFillFromDraft(payload, draftId, draftType);
      }, 400);
    } else {
      if (typeof switchView === 'function') switchView('nested-builder');
    }
  } catch (e) {
    console.error('_openDraftEditor error:', e);
    alert('開啟草稿失敗：' + e.message);
  }
}

// ══════════════════════════════════════════════════════════════
// Phase 9 — Copilot: Slash Menu, Slot Filling, Direct Invocation
// ══════════════════════════════════════════════════════════════

/** Called on every keystroke in the chat textarea. */
function handleInputChange(event) {
  const val = event.target.value;
  if (val === '/') {
    _showSlashMenu();
  } else if (!val.startsWith('/')) {
    _hideSlashMenu();
  }
}

/** Fetch tools from API and render slash popup above the textarea. */
async function _showSlashMenu() {
  _hideSlashMenu();
  _slashMenuVisible = true;

  const anchor = document.getElementById('slash-menu-anchor');
  if (!anchor) return;

  anchor.innerHTML = '<div class="slash-menu"><div class="p-3 text-xs text-slate-400">載入工具清單...</div></div>';

  if (!_slashMenuItems) {
    try {
      const [mcpRes, skillRes] = await Promise.all([
        fetch('/api/v1/mcp-definitions',   { headers: { Authorization: `Bearer ${_token}` } }),
        fetch('/api/v1/skill-definitions', { headers: { Authorization: `Bearer ${_token}` } }),
      ]);
      const mcpJson   = await mcpRes.json();
      const skillJson = await skillRes.json();
      _slashMenuItems = {
        mcps:   mcpJson.data   || [],
        skills: skillJson.data || [],
      };
    } catch {
      if (anchor) anchor.innerHTML = '<div class="slash-menu"><div class="p-3 text-xs text-red-400">工具清單載入失敗</div></div>';
      return;
    }
  }

  if (!_slashMenuVisible) return;  // user navigated away while loading

  const { mcps, skills } = _slashMenuItems;
  let html = '<div class="slash-menu">';

  if (mcps.length) {
    html += '<div class="slash-menu-section">🔍 MCP 資料查詢工具</div>';
    for (const m of mcps) {
      const desc = (m.processing_intent || m.name || '').slice(0, 80);
      // Use data-* attributes to avoid double-quote conflicts in onclick=""
      html += `<div class="slash-menu-item"
        data-tool-id="${m.id}" data-tool-type="mcp" data-tool-name="${_escapeHtml(m.name)}"
        onclick="_selectSlashTool(parseInt(this.dataset.toolId),this.dataset.toolType,this.dataset.toolName)">
        <span class="slash-menu-badge slash-mcp-badge">MCP</span>
        <div class="slash-menu-item-content">
          <div class="slash-menu-item-name">${_escapeHtml(m.name)}</div>
          <div class="slash-menu-item-desc">${_escapeHtml(desc)}</div>
        </div>
      </div>`;
    }
  }

  if (skills.length) {
    html += '<div class="slash-menu-section">🧠 Skill 智能診斷技能</div>';
    for (const s of skills) {
      const desc = (s.description || s.name || '').slice(0, 80);
      html += `<div class="slash-menu-item"
        data-tool-id="${s.id}" data-tool-type="skill" data-tool-name="${_escapeHtml(s.name)}"
        onclick="_selectSlashTool(parseInt(this.dataset.toolId),this.dataset.toolType,this.dataset.toolName)">
        <span class="slash-menu-badge slash-skill-badge">Skill</span>
        <div class="slash-menu-item-content">
          <div class="slash-menu-item-name">${_escapeHtml(s.name)}</div>
          <div class="slash-menu-item-desc">${_escapeHtml(desc)}</div>
        </div>
      </div>`;
    }
  }

  html += '</div>';
  if (anchor) anchor.innerHTML = html;
}

function _hideSlashMenu() {
  _slashMenuVisible = false;
  const anchor = document.getElementById('slash-menu-anchor');
  if (anchor) anchor.innerHTML = '';
}

/** Called when user clicks a tool in the slash menu. */
function _selectSlashTool(toolId, toolType, toolName) {
  _hideSlashMenu();
  _slotToolId   = toolId;
  _slotToolType = toolType;
  _slotContext  = {};  // reset params for new tool

  // Show "tool selected" tag above the input
  const wrap = document.getElementById('copilot-tool-tag-wrap');
  if (wrap) {
    const badgeCls = toolType === 'mcp' ? 'slash-mcp-badge' : 'slash-skill-badge';
    const label    = toolType === 'mcp' ? '🔍 MCP' : '🧠 Skill';
    wrap.innerHTML = `<div class="copilot-tool-tag">
      <span class="slash-menu-badge ${badgeCls}">${label}</span>
      <span>${_escapeHtml(toolName)}</span>
      <span class="remove-tag" onclick="_clearSlashTool()" title="取消選擇">×</span>
    </div>`;
    wrap.classList.remove('hidden');
  }

  // Pre-fill textarea with the tool's full intent/description as a ready-to-send prompt
  const input = document.getElementById('issue-input');
  if (input) {
    let prompt = '';
    if (toolType === 'mcp') {
      const m = (_slashMenuItems?.mcps || []).find(x => x.id === toolId);
      prompt = m?.processing_intent || m?.description || toolName;
    } else {
      const s = (_slashMenuItems?.skills || []).find(x => x.id === toolId);
      prompt = s?.description || toolName;
    }
    input.value = prompt || '';
    input.focus();
    // Place cursor at end so user can append to the prompt
    input.setSelectionRange(input.value.length, input.value.length);
  }
}

function _clearSlashTool() {
  _slotToolId   = null;
  _slotToolType = null;
  _slotContext  = {};
  const wrap = document.getElementById('copilot-tool-tag-wrap');
  if (wrap) { wrap.innerHTML = ''; wrap.classList.add('hidden'); }
}

/** Primary send handler — v12 Copilot or v13 Agent depending on _v13Mode. */
async function _sendCopilotMessage() {
  if (_v13Mode) { await _sendAgentV13Message(); return; }
  if (_isStreaming) return;

  const input   = document.getElementById('issue-input');
  const message = input.value.trim();
  if (!message) return;

  input.value  = '';
  _isStreaming = true;
  _setInputLocked(true);
  _setStatus('streaming');
  _hideSlashMenu();

  _addChatBubble('user', _escapeHtml(message));
  _copilotHistory.push({ role: 'user', content: message });
  _diagLogLine('→', message.length > 60 ? message.slice(0, 60) + '…' : message, '#cbd5e1');

  // Build slot context: include pre-selected tool hint
  const slotCtx = { ..._slotContext };
  if (_slotToolId) {
    slotCtx._selected_tool_id   = _slotToolId;
    slotCtx._selected_tool_type = _slotToolType;
  }

  const body = {
    message,
    slot_context: slotCtx,
    history: _copilotHistory.slice(-12),
  };

  try {
    const response = await fetch('/api/v1/diagnose/copilot-chat', {
      method:  'POST',
      headers: {
        'Content-Type':  'application/json',
        'Authorization': `Bearer ${_token}`,
      },
      body: JSON.stringify(body),
    });

    if (response.status === 401) { logout(); return; }
    if (!response.ok) {
      let msg = `HTTP ${response.status}`;
      try { const err = await response.json(); msg = err.message || msg; } catch { /* */ }
      _addChatBubble('error', `❌ 請求失敗：${msg}`);
      return;
    }

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = '';
    let   lastMsg = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      const parts = buf.split('\n\n');
      buf = parts.pop();

      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;
        const ev = _parseCopilotChunk(trimmed);
        if (ev) { const m = _handleCopilotEvent(ev); if (m) lastMsg = m; }
      }
    }
    if (buf.trim()) {
      const ev = _parseCopilotChunk(buf.trim());
      if (ev) _handleCopilotEvent(ev);
    }

    if (lastMsg) _copilotHistory.push({ role: 'assistant', content: lastMsg });

  } catch (err) {
    _addChatBubble('error', `❌ 連線錯誤：${err.message}`);
    _setStatus('ready');
  } finally {
    _isStreaming = false;
    _setInputLocked(false);
  }
}

/** Parse a raw SSE chunk into a JSON object (type is embedded in the JSON). */
function _parseCopilotChunk(text) {
  let dataStr = null;
  for (const line of text.split('\n')) {
    if (line.startsWith('data: ')) dataStr = line.slice(6).trim();
  }
  if (!dataStr) return null;
  try { return JSON.parse(dataStr); } catch { return null; }
}

/** Dispatch copilot SSE event. Returns the agent's text message (for history). */
function _handleCopilotEvent(ev) {
  if (!ev || !ev.type) return null;

  switch (ev.type) {

    case 'thinking': {
      // Show subtle status bubble — replace previous thinking bubble
      const prev = document.getElementById('copilot-thinking-bubble');
      if (prev) prev.closest('.flex')?.remove();
      _addChatBubble(
        'tool',
        `<span style="color:#94a3b8;font-size:12px;">${_escapeHtml(ev.message || '')}</span>`,
        'copilot-thinking-bubble',
      );
      _diagLogLine('🤔', ev.message || 'Agent 思考中…', '#64748b');
      return null;
    }

    case 'chat': {
      document.getElementById('copilot-thinking-bubble')?.closest('.flex')?.remove();
      _addChatBubble('agent', _escapeHtml(ev.message || ''));
      return ev.message;
    }

    case 'question': {
      // Slot filling — persist slot state for the next user turn
      document.getElementById('copilot-thinking-bubble')?.closest('.flex')?.remove();
      _slotContext  = ev.slot_context || {};
      _slotToolId   = ev.tool_id   != null ? ev.tool_id   : _slotToolId;
      _slotToolType = ev.tool_type || _slotToolType;

      const qWrap = document.createElement('div');
      qWrap.className = 'flex justify-start';
      const qBubble = document.createElement('div');
      qBubble.className = 'chat-copilot-question';
      qBubble.innerHTML = `<span style="font-size:11px;opacity:0.6;display:block;margin-bottom:3px;">💬 Copilot</span>${_escapeHtml(ev.question || '')}`;
      qWrap.appendChild(qBubble);
      document.getElementById('chat-history').appendChild(qWrap);
      document.getElementById('chat-history').scrollTop = 99999;
      return ev.question;
    }

    case 'mcp_result': {
      console.log('【1. SSE 收到原始 Payload】mcp_result', JSON.parse(JSON.stringify(ev)));
      document.getElementById('copilot-thinking-bubble')?.closest('.flex')?.remove();
      _clearSlashTool();
      _slotContext = {};
      _renderCopilotMcpPanel(ev);
      _diagLogLine('🔧', `MCP「${ev.mcp_name || ''}」查詢完成`, '#34d399');
      _addChatBubble('agent', `✅ <strong>${_escapeHtml(ev.mcp_name || '')}</strong> 查詢完成，結果已呈現於右側報告區。`);
      return `${ev.mcp_name} 查詢完成`;
    }

    case 'skill_result': {
      document.getElementById('copilot-thinking-bubble')?.closest('.flex')?.remove();
      _clearSlashTool();
      _slotContext = {};
      _renderCopilotSkillPanel(ev);
      const icon = ev.status === 'NORMAL' ? '✅' : '⚠️';
      const statusColor = ev.status === 'NORMAL' ? '#34d399' : '#fbbf24';
      _diagLogLine(icon, `Skill「${ev.skill_name || ''}」→ ${ev.status || '完成'}`, statusColor);
      _addChatBubble('agent', `${icon} <strong>${_escapeHtml(ev.skill_name || '')}</strong> 診斷完成，結果已呈現於右側報告區。`);
      return `${ev.skill_name} 診斷完成`;
    }

    case 'draft_ready': {
      document.getElementById('copilot-thinking-bubble')?.closest('.flex')?.remove();
      const draftType = ev.draft_type || 'skill';
      const draftId   = ev.draft_id || '';
      const draftMsg  = ev.message || '草稿已準備完畢！';
      _diagLogLine('📝', `草稿已建立 (${draftType}): ${draftId.slice(0,8)}…`, '#a78bfa');

      // Render clickable bubble with "開啟建構器" button
      const bubbleDiv = document.createElement('div');
      bubbleDiv.className = 'flex justify-start';
      bubbleDiv.innerHTML = `
        <div class="chat-copilot-question" style="max-width:90%;">
          <span style="font-size:11px;opacity:0.6;display:block;margin-bottom:4px;">📝 Agent 草稿</span>
          <p style="margin:0 0 8px;">${_escapeHtml(draftMsg)}</p>
          <button onclick="_openDraftEditor('${_escapeHtml(draftId)}','${_escapeHtml(draftType)}')"
            style="background:#7c3aed;color:#fff;border:none;border-radius:6px;padding:5px 12px;cursor:pointer;font-size:12px;">
            👉 點擊開啟建構器
          </button>
        </div>`;
      document.getElementById('chat-history').appendChild(bubbleDiv);
      document.getElementById('chat-history').scrollTop = 99999;
      return draftMsg;
    }

    case 'error': {
      document.getElementById('copilot-thinking-bubble')?.closest('.flex')?.remove();
      _diagLogLine('✗', ev.message || '未知錯誤', '#f87171');
      _addChatBubble('error', `❌ ${_escapeHtml(ev.message || '未知錯誤')}`);
      return null;
    }

    case 'done': {
      _diagLogLine('✓', 'Agent 完成', '#34d399');
      _setStatus('ready');
      return null;
    }
  }
  return null;
}

/**
 * Render a direct MCP query result into the right report panel
 * as a dedicated "Copilot 查詢" tab with Universal Data Viewer.
 */
function _renderCopilotMcpPanel(ev) {
  _showReportPanel();
  const tabId    = `mcp-${Date.now()}`;
  const rawName = ev.mcp_name || 'MCP 查詢';
  const shortName = rawName.length > 18 ? rawName.slice(0, 17) + '…' : rawName;
  const tabTitle = ev.tab_title || `🔍 ${shortName}`;
  const evidenceHtml = _renderMcpEvidence(ev.mcp_output);

  const contentHtml = `
    <div class="p-4">
      <div class="flex items-center gap-2 mb-3">
        <span class="inline-block px-2 py-0.5 rounded-full text-xs font-bold bg-blue-100 text-blue-700">MCP 查詢</span>
        <span class="text-sm font-semibold text-slate-800">${_escapeHtml(ev.mcp_name || '')}</span>
      </div>
      ${evidenceHtml || '<p class="text-slate-400 text-sm p-4">無資料回傳</p>'}
    </div>`;

  const { panel } = _createWorkspaceTab(tabId, tabTitle, contentHtml);
  requestAnimationFrame(() => _initChartsInCard(panel));
}

/**
 * Render a direct Skill diagnosis result into the right report panel,
 * reusing _renderSkillBlock for consistent card styling.
 */
function _renderCopilotSkillPanel(ev) {
  _showReportPanel();
  const icon     = ev.status === 'NORMAL' ? '✅' : '⚠️';
  const tabId    = `skill-${Date.now()}`;
  const tabTitle = ev.tab_title || `${icon} ${ev.skill_name || 'Skill 診斷'}`;

  const contentHtml = `<div class="p-4">${_renderSkillBlock(ev)}</div>`;

  const { panel } = _createWorkspaceTab(tabId, tabTitle, contentHtml);
  requestAnimationFrame(() => _initChartsInCard(panel));
}

/**
 * v13.3 + split-screen: Render <ai_analysis> content into the right analysis pane.
 */
function _renderAiAnalysisPanel(markdownContent) {
  _showReportPanel();
  const content = document.getElementById('ws-analysis-content');
  if (!content) return;
  const rendered = (typeof marked !== 'undefined')
    ? marked.parse(markdownContent)
    : markdownContent.replace(/\n/g, '<br>');
  document.getElementById('ws-analysis-placeholder')?.remove();
  content.innerHTML = `
    <div class="p-3 ai-analysis-body">
      ${rendered}
    </div>`;
}

/**
 * Render an Agent draft action card in the workspace panel.
 * Shows a preview of the draft payload and an "Open Editor" button.
 */
function _renderDraftActionCard(card) {
  _showReportPanel();
  const tabId = `draft-${Date.now()}`;
  const TYPE_META = {
    skill:            { icon: '⚙️', label: 'Skill 草稿' },
    mcp:              { icon: '🔗', label: 'MCP 草稿' },
    routine_check:    { icon: '🕒', label: '排程巡檢草稿' },
    event_skill_link: { icon: '🔗', label: 'Event→Skill 連結草稿' },
    schedule:         { icon: '🕒', label: '排程草稿' },
    event:            { icon: '⚡', label: '事件草稿' },
  };
  const meta      = TYPE_META[card.draft_type] || { icon: '📋', label: '草稿' };
  const icon      = meta.icon;
  const typeLabel = meta.label;

  const _fmtVal = v => {
    if (v === null || v === undefined) return '';
    if (typeof v === 'object') return JSON.stringify(v).slice(0, 120);
    return String(v).slice(0, 120);
  };
  const autoFill = card.auto_fill || {};
  const mcpParams = autoFill.mcp_input_params || null;
  const fillRows = Object.entries(autoFill)
    .filter(([k, v]) => k !== 'mcp_input_params' && v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length))
    .map(([k, v]) => `
      <div class="flex gap-2 text-xs py-1 border-b border-slate-100 last:border-0">
        <span class="font-mono text-purple-600 w-36 shrink-0">${_escapeHtml(k)}</span>
        <span class="text-slate-700 truncate">${_escapeHtml(_fmtVal(v))}</span>
      </div>`).join('');
  const paramRows = mcpParams
    ? Object.entries(mcpParams).map(([k, v]) => `
        <div class="flex gap-2 text-xs py-1 border-b border-slate-100 last:border-0">
          <span class="font-mono text-blue-600 w-36 shrink-0">${_escapeHtml(k)}</span>
          <span class="text-slate-700 truncate">${_escapeHtml(_fmtVal(v))}</span>
        </div>`).join('')
    : '';

  const contentHtml = `
    <div class="p-5 flex flex-col gap-4 h-full overflow-y-auto">
      <div class="flex items-start gap-3">
        <span class="text-3xl leading-none">${icon}</span>
        <div class="flex-1 min-w-0">
          <div class="font-bold text-slate-800 text-base">${typeLabel} — 待人工審核</div>
          <div class="text-[11px] text-slate-400 font-mono mt-0.5 truncate">${_escapeHtml(card.draft_id)}</div>
        </div>
        <span class="shrink-0 inline-block px-2 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-700">待發佈</span>
      </div>

      <div class="bg-slate-50 rounded-lg border border-slate-200 px-3 py-2">
        <div class="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">草稿預覽</div>
        ${fillRows || '<span class="text-slate-400 text-xs">（無預覽資料）</span>'}
      </div>
      ${paramRows ? `
      <div class="bg-blue-50 rounded-lg border border-blue-200 px-3 py-2">
        <div class="text-[10px] font-bold text-blue-500 uppercase tracking-wider mb-2">🔢 MCP 輸入參數（Agent 帶入）</div>
        ${paramRows}
      </div>` : ''}

      <div class="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs text-blue-700">
        ℹ️ Agent 草稿不會直接修改正式資料。點擊下方按鈕開啟編輯器，確認內容後再正式發佈。
      </div>

      <button onclick="_openDraftEditor('${_escapeHtml(card.draft_id)}', '${_escapeHtml(card.draft_type)}', '${tabId}')"
              class="w-full py-3 rounded-lg bg-purple-600 hover:bg-purple-500 active:bg-purple-700
                     text-white text-sm font-semibold transition-colors shadow-sm">
        ✏️ 開啟編輯器 — 審核並發佈
      </button>
    </div>`;

  _createWorkspaceTab(tabId, `${icon} ${typeLabel}`, contentHtml);
}

// ══════════════════════════════════════════════════════════════
// Initialisation
// ══════════════════════════════════════════════════════════════

(function init() {
  if (_token) {
    if (_isTokenExpired(_token)) {
      // Token has expired — clear it and show login screen
      logout();
    } else {
      _showMainApp('');
    }
  }

  // Apply i18n on load
  _applyI18n();

  // Configure marked.js
  if (typeof marked !== 'undefined') {
    marked.setOptions({ breaks: true, gfm: true });
  }
})();


// ══════════════════════════════════════════════════════════════
// Help Chat — Usage Assistant
// ══════════════════════════════════════════════════════════════

/** Toggle the help chat panel open/closed (non-floating right panel). */
function toggleHelpPanel() {
  _helpPanelOpen = !_helpPanelOpen;
  const panel = document.getElementById('help-panel');
  if (!panel) return;

  if (_helpPanelOpen) {
    panel.style.display = 'flex';
    panel.style.flexDirection = 'column';
    // Show welcome bubble only once per session
    if (!_helpWelcomeShown) {
      _helpWelcomeShown = true;
      _addHelpBubble('agent',
        '👋 您好！我是 Glass Box 使用說明 AI 助理，可以回答您關於系統操作的問題。<br>請問有什麼需要幫助的嗎？');
    }
    setTimeout(() => document.getElementById('help-input')?.focus(), 150);
  } else {
    panel.style.display = 'none';
  }
}

/** Append a chat bubble to the help panel. */
function _addHelpBubble(type, html) {
  const container = document.getElementById('help-chat-history');
  if (!container) return null;
  const wrapper = document.createElement('div');
  wrapper.className = type === 'user' ? 'flex justify-end' : 'flex justify-start';
  const bubble = document.createElement('div');
  bubble.className = type === 'user' ? 'chat-bubble chat-user' : 'chat-bubble chat-agent';
  bubble.innerHTML = html;
  wrapper.appendChild(bubble);
  container.appendChild(wrapper);
  container.scrollTop = container.scrollHeight;
  return bubble;
}

/** Send a message to the help chat backend. */
async function _sendHelpMessage() {
  if (_helpStreaming) return;
  const input = document.getElementById('help-input');
  const message = input?.value.trim();
  if (!message) return;

  input.value = '';
  _addHelpBubble('user', _escapeHtml ? _escapeHtml(message) : message);
  _helpHistory.push({ role: 'user', content: message });

  _helpStreaming = true;
  const sendBtn = document.getElementById('help-send-btn');
  if (sendBtn) sendBtn.disabled = true;

  // Create streaming agent bubble
  const container = document.getElementById('help-chat-history');
  const wrapper   = document.createElement('div');
  wrapper.className = 'flex justify-start';
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble chat-agent';
  bubble.innerHTML = '<span class="text-slate-400 text-xs animate-pulse">思考中...</span>';
  wrapper.appendChild(bubble);
  container?.appendChild(wrapper);
  if (container) container.scrollTop = container.scrollHeight;

  let fullText = '';
  try {
    const response = await fetch('/api/v1/help/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${_token}`,
      },
      body: JSON.stringify({ message, history: _helpHistory.slice(0, -1) }),
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    bubble.innerHTML = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        const ev = _parseCopilotChunk(part.trim());  // reuse existing SSE parser
        if (!ev) continue;
        if (ev.type === 'chat') {
          fullText += ev.message || '';
          // Render with line breaks
          bubble.innerHTML = (typeof marked !== 'undefined')
            ? marked.parse(fullText)
            : fullText.replace(/\n/g, '<br>');
          if (container) container.scrollTop = container.scrollHeight;
        } else if (ev.type === 'error') {
          bubble.innerHTML = `<span class="text-red-500">❌ ${ev.message}</span>`;
        }
      }
    }

    if (fullText) _helpHistory.push({ role: 'assistant', content: fullText });

  } catch (e) {
    bubble.innerHTML = `<span class="text-red-500">❌ 請求失敗：${e.message}</span>`;
  } finally {
    _helpStreaming = false;
    if (sendBtn) sendBtn.disabled = false;
    setTimeout(() => document.getElementById('help-input')?.focus(), 50);
  }
}

// ══════════════════════════════════════════════════════════════
// v13 Real Agentic Loop — Glass-box Console + Context Control
// ══════════════════════════════════════════════════════════════

function _setChatMode(mode) {
  _v13Mode = mode === 'v13';
  const v12Btn = document.getElementById('chat-mode-v12');
  const v13Btn = document.getElementById('chat-mode-v13');
  if (!v12Btn || !v13Btn) return;
  if (_v13Mode) {
    v12Btn.className = 'px-2.5 py-1 rounded-l-md text-slate-500 hover:text-slate-700 transition-all';
    v13Btn.className = 'px-2.5 py-1 rounded-r-md bg-purple-600 text-white transition-all';
    _addChatBubble('agent',
      '<span style="color:#7c3aed;font-size:11px;">⚡ <strong>v13 Agentic Mode</strong> — Agent 具備 Tool Use + RAG 長期記憶</span>');
  } else {
    v12Btn.className = 'px-2.5 py-1 rounded-l-md bg-blue-600 text-white transition-all';
    v13Btn.className = 'px-2.5 py-1 rounded-r-md text-slate-500 hover:text-slate-700 transition-all';
    _addChatBubble('agent',
      '<span style="color:#2563eb;font-size:11px;">💬 已切換至 Copilot 模式</span>');
  }
}

/** v13 Agent — calls POST /agent/chat/stream and renders Glass-box Console events */
async function _clearAgentSession() {
  if (_isStreaming) return;
  if (_v13SessionId) {
    try {
      await fetch(`/api/v1/agent/session/${_v13SessionId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${_token}` },
      });
    } catch { /* ignore */ }
  }
  _v13SessionId = null;
  // Clear chat history UI
  const hist = document.getElementById('chat-history');
  if (hist) hist.innerHTML = '<div class="text-center py-8"><p class="text-xs text-slate-400 bg-white border border-slate-200 inline-block px-3 py-1 rounded-full">新對話已開始</p></div>';
  // Reset token badge
  const badge = document.getElementById('v13-token-badge');
  if (badge) { badge.textContent = ''; badge.classList.add('hidden'); }
  _diagConsoleClear();
  _diagLogLine('🗑', '對話歷史已清除，下次傳訊將使用全新 Session', '#f87171');
}

async function _sendAgentV13Message() {
  if (_isStreaming) return;

  const input   = document.getElementById('issue-input');
  const message = input.value.trim();
  if (!message) return;

  input.value  = '';
  _isStreaming = true;
  _setInputLocked(true);
  _setStatus('streaming');
  _hideSlashMenu();

  _addChatBubble('user', _escapeHtml(message));

  // Thinking placeholder
  _addChatBubble('agent',
    '<span id="v13-thinking-bubble" class="inline-flex items-center gap-1.5 text-slate-400 text-xs">' +
    '<span class="animate-spin text-base">⏳</span> 思考中…</span>');

  // Reset token badge for new message
  const _badge = document.getElementById('v13-token-badge');
  if (_badge) { _badge.textContent = ''; _badge.classList.add('hidden'); delete _badge._totalIn; delete _badge._totalOut; }

  // Expand Agent Console and mark new session
  _diagConsoleClear();
  _diagConsoleExpand();
  _diagLogLine('🚀', `新對話開始 | "${message.slice(0, 60)}${message.length > 60 ? '…' : ''}"`, '#38bdf8');

  const body = {
    message,
    session_id: _v13SessionId || null,
  };

  try {
    const response = await fetch('/api/v1/agent/chat/stream', {
      method:  'POST',
      headers: {
        'Content-Type':  'application/json',
        'Authorization': `Bearer ${_token}`,
      },
      body: JSON.stringify(body),
    });

    if (response.status === 401) { logout(); return; }
    if (!response.ok) {
      let msg = `HTTP ${response.status}`;
      try { const err = await response.json(); msg = err.message || msg; } catch { /* */ }
      _addChatBubble('error', `❌ 請求失敗：${msg}`);
      return;
    }

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = '';

    // Remove any stale thinking placeholder
    document.getElementById('v13-thinking-bubble')?.closest('.flex')?.remove();

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      const parts = buf.split('\n\n');
      buf = parts.pop();

      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;
        const ev = _parseCopilotChunk(trimmed);  // reuse SSE parser
        if (ev) _handleV13Event(ev);
      }
    }
    if (buf.trim()) {
      const ev = _parseCopilotChunk(buf.trim());
      if (ev) _handleV13Event(ev);
    }

  } catch (err) {
    _addChatBubble('error', `❌ 連線錯誤：${err.message}`);
  } finally {
    _isStreaming = false;
    _setInputLocked(false);
    _setStatus('ready');
  }
}

/**
 * Render Agent synthesis text as a chat bubble with line-by-line reveal.
 * Uses marked.parse() for markdown (tables, bold, etc.).
 * Lines are revealed one every 40ms so long responses feel progressive.
 */
function _streamSynthesisBubble(text) {
  const container = document.getElementById('chat-history');
  if (!container) return;

  // Build the bubble shell immediately (empty)
  const wrapper = document.createElement('div');
  wrapper.className = 'flex justify-start';
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble chat-agent';
  wrapper.appendChild(bubble);
  container.appendChild(wrapper);
  container.scrollTop = container.scrollHeight;

  // Split into logical lines (preserve blank lines for paragraph spacing)
  const lines = text.split('\n');
  let accumulated = '';
  let idx = 0;

  function revealNext() {
    if (idx >= lines.length) return;
    accumulated += (idx > 0 ? '\n' : '') + lines[idx];
    idx++;
    // Render accumulated markdown
    bubble.innerHTML = (typeof marked !== 'undefined')
      ? marked.parse(accumulated)
      : accumulated.replace(/\n/g, '<br>');
    container.scrollTop = container.scrollHeight;
    // Reveal next line after short delay; blank lines are faster
    const delay = lines[idx - 1].trim() === '' ? 8 : 40;
    setTimeout(revealNext, delay);
  }

  revealNext();
}

/** Render a v13 SSE event as a Glass-box Console line */
function _handleV13Event(ev) {
  if (!ev || !ev.type) return;

  switch (ev.type) {

    case 'context_load': {
      const ragCount = ev.rag_count || 0;
      const pref = ev.pref_summary && ev.pref_summary !== '(無)' ? ev.pref_summary : '未設定';
      const turns = ev.history_turns || 0;
      _diagLogLine('📦', `CONTEXT | Soul 載入 | 偏好: ${pref} | RAG: ${ragCount} 條 | 歷史: ${turns} 輪`, '#60a5fa');
      break;
    }

    case 'thinking': {
      _diagLogLine('💭', `THINKING | ${(ev.text || '').slice(0, 160)}${(ev.text||'').length > 160 ? '…' : ''}`, '#94a3b8');
      break;
    }

    case 'llm_usage': {
      const badge = document.getElementById('v13-token-badge');
      if (badge) {
        badge._totalIn  = (badge._totalIn  || 0) + (ev.input_tokens  || 0);
        badge._totalOut = (badge._totalOut || 0) + (ev.output_tokens || 0);
        badge.textContent = `in ${badge._totalIn.toLocaleString()} / out ${badge._totalOut.toLocaleString()} tok`;
        badge.classList.remove('hidden');
      }
      _diagLogLine('🔢', `LLM #${ev.iteration} tokens | in=${ev.input_tokens} out=${ev.output_tokens}`, '#64748b');
      break;
    }

    case 'tool_start': {
      const inputStr = JSON.stringify(ev.input || {});
      _diagLogLine('🔧', `TOOL #${ev.iteration || '?'} → ${ev.tool || ''}(${inputStr.slice(0, 80)}${inputStr.length > 80 ? '…' : ''})`, '#fbbf24');
      break;
    }

    case 'tool_done': {
      _diagLogLine('✅', `DONE  → ${ev.tool || ''} | ${ev.result_summary || ''}`, '#4ade80');
      // Render result in right workspace panel
      if (ev.render_card) {
        if (ev.render_card.type === 'skill') {
          _renderCopilotSkillPanel(ev.render_card);
        } else if (ev.render_card.type === 'mcp') {
          _renderCopilotMcpPanel(ev.render_card);
        } else if (ev.render_card.type === 'draft') {
          _renderDraftActionCard(ev.render_card);
        }
      } else {
        // No render_card — show pending synthesis indicator in console and right panel
        _diagLogLine('🤔', 'AI 正在整合分析結果…', '#a78bfa');
        _showReportPanel();
        const _wsContent = document.getElementById('ws-analysis-content');
        if (_wsContent && !_wsContent.querySelector('#ws-synthesis-pending')) {
          const _existing = _wsContent.querySelector('.ai-analysis-body');
          if (!_existing) {
            _wsContent.innerHTML = `<div id="ws-synthesis-pending" class="flex flex-col items-center justify-center h-40 gap-3 text-slate-400">
              <span class="animate-spin text-3xl">⏳</span>
              <span class="text-sm font-medium">AI 正在整合分析結果…</span>
            </div>`;
          }
        }
      }
      break;
    }

    case 'synthesis': {
      document.getElementById('v13-thinking-bubble')?.closest('.flex')?.remove();
      document.getElementById('ws-synthesis-pending')?.remove();
      const fullText = ev.text || '(無回答)';
      // v13.3 Output Routing: split <ai_analysis> from chat text
      const analysisMatch = fullText.match(/<ai_analysis>([\s\S]*?)<\/ai_analysis>/);
      if (analysisMatch) {
        const chatText = fullText.replace(/<ai_analysis>[\s\S]*?<\/ai_analysis>/g, '').trim()
                         || '👉 請檢視右側 AI 分析報告。';
        _streamSynthesisBubble(chatText);
        _renderAiAnalysisPanel(analysisMatch[1].trim());
      } else {
        _streamSynthesisBubble(fullText);
      }
      _diagLogLine('💬', `SYNTHESIS 完成 (${fullText.length} chars${analysisMatch ? ', 含 AI 分析' : ''})`, '#a78bfa');
      break;
    }

    case 'memory_write': {
      const conflict = ev.conflict_resolved ? ' [衝突已解決→UPDATE]' : '';
      _diagLogLine('🧠', `MEMORY | 已記住: ${(ev.content || '').slice(0, 80)} (source: ${ev.source || '?'})${conflict}`, '#c084fc');
      break;
    }

    case 'error': {
      document.getElementById('v13-thinking-bubble')?.closest('.flex')?.remove();
      _diagLogLine('❌', `ERROR | ${ev.message || '未知錯誤'}${ev.iteration ? ` (iter ${ev.iteration})` : ''}`, '#f87171');
      _addChatBubble('error', `⚠️ Agent 錯誤：${_escapeHtml(ev.message || '未知錯誤')}`);
      break;
    }

    case 'done': {
      if (ev.session_id) _v13SessionId = ev.session_id;
      _diagLogLine('🏁', `DONE | session=${ev.session_id || '?'}`, '#475569');
      _v14UpdateStageBar(null); // reset bar
      break;
    }

    // ── v14 New Events ──────────────────────────────────────────

    case 'stage_update': {
      const stageNum = ev.stage || 0;
      const stageLabel = ev.label || `Stage ${stageNum}`;
      const status = ev.status || 'running';
      const icon = status === 'complete' ? '✅' : '⏳';
      _diagLogLine(icon, `Stage ${stageNum} ${status === 'complete' ? '完成' : '執行中'}: ${stageLabel}`, status === 'complete' ? '#4ade80' : '#fbbf24');
      _v14UpdateStageBar(stageNum, status);
      if (ev.plan) {
        _diagLogLine('📋', `PLAN | ${ev.plan.slice(0, 200)}`, '#93c5fd');
      }
      break;
    }

    case 'token_usage': {
      const total = (ev.cumulative_tokens || 0).toLocaleString();
      const compaction = ev.compaction ? ' 🗜️ 已壓縮' : '';
      _diagLogLine('📊', `TOKEN BUDGET | 累計: ${total} tokens${compaction}`, '#64748b');
      break;
    }

    case 'approval_required': {
      _diagLogLine('⚠️', `HITL | 等待批准: ${ev.tool || ''}（token: ${ev.approval_token}）`, '#f97316');
      _v14ShowApprovalModal(ev);
      break;
    }

    case 'workspace_update': {
      const keys = Object.keys(ev.canvas_overrides || {}).join(', ');
      _diagLogLine('🖼️', `WORKSPACE | Canvas overrides 已注入: ${keys}`, '#818cf8');
      break;
    }
  }
}

// ── v14: Stage Progress Bar ────────────────────────────────────────────────────

const _V14_STAGE_LABELS = ['', '情境感知', '意圖規劃', '工具執行', '邏輯推理', '記憶寫入'];

function _v14UpdateStageBar(activeStage, status) {
  const bar = document.getElementById('v14-stage-bar');
  if (!bar) return;
  if (activeStage === null) {
    // Reset
    bar.querySelectorAll('.v14-stage-dot').forEach(d => {
      d.className = 'v14-stage-dot w-5 h-5 rounded-full bg-slate-600 text-[9px] flex items-center justify-center font-bold text-slate-400';
    });
    return;
  }
  for (let i = 1; i <= 5; i++) {
    const dot = bar.querySelector(`[data-stage="${i}"]`);
    if (!dot) continue;
    if (i < activeStage) {
      dot.className = 'v14-stage-dot w-5 h-5 rounded-full bg-green-500 text-[9px] flex items-center justify-center font-bold text-white';
    } else if (i === activeStage) {
      const cls = status === 'complete'
        ? 'v14-stage-dot w-5 h-5 rounded-full bg-green-500 text-[9px] flex items-center justify-center font-bold text-white'
        : 'v14-stage-dot w-5 h-5 rounded-full bg-yellow-400 text-[9px] flex items-center justify-center font-bold text-slate-900 animate-pulse';
      dot.className = cls;
    } else {
      dot.className = 'v14-stage-dot w-5 h-5 rounded-full bg-slate-600 text-[9px] flex items-center justify-center font-bold text-slate-400';
    }
  }
}

// ── v14: HITL Approval Modal ──────────────────────────────────────────────────

function _v14ShowApprovalModal(ev) {
  const existing = document.getElementById('v14-approval-modal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'v14-approval-modal';
  modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm';
  modal.innerHTML = `
    <div class="bg-slate-800 border border-orange-500 rounded-2xl p-6 max-w-md w-full mx-4 shadow-2xl">
      <div class="flex items-center gap-3 mb-4">
        <span class="text-2xl">⚠️</span>
        <div>
          <div class="text-white font-bold text-base">高風險操作審核</div>
          <div class="text-orange-300 text-xs mt-0.5">Human-in-the-loop (HITL) v14</div>
        </div>
      </div>
      <div class="bg-slate-900 rounded-lg p-3 mb-4 text-sm">
        <div class="text-slate-400 text-xs mb-1">工具</div>
        <div class="text-yellow-300 font-mono">${_escapeHtml(ev.tool || '')}</div>
        <div class="text-slate-400 text-xs mt-2 mb-1">參數</div>
        <div class="text-slate-300 font-mono text-xs break-all">${_escapeHtml(JSON.stringify(ev.input || {}, null, 2).slice(0, 200))}</div>
      </div>
      <p class="text-slate-300 text-sm mb-5">${_escapeHtml(ev.message || '')}</p>
      <div class="flex gap-3">
        <button onclick="_v14ResolveApproval('${ev.approval_token}', true)"
          class="flex-1 bg-green-600 hover:bg-green-500 text-white font-bold py-2.5 rounded-xl text-sm transition-colors">
          ✅ 批准執行
        </button>
        <button onclick="_v14ResolveApproval('${ev.approval_token}', false)"
          class="flex-1 bg-red-700 hover:bg-red-600 text-white font-bold py-2.5 rounded-xl text-sm transition-colors">
          ❌ 拒絕
        </button>
      </div>
      <div class="text-center text-slate-500 text-xs mt-3">
        ⏱️ 60 秒內未操作將自動拒絕
      </div>
    </div>`;
  document.body.appendChild(modal);

  // Auto-close after 62s (agent will have timed out)
  setTimeout(() => modal.remove(), 62000);
}

async function _v14ResolveApproval(token, approved) {
  document.getElementById('v14-approval-modal')?.remove();
  const action = approved ? '批准' : '拒絕';
  _diagLogLine(approved ? '✅' : '❌', `HITL | 用戶${action}: token=${token}`, approved ? '#4ade80' : '#f87171');
  try {
    const authHeader = _getAuthHeader ? _getAuthHeader() : {};
    await fetch(`/api/v1/agent/approve/${token}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ approved }),
    });
  } catch (e) {
    _diagLogLine('⚠️', `HITL 回報失敗: ${e.message}`, '#f97316');
  }
}

// ══════════════════════════════════════════════════════════════
// Agent Brain — Context Control Center functions
// ══════════════════════════════════════════════════════════════

async function _brainLoadSoul() {
  const textarea = document.getElementById('brain-soul-textarea');
  if (!textarea) return;
  try {
    const r = await fetch('/api/v1/agent/soul', {
      headers: { 'Authorization': `Bearer ${_token}` }
    });
    const d = await r.json();
    textarea.value = d.soul_prompt || d.data?.soul_prompt || '(尚未設定)';
  } catch(e) {
    textarea.value = `載入失敗: ${e.message}`;
  }
}

async function _brainSaveSoul() {
  const textarea = document.getElementById('brain-soul-textarea');
  if (!textarea) return;
  try {
    const r = await fetch('/api/v1/agent/soul', {
      method: 'PUT',
      headers: { 'Authorization': `Bearer ${_token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ soul_prompt: textarea.value }),
    });
    const d = await r.json();
    if (d.status === 'success') {
      alert('Soul Prompt 已儲存');
    } else {
      alert(`儲存失敗: ${JSON.stringify(d)}`);
    }
  } catch(e) {
    alert(`儲存失敗: ${e.message}`);
  }
}

async function _brainLoadPref() {
  const textarea = document.getElementById('brain-pref-textarea');
  if (!textarea) return;
  try {
    const r = await fetch('/api/v1/agent/preference', {
      headers: { 'Authorization': `Bearer ${_token}` }
    });
    const d = await r.json();
    textarea.value = d.preferences || '';
  } catch(e) {
    textarea.value = `載入失敗: ${e.message}`;
  }
}

async function _brainSavePref() {
  const textarea = document.getElementById('brain-pref-textarea');
  const status   = document.getElementById('brain-pref-status');
  if (!textarea || !status) return;

  status.textContent = '⏳ AI 安全審查中...';
  status.style.color = '#64748b';

  try {
    const r = await fetch('/api/v1/agent/preference', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${_token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: textarea.value }),
    });
    const d = await r.json();
    if (d.blocked) {
      status.textContent = `⛔ 被阻擋：${d.reason}`;
      status.style.color = '#dc2626';
    } else if (d.status === 'success') {
      status.textContent = '✓ 偏好已儲存';
      status.style.color = '#16a34a';
    } else {
      status.textContent = `⚠️ ${d.message || JSON.stringify(d)}`;
      status.style.color = '#d97706';
    }
  } catch(e) {
    status.textContent = `失敗: ${e.message}`;
    status.style.color = '#dc2626';
  }
}

async function _brainLoadMemories() {
  const list = document.getElementById('brain-memory-list');
  if (!list) return;
  list.innerHTML = '<p class="text-xs text-slate-400 text-center py-2">載入中...</p>';
  try {
    const r = await fetch('/api/v1/agent/memory?limit=100', {
      headers: { 'Authorization': `Bearer ${_token}` }
    });
    const d = await r.json();
    const memories = d.memories || d.data?.memories || [];
    _renderMemoryList(memories);
  } catch(e) {
    list.innerHTML = `<p class="text-xs text-red-500">載入失敗: ${e.message}</p>`;
  }
}

async function _brainSearchMemories() {
  const q = document.getElementById('brain-memory-search')?.value?.trim();
  if (!q) { _brainLoadMemories(); return; }
  const list = document.getElementById('brain-memory-list');
  list.innerHTML = '<p class="text-xs text-slate-400 text-center py-2">搜尋中...</p>';
  try {
    const r = await fetch(`/api/v1/agent/memory/search?q=${encodeURIComponent(q)}`, {
      headers: { 'Authorization': `Bearer ${_token}` }
    });
    const d = await r.json();
    const memories = d.memories || [];
    if (!memories.length) {
      list.innerHTML = `<p class="text-xs text-slate-400 text-center py-2">未找到「${_escapeHtml(q)}」相關記憶</p>`;
      return;
    }
    _renderMemoryList(memories);
  } catch(e) {
    list.innerHTML = `<p class="text-xs text-red-500">搜尋失敗: ${e.message}</p>`;
  }
}

function _renderMemoryList(memories) {
  const list = document.getElementById('brain-memory-list');
  if (!list) return;
  if (!memories.length) {
    list.innerHTML = '<p class="text-xs text-slate-400 text-center py-4">目前沒有長期記憶</p>';
    return;
  }
  list.innerHTML = memories.map(m => `
    <div class="flex items-start gap-2 p-2 bg-slate-50 border border-slate-100 rounded-lg">
      <div class="flex-1 min-w-0">
        <p class="text-xs text-slate-800 leading-relaxed">${_escapeHtml(m.content)}</p>
        <p class="text-[10px] text-slate-400 mt-0.5">
          <span class="inline-block bg-purple-100 text-purple-600 px-1.5 rounded">${m.source || 'manual'}</span>
          ${m.created_at ? m.created_at.slice(0, 16).replace('T', ' ') : ''}
          ${m.ref_id ? `· ref: ${_escapeHtml(m.ref_id)}` : ''}
        </p>
      </div>
      <button onclick="_brainDeleteMemory(${m.id})"
        class="flex-shrink-0 text-[10px] text-red-400 hover:text-red-600 hover:bg-red-50
               border border-red-200 rounded px-2 py-0.5 transition-colors">
        🗑️
      </button>
    </div>
  `).join('');
}

async function _brainDeleteMemory(id) {
  if (!confirm(`確定刪除記憶 #${id}？`)) return;
  try {
    const r = await fetch(`/api/v1/agent/memory/${id}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${_token}` }
    });
    const d = await r.json();
    if (d.status === 'success') _brainLoadMemories();
    else alert(`刪除失敗: ${JSON.stringify(d)}`);
  } catch(e) {
    alert(`刪除失敗: ${e.message}`);
  }
}

async function _brainDeleteAllMemories() {
  if (!confirm('確定清除所有長期記憶？此操作無法復原。')) return;
  try {
    const r = await fetch('/api/v1/agent/memory', {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${_token}` }
    });
    const d = await r.json();
    if (d.status === 'success') {
      alert(`已清除 ${d.deleted_count} 條記憶`);
      _brainLoadMemories();
    }
  } catch(e) {
    alert(`清除失敗: ${e.message}`);
  }
}
