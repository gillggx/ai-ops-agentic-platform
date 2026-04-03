/**
 * v18 — Alarm Homepage + Skill Designer 2.0
 *
 * Depends on:  _api(), _esc(), _token  (from builder.js / app.js)
 * Load order:  after builder.js
 */

'use strict';

// ════════════════════════════════════════════════════════════════
// Alarm Page
// ════════════════════════════════════════════════════════════════

window._alarmPage = (function () {

  let _filters = { status: 'active', severity: '', equipment_id: '', days: 7 };

  // ── helpers ─────────────────────────────────────────────────

  function _timeAgo(isoStr) {
    if (!isoStr) return '';
    const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
    if (diff < 60)   return `${diff} 秒前`;
    if (diff < 3600) return `${Math.floor(diff / 60)} 分鐘前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小時前`;
    return `${Math.floor(diff / 86400)} 天前`;
  }

  const _SEVERITY_STYLE = {
    CRITICAL: { badge: 'bg-red-600 text-white',    dot: '🔴' },
    HIGH:     { badge: 'bg-orange-500 text-white',  dot: '🟠' },
    MEDIUM:   { badge: 'bg-yellow-400 text-slate-900', dot: '🟡' },
    LOW:      { badge: 'bg-slate-400 text-white',   dot: '🔵' },
  };

  function _sevStyle(sev) {
    return _SEVERITY_STYLE[sev] || { badge: 'bg-slate-300 text-slate-700', dot: '⚪' };
  }

  // ── stats badge bar ─────────────────────────────────────────

  async function loadStats() {
    try {
      const stats = await _api('GET', '/alarms/stats');
      _renderStats(stats);
    } catch (e) {
      const bar = document.getElementById('alm-badge-bar');
      if (bar) bar.innerHTML = `<span class="text-xs text-slate-400">Badge 載入失敗</span>`;
    }
  }

  function _renderStats(stats) {
    const bar = document.getElementById('alm-badge-bar');
    if (!bar) return;
    const items = [
      { key: 'critical', label: 'CRITICAL', cls: 'bg-red-600 text-white' },
      { key: 'high',     label: 'HIGH',     cls: 'bg-orange-500 text-white' },
      { key: 'medium',   label: 'MEDIUM',   cls: 'bg-yellow-400 text-slate-900' },
      { key: 'low',      label: 'LOW',      cls: 'bg-slate-400 text-white' },
    ];
    bar.innerHTML = items.map(it => `
      <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold ${it.cls}
                   cursor-pointer select-none hover:opacity-80 transition-opacity"
            onclick="_alarmPage.filterBySeverity('${it.label}')">
        ${it.label}: ${stats[it.key] || 0}
      </span>
    `).join('') + `
      <span class="ml-2 text-xs text-slate-400">Total active: ${stats.total_active || 0}</span>
    `;
  }

  // ── alarm list ──────────────────────────────────────────────

  async function loadList() {
    const container = document.getElementById('alm-list');
    if (!container) return;
    container.innerHTML = '<p class="text-center text-slate-400 py-12 text-sm">載入中…</p>';
    try {
      const qs = new URLSearchParams();
      if (_filters.status)       qs.set('status', _filters.status);
      if (_filters.severity)     qs.set('severity', _filters.severity);
      if (_filters.equipment_id) qs.set('equipment_id', _filters.equipment_id);
      qs.set('days', _filters.days);
      qs.set('limit', 100);
      const alarms = await _api('GET', `/alarms?${qs}`);
      _renderList(Array.isArray(alarms) ? alarms : []);
    } catch (e) {
      if (container) container.innerHTML = `<p class="text-center text-red-400 py-12 text-sm">載入失敗：${_esc(e.message)}</p>`;
    }
  }

  function _renderList(alarms) {
    const container = document.getElementById('alm-list');
    if (!container) return;
    if (alarms.length === 0) {
      container.innerHTML = `
        <div class="flex flex-col items-center justify-center py-20 text-slate-400">
          <svg class="w-12 h-12 mb-3 opacity-20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                  d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>
          </svg>
          <p class="text-sm font-medium">目前沒有 Alarm</p>
          <p class="text-xs mt-1">最近 ${_filters.days} 天 · ${_filters.status === 'all' ? '全部狀態' : _filters.status}</p>
        </div>`;
      return;
    }

    container.innerHTML = alarms.map(a => {
      const st  = _sevStyle(a.severity);
      const isActive = a.status === 'active';
      const isAcked  = a.status === 'acknowledged';
      const canAck   = isActive;
      const canRes   = isActive || isAcked;
      return `
        <div class="alm-card border border-slate-200 bg-white rounded-xl px-5 py-4 flex items-start gap-4
                    hover:border-slate-300 hover:shadow-sm transition-all"
             id="alm-card-${a.id}">
          <!-- Severity badge -->
          <div class="flex-shrink-0 mt-0.5">
            <span class="inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-bold ${st.badge}">
              ${st.dot} ${_esc(a.severity)}
            </span>
          </div>
          <!-- Body -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-semibold text-sm text-slate-800">${_esc(a.title)}</span>
              <span class="text-[11px] text-slate-400 font-mono">${_esc(a.trigger_event || '')}</span>
              ${a.status !== 'active' ? `<span class="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 font-medium">${_esc(a.status)}</span>` : ''}
            </div>
            <div class="flex items-center gap-3 mt-1 text-xs text-slate-500 flex-wrap">
              <span class="font-mono">${_esc(a.equipment_id)}</span>
              <span>·</span>
              <span class="font-mono">${_esc(a.lot_id)}</span>
              ${a.step ? `<span>·</span><span class="font-mono">${_esc(a.step)}</span>` : ''}
              <span>·</span>
              <span>${_timeAgo(a.created_at)}</span>
              ${a.acknowledged_by ? `<span>· 已認領 by <b>${_esc(a.acknowledged_by)}</b></span>` : ''}
            </div>
            ${a.summary ? `<p class="text-xs text-slate-500 mt-1.5 leading-relaxed line-clamp-2">${_esc(a.summary)}</p>` : ''}
          </div>
          <!-- Actions -->
          <div class="flex-shrink-0 flex items-center gap-2">
            ${canAck ? `<button onclick="_alarmPage.acknowledge(${a.id})"
                class="text-xs px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600
                       hover:bg-slate-50 hover:border-slate-400 font-medium transition-colors whitespace-nowrap">
                認領
              </button>` : ''}
            ${canRes ? `<button onclick="_alarmPage.resolve(${a.id})"
                class="text-xs px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-white
                       font-medium transition-colors whitespace-nowrap">
                解決
              </button>` : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  // ── actions ─────────────────────────────────────────────────

  async function acknowledge(id) {
    const by = prompt('認領者姓名 / 工號：', '');
    if (by === null) return;
    try {
      await _api('PATCH', `/alarms/${id}/acknowledge`, { acknowledged_by: by || 'unknown' });
      await init();
    } catch (e) { alert('認領失敗：' + e.message); }
  }

  async function resolve(id) {
    if (!confirm('確認將此 Alarm 標記為已解決？')) return;
    try {
      await _api('PATCH', `/alarms/${id}/resolve`, {});
      await init();
    } catch (e) { alert('解決失敗：' + e.message); }
  }

  // ── filter controls ──────────────────────────────────────────

  function filterBySeverity(sev) {
    _filters.severity = _filters.severity === sev ? '' : sev;
    const sel = document.getElementById('alm-filter-severity');
    if (sel) sel.value = _filters.severity;
    loadList();
  }

  function applyFilters() {
    _filters.status       = document.getElementById('alm-filter-status')?.value || 'active';
    _filters.severity     = document.getElementById('alm-filter-severity')?.value || '';
    _filters.equipment_id = document.getElementById('alm-filter-eqp')?.value?.trim() || '';
    _filters.days         = parseInt(document.getElementById('alm-filter-days')?.value) || 7;
    loadList();
  }

  // ── public entry ────────────────────────────────────────────

  async function init() {
    await Promise.all([loadStats(), loadList()]);
  }

  return { init, loadStats, loadList, acknowledge, resolve, filterBySeverity, applyFilters };
})();


// ════════════════════════════════════════════════════════════════
// Skill Builder v18 — overrides builder.js implementations
// ════════════════════════════════════════════════════════════════

// v18 editor state
let _skV18Id           = null;  // null = new skill
let _skV18Steps        = [];    // [{step_id, nl_segment, python_code}]
let _skV18OutputSchema = [];    // [{field, type, label, ...}] — v2.0
let _skV18ETypes       = [];    // event_types cache

// ── helpers ─────────────────────────────────────────────────────

async function _skV18LoadETypes() {
  if (_skV18ETypes.length) return _skV18ETypes;
  try { _skV18ETypes = await _api('GET', '/event-types') || []; } catch {}
  return _skV18ETypes;
}

function _skV18Log(msg, cls) {
  const el = document.getElementById('skv18-console');
  if (!el) return;
  const line = document.createElement('div');
  line.className = 'text-[11px] leading-relaxed font-mono ' + (cls || 'text-slate-300');
  line.textContent = msg;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function _skV18ClearConsole() {
  const el = document.getElementById('skv18-console');
  if (el) el.innerHTML = '';
}

// ── list rendering (replaces old _loadSkillDefs) ──────────────────

async function _loadSkillDefs() {
  const container = document.getElementById('skill-list');
  if (!container) return;
  container.innerHTML = '<p class="text-center text-slate-400 py-12 text-sm">載入中…</p>';
  try {
    _skillDefs = await _api('GET', '/skill-definitions') || [];
    _skV18ETypes = await _skV18LoadETypes();

    if (_skillDefs.length === 0) {
      container.innerHTML = `
        <div class="flex flex-col items-center justify-center py-20 text-slate-400">
          <p class="text-sm font-medium">尚無 Skill</p>
          <p class="text-xs mt-1">點擊右上角「+ 新增 Skill」開始設計</p>
        </div>`;
      return;
    }

    const _MODE_LABEL = { schedule: '定期排程', event: 'Event 驅動', both: '雙觸發' };
    container.innerHTML = _skillDefs.map(sk => {
      const stepCount = Array.isArray(sk.steps_mapping) ? sk.steps_mapping.length : 0;
      const modeTag = `<span class="builder-tag" style="background:#ede9fe;color:#5b21b6">${_MODE_LABEL[sk.trigger_mode] || sk.trigger_mode}</span>`;
      const etTag = sk.trigger_event_name
        ? `<span class="builder-tag">${_esc(sk.trigger_event_name)}</span>`
        : `<span class="builder-tag" style="color:#94a3b8">無 Event 觸發</span>`;
      const stepsTag = stepCount > 0
        ? `<span class="builder-tag builder-tag-green">🐍 ${stepCount} Steps</span>`
        : `<span class="builder-tag" style="color:#94a3b8">無 Steps</span>`;
      const activeBadge = sk.is_active
        ? ''
        : '<span class="builder-tag" style="background:#fef9c3;color:#92400e">停用</span>';

      return `
        <div class="builder-card" onclick="_skOpenEditor(${sk.id})">
          <div class="flex-1">
            <div class="builder-card-name">${_esc(sk.name)}</div>
            <div class="builder-card-desc">${_esc(sk.description || '（無說明）')}</div>
            <div class="builder-card-meta flex-wrap gap-1">
              ${etTag} ${modeTag} ${stepsTag} ${activeBadge}
            </div>
          </div>
          <div class="flex items-center gap-2">
            <div class="text-slate-600 text-sm">›</div>
            <button onclick="event.stopPropagation(); _skV18Delete(${sk.id}, '${_esc(sk.name).replace(/'/g, "\\'")}')"
                    title="刪除 Skill"
                    class="w-7 h-7 flex items-center justify-center rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50 transition-colors">
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/>
                <path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/>
              </svg>
            </button>
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    if (container) container.innerHTML = `<p class="text-center text-red-400 py-12 text-sm">載入失敗：${_esc(e.message)}</p>`;
  }
}

async function _skV18Delete(id, name) {
  if (!confirm(`確定要刪除 Skill「${name}」？`)) return;
  try {
    await _api('DELETE', `/skill-definitions/${id}`);
    _loadSkillDefs();
  } catch (e) { alert('刪除失敗：' + e.message); }
}

// ── open editor (replaces old _skOpenEditor) ──────────────────────

async function _skOpenEditor(id) {
  _skV18Id    = id || null;
  _skV18Steps = [];
  _skV18ClearConsole();

  // Show editor, hide list
  document.getElementById('sk-list-state')?.classList.add('hidden');
  document.getElementById('sk-editor')?.classList.remove('hidden');
  document.getElementById('sk-editor')?.classList.add('flex');
  document.getElementById('sk-editor-title').textContent = id ? '編輯 Skill' : '新增 Skill';

  // Load event types for dropdown
  await _skV18LoadETypes();
  _skV18RenderETypeSelect();

  if (id) {
    try {
      const sk = await _api('GET', `/skill-definitions/${id}`);
      document.getElementById('skv18-name').value = sk.name || '';
      document.getElementById('skv18-desc').value = sk.description || '';
      document.getElementById('skv18-trigger-event').value = sk.trigger_event_id || '';
      document.getElementById('skv18-visibility').value = sk.visibility || 'private';
      _skV18SetMode(sk.trigger_mode || 'both');
      _skV18Steps = Array.isArray(sk.steps_mapping) ? sk.steps_mapping : [];
      _skV18OutputSchema = Array.isArray(sk.output_schema) ? sk.output_schema : [];
      _skV18RenderSteps();
    } catch (e) { alert('載入 Skill 失敗：' + e.message); }
  } else {
    // Reset form
    document.getElementById('skv18-name').value = '';
    document.getElementById('skv18-desc').value = '';
    document.getElementById('skv18-trigger-event').value = '';
    document.getElementById('skv18-visibility').value = 'private';
    _skV18SetMode('both');
    _skV18RenderSteps();
  }
}

function _skV18BackToList() {
  document.getElementById('sk-editor')?.classList.add('hidden');
  document.getElementById('sk-editor')?.classList.remove('flex');
  document.getElementById('sk-list-state')?.classList.remove('hidden');
  _loadSkillDefs();
}

function _skV18RenderETypeSelect() {
  const sel = document.getElementById('skv18-trigger-event');
  if (!sel) return;
  const cur = sel.value;
  sel.innerHTML = '<option value="">— 無 Event 觸發（排程only）—</option>'
    + _skV18ETypes.filter(e => e.is_active !== false).map(e =>
        `<option value="${e.id}">${_esc(e.name)}</option>`
      ).join('');
  sel.value = cur;
}

// ── trigger_mode toggle ──────────────────────────────────────────

let _skV18CurrentMode = 'both';
function _skV18SetMode(mode) {
  _skV18CurrentMode = mode;
  ['schedule', 'event', 'both'].forEach(m => {
    const btn = document.getElementById(`skv18-mode-${m}`);
    if (!btn) return;
    if (m === mode) {
      btn.classList.add('bg-violet-600', 'text-white');
      btn.classList.remove('text-slate-500', 'bg-white');
    } else {
      btn.classList.remove('bg-violet-600', 'text-white');
      btn.classList.add('text-slate-500', 'bg-white');
    }
  });
}

// ── steps rendering ──────────────────────────────────────────────

function _skV18RenderSteps() {
  const nlContainer  = document.getElementById('skv18-nl-steps');
  const pyContainer  = document.getElementById('skv18-py-steps');
  if (!nlContainer || !pyContainer) return;

  if (_skV18Steps.length === 0) {
    nlContainer.innerHTML = `
      <div class="text-center text-slate-400 py-8 text-xs">
        <p>尚無 Steps</p>
        <p class="mt-1">填寫右側 NL 說明後，點擊「Generate Steps」</p>
      </div>`;
    pyContainer.innerHTML = `
      <div class="text-center text-slate-400 py-8 text-xs">
        <p>LLM 生成後 Python 程式碼將顯示於此</p>
      </div>`;
    return;
  }

  nlContainer.innerHTML = _skV18Steps.map((s, i) => `
    <div class="skv18-nl-card p-3 bg-white border border-slate-200 rounded-xl cursor-pointer
                transition-all hover:border-violet-400 hover:shadow-sm group"
         id="nl-card-${i}"
         onmouseenter="_skV18Highlight(${i}, true)"
         onmouseleave="_skV18Highlight(${i}, false)">
      <div class="flex items-center gap-2 mb-1.5">
        <span class="text-[10px] font-bold text-violet-600 uppercase tracking-widest
                     bg-violet-50 px-2 py-0.5 rounded-full border border-violet-100">
          ${_esc(s.step_id)}
        </span>
      </div>
      <p class="text-xs text-slate-700 leading-relaxed">${_esc(s.nl_segment)}</p>
    </div>
  `).join('');

  pyContainer.innerHTML = _skV18Steps.map((s, i) => `
    <div class="skv18-py-card" id="py-card-${i}">
      <div class="flex items-center justify-between mb-1">
        <span class="text-[10px] font-bold text-emerald-600 uppercase tracking-widest">${_esc(s.step_id)}</span>
      </div>
      <textarea id="py-code-${i}" rows="5"
                class="w-full bg-slate-800 text-green-300 font-mono text-[11px] rounded-lg p-3
                       border border-slate-600 resize-y outline-none leading-relaxed
                       focus:border-violet-500 focus:ring-1 focus:ring-violet-500"
                spellcheck="false"
                oninput="_skV18SyncCode(${i}, this.value)"
      >${_escCode(s.python_code || '')}</textarea>
    </div>
  `).join('');
}

function _escCode(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function _skV18SyncCode(index, value) {
  if (_skV18Steps[index]) _skV18Steps[index].python_code = value;
}

function _skV18Highlight(index, active) {
  const nl = document.getElementById(`nl-card-${index}`);
  const py = document.getElementById(`py-card-${index}`);
  if (nl) nl.classList.toggle('border-violet-500', active);
  if (nl) nl.classList.toggle('bg-violet-50', active);
  if (py) py.classList.toggle('ring-2', active);
  if (py) py.classList.toggle('ring-violet-400', active);
}

// ── Generate Steps (LLM) ────────────────────────────────────────

async function _skV18GenerateSteps() {
  const etId = parseInt(document.getElementById('skv18-trigger-event')?.value) || null;
  const nl   = document.getElementById('skv18-nl-desc')?.value?.trim();
  if (!nl || nl.length < 10) {
    alert('請先填寫 NL 說明（至少 10 字）');
    return;
  }
  const btn = document.getElementById('skv18-gen-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 生成中…'; }
  try {
    const body = { nl_description: nl, trigger_event_id: etId || 0 };
    const resp = await _api('POST', '/skill-definitions/generate-steps', body);
    if (!resp.success) throw new Error(resp.error || '生成失敗');
    _skV18Steps = resp.steps_mapping || [];
    _skV18OutputSchema = resp.output_schema || [];
    _skV18RenderSteps();
  } catch (e) {
    alert('Generate Steps 失敗：' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '✨ Generate Steps'; }
  }
}

// ── Try-Run ─────────────────────────────────────────────────────

async function _skV18TryRun() {
  // If unsaved, do a quick save first
  let skillId = _skV18Id;
  if (!skillId) {
    const saved = await _skV18Save(true);
    if (!saved) return;
    skillId = _skV18Id;
  }

  _skV18ClearConsole();
  _skV18Log('▶ Try-Run 開始…', 'text-violet-300');

  const payload = {
    event_type:    document.getElementById('skv18-try-event-type')?.value || 'SPC_OOC',
    equipment_id:  document.getElementById('skv18-try-eqp')?.value || 'EQP-01',
    lot_id:        document.getElementById('skv18-try-lot')?.value || 'LOT-0001',
    step:          document.getElementById('skv18-try-step')?.value || 'STEP_091',
    event_time:    new Date().toISOString(),
  };

  const btn = document.getElementById('skv18-try-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 執行中…'; }

  try {
    const resp = await _api('POST', `/skill-definitions/${skillId}/try-run`, { mock_payload: payload });
    if (resp.step_results) {
      resp.step_results.forEach(sr => {
        const icon = sr.status === 'ok' ? '✅' : sr.status === 'error' ? '❌' : '⏩';
        const cls  = sr.status === 'ok' ? 'text-green-400' : sr.status === 'error' ? 'text-red-400' : 'text-slate-400';
        _skV18Log(`${icon} [${sr.step_id}] ${sr.nl_segment}`, cls);
        if (sr.error) _skV18Log(`   └ 錯誤: ${sr.error}`, 'text-red-300');
      });
    }
    // ── findings (v2.0: condition_met + evidence) ──────────────
    const findings = resp.findings;
    if (findings) {
      _skV18Log('', '');
      const condIcon = findings.condition_met ? '🔴' : '🟢';
      _skV18Log(`${condIcon} condition_met = ${findings.condition_met}`, findings.condition_met ? 'text-red-400' : 'text-green-400');
      if (findings.impacted_lots?.length > 0) {
        _skV18Log(`   📦 impacted_lots: ${findings.impacted_lots.join(', ')}`, 'text-yellow-300');
      }
      const evKeys = Object.keys(findings.evidence || {});
      if (evKeys.length > 0) {
        _skV18Log('   📊 evidence:', 'text-slate-400');
        evKeys.forEach(k => {
          const v = findings.evidence[k];
          const display = Array.isArray(v) ? `[${v.length} rows]` : JSON.stringify(v);
          _skV18Log(`      ${k}: ${display}`, 'text-slate-300');
        });
      }
      if (findings.schema_warnings?.length > 0) {
        findings.schema_warnings.forEach(w => _skV18Log(`   ⚠ ${w}`, 'text-amber-400'));
      }
    }
    _skV18Log(`\n✅ 完成 · ${resp.total_elapsed_ms?.toFixed(0) || '—'}ms`, 'text-green-400');
  } catch (e) {
    _skV18Log('❌ Try-Run 失敗：' + e.message, 'text-red-400');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '▶ Try-Run'; }
  }
}

// ── Save ────────────────────────────────────────────────────────

async function _skV18Save(silent = false) {
  // Sync any textarea edits into _skV18Steps
  _skV18Steps.forEach((s, i) => {
    const ta = document.getElementById(`py-code-${i}`);
    if (ta) s.python_code = ta.value;
  });

  const name = document.getElementById('skv18-name')?.value?.trim();
  if (!name) { alert('請填寫 Skill 名稱'); return false; }

  const etId  = parseInt(document.getElementById('skv18-trigger-event')?.value) || null;
  const vis   = document.getElementById('skv18-visibility')?.value || 'private';

  const body = {
    name,
    description:       document.getElementById('skv18-desc')?.value?.trim() || '',
    trigger_event_id:  etId,
    trigger_mode:      _skV18CurrentMode,
    steps_mapping:     _skV18Steps,
    output_schema:     _skV18OutputSchema || [],
    visibility:        vis,
  };

  try {
    let resp;
    if (_skV18Id) {
      resp = await _api('PATCH', `/skill-definitions/${_skV18Id}`, body);
    } else {
      resp = await _api('POST', '/skill-definitions', body);
      _skV18Id = resp.id;
    }
    if (!silent) {
      _skV18Log(`✅ Skill 已儲存 (id=${_skV18Id})`, 'text-green-400');
    }
    return true;
  } catch (e) {
    alert('儲存失敗：' + e.message);
    return false;
  }
}


// ════════════════════════════════════════════════════════════════
// Auto-Patrol Page (v2.0)
// ════════════════════════════════════════════════════════════════

window._autoPatrolPage = (function () {

  let _patrols   = [];
  let _skillDefs = [];
  let _etypes    = [];
  let _editId    = null;   // null = create, int = edit

  const _SEV_STYLE = {
    CRITICAL: 'bg-red-100 text-red-700',
    HIGH:     'bg-orange-100 text-orange-700',
    MEDIUM:   'bg-yellow-100 text-yellow-700',
    LOW:      'bg-slate-100 text-slate-600',
  };

  // ── public: init ──────────────────────────────────────────────

  async function init() {
    try {
      [_patrols, _skillDefs, _etypes] = await Promise.all([
        _api('GET', '/auto-patrols'),
        _api('GET', '/skill-definitions'),
        _api('GET', '/event-types'),
      ]);
    } catch (e) {
      document.getElementById('ap-list').innerHTML =
        `<p class="text-center text-red-400 py-12 text-sm">載入失敗：${_esc(e.message)}</p>`;
      return;
    }
    _render();
  }

  // ── public: filter toggle ─────────────────────────────────────

  function applyFilters() {
    _render();
  }

  // ── render list ───────────────────────────────────────────────

  function _render() {
    const container = document.getElementById('ap-list');
    if (!container) return;
    const activeOnly = document.getElementById('ap-filter-active')?.checked;
    const list = activeOnly ? _patrols.filter(p => p.is_active) : _patrols;

    if (list.length === 0) {
      container.innerHTML = `
        <div class="text-center py-16 text-slate-400">
          <p class="text-sm">尚無 Auto-Patrol</p>
          <p class="text-xs mt-1">點擊右上角「+ 新增 Auto-Patrol」開始設定</p>
        </div>`;
      return;
    }

    container.innerHTML = list.map(p => {
      const skill = _skillDefs.find(s => s.id === p.skill_id);
      const etype = _etypes.find(e => e.id === p.event_type_id);
      const sevStyle = _SEV_STYLE[p.alarm_severity] || 'bg-slate-100 text-slate-600';
      const triggerLabel = p.trigger_mode === 'event'
        ? `⚡ Event: ${etype ? _esc(etype.name) : p.event_type_id || '—'}`
        : `🕐 排程: ${_esc(p.cron_expr || '—')}`;

      return `
        <div class="bg-white border border-slate-200 rounded-xl p-4 hover:border-violet-300 transition-colors">
          <div class="flex items-start justify-between gap-3">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <span class="font-medium text-sm text-slate-800">${_esc(p.name)}</span>
                ${p.is_active
                  ? '<span class="text-[10px] bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">啟用</span>'
                  : '<span class="text-[10px] bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">停用</span>'}
              </div>
              ${p.description ? `<p class="text-xs text-slate-500 mb-2">${_esc(p.description)}</p>` : ''}
              <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                <span>🔧 ${skill ? _esc(skill.name) : `Skill #${p.skill_id}`}</span>
                <span>${triggerLabel}</span>
                ${p.alarm_severity ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-medium ${sevStyle}">${p.alarm_severity}</span>` : ''}
              </div>
            </div>
            <div class="flex items-center gap-1 flex-shrink-0">
              <button onclick="_autoPatrolPage.triggerManual(${p.id}, '${_esc(p.name).replace(/'/g,"\\'")}')"
                title="手動觸發"
                class="w-8 h-8 flex items-center justify-center rounded-lg text-violet-500
                       hover:bg-violet-50 border border-transparent hover:border-violet-200 transition-colors text-sm">
                ▶
              </button>
              <button onclick="_autoPatrolPage.openEdit(${p.id})"
                title="編輯"
                class="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400
                       hover:text-slate-700 hover:bg-slate-100 transition-colors">
                <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
                  <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
              </button>
              <button onclick="_autoPatrolPage.deletePatrol(${p.id}, '${_esc(p.name).replace(/'/g,"\\'")}')"
                title="刪除"
                class="w-8 h-8 flex items-center justify-center rounded-lg text-slate-300
                       hover:text-red-500 hover:bg-red-50 transition-colors">
                <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/>
                  <path d="M10 11v6M14 11v6M9 6V4h6v2"/>
                </svg>
              </button>
            </div>
          </div>
        </div>`;
    }).join('');
  }

  // ── modal helpers ─────────────────────────────────────────────

  function _buildModalBody(p) {
    const skillOpts = _skillDefs.map(s =>
      `<option value="${s.id}"${p?.skill_id === s.id ? ' selected' : ''}>${_esc(s.name)}</option>`
    ).join('');
    const etOpts = _etypes.map(e =>
      `<option value="${e.id}"${p?.event_type_id === e.id ? ' selected' : ''}>${_esc(e.name)}</option>`
    ).join('');
    const mode = p?.trigger_mode || 'schedule';

    return `
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">名稱 <span class="text-red-400">*</span></label>
        <input id="ap-f-name" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400"
               value="${_esc(p?.name || '')}" placeholder="e.g. SPC-OOC-每5分鐘巡查" />
      </div>
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">說明</label>
        <textarea id="ap-f-desc" rows="2"
          class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-violet-400"
        >${_esc(p?.description || '')}</textarea>
      </div>
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">Skill <span class="text-red-400">*</span></label>
        <select id="ap-f-skill" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400">
          <option value="">— 請選擇 Skill —</option>
          ${skillOpts}
        </select>
      </div>
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">觸發模式</label>
        <div class="flex gap-3">
          <label class="flex items-center gap-1.5 text-xs cursor-pointer">
            <input type="radio" name="ap-trigger-mode" value="event" ${mode === 'event' ? 'checked' : ''}
                   onchange="_apToggleTriggerMode(this.value)" /> Event 觸發
          </label>
          <label class="flex items-center gap-1.5 text-xs cursor-pointer">
            <input type="radio" name="ap-trigger-mode" value="schedule" ${mode === 'schedule' ? 'checked' : ''}
                   onchange="_apToggleTriggerMode(this.value)" /> 排程觸發
          </label>
        </div>
      </div>
      <div id="ap-f-event-row" class="${mode === 'event' ? '' : 'hidden'}">
        <label class="block text-xs font-medium text-slate-600 mb-1">Event Type</label>
        <select id="ap-f-event-type" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400">
          <option value="">— 請選擇 Event Type —</option>
          ${etOpts}
        </select>
      </div>
      <div id="ap-f-cron-row" class="${mode === 'schedule' ? '' : 'hidden'}">
        <label class="block text-xs font-medium text-slate-600 mb-1">Cron 表達式</label>
        <input id="ap-f-cron" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-violet-400"
               value="${_esc(p?.cron_expr || '')}" placeholder="e.g. */5 * * * *" />
      </div>
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">Alarm 嚴重程度（條件成立時建立）</label>
        <select id="ap-f-severity" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400">
          <option value="">— 不建立 Alarm —</option>
          ${['LOW','MEDIUM','HIGH','CRITICAL'].map(s =>
            `<option value="${s}"${p?.alarm_severity === s ? ' selected' : ''}>${s}</option>`
          ).join('')}
        </select>
      </div>
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">Alarm 標題</label>
        <input id="ap-f-alarm-title" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400"
               value="${_esc(p?.alarm_title || '')}" placeholder="e.g. [SPC-OOC] 機台連續異常" />
      </div>
      <div>
        <label class="flex items-center gap-1.5 text-xs font-medium text-slate-600 cursor-pointer">
          <input type="checkbox" id="ap-f-active" ${p?.is_active !== false ? 'checked' : ''} />
          啟用此 Auto-Patrol
        </label>
      </div>
    `;
  }

  // ── public: open modal ────────────────────────────────────────

  function openCreate() {
    _editId = null;
    document.getElementById('ap-modal-title').textContent = '新增 Auto-Patrol';
    document.getElementById('ap-modal-body').innerHTML = _buildModalBody(null);
    document.getElementById('ap-modal').classList.remove('hidden');
  }

  async function openEdit(id) {
    _editId = id;
    const p = _patrols.find(x => x.id === id);
    document.getElementById('ap-modal-title').textContent = '編輯 Auto-Patrol';
    document.getElementById('ap-modal-body').innerHTML = _buildModalBody(p);
    document.getElementById('ap-modal').classList.remove('hidden');
  }

  function closeModal() {
    document.getElementById('ap-modal').classList.add('hidden');
    _editId = null;
  }

  // ── public: save ──────────────────────────────────────────────

  async function save() {
    const name     = document.getElementById('ap-f-name')?.value?.trim();
    const skillId  = parseInt(document.getElementById('ap-f-skill')?.value) || null;
    if (!name) { alert('請填寫名稱'); return; }
    if (!skillId) { alert('請選擇 Skill'); return; }

    const modeEl   = document.querySelector('input[name="ap-trigger-mode"]:checked');
    const mode     = modeEl?.value || 'schedule';
    const etId     = parseInt(document.getElementById('ap-f-event-type')?.value) || null;
    const cronExpr = document.getElementById('ap-f-cron')?.value?.trim() || null;
    const severity = document.getElementById('ap-f-severity')?.value || null;
    const title    = document.getElementById('ap-f-alarm-title')?.value?.trim() || null;
    const isActive = document.getElementById('ap-f-active')?.checked ?? true;

    const body = {
      name,
      description:    document.getElementById('ap-f-desc')?.value?.trim() || '',
      skill_id:       skillId,
      trigger_mode:   mode,
      event_type_id:  mode === 'event' ? etId : null,
      cron_expr:      mode === 'schedule' ? cronExpr : null,
      alarm_severity: severity || null,
      alarm_title:    title || null,
      is_active:      isActive,
    };

    const btn = document.getElementById('ap-modal-save');
    if (btn) { btn.disabled = true; btn.textContent = '儲存中…'; }
    try {
      if (_editId) {
        await _api('PATCH', `/auto-patrols/${_editId}`, body);
      } else {
        await _api('POST', '/auto-patrols', body);
      }
      closeModal();
      await init();
    } catch (e) {
      alert('儲存失敗：' + e.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '儲存'; }
    }
  }

  // ── public: delete ────────────────────────────────────────────

  async function deletePatrol(id, name) {
    if (!confirm(`確定要刪除「${name}」？`)) return;
    try {
      await _api('DELETE', `/auto-patrols/${id}`);
      await init();
    } catch (e) { alert('刪除失敗：' + e.message); }
  }

  // ── public: manual trigger ────────────────────────────────────

  async function triggerManual(id, name) {
    const equipId = prompt(`手動觸發「${name}」\n\n請輸入 equipment_id（可留空）:`) ?? '';
    const lotId   = prompt('lot_id（可留空）:') ?? '';

    const payload = {};
    if (equipId.trim()) payload.equipment_id = equipId.trim();
    if (lotId.trim())   payload.lot_id = lotId.trim();

    try {
      const resp = await _api('POST', `/auto-patrols/${id}/trigger`, { event_payload: payload });
      const condIcon = resp.condition_met ? '🔴' : '🟢';
      const alarmNote = resp.alarm_created ? `\n🔔 Alarm 已建立 (id=${resp.alarm_id})` : '';
      alert(`${condIcon} condition_met = ${resp.condition_met}${alarmNote}`);
    } catch (e) {
      alert('觸發失敗：' + e.message);
    }
  }

  // ── public API ────────────────────────────────────────────────

  return { init, applyFilters, openCreate, openEdit, closeModal, save, deletePatrol, triggerManual };

})();

// ── helper: toggle event/cron rows in modal ───────────────────────────────────

function _apToggleTriggerMode(mode) {
  const eventRow = document.getElementById('ap-f-event-row');
  const cronRow  = document.getElementById('ap-f-cron-row');
  if (eventRow) eventRow.classList.toggle('hidden', mode !== 'event');
  if (cronRow)  cronRow.classList.toggle('hidden', mode !== 'schedule');
}
