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

// Phase 9 — Copilot state
let _slotContext     = {};     // accumulated params for current slot-filling session
let _slotToolId      = null;   // tool_id being filled
let _slotToolType    = null;   // 'mcp' | 'skill'
let _copilotHistory  = [];     // [{role, content}] conversation history
let _slashMenuVisible = false;
let _slashMenuItems  = null;   // cached {mcps, skills} for slash menu

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
    .map(([k, v]) => `<div class="flex justify-between text-xs py-0.5">
        <span class="text-red-700 font-mono">${_escapeHtml(k)}</span>
        <span class="text-red-900 font-mono font-medium">${_escapeHtml(v)}</span>
      </div>`)
    .join('');

  const cardHtml = `
    <div class="event-alert-card">
      <div class="event-alert-header">
        <span class="text-red-600 font-bold">⚡ 事件通知</span>
        <span class="text-xs text-red-500 ml-auto">${_escapeHtml(_SPC_OOC_EVENT.timestamp)}</span>
      </div>
      <div class="event-alert-type">${_escapeHtml(_SPC_OOC_EVENT.event_type)}</div>
      <div class="event-alert-id text-xs text-red-600 mb-2"># ${_escapeHtml(_SPC_OOC_EVENT.event_id)}</div>
      <div class="event-alert-params border border-red-200 rounded-lg p-2 bg-red-50 mb-3">${paramsHtml}</div>
      <button onclick="_launchEventDiagnosis()"
        class="w-full flex items-center justify-center gap-2
               bg-red-300 hover:bg-red-400 border border-red-400
               text-red-900 text-sm font-semibold
               rounded-xl px-4 py-2.5 transition-colors">
        🔍 啟動診斷分析
      </button>
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
          _addChatBubble('error', `⚠️ ${_escapeHtml(evt.message)}`);
          _renderPipelineError(evt.message);

        } else if (evt.type === 'start') {
          totalSkills = evt.skill_count || 0;
          _addChatBubble('agent', `📋 共找到 <strong>${totalSkills}</strong> 個 Skill，逐一執行中...`);

        } else if (evt.type === 'skill_start') {
          const bubbleId = `skill-bubble-${evt.index}`;
          _addChatBubble('agent', `⏳ 正在執行 <strong>${_escapeHtml(evt.skill_name)}</strong>...`, bubbleId);
          skillBubbles[evt.index] = document.getElementById(bubbleId);

        } else if (evt.type === 'skill_done') {
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
            _addChatBubble('agent', '⚠️ 未找到綁定此 Event 的 Skill，請先在 Skill Builder 建立。');
          } else if (abnormal > 0) {
            _addChatBubble('agent', `🚨 診斷完成：${totalSkills} 個 Skill 中有 <strong>${abnormal}</strong> 個檢測到異常，請查看右側報告。`);
          } else {
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
      <div id="diagnosis-summary" class="hidden diagnosis-summary-bar flex-shrink-0"></div>
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

  // Init charts in the new panel
  _initChartsInCard(panel);
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
 * Render diagnosis summary bar above skill tabs (called after all skills complete).
 */
function _renderDiagnosisSummary(skills) {
  const el = document.getElementById('diagnosis-summary');
  if (!el || skills.length === 0) return;

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

  el.innerHTML = `
    <div class="text-xs font-bold text-blue-900 uppercase tracking-wider mb-2">📊 診斷總覽</div>
    ${headerCols}
    ${rows}`;
  el.classList.remove('hidden');
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
          const layout = Object.assign({
            margin: { t: 30, b: 40, l: 50, r: 20 },
            height: 260,
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor:  '#f8fafc',
            font: { color: '#374151', size: 11 },
          }, spec.layout || {});
          Plotly.newPlot(div, traces, layout, { responsive: true, displayModeBar: false });
        } else {
          // Plotly not loaded — hide the empty chart div (table fallback still shows)
          div.style.display = 'none';
        }
      } else if (raw.startsWith('data:image/')) {
        div.innerHTML = `<img src="${raw}" style="max-width:100%;border-radius:6px">`;
      }
    } catch (e) {
      div.style.display = 'none';  // hide on error; table fallback remains visible
    }
  });
}

/** Legacy: kept so old non-streaming code paths don't break */
function _renderPipelineResults(result) {
  _initReportPanel(result.event || {});
  (result.skills || []).forEach(s => _appendSkillCard(s));
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

  const evidenceHtml = (s.evidence || []).length > 0
    ? `<ul class="pipeline-evidence-list">${(s.evidence || []).map(e => `<li>${_escapeHtml(e)}</li>`).join('')}</ul>`
    : '';

  const recommendHtml = s.human_recommendation && s.status !== 'NORMAL'
    ? `<div class="pipeline-recommendation">💡 <strong>建議動作：</strong>${_escapeHtml(s.human_recommendation)}</div>`
    : '';

  const chartHtml = _renderMcpEvidence(s.mcp_output);

  return `
    <div class="pipeline-report-block">
      <div class="pipeline-block-header">
        <span class="text-sm font-semibold text-slate-700">⚙️ ${_escapeHtml(s.skill_name)}</span>
        <span class="text-xs text-slate-400 ml-2 font-mono">${_escapeHtml(s.mcp_name)}</span>
        <span class="pipeline-block-status ${statusClass}">${statusLabel}</span>
      </div>
      <div class="pipeline-block-body">
        <p class="text-sm text-slate-800 font-medium mb-1">${_escapeHtml(s.conclusion)}</p>
        ${evidenceHtml}
        ${s.summary ? `<p class="text-xs text-slate-500 mt-2 italic">${_escapeHtml(s.summary)}</p>` : ''}
        ${chartHtml}
        ${recommendHtml}
      </div>
    </div>`;
}

/**
 * Render MCP output evidence as a chart + dataset table.
 * Chart (Plotly/PNG) renders via _initChartsInCard() after DOM insert.
 * Dataset table is ALWAYS shown when rows are available (fallback for chart failures).
 */
function _renderMcpEvidence(mcpOutput) {
  if (!mcpOutput) return '';

  const uiRender = mcpOutput.ui_render;
  const rows = Array.isArray(mcpOutput.dataset) ? mcpOutput.dataset.slice(0, 15) : [];
  let chartHtml = '';
  let tableHtml = '';

  // ── Chart section ──────────────────────────────────────────
  if (uiRender && uiRender.chart_data) {
    const chartData = typeof uiRender.chart_data === 'string'
      ? uiRender.chart_data
      : JSON.stringify(uiRender.chart_data);
    const escaped = chartData.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    chartHtml = `<div class="evidence-chart" data-chart="${escaped}"></div>`;
  }

  // ── Dataset table (always shown if rows exist) ─────────────
  if (rows.length > 0) {
    const cols       = Object.keys(rows[0]);
    const headerRow  = cols.map(c => `<th>${_escapeHtml(String(c))}</th>`).join('');
    const bodyRows   = rows.map(r =>
      `<tr>${cols.map(c => `<td>${_escapeHtml(String(r[c] ?? ''))}</td>`).join('')}</tr>`
    ).join('');
    tableHtml = `
      <div style="overflow-x:auto;margin-top:${chartHtml ? '10px' : '0'}">
        <table class="evidence-table">
          <thead><tr>${headerRow}</tr></thead>
          <tbody>${bodyRows}</tbody>
        </table>
      </div>`;
  }

  if (!chartHtml && !tableHtml) return '';

  const sectionTitle = chartHtml ? '📊 數據圖表佐證' : '📋 數據表格佐證';
  return `
    <div class="evidence-chart-section">
      <div class="evidence-chart-title">${sectionTitle}</div>
      ${chartHtml}
      ${tableHtml}
    </div>`;
}

// ══════════════════════════════════════════════════════════════
// Auth helpers
// ══════════════════════════════════════════════════════════════

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
function _createWorkspaceTab(tabId, title, contentHtml) {
  // Hide placeholder / empty hint
  document.getElementById('workspace-placeholder')?.classList.add('hidden');
  document.getElementById('ws-empty-hint')?.classList.add('hidden');

  // ── Tab button ──────────────────────────────────────────────
  const btn = document.createElement('button');
  btn.id        = `ws-tab-btn-${tabId}`;
  btn.className = 'tab-btn ws-tab whitespace-nowrap';
  btn.innerHTML =
    `<span class="ws-tab-label">${title}</span>` +
    `<span class="ws-close-btn" title="關閉"` +
    ` onclick="_closeWorkspaceTab('${tabId.replace(/'/g, "\\'")}');event.stopPropagation()">×</span>`;
  btn.onclick = () => _activateWorkspaceTab(tabId);
  document.getElementById('tab-bar').appendChild(btn);

  // ── Panel ────────────────────────────────────────────────────
  const panel = document.createElement('div');
  panel.id        = `ws-panel-${tabId}`;
  panel.className = 'tab-panel hidden flex flex-col flex-1 min-h-0';
  panel.innerHTML = contentHtml;
  document.getElementById('tab-content').appendChild(panel);

  _workspaceTabs[tabId] = { btn, panel };
  _activateWorkspaceTab(tabId);
  return { btn, panel };
}

/** Activate a workspace tab (deactivates all others). */
function _activateWorkspaceTab(tabId) {
  Object.values(_workspaceTabs).forEach(({ btn, panel }) => {
    btn.classList.remove('active-tab');
    panel.classList.add('hidden');
  });
  const entry = _workspaceTabs[tabId];
  if (!entry) return;
  entry.btn.classList.add('active-tab');
  entry.panel.classList.remove('hidden');
  _activeTabId = tabId;
}

/**
 * Close a workspace tab. If it was the active tab, focus the most recent
 * remaining tab; if none remain, show the workspace placeholder again.
 * Exposed globally so the inline onclick handler can call it.
 */
function _closeWorkspaceTab(tabId) {
  const entry = _workspaceTabs[tabId];
  if (!entry) return;
  const wasActive = _activeTabId === tabId;
  entry.btn.remove();
  entry.panel.remove();
  delete _workspaceTabs[tabId];

  const remaining = Object.keys(_workspaceTabs);
  if (remaining.length > 0) {
    if (wasActive) _activateWorkspaceTab(remaining[remaining.length - 1]);
  } else {
    _activeTabId = null;
    document.getElementById('workspace-placeholder')?.classList.remove('hidden');
    document.getElementById('ws-empty-hint')?.classList.remove('hidden');
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

  // Show workspace placeholder + empty hint
  document.getElementById('workspace-placeholder')?.classList.remove('hidden');
  document.getElementById('ws-empty-hint')?.classList.remove('hidden');

  // Reset copilot slot state (keep history for context continuity)
  _slotContext  = {};
  _slotToolId   = null;
  _slotToolType = null;
  _clearSlashTool();

  // Hide report panel for new diagnosis
  _hideReportPanel();

  // Add visual separator in chat
  _addChatDivider('── 新診斷開始 ──');
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

function _escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
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
      const desc = (m.processing_intent || m.name || '').slice(0, 60);
      html += `<div class="slash-menu-item" onclick="_selectSlashTool(${m.id},'mcp',${JSON.stringify(m.name)},${JSON.stringify(desc)})">
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
      const desc = (s.description || s.name || '').slice(0, 60);
      html += `<div class="slash-menu-item" onclick="_selectSlashTool(${s.id},'skill',${JSON.stringify(s.name)},${JSON.stringify(desc)})">
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
function _selectSlashTool(toolId, toolType, toolName, desc) {
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

  const input = document.getElementById('issue-input');
  if (input) { input.value = ''; input.focus(); }
}

function _clearSlashTool() {
  _slotToolId   = null;
  _slotToolType = null;
  _slotContext  = {};
  const wrap = document.getElementById('copilot-tool-tag-wrap');
  if (wrap) { wrap.innerHTML = ''; wrap.classList.add('hidden'); }
}

/** Primary send handler — replaces raw sendDiagnosis() for normal chat. */
async function _sendCopilotMessage() {
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
      document.getElementById('copilot-thinking-bubble')?.closest('.flex')?.remove();
      _clearSlashTool();
      _slotContext = {};
      _renderCopilotMcpPanel(ev);
      _addChatBubble('agent', `✅ <strong>${_escapeHtml(ev.mcp_name || '')}</strong> 查詢完成，結果已呈現於右側報告區。`);
      return `${ev.mcp_name} 查詢完成`;
    }

    case 'skill_result': {
      document.getElementById('copilot-thinking-bubble')?.closest('.flex')?.remove();
      _clearSlashTool();
      _slotContext = {};
      _renderCopilotSkillPanel(ev);
      const icon = ev.status === 'NORMAL' ? '✅' : '⚠️';
      _addChatBubble('agent', `${icon} <strong>${_escapeHtml(ev.skill_name || '')}</strong> 診斷完成，結果已呈現於右側報告區。`);
      return `${ev.skill_name} 診斷完成`;
    }

    case 'error': {
      document.getElementById('copilot-thinking-bubble')?.closest('.flex')?.remove();
      _addChatBubble('error', `❌ ${_escapeHtml(ev.message || '未知錯誤')}`);
      return null;
    }

    case 'done': {
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
  const tabTitle = ev.tab_title || `🔍 ${ev.mcp_name || 'MCP 查詢'}`;
  const evidenceHtml = _renderMcpEvidence(ev.mcp_output);

  const contentHtml = `
    <div class="p-4 overflow-y-auto flex-1">
      <div class="flex items-center gap-2 mb-3">
        <span class="inline-block px-2 py-0.5 rounded-full text-xs font-bold bg-blue-100 text-blue-700">MCP 查詢</span>
        <span class="text-sm font-semibold text-slate-800">${_escapeHtml(ev.mcp_name || '')}</span>
      </div>
      ${evidenceHtml || '<p class="text-slate-400 text-sm p-4">無資料回傳</p>'}
    </div>`;

  const { panel } = _createWorkspaceTab(tabId, tabTitle, contentHtml);
  _initChartsInCard(panel);
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

  const contentHtml = `<div class="p-4 overflow-y-auto flex-1">${_renderSkillBlock(ev)}</div>`;

  const { panel } = _createWorkspaceTab(tabId, tabTitle, contentHtml);
  _initChartsInCard(panel);
}

// ══════════════════════════════════════════════════════════════
// Initialisation
// ══════════════════════════════════════════════════════════════

(function init() {
  if (_token) {
    _showMainApp('');
  }

  // Apply i18n on load
  _applyI18n();

  // Configure marked.js
  if (typeof marked !== 'undefined') {
    marked.setOptions({ breaks: true, gfm: true });
  }
})();
