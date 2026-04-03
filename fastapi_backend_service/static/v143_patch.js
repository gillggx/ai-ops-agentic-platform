/* ============================================================
   v14.3 — Scenario Pilot + View State Machine  (patch script)

   3 Discovery Cards — each auto-sends a question to the LLM:
     🔬 技能檢查  → "有哪些診斷技能（Skill）可以執行？請列出並說明用途。"
     📊 圖表分析  → "有哪些圖表分析 MCP 可以呼叫？請列出並說明每個的功能。"
     🗄️ 原始資料  → "有哪些 System MCP 原始資料來源可以查詢？請列出並說明欄位。"

   LLM naturally replies with available options — user picks one
   and follows up with details.

   Rollback:
     1. Remove from index.html (2 lines):
          <link rel="stylesheet" href="/v143_styles.css">
          <script src="/v143_patch.js"></script>
     2. Delete v143_styles.css  and  v143_patch.js
   ============================================================ */

(function () {
  'use strict';

  /* ── View State Machine ─────────────────────────────────
     HOME    3 Discovery Cards，Console 收起
     RUNNING Skeleton loading，Console 自動彈起
     RESULT  報告顯示，右上角「🏠 返回首頁」
  ── ────────────────────────────────────────────────────── */
  let _state = 'HOME';

  /* ── Static Discovery Cards ─────────────────────────────
     Clicking sends a discovery question directly to the LLM.
  ── ────────────────────────────────────────────────────── */
  const CARDS = [
    {
      icon:      '🔬',
      colorCard: 'v143-card-blue',
      colorIcon: 'v143-icon-blue',
      title:     '技能檢查',
      subtitle:  'Skill',
      body:      '查詢可用的自動化診斷技能',
      question:  '有哪些診斷技能（Skill）可以執行？請列出並說明各自的用途與適用情境。',
    },
    {
      icon:      '📊',
      colorCard: 'v143-card-green',
      colorIcon: 'v143-icon-green',
      title:     '圖表分析',
      subtitle:  'Custom MCP',
      body:      '查詢可用的資料處理與圖表管線',
      question:  '有哪些圖表分析 MCP 可以呼叫？請列出並說明每個 MCP 的功能與輸入參數。',
    },
    {
      icon:      '🗄️',
      colorCard: 'v143-card-violet',
      colorIcon: 'v143-icon-violet',
      title:     '原始資料',
      subtitle:  'System MCP',
      body:      '查詢可直接存取的資料來源',
      question:  '有哪些 System MCP 原始資料來源可以查詢？請列出並說明各資料來源的欄位與用途。',
    },
  ];

  /* ── DOM refs ───────────────────────────────────────────── */
  let _dataContent = null;
  let _dataHeader  = null;
  let _homeView    = null;
  let _skeleton    = null;
  let _rollbackBtn = null;

  /* ── Init ───────────────────────────────────────────────── */
  function _init() {
    _dataContent = document.getElementById('ws-data-content');
    if (!_dataContent) return;

    _dataHeader = _dataContent.closest('#ws-data-pane')
      ?.querySelector('.flex.flex-shrink-0');

    // Inject rollback button into DATA & CHART header
    if (_dataHeader) {
      _rollbackBtn = document.createElement('button');
      _rollbackBtn.id = 'v143-rollback-btn';
      _rollbackBtn.title = '返回情境首頁';
      _rollbackBtn.innerHTML = '🏠 返回首頁';
      _rollbackBtn.addEventListener('click', _onRollback);
      _dataHeader.appendChild(_rollbackBtn);
    }

    // Inject skeleton overlay
    _skeleton = document.createElement('div');
    _skeleton.id = 'v143-skeleton';
    _skeleton.innerHTML = _buildSkeletonHTML();
    _dataContent.style.position = 'relative';
    _dataContent.appendChild(_skeleton);

    // Inject HomeView overlay
    _homeView = document.createElement('div');
    _homeView.id = 'v143-home-view';
    _homeView.innerHTML = _buildHomeViewHTML();
    _dataContent.appendChild(_homeView);

    // Bind card clicks
    _bindCardClicks();

    // Wire up event hooks
    _patchV13EventHandler();
    _patchSendMessage();
    _bindKeyboard();

    // Set initial state
    _setState('HOME');
  }

  /* ── State transitions ──────────────────────────────────── */
  function _setState(newState) {
    _state = newState;
    if (newState === 'HOME')         _showHome();
    else if (newState === 'RUNNING') _showRunning();
    else if (newState === 'RESULT')  _showResult();
  }

  function _showHome() {
    if (_skeleton)    _skeleton.classList.remove('v143-visible');
    if (_rollbackBtn) _rollbackBtn.classList.remove('v143-visible');
    if (_homeView) {
      _homeView.classList.remove('v143-hidden', 'v143-exiting');
      _homeView.style.animation = 'v143FadeIn 0.25s ease';
    }
    // Collapse Agent Console
    const con = document.getElementById('diag-console');
    if (con) {
      con.style.height = '0';
      const chev = document.getElementById('diag-console-chevron');
      if (chev) chev.style.transform = 'rotate(0deg)';
      if (typeof _diagConsoleOpen !== 'undefined') window._diagConsoleOpen = false;
    }
  }

  function _showRunning() {
    if (_homeView && !_homeView.classList.contains('v143-hidden')) {
      _homeView.classList.add('v143-exiting');
      setTimeout(() => {
        if (_state !== 'HOME') _homeView.classList.add('v143-hidden');
      }, 320);
    }
    if (_skeleton)    _skeleton.classList.add('v143-visible');
    if (_rollbackBtn) _rollbackBtn.classList.remove('v143-visible');
    // Auto-expand Agent Console
    if (typeof _diagConsoleExpand === 'function') _diagConsoleExpand();
    else {
      const con = document.getElementById('diag-console');
      if (con) con.style.height = '184px';
    }
  }

  function _showResult() {
    if (_skeleton)    _skeleton.classList.remove('v143-visible');
    if (_rollbackBtn) _rollbackBtn.classList.add('v143-visible');
    if (_homeView) {
      _homeView.classList.remove('v143-exiting');
      _homeView.classList.add('v143-hidden');
    }
  }

  /* ── Card click: auto-send discovery question to LLM ────── */
  function _onCardClick(question) {
    // Fill input with the discovery question
    const input = document.getElementById('issue-input');
    if (!input) return;
    input.value = question;
    input.dispatchEvent(new Event('input', { bubbles: true }));

    // Log to Agent Console
    if (typeof _diagLogLine === 'function') {
      _diagLogLine('🔍', `問 LLM：${question.slice(0, 60)}…`, '#93c5fd');
    }

    // Transition immediately then send
    _setState('RUNNING');

    // Send via whichever send function is available
    if (typeof _sendCopilotMessage === 'function') {
      _sendCopilotMessage();
    } else if (typeof _sendAgentV13Message === 'function') {
      _sendAgentV13Message();
    } else {
      // Fallback: click the send button
      const btn = document.getElementById('send-btn') ||
                  document.querySelector('button[onclick*="send"]');
      if (btn) btn.click();
    }
  }

  /* ── Rollback ───────────────────────────────────────────── */
  function _onRollback() {
    _setState('HOME');
    if (typeof _diagLogLine === 'function') {
      _diagLogLine('🏠', 'Rollback → 返回情境首頁', '#60a5fa');
    }
  }

  /* ── Patch _sendAgentV13Message / _sendCopilotMessage ────── */
  // Only track state when user sends MANUALLY (not via card click which sets
  // state to RUNNING first). Guard with _state check.
  function _patchSendMessage() {
    const hookSend = fnName => {
      const orig = window[fnName];
      if (typeof orig !== 'function') return;
      window[fnName] = async function () {
        if (_state === 'HOME') _setState('RUNNING');
        return orig.apply(this, arguments);
      };
    };
    hookSend('_sendAgentV13Message');
    hookSend('_sendCopilotMessage');
  }

  /* ── Patch _handleV13Event: detect RESULT from SSE ─────── */
  function _patchV13EventHandler() {
    const orig = window._handleV13Event;
    if (typeof orig !== 'function') return;
    window._handleV13Event = function (ev) {
      orig.call(this, ev);
      if (!ev?.type) return;
      switch (ev.type) {
        case 'tool_done':
          if (_state === 'RUNNING')
            setTimeout(() => { if (_state === 'RUNNING') _setState('RESULT'); }, 600);
          break;
        case 'synthesis':
          if (_state !== 'HOME') _setState('RESULT');
          break;
        case 'done':
          if (_state === 'RUNNING') _setState('RESULT');
          break;
        case 'error':
          if (_state === 'RUNNING')
            setTimeout(() => { if (_state === 'RUNNING') _setState('HOME'); }, 3000);
          break;
      }
    };
  }

  /* ── HTML builders ──────────────────────────────────────── */
  function _buildHomeViewHTML() {
    const cardHTML = CARDS.map(c => `
      <div class="v143-card ${c.colorCard}"
           data-question="${_esc(c.question)}"
           role="button" tabindex="0" aria-label="${_esc(c.title)}">
        <div class="v143-card-icon ${c.colorIcon}">${c.icon}</div>
        <div style="flex:1;min-width:0;">
          <div class="v143-card-title">${_esc(c.title)}</div>
          <div class="v143-card-subtitle">${_esc(c.subtitle)}</div>
        </div>
        <div class="v143-card-body">${_esc(c.body)}</div>
        <div class="v143-card-arrow">→</div>
      </div>`
    ).join('');

    return `
      <div class="v143-home-header">
        <div class="v143-home-title">✨ 智能導航</div>
        <div class="v143-home-sub">點選任一類別，AI 將列出可用的工具與資料來源</div>
      </div>
      <div class="v143-card-grid">${cardHTML}</div>
      <p style="font-size:11px;color:#94a3b8;margin-top:4px;">
        也可直接在左側輸入自訂指令
      </p>`;
  }

  function _buildSkeletonHTML() {
    return `
      <div class="v143-skeleton-bar" style="height:18px;width:40%;opacity:.7;margin-bottom:6px;"></div>
      <div class="v143-skeleton-bar" style="height:280px;width:100%;border-radius:10px;"></div>
      <div style="display:flex;gap:10px;margin-top:8px;">
        <div class="v143-skeleton-bar" style="height:76px;flex:1;border-radius:8px;"></div>
        <div class="v143-skeleton-bar" style="height:76px;flex:1;border-radius:8px;"></div>
        <div class="v143-skeleton-bar" style="height:76px;flex:1;border-radius:8px;"></div>
      </div>`;
  }

  /* ── Bind card click events ─────────────────────────────── */
  function _bindCardClicks() {
    if (!_homeView) return;
    _homeView.querySelectorAll('.v143-card').forEach(card => {
      const fresh = card.cloneNode(true);
      card.replaceWith(fresh);
      fresh.addEventListener('click', () => _onCardClick(fresh.dataset.question));
    });
  }

  /* ── Keyboard support ───────────────────────────────────── */
  function _bindKeyboard() {
    document.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const el = document.activeElement;
      if (el?.classList.contains('v143-card')) {
        e.preventDefault();
        el.click();
      }
    });
  }

  /* ── Utils ──────────────────────────────────────────────── */
  function _esc(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* ── Bootstrap ──────────────────────────────────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(_init, 250));
  } else {
    setTimeout(_init, 250);
  }

  // Expose for debug
  window._v143 = {
    setState: _setState,
    rollback: _onRollback,
  };

})();
