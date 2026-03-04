/**
 * Glass Box Builder — Phase 8 Frontend
 *
 * Handles: Navigation, DataSubjects, EventTypes, MCP Builder, Skill Builder
 * All drawers are w-[60vw] per PRD §6
 */

'use strict';

// ══════════════════════════════════════════════════════════════
// State
// ══════════════════════════════════════════════════════════════
let _currentView    = 'diagnose';
let _currentDrawer  = null;  // active drawer type
let _editingId      = null;  // ID being edited (null = create)
let _dataSubjects   = [];
let _eventTypes     = [];
let _mcpDefs        = [];
let _skillDefs      = [];
// Temp state for MCP builder multi-step
let _mcpGenerating  = false;
let _mcpGenResult   = null;
// Phase 8.3 Try Run state
let _sampleData     = null;   // raw JSON fetched from DS API
let _tryRunPassed   = false;  // true once sandbox execution succeeds
let _tryRunResult   = null;   // full result from the last successful try-run
// Phase 8.4 Skill diagnosis state
let _skillDiagPassed = false; // true once skill simulation diagnosis succeeds
// Phase 8.9.2 Skill builder state (1-to-1)
let _selectedSkillMcp   = null;  // Single MCP ID bound to the skill (1-to-1)
let _skillMcpExecResult = null;  // MCPTryRunResponse from latest full-chain execution
let _diagnosisRunResult = null;  // Saved after successful _runCodeDiagnosis (diagnosis_message, problem_object, check_output_schema)
// Phase 11 v2 — ET diagnosis skills state
let _etDiagnosisSkills  = [];   // [{skill_id, param_mappings}] for the open ET drawer
let _etPendingSkillId   = null; // skill being configured before "加入清單"

let _drawerDirty = false;  // true when user has unsaved changes in the open drawer
// Phase 8.5 Settings state
let _systemParams   = [];
// Phase 8.6 Try-tab + UX state
let _tryTabs            = [];   // Array of { n, intent, status }
let _activeTryTabN      = 1;    // 1-indexed active try tab
let _diagnoseWelcomeSent = false;
// Suggested prompts from intent check (keyed by tab n)
const _suggestedIntents = {};

// ══════════════════════════════════════════════════════════════
// API helpers
// ══════════════════════════════════════════════════════════════

async function _api(method, path, body) {
  const opts = {
    method,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${_token}`,
    },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`/api/v1${path}`, opts);
  const json = await res.json();
  if (!res.ok) throw new Error(json.message || `HTTP ${res.status}`);
  // StandardResponse wraps payload in .data; some legacy endpoints return directly
  return json.data !== undefined ? json.data : json;
}

function _esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _prettyJson(obj) {
  try {
    return JSON.stringify(obj, null, 2);
  } catch { return '{}'; }
}

// ══════════════════════════════════════════════════════════════
// Navigation
// ══════════════════════════════════════════════════════════════

function switchView(name) {
  // Deactivate all views
  document.querySelectorAll('.view-panel').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active-nav'));

  const view = document.getElementById(`view-${name}`);
  if (view) view.classList.remove('hidden');
  const nav = document.getElementById(`nav-${name}`);
  if (nav) nav.classList.add('active-nav');

  _currentView = name;

  // Refresh data when switching to builder views
  if (name === 'data-subjects')   _loadDataSubjects();
  if (name === 'event-types')     _loadEventTypes();
  if (name === 'mcp-builder')     _loadMcpDefs();
  if (name === 'skill-builder')   _loadSkillDefs();
  if (name === 'settings')        _loadSettings();
  if (name === 'routine-checks')  _loadRoutineChecks();
  if (name === 'generated-events') _loadGeneratedEvents();

  // Phase 8.6: send AI welcome message once when entering diagnose view
  if (name === 'diagnose' && !_diagnoseWelcomeSent) {
    _diagnoseWelcomeSent = true;
    setTimeout(() => {
      if (typeof _addChatBubble === 'function') {
        _addChatBubble('agent', '👋 您好！我是 AI Ops 智能診斷助手。<br>請描述您觀察到的異常症狀，或點擊上方「⚡ 模擬觸發」按鈕來快速測試診斷管線。');
      }
    }, 600);
  }
}

// ══════════════════════════════════════════════════════════════
// Drawer helpers
// ══════════════════════════════════════════════════════════════

function openDrawer(type, id) {
  _currentDrawer = type;
  _editingId = id || null;
  _mcpGenResult = null;
  _selectedSkillMcp = null;
  _skillMcpExecResult = null;
  _diagnosisRunResult = null;
  _tryRunResult = null;
  _skillDiagPassed = false;
  _drawerDirty = false;

  const overlay = document.getElementById('drawer-overlay');
  const drawer  = document.getElementById('drawer');
  overlay.classList.remove('hidden');
  drawer.classList.add('drawer-open');

  _renderDrawerContent(type, id);
}

// Pass force=true after a successful save to skip the confirmation dialog.
function closeDrawer(force = false) {
  if (!force && _drawerDirty) {
    if (!confirm('您有尚未儲存的變更，確定要放棄並關閉？')) return;
  }
  document.getElementById('drawer-overlay').classList.add('hidden');
  document.getElementById('drawer').classList.remove('drawer-open');
  _currentDrawer = null;
  _editingId = null;
  _drawerDirty = false;
}

function _setDrawerContent(title, body, footer) {
  document.getElementById('drawer-title').innerHTML = title;
  document.getElementById('drawer-body').innerHTML  = body;
  document.getElementById('drawer-footer').innerHTML = footer;
}

// Mark drawer dirty whenever user types or changes any input/select/textarea inside it.
// Attached once at page load via event delegation on drawer-body.
(function _attachDrawerDirtyListeners() {
  const body = document.getElementById('drawer-body');
  if (!body) return;
  const mark = () => { if (_currentDrawer) _drawerDirty = true; };
  body.addEventListener('input',  mark);
  body.addEventListener('change', mark);
})();

async function _renderDrawerContent(type, id) {
  switch (type) {
    case 'ds-create':
    case 'ds-edit':
      await _renderDSDrawer(id);
      break;
    case 'et-create':
    case 'et-edit':
      await _renderETDrawer(id);
      break;
    case 'mcp-create':
    case 'mcp-edit':
      await _renderMCPDrawer(id);
      break;
    case 'skill-create':
    case 'skill-edit':
      await _renderSkillDrawer(id);
      break;
    case 'routine-check-create':
    case 'routine-check-edit':
      _openRoutineCheckDrawer(id);
      break;
  }
}

// ══════════════════════════════════════════════════════════════
// DATA SUBJECTS
// ══════════════════════════════════════════════════════════════

async function _loadDataSubjects() {
  const container = document.getElementById('ds-list');
  try {
    _dataSubjects = await _api('GET', '/data-subjects') || [];
    if (_dataSubjects.length === 0) {
      container.innerHTML = '<p class="text-center text-slate-600 py-12">尚無 DataSubject，點擊右上角新增</p>';
      return;
    }
    container.innerHTML = _dataSubjects.map(ds => `
      <div class="builder-card" onclick="openDrawer('ds-edit', ${ds.id})">
        <div class="flex-1">
          <div class="flex items-center gap-2">
            <span class="builder-card-name">${_esc(ds.name)}</span>
            ${ds.is_builtin ? '<span class="builder-tag builder-tag-builtin">內建</span>' : ''}
          </div>
          <div class="builder-card-desc">${_esc(ds.description || '（無說明）')}</div>
          <div class="builder-card-meta">
            <span class="builder-tag">${_esc(ds.api_config?.method || 'GET')} ${_esc(ds.api_config?.endpoint_url || '')}</span>
          </div>
        </div>
        <div class="text-slate-600 text-sm">›</div>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<p class="text-center text-red-400 py-12">載入失敗：${_esc(e.message)}</p>`;
  }
}

async function _renderDSDrawer(id) {
  let ds = null;
  if (id) {
    ds = _dataSubjects.find(d => d.id === id) || await _api('GET', `/data-subjects/${id}`);
  }
  const title = id ? `編輯 Data Subject — ${_esc(ds?.name || '')}` : '新增 Data Subject';
  const apiConfig  = ds?.api_config  || { endpoint_url: '', method: 'GET', headers: {} };
  const inSchema   = ds?.input_schema  || { fields: [] };
  const outSchema  = ds?.output_schema || { fields: [] };
  const isBuiltin  = ds?.is_builtin || false;
  const readOnly   = isBuiltin ? 'disabled' : '';
  const roMsg      = isBuiltin ? '<p class="text-xs text-amber-400 mb-4 bg-amber-400/10 border border-amber-400/20 rounded-lg px-3 py-2">⚠ 內建 DataSubject 不可修改</p>' : '';

  const body = `
    ${roMsg}
    <div class="builder-field">
      <label class="builder-label required">名稱</label>
      <input id="ds-name" class="builder-input" value="${_esc(ds?.name || '')}" placeholder="e.g. APC_Data" ${readOnly} />
    </div>
    <div class="builder-field">
      <label class="builder-label">說明</label>
      <textarea id="ds-desc" class="builder-textarea" rows="2" placeholder="資料源用途說明" ${readOnly}>${_esc(ds?.description || '')}</textarea>
    </div>
    <div class="builder-field">
      <label class="builder-label required">API Endpoint URL</label>
      <input id="ds-url" class="builder-input" value="${_esc(apiConfig.endpoint_url)}" placeholder="/api/v1/mock/apc" ${readOnly} />
    </div>
    <div class="builder-field">
      <label class="builder-label">HTTP Method</label>
      <select id="ds-method" class="builder-select" ${readOnly}>
        <option value="GET" ${apiConfig.method === 'GET' ? 'selected' : ''}>GET</option>
        <option value="POST" ${apiConfig.method === 'POST' ? 'selected' : ''}>POST</option>
      </select>
    </div>
    <div class="builder-field">
      <label class="builder-label">Headers (JSON)</label>
      <textarea id="ds-headers" class="builder-textarea font-mono text-xs" rows="3" ${readOnly}>${_esc(_prettyJson(apiConfig.headers || {}))}</textarea>
    </div>
    <div class="builder-field">
      <label class="builder-label">Input Schema (JSON)</label>
      <textarea id="ds-input-schema" class="builder-textarea font-mono text-xs" rows="6" ${readOnly}>${_esc(_prettyJson(inSchema))}</textarea>
    </div>
    <div class="builder-field">
      <label class="builder-label">Output Schema (JSON)</label>
      <textarea id="ds-output-schema" class="builder-textarea font-mono text-xs" rows="6" ${readOnly}>${_esc(_prettyJson(outSchema))}</textarea>
    </div>
  `;

  const footer = isBuiltin ? `
    <button class="builder-btn-secondary" onclick="closeDrawer()">關閉</button>
  ` : `
    <button class="builder-btn-secondary" onclick="closeDrawer()">取消</button>
    ${id ? `<button class="builder-btn-danger mr-auto" onclick="_deleteDS(${id})">刪除</button>` : ''}
    <button class="builder-btn-primary" onclick="_saveDS(${id || 'null'})">
      ${id ? '更新' : '建立'}
    </button>
  `;

  _setDrawerContent(title, body, footer);
}

async function _saveDS(id) {
  const name = document.getElementById('ds-name').value.trim();
  if (!name) { alert('請填寫名稱'); return; }
  let headers = {};
  try { headers = JSON.parse(document.getElementById('ds-headers').value || '{}'); } catch {}
  let inputSchema = {};
  try { inputSchema = JSON.parse(document.getElementById('ds-input-schema').value || '{}'); } catch {}
  let outputSchema = {};
  try { outputSchema = JSON.parse(document.getElementById('ds-output-schema').value || '{}'); } catch {}

  const body = {
    name,
    description: document.getElementById('ds-desc').value.trim(),
    api_config: {
      endpoint_url: document.getElementById('ds-url').value.trim(),
      method: document.getElementById('ds-method').value,
      headers,
    },
    input_schema: inputSchema,
    output_schema: outputSchema,
  };
  try {
    if (id) {
      await _api('PATCH', `/data-subjects/${id}`, body);
    } else {
      await _api('POST', '/data-subjects', body);
    }
    closeDrawer(true);
    _loadDataSubjects();
  } catch (e) {
    alert(`儲存失敗：${e.message}`);
  }
}

async function _deleteDS(id) {
  if (!confirm('確定要刪除此 DataSubject？')) return;
  try {
    await _api('DELETE', `/data-subjects/${id}`);
    closeDrawer(true);
    _loadDataSubjects();
  } catch (e) { alert(`刪除失敗：${e.message}`); }
}

// ══════════════════════════════════════════════════════════════
// EVENT TYPES
// ══════════════════════════════════════════════════════════════

async function _loadEventTypes() {
  const container = document.getElementById('et-list');
  try {
    _eventTypes = await _api('GET', '/event-types') || [];
    if (_eventTypes.length === 0) {
      container.innerHTML = '<p class="text-center text-slate-600 py-12">尚無 Event Type，點擊右上角新增</p>';
      return;
    }
    container.innerHTML = _eventTypes.map(et => `
      <div class="builder-card" onclick="openDrawer('et-edit', ${et.id})">
        <div class="flex-1">
          <div class="builder-card-name">${_esc(et.name)}</div>
          <div class="builder-card-desc">${_esc(et.description || '（無說明）')}</div>
          <div class="builder-card-meta">
            <span class="builder-tag">${(et.attributes || []).length} 個屬性</span>
          </div>
        </div>
        <div class="text-slate-600 text-sm">›</div>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<p class="text-center text-red-400 py-12">載入失敗：${_esc(e.message)}</p>`;
  }
}

async function _renderETDrawer(id) {
  let et = null;
  if (id) et = _eventTypes.find(e => e.id === id) || await _api('GET', `/event-types/${id}`);
  // Ensure skill list is available for the skills table
  if (_skillDefs.length === 0) {
    try { _skillDefs = await _api('GET', '/skill-definitions') || []; } catch {}
  }
  const attrs = et?.attributes || [];
  const title = id ? `編輯 Event Type — ${_esc(et?.name || '')}` : '新增 Event Type';

  const attrsHtml = attrs.map((a, i) => _attrRowHtml(i, a)).join('');

  const body = `
    <div class="builder-field">
      <label class="builder-label required">Event Type 名稱</label>
      <input id="et-name" class="builder-input" value="${_esc(et?.name || '')}" placeholder="e.g. SPC_OOC_Etch" />
    </div>
    <div class="builder-field">
      <label class="builder-label required">說明（LLM 映射依賴此欄位）</label>
      <textarea id="et-desc" class="builder-textarea" rows="2" placeholder="描述此事件的業務意義">${_esc(et?.description || '')}</textarea>
    </div>
    <!-- ══ Skills section (first) ══════════════════════════════════ -->
    <div class="builder-field mt-4">
      <label class="builder-label">診斷 Skills（觸發此 EventType 時依序執行）</label>
      <p class="text-xs text-slate-500 mb-3">加入 Skill 並設定 MCP 參數映射（EventType 屬性 → MCP 輸入）</p>

      <!-- Skills already bound — cards -->
      <div id="et-skills-table-wrap" class="mb-3">
        <!-- rendered by _renderEtSkillsTable() -->
      </div>

      <!-- Add skill: keyword search + dropdown -->
      <div class="relative">
        <input id="et-skill-search" type="text" autocomplete="off"
          class="builder-input pr-8" placeholder="搜尋 Skill 名稱..."
          oninput="_filterEtSkillDropdown()" onfocus="_filterEtSkillDropdown()"
          onblur="setTimeout(()=>document.getElementById('et-skill-dropdown')?.classList.add('hidden'),200)" />
        <div id="et-skill-dropdown"
          class="hidden absolute z-20 w-full bg-white border border-slate-200 rounded-lg shadow-lg max-h-44 overflow-y-auto mt-1 text-sm">
        </div>
      </div>

      <!-- Param-mapping config for the skill being added -->
      <div id="et-skill-mapping-panel" class="hidden mt-3 border border-indigo-200 rounded-xl bg-indigo-50/40 p-4">
        <div class="flex items-start justify-between gap-2 mb-3">
          <div class="flex-1 min-w-0">
            <span id="et-skill-mapping-title" class="text-sm font-semibold text-indigo-700 block"></span>
            <span id="et-skill-mapping-desc" class="text-xs text-slate-500 mt-0.5 block leading-relaxed"></span>
          </div>
          <button class="text-xs text-slate-400 hover:text-slate-600 flex-shrink-0" onclick="_cancelEtSkillAdd()">✕ 取消</button>
        </div>
        <div class="grid text-xs text-slate-500 font-medium mb-2 px-0.5"
             style="grid-template-columns:1fr 18px 1fr;gap:8px;">
          <span>MCP 輸入參數</span><span></span><span>對應 Event 屬性</span>
        </div>
        <div id="et-skill-mapping-rows" class="mb-2"></div>
        <div id="et-skill-mapping-status" class="mb-2"></div>
        <div class="flex gap-2">
          <button class="builder-btn-secondary text-xs flex-1" onclick="_autoMapEtSkill()">✨ LLM 自動映射</button>
          <button class="builder-btn-primary text-xs flex-1" onclick="_confirmEtSkillAdd()">+ 加入清單</button>
        </div>
      </div>
    </div>

    <!-- ══ Attributes section (second) ═════════════════════════════ -->
    <div class="flex items-center justify-between mb-3 mt-5">
      <span class="text-sm font-medium text-slate-700">屬性列表</span>
      <button onclick="_addAttrRow()" class="builder-btn-secondary text-xs px-3 py-1.5">+ 新增屬性</button>
    </div>
    <div class="text-xs text-amber-600 mb-3 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
      ⚠ 每個屬性的「說明」為 LLM 自動映射的關鍵，<strong>必須填寫</strong>
    </div>
    <div class="grid text-xs text-slate-500 font-medium mb-1 px-1"
         style="grid-template-columns: 1fr 100px 1fr auto; gap: 8px;">
      <span>屬性名稱</span><span>類型</span><span>說明 (必填)</span><span></span>
    </div>
    <div id="et-attrs-container">
      ${attrsHtml}
    </div>
  `;

  const footer = `
    <button class="builder-btn-secondary" onclick="closeDrawer()">取消</button>
    ${id ? `<button class="builder-btn-danger mr-auto" onclick="_deleteET(${id})">刪除</button>` : ''}
    <button class="builder-btn-primary" onclick="_saveET(${id || 'null'})">
      ${id ? '更新' : '建立'}
    </button>
  `;
  _setDrawerContent(title, body, footer);

  // Initialize diagnosis skills state and render the table
  _etDiagnosisSkills = (et?.diagnosis_skills || []).map(s => ({
    skill_id: s.skill_id,
    param_mappings: s.param_mappings || [],
  }));
  _etPendingSkillId = null;
  _renderEtSkillsTable();
}

function _attrRowHtml(i, a) {
  a = a || {};
  return `
    <div class="attr-row" id="attr-row-${i}">
      <input class="builder-input attr-name" data-idx="${i}" value="${_esc(a.name || '')}" placeholder="lot_id" />
      <select class="builder-select attr-type" data-idx="${i}">
        <option value="string"  ${(a.type||'string')==='string' ?'selected':''}>string</option>
        <option value="number"  ${a.type==='number'  ?'selected':''}>number</option>
        <option value="boolean" ${a.type==='boolean' ?'selected':''}>boolean</option>
      </select>
      <input class="builder-input attr-desc" data-idx="${i}" value="${_esc(a.description || '')}" placeholder="批次 ID（必填）" />
      <button class="builder-btn-danger" onclick="_removeAttrRow(${i})">✕</button>
    </div>
  `;
}

function _addAttrRow() {
  const container = document.getElementById('et-attrs-container');
  const idx = container.querySelectorAll('.attr-row').length;
  container.insertAdjacentHTML('beforeend', _attrRowHtml(idx, {}));
}

function _removeAttrRow(i) {
  document.getElementById(`attr-row-${i}`)?.remove();
}

function _collectAttrs() {
  const rows = document.querySelectorAll('#et-attrs-container .attr-row');
  const attrs = [];
  for (const row of rows) {
    const name = row.querySelector('.attr-name')?.value.trim();
    const type = row.querySelector('.attr-type')?.value;
    const desc = row.querySelector('.attr-desc')?.value.trim();
    if (!name) continue;
    if (!desc) {
      alert(`屬性「${name}」的說明為必填項！`);
      return null;
    }
    attrs.push({ name, type: type || 'string', description: desc, required: true });
  }
  return attrs;
}

async function _saveET(id) {
  const name = document.getElementById('et-name').value.trim();
  const desc = document.getElementById('et-desc').value.trim();
  if (!name || !desc) { alert('名稱與說明均為必填'); return; }
  const attrs = _collectAttrs();
  if (attrs === null) return;

  const body = { name, description: desc, attributes: attrs, diagnosis_skills: _etDiagnosisSkills };
  try {
    if (id) await _api('PATCH', `/event-types/${id}`, body);
    else    await _api('POST', '/event-types', body);
    closeDrawer(true);
    _loadEventTypes();
  } catch (e) { alert(`儲存失敗：${e.message}`); }
}

async function _deleteET(id) {
  if (!confirm('確定要刪除此 Event Type？')) return;
  try {
    await _api('DELETE', `/event-types/${id}`);
    closeDrawer(true);
    _loadEventTypes();
  } catch (e) { alert(`刪除失敗：${e.message}`); }
}

// ── ET Skills table helpers ──────────────────────────────────

function _renderEtSkillsTable() {
  const wrap = document.getElementById('et-skills-table-wrap');
  if (!wrap) return;
  if (_etDiagnosisSkills.length === 0) {
    wrap.innerHTML = '<p class="text-xs text-slate-400 text-center py-3 border border-dashed border-slate-200 rounded-xl">尚無綁定 Skill，請從下方搜尋加入</p>';
    return;
  }
  wrap.innerHTML = _etDiagnosisSkills.map(binding => {
    const skill = _skillDefs.find(s => s.id === binding.skill_id);
    const skillName = skill ? skill.name : `Skill #${binding.skill_id}`;
    const skillDesc = skill?.description || '';
    const mappings = (binding.param_mappings || []).filter(m => m.event_field && m.mcp_param);
    const pills = mappings.map(m =>
      `<span class="inline-block text-xs bg-indigo-50 text-indigo-600 border border-indigo-100 rounded px-1.5 py-0.5 font-mono">${_esc(m.mcp_param)} ← ${_esc(m.event_field)}</span>`
    ).join('');
    return `
      <div class="border border-slate-200 rounded-xl bg-white p-3 mb-2">
        <div class="flex items-start justify-between gap-2">
          <div class="flex-1 min-w-0">
            <div class="text-sm font-semibold text-slate-800">${_esc(skillName)}</div>
            ${skillDesc ? `<div class="text-xs text-slate-500 mt-0.5 leading-relaxed line-clamp-2">${_esc(skillDesc)}</div>` : ''}
            <div class="mt-2 flex flex-wrap gap-1">
              ${mappings.length > 0 ? pills : '<span class="text-xs text-slate-400">（無參數映射）</span>'}
            </div>
          </div>
          <button class="text-red-400 hover:text-red-600 text-xs flex-shrink-0 mt-0.5 px-1" onclick="_removeEtSkill(${binding.skill_id})">✕</button>
        </div>
      </div>
    `;
  }).join('');
}

function _filterEtSkillDropdown() {
  const input = document.getElementById('et-skill-search');
  const dropdown = document.getElementById('et-skill-dropdown');
  if (!input || !dropdown) return;
  const q = input.value.trim().toLowerCase();
  const alreadyAdded = new Set(_etDiagnosisSkills.map(s => s.skill_id));
  const filtered = _skillDefs.filter(s =>
    !alreadyAdded.has(s.id) && (q === '' || s.name.toLowerCase().includes(q))
  );
  if (filtered.length === 0) {
    dropdown.innerHTML = '<div class="px-3 py-2 text-slate-400 text-xs">無符合結果</div>';
    dropdown.classList.remove('hidden');
    return;
  }
  dropdown.innerHTML = filtered.map(s =>
    `<div class="px-3 py-2 hover:bg-indigo-50 cursor-pointer text-slate-800 text-sm transition-colors"
          onmousedown="_selectEtSkillToAdd(${s.id})">${_esc(s.name)}</div>`
  ).join('');
  dropdown.classList.remove('hidden');
}

async function _selectEtSkillToAdd(skillId) {
  const skill = _skillDefs.find(s => s.id === skillId);
  if (!skill) return;
  _etPendingSkillId = skillId;
  document.getElementById('et-skill-dropdown')?.classList.add('hidden');
  document.getElementById('et-skill-search').value = skill.name;
  // Show mapping panel with skill info
  document.getElementById('et-skill-mapping-title').textContent = `設定「${skill.name}」的參數映射`;
  const descEl = document.getElementById('et-skill-mapping-desc');
  if (descEl) descEl.textContent = skill.description || '';
  const statusEl = document.getElementById('et-skill-mapping-status');
  if (statusEl) statusEl.innerHTML = '';
  await _renderEtMappingRows(skillId, []);
  document.getElementById('et-skill-mapping-panel')?.classList.remove('hidden');
  // Auto-trigger LLM mapping immediately
  await _autoMapEtSkill();
}

function _getEtCurrentAttrs() {
  const attrs = [];
  document.querySelectorAll('#et-attrs-container .attr-row').forEach(row => {
    const name = row.querySelector('.attr-name')?.value.trim();
    if (name) attrs.push(name);
  });
  return attrs;
}

function _getEtCurrentAttrObjects() {
  const attrs = [];
  document.querySelectorAll('#et-attrs-container .attr-row').forEach(row => {
    const name = row.querySelector('.attr-name')?.value.trim();
    const type = row.querySelector('.attr-type')?.value || 'string';
    const desc = row.querySelector('.attr-desc')?.value.trim();
    if (name) attrs.push({ name, type, description: desc || '' });
  });
  return attrs;
}

async function _renderEtMappingRows(skillId, existingMappings) {
  const container = document.getElementById('et-skill-mapping-rows');
  if (!container) return;
  const skill = _skillDefs.find(s => s.id === skillId);
  if (!skill) { container.innerHTML = ''; return; }

  // Resolve first MCP, then its DataSubject input_schema fields
  let mcpParams = [];
  let mcpParamDescs = {};
  let mcpIdList = [];
  try { mcpIdList = JSON.parse(skill.mcp_ids || '[]'); } catch {}
  if (!Array.isArray(mcpIdList)) mcpIdList = mcpIdList ? [mcpIdList] : [];
  if (mcpIdList.length === 0 && skill.mcp_id) mcpIdList = [skill.mcp_id];
  const mcpId = mcpIdList[0] || null;

  if (mcpId) {
    if (_mcpDefs.length === 0) {
      try { _mcpDefs = await _api('GET', '/mcp-definitions') || []; } catch {}
    }
    const mcp = _mcpDefs.find(m => m.id === mcpId);
    if (mcp?.data_subject_id) {
      // Lazy-load DataSubjects if needed
      if (_dataSubjects.length === 0) {
        try { _dataSubjects = await _api('GET', '/data-subjects') || []; } catch {}
      }
      const ds = _dataSubjects.find(d => d.id === mcp.data_subject_id);
      if (ds?.input_schema) {
        try {
          const schema = typeof ds.input_schema === 'string'
            ? JSON.parse(ds.input_schema) : ds.input_schema;
          const fields = schema.fields || [];
          for (const f of fields) {
            if (f.name) {
              mcpParams.push(f.name);
              mcpParamDescs[f.name] = f.description || '';
            }
          }
        } catch {}
      }
    }
  }

  const attrs = _getEtCurrentAttrs();
  if (mcpParams.length === 0) {
    container.innerHTML = '<p class="text-xs text-slate-500 text-center py-2">找不到此 Skill MCP 對應的 DataSubject 查詢參數</p>';
    return;
  }

  const existingMap = {};
  for (const m of (existingMappings || [])) existingMap[m.mcp_param] = m.event_field;

  container.innerHTML = mcpParams.map(param => {
    const desc = mcpParamDescs[param] || '';
    return `
      <div class="grid gap-2 items-start mb-2" style="grid-template-columns:1fr 18px 1fr">
        <div class="min-w-0">
          <div class="text-xs font-mono bg-slate-100 rounded px-2 py-1 text-slate-700 truncate"
               title="${_esc(desc || param)}">${_esc(param)}</div>
          ${desc ? `<div class="text-xs text-slate-400 truncate px-1 mt-0.5 leading-tight">${_esc(desc)}</div>` : ''}
        </div>
        <div class="text-slate-400 text-xs text-center pt-1.5">←</div>
        <select class="builder-select text-xs et-map-select" data-mcp-param="${_esc(param)}" data-mcp-id="${mcpId || ''}">
          <option value="">(不映射)</option>
          ${attrs.map(a => `<option value="${_esc(a)}" ${existingMap[param] === a ? 'selected' : ''}>${_esc(a)}</option>`).join('')}
        </select>
      </div>
    `;
  }).join('');
}

async function _autoMapEtSkill() {
  const skillId = _etPendingSkillId;
  if (!skillId) return;
  const statusEl = document.getElementById('et-skill-mapping-status');

  // Build event_schema from current ET attributes
  const attrObjs = _getEtCurrentAttrObjects();
  const event_schema = {};
  for (const a of attrObjs) {
    event_schema[a.name] = { type: a.type || 'string', description: a.description || a.name };
  }

  // Resolve MCP id from skill
  const skill = _skillDefs.find(s => s.id === skillId);
  if (!skill) return;
  let mcpIdList = [];
  try { mcpIdList = JSON.parse(skill.mcp_ids || '[]'); } catch {}
  if (!Array.isArray(mcpIdList)) mcpIdList = mcpIdList ? [mcpIdList] : [];
  if (mcpIdList.length === 0 && skill.mcp_id) mcpIdList = [skill.mcp_id];
  const mcpId = mcpIdList[0] || null;

  // Fallback to name-based if no attrs or no MCP
  if (Object.keys(event_schema).length === 0 || !mcpId) {
    _autoMapEtSkillByName();
    return;
  }

  const mcp = _mcpDefs.find(m => m.id === mcpId);
  if (!mcp) { _autoMapEtSkillByName(); return; }

  // Build tool_input_schema from DataSubject.input_schema (not mcp.input_definition)
  let tool_input_schema = {};
  if (mcp.data_subject_id) {
    if (_dataSubjects.length === 0) {
      try { _dataSubjects = await _api('GET', '/data-subjects') || []; } catch {}
    }
    const ds = _dataSubjects.find(d => d.id === mcp.data_subject_id);
    if (ds?.input_schema) {
      try {
        const schema = typeof ds.input_schema === 'string'
          ? JSON.parse(ds.input_schema) : ds.input_schema;
        const fields = schema.fields || [];
        const properties = {};
        const required = [];
        for (const f of fields) {
          if (!f.name) continue;
          properties[f.name] = { type: f.type || 'string', description: f.description || f.name };
          if (f.required) required.push(f.name);
        }
        tool_input_schema = { type: 'object', properties, required };
      } catch {}
    }
  }

  if (!Object.keys(tool_input_schema.properties || {}).length) {
    _autoMapEtSkillByName();
    return;
  }

  if (statusEl) statusEl.innerHTML = '<p class="text-xs text-indigo-500 italic flex items-center gap-1"><span class="llm-spinner" style="width:10px;height:10px;flex-shrink:0"></span> LLM 語意映射中...</p>';

  try {
    const result = await _api('POST', '/builder/auto-map', { event_schema, tool_input_schema });
    const mappings = result.mappings || [];
    let applied = 0;
    for (const m of mappings) {
      if (!m.event_field) continue;
      const sel = document.querySelector(`#et-skill-mapping-rows .et-map-select[data-mcp-param="${m.tool_param}"]`);
      if (sel) { sel.value = m.event_field; applied++; }
    }
    if (statusEl) statusEl.innerHTML = applied > 0
      ? `<p class="text-xs text-indigo-400 italic">✨ ${applied} 個參數已映射。${_esc(result.summary || '')}</p>`
      : `<p class="text-xs text-slate-500 italic">LLM 無法自動映射，請手動選擇。</p>`;
  } catch (e) {
    if (statusEl) statusEl.innerHTML = `<p class="text-xs text-slate-500 italic">LLM 映射失敗，請手動選擇。</p>`;
    _autoMapEtSkillByName();
  }
}

function _autoMapEtSkillByName() {
  const attrs = _getEtCurrentAttrs();
  document.querySelectorAll('#et-skill-mapping-rows .et-map-select').forEach(sel => {
    const param = (sel.dataset.mcpParam || '').toLowerCase();
    const match = attrs.find(a =>
      a.toLowerCase().includes(param) || param.includes(a.toLowerCase())
    );
    if (match) sel.value = match;
  });
}

function _collectEtPendingMappings() {
  const mappings = [];
  document.querySelectorAll('#et-skill-mapping-rows .et-map-select').forEach(sel => {
    const mcpParam = sel.dataset.mcpParam;
    const mcpId   = parseInt(sel.dataset.mcpId) || null;
    const eventField = sel.value;
    if (mcpParam && eventField && mcpId) {
      mappings.push({ event_field: eventField, mcp_id: mcpId, mcp_param: mcpParam });
    }
  });
  return mappings;
}

function _confirmEtSkillAdd() {
  const skillId = _etPendingSkillId;
  if (!skillId) return;
  const param_mappings = _collectEtPendingMappings();
  _etDiagnosisSkills = _etDiagnosisSkills.filter(s => s.skill_id !== skillId);
  _etDiagnosisSkills.push({ skill_id: skillId, param_mappings });
  _etPendingSkillId = null;
  document.getElementById('et-skill-mapping-panel')?.classList.add('hidden');
  document.getElementById('et-skill-search').value = '';
  _renderEtSkillsTable();
}

function _cancelEtSkillAdd() {
  _etPendingSkillId = null;
  document.getElementById('et-skill-mapping-panel')?.classList.add('hidden');
  document.getElementById('et-skill-search').value = '';
}

function _removeEtSkill(skillId) {
  _etDiagnosisSkills = _etDiagnosisSkills.filter(s => s.skill_id !== skillId);
  _renderEtSkillsTable();
}

// ══════════════════════════════════════════════════════════════
// MCP BUILDER
// ══════════════════════════════════════════════════════════════

async function _loadMcpDefs() {
  const container = document.getElementById('mcp-list');
  try {
    _mcpDefs = await _api('GET', '/mcp-definitions') || [];
    if (_dataSubjects.length === 0) _dataSubjects = await _api('GET', '/data-subjects') || [];
    if (_mcpDefs.length === 0) {
      container.innerHTML = '<p class="text-center text-slate-600 py-12">尚無 MCP，點擊右上角新增</p>';
      return;
    }
    container.innerHTML = _mcpDefs.map(mcp => {
      const ds = _dataSubjects.find(d => d.id === mcp.data_subject_id);
      const hasGenerated = !!(mcp.processing_script);
      return `
        <div class="builder-card" onclick="openDrawer('mcp-edit', ${mcp.id})">
          <div class="flex-1">
            <div class="builder-card-name">${_esc(mcp.name)}</div>
            <div class="builder-card-desc">${_esc(mcp.description || '（無說明）')}</div>
            <div class="builder-card-meta">
              <span class="builder-tag">${_esc(ds?.name || `DS #${mcp.data_subject_id}`)}</span>
              ${hasGenerated ? '<span class="builder-tag builder-tag-green">✓ LLM 已生成</span>' : '<span class="builder-tag builder-tag-amber">待 LLM 生成</span>'}
            </div>
          </div>
          <div class="text-slate-600 text-sm">›</div>
        </div>
      `;
    }).join('');
  } catch (e) {
    container.innerHTML = `<p class="text-center text-red-400 py-12">載入失敗：${_esc(e.message)}</p>`;
  }
}

async function _renderMCPDrawer(id) {
  // Reset try-run state for new MCPs
  if (!id) { _sampleData = null; _tryRunPassed = false; _tryRunResult = null; }

  if (_dataSubjects.length === 0) _dataSubjects = await _api('GET', '/data-subjects') || [];
  let mcp = null;
  if (id) mcp = _mcpDefs.find(m => m.id === id) || await _api('GET', `/mcp-definitions/${id}`);
  const title = id ? `編輯 MCP — ${_esc(mcp?.name || '')}` : '新增 MCP';

  const dsOptions = _dataSubjects.map(ds =>
    `<option value="${ds.id}" ${mcp?.data_subject_id === ds.id ? 'selected' : ''}>${_esc(ds.name)}</option>`
  ).join('');

  // Save button: disabled for new MCP until try-run passes; always enabled when editing
  const saveDisabled = (!id) ? 'disabled style="opacity:0.4;cursor:not-allowed"' : '';
  const saveId = 'mcp-save-btn';

  const body = `
    <div class="builder-field">
      <label class="builder-label required">MCP 名稱</label>
      <input id="mcp-name" class="builder-input" value="${_esc(mcp?.name || '')}" placeholder="e.g. APC_Moving_Average" />
    </div>
    <div class="builder-field">
      <label class="builder-label">說明</label>
      <textarea id="mcp-desc" class="builder-textarea" rows="2" placeholder="MCP 用途說明">${_esc(mcp?.description || '')}</textarea>
    </div>

    <!-- ── Step 1: 選定資料源 ─────────────────────────────────── -->
    <div class="text-xs font-semibold text-slate-400 uppercase tracking-widest mt-4 mb-2 border-b border-slate-200 pb-1">
      Step 1 · 選定資料源 &amp; 撈取樣本
    </div>
    <div class="builder-field">
      <label class="builder-label required">選定 DataSubject</label>
      <select id="mcp-ds" class="builder-select" onchange="_onDsChange()">
        <option value="">— 請選擇 —</option>
        ${dsOptions}
      </select>
    </div>
    <div id="mcp-schema-ref"></div>
    <div id="mcp-sample-form"></div>
    <div id="mcp-sample-preview"></div>

    <!-- ── Steps 2-4: Try Session Area (multi-tab, Phase 8.6) ── -->
    <div class="text-xs font-semibold text-slate-400 uppercase tracking-widest mt-4 mb-2 border-b border-slate-200 pb-1">
      Step 2–4 · 加工意圖 &amp; 試跑
    </div>
    <div id="try-session-area">
      <div id="try-tab-bar" class="flex items-center gap-1 mb-3 flex-wrap"></div>
      <div id="try-tab-content"></div>
    </div>

  `;

  const footer = `
    <button class="builder-btn-secondary" onclick="closeDrawer()">取消</button>
    ${id ? `<button class="builder-btn-danger mr-auto" onclick="_deleteMCP(${id})">刪除</button>` : ''}
    <button id="${saveId}" class="builder-btn-primary" ${saveDisabled} onclick="_saveMCP(${id || 'null'})">
      ${id ? '更新' : '建立 MCP'}
    </button>
  `;
  _setDrawerContent(title, body, footer);
  _onDsChange(); // populate schema reference & sample form if a DS is already selected
  _initTryTabs(mcp?.processing_intent || '');
  // Restore saved try-run result so user sees Step 4 without re-running
  if (id && mcp?.sample_output) _renderSavedTryRunResult(mcp);
}

function _onDsChange() {
  // Reset sample state when DS changes
  _sampleData = null;
  const preview = document.getElementById('mcp-sample-preview');
  if (preview) preview.innerHTML = '';

  const sel = document.getElementById('mcp-ds');
  const ref = document.getElementById('mcp-schema-ref');
  const formEl = document.getElementById('mcp-sample-form');
  if (!sel || !ref) return;

  const dsId = parseInt(sel.value);
  if (!dsId) { ref.innerHTML = ''; if (formEl) formEl.innerHTML = ''; return; }
  const ds = _dataSubjects.find(d => d.id === dsId);
  if (!ds) { ref.innerHTML = ''; if (formEl) formEl.innerHTML = ''; return; }

  // ── Output schema reference block ────────────────────────────
  const outFields = (ds.output_schema?.fields) || [];
  if (outFields.length > 0) {
    const rows = outFields.map(f =>
      `<div class="flex items-start gap-2 py-1 border-b border-slate-100 last:border-0">
        <span class="text-emerald-600 font-mono text-xs w-36 shrink-0">${_esc(f.name)}</span>
        <span class="text-sky-600 text-xs w-20 shrink-0">${_esc(f.type)}</span>
        <span class="text-slate-600 text-xs">${_esc(f.description || '')}</span>
      </div>`
    ).join('');
    ref.innerHTML = `
      <div class="builder-field">
        <label class="builder-label" style="color:#94a3b8">📋 輸出欄位參考 (Output Schema)</label>
        <div class="bg-slate-50 p-4 rounded-md text-sm text-slate-700 mt-1 border border-slate-200">
          <div class="flex items-center gap-2 pb-2 mb-1 border-b border-slate-200">
            <span class="text-slate-500 text-xs w-36">欄位名稱</span>
            <span class="text-slate-500 text-xs w-20">型態</span>
            <span class="text-slate-500 text-xs">說明</span>
          </div>
          ${rows}
        </div>
      </div>
    `;
  } else {
    ref.innerHTML = '';
  }

  // ── Sample fetch form (based on input_schema) ────────────────
  if (!formEl) return;
  const inFields = (ds.input_schema?.fields) || [];
  if (inFields.length === 0) { formEl.innerHTML = ''; return; }

  const inputs = inFields.map(f => `
    <div class="flex items-center gap-2 mb-2">
      <label class="text-xs text-slate-400 w-36 shrink-0">${_esc(f.name)}${f.required ? ' *' : ''}</label>
      <input id="mcp-sample-${_esc(f.name)}" class="builder-input flex-1 py-1 text-xs"
        placeholder="${_esc(f.description || f.name)}"
        value="${_esc(_defaultSampleValue(f.name))}" />
    </div>
  `).join('');

  formEl.innerHTML = `
    <div class="builder-field">
      <label class="builder-label" style="color:#94a3b8">🔌 測試參數（撈取樣本用）</label>
      <div class="bg-slate-50 p-3 rounded-md mt-1 border border-slate-200">
        ${inputs}
        <button class="builder-btn-llm mt-2 text-xs" onclick="_fetchSample()">
          📥 撈取樣本資料
        </button>
      </div>
    </div>
  `;
}

function _defaultSampleValue(name) {
  const defaults = {
    lot_id: 'L12345.00', operation_number: '3200',
    tool_id: 'ET_01',   chamber_id: 'CH1',
  };
  return defaults[name] || '';
}

function _renderMcpGeneratedBlock(mcp) {
  const outSchema    = mcp.output_schema    || {};
  const uiConfig     = mcp.ui_render_config || {};
  const inputDef     = mcp.input_definition || {};
  const fields = (outSchema.fields || []).map(f =>
    `<div class="schema-field-row">
      <span class="schema-field-name">${_esc(f.name)}</span>
      <span class="schema-field-type ml-2">${_esc(f.type)}</span>
      <span class="schema-field-desc ml-2">${_esc(f.description)}</span>
    </div>`
  ).join('');

  return `
    <div class="llm-result-block mb-3">
      <div class="llm-result-label">Output Dataset Schema</div>
      ${fields || '<p class="text-xs text-slate-600">（無）</p>'}
    </div>
    <div class="llm-result-block mb-3">
      <div class="llm-result-label">UI 呈現建議</div>
      <div class="text-xs text-slate-600">
        圖表類型：<span class="text-indigo-600">${_esc(uiConfig.chart_type || '—')}</span>
        &nbsp;|&nbsp; X 軸：<span class="text-indigo-600">${_esc(uiConfig.x_axis || '—')}</span>
        &nbsp;|&nbsp; Y 軸：<span class="text-indigo-600">${_esc(uiConfig.y_axis || '—')}</span>
      </div>
      ${uiConfig.notes ? `<p class="text-xs text-slate-500 mt-1">${_esc(uiConfig.notes)}</p>` : ''}
    </div>
    <div class="llm-result-block mb-3">
      <div class="llm-result-label">Input 參數定義</div>
      ${(inputDef.params || []).map(p =>
        `<div class="schema-field-row">
          <span class="schema-field-name">${_esc(p.name)}</span>
          <span class="schema-field-type ml-2">${_esc(p.type)}</span>
          <span class="builder-tag ml-2 text-xs">${_esc(p.source)}</span>
          <span class="schema-field-desc ml-2">${_esc(p.description)}</span>
        </div>`
      ).join('') || '<p class="text-xs text-slate-600">（無）</p>'}
    </div>
    <div class="llm-result-block">
      <div class="llm-result-label">Python 腳本（節錄）</div>
      <pre class="code-block" style="max-height:200px;overflow-y:auto;font-size:11px;">${_esc(mcp.processing_script || '').slice(0, 1000)}${mcp.processing_script?.length > 1000 ? '\n...' : ''}</pre>
    </div>
  `;
}

async function _fetchSample() {
  const sel = document.getElementById('mcp-ds');
  const preview = document.getElementById('mcp-sample-preview');
  if (!sel || !preview) return;

  const dsId = parseInt(sel.value);
  const ds = _dataSubjects.find(d => d.id === dsId);
  if (!ds) return;

  const inFields = (ds.input_schema?.fields) || [];
  const params = new URLSearchParams();
  for (const f of inFields) {
    const val = document.getElementById(`mcp-sample-${f.name}`)?.value?.trim();
    if (val) params.append(f.name, val);
  }

  preview.innerHTML = '<div class="llm-loading mt-2"><div class="llm-spinner"></div><span class="text-xs">正在撈取樣本資料...</span></div>';

  try {
    // Strip /api/v1 prefix since _api() prepends it
    const rawUrl = ds.api_config?.endpoint_url || '';
    const path = rawUrl.replace(/^\/api\/v1/, '');
    const method = (ds.api_config?.method || 'GET').toUpperCase();
    const fullPath = method === 'GET' && params.toString() ? `${path}?${params}` : path;
    const body = method !== 'GET' ? Object.fromEntries(params) : undefined;

    _sampleData = await _api(method, fullPath, body);
    const uid = 'sample-' + Date.now();
    preview.innerHTML = `
      <div class="builder-field mt-2">
        <label class="builder-label text-green-400">✓ 樣本資料 (Raw Data Preview)</label>
        ${_udv(_sampleData, uid)}
      </div>
    `;
  } catch (e) {
    _sampleData = null;
    preview.innerHTML = `<p class="text-xs text-red-400 mt-2">✗ 撈取失敗：${_esc(e.message)}</p>`;
  }
}

async function _tryRunMCP(n) {
  const tabN     = n || _activeTryTabN;
  const intent   = document.getElementById(`mcp-intent-${tabN}`)?.value?.trim();
  const dsId     = parseInt(document.getElementById('mcp-ds')?.value);
  const statusEl = document.getElementById(`mcp-tryrun-status-${tabN}`);
  const btn      = document.getElementById(`mcp-tryrun-btn-${tabN}`);

  if (!intent)      { alert('請先填寫加工意圖'); return; }
  if (!dsId)        { alert('請先選定 DataSubject'); return; }
  if (!_sampleData) { alert('請先點擊「撈取樣本資料」取得真實資料'); return; }

  btn.disabled = true;

  // ── Step 0: Semantic check — verify intent is clear before heavy LLM call ─
  btn.textContent = '⏳ 分析意圖語意...';
  statusEl.innerHTML = '<div class="llm-loading"><div class="llm-spinner"></div><span>AI 正在分析加工意圖是否明確，約 5~10 秒…</span></div>';

  try {
    const check = await _api('POST', '/mcp-definitions/check-intent', {
      processing_intent: intent,
      data_subject_id: dsId,
    });

    const improvedIntent = check.improved_intent || check.suggested_prompt || '';
    const changes        = check.changes || '';
    const isAlreadyClear = check.is_clear !== false;
    const questions      = check.questions || [];

    // Always show improved intent card if LLM produced one and it differs from original
    if (improvedIntent && improvedIntent.trim() !== intent.trim()) {
      // Store in window to avoid onclick escaping issues
      window._pendingImprovedIntent  = improvedIntent;
      window._pendingTryRunTabN      = tabN;

      const questionsHtml = questions.map(q =>
        `<li class="text-xs text-slate-400 list-disc ml-4">${_esc(q)}</li>`
      ).join('');

      const headerHtml = isAlreadyClear
        ? `<p class="text-xs text-indigo-300 font-semibold">✨ LLM 為您改寫了更精確的加工意圖${changes ? `（${_esc(changes)}）` : ''}：</p>`
        : `<div>
             <p class="text-xs text-amber-300 font-semibold mb-1">⚠ LLM 發現意圖尚不夠具體${changes ? `（${_esc(changes)}）` : ''}，建議先確認：</p>
             ${questionsHtml ? `<ul class="space-y-0.5 mb-2">${questionsHtml}</ul>` : ''}
             <p class="text-xs text-indigo-300 font-semibold">✨ 改寫後的加工意圖：</p>
           </div>`;

      statusEl.innerHTML = `
        <div class="rounded-lg border border-indigo-500/30 bg-indigo-500/5 px-4 py-3 space-y-3">
          ${headerHtml}
          <div class="bg-slate-50 border border-slate-200 rounded px-3 py-2.5">
            <p class="text-xs text-slate-700 whitespace-pre-wrap leading-relaxed">${_esc(improvedIntent)}</p>
          </div>
          <div class="flex gap-2">
            <button onclick="_applyIntentAndRun()"
              class="text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded px-3 py-1.5 font-medium transition-colors">
              ✨ 套用改寫並執行試跑
            </button>
            <button onclick="_doTryRun(window._pendingTryRunTabN)"
              class="text-xs bg-slate-600 hover:bg-slate-500 text-white rounded px-3 py-1.5 font-medium transition-colors">
              ▶ 仍用原意圖試跑
            </button>
          </div>
        </div>`;
      btn.disabled = false;
      btn.innerHTML = '<span>✨</span> 執行試跑 (Try Run)';
      return;
    }
  } catch (e) {
    // Intent check is non-blocking — log and continue
    console.warn('Intent check failed (continuing):', e.message);
  }

  await _doTryRun(tabN);
}

/** Apply improved intent to textarea then immediately run try-run. */
async function _applyIntentAndRun() {
  const improved = window._pendingImprovedIntent || '';
  const n = window._pendingTryRunTabN || _activeTryTabN;
  const el = document.getElementById(`mcp-intent-${n}`);
  if (el && improved) {
    el.value = improved;
    el.focus();
    el.setSelectionRange(improved.length, improved.length);
  }
  await _doTryRun(n);
}

/** Apply LLM-suggested prompt to the intent textarea for the given tab (legacy). */
function _applyIntent(n) {
  const text = _suggestedIntents[n];
  if (!text) return;
  const el = document.getElementById(`mcp-intent-${n}`);
  if (el) {
    el.value = text;
    el.focus();
    el.setSelectionRange(text.length, text.length);
  }
  const statusEl = document.getElementById(`mcp-tryrun-status-${n}`);
  if (statusEl) {
    statusEl.innerHTML = '<p class="text-xs text-indigo-300 bg-indigo-400/10 border border-indigo-400/20 rounded-lg px-3 py-2">✓ 建議意圖已套用，請確認後點擊試跑。</p>';
  }
}

/** Called after intent check passes, or when user clicks "仍然繼續". */
async function _doTryRun(n) {
  const tabN     = n || _activeTryTabN;
  const intent   = document.getElementById(`mcp-intent-${tabN}`)?.value?.trim();
  const dsId     = parseInt(document.getElementById('mcp-ds')?.value);
  const statusEl = document.getElementById(`mcp-tryrun-status-${tabN}`);
  const resultEl = document.getElementById(`mcp-tryrun-result-${tabN}`);
  const btn      = document.getElementById(`mcp-tryrun-btn-${tabN}`);

  // Update tab status to 'running'
  const tabObj = _tryTabs.find(t => t.n === tabN);
  if (tabObj) { tabObj.status = 'running'; _renderTryTabBar(); }

  btn.disabled = true;
  btn.textContent = '⏳ 試跑中（LLM 生成 + 沙盒執行）...';
  statusEl.innerHTML = '<div class="llm-loading"><div class="llm-spinner"></div><span>LLM 正在依據真實樣本生成腳本並執行，約 20~40 秒…</span></div>';
  if (resultEl) resultEl.innerHTML = '';

  try {
    const result = await _api('POST', '/mcp-definitions/try-run', {
      processing_intent: intent,
      data_subject_id: dsId,
      sample_data: _sampleData,
    });

    if (!result.success) {
      const analysis = result.error_analysis
        ? `<div class="mt-3 bg-amber-500/10 border border-amber-500/20 rounded-xl p-4">
             <div class="text-xs font-semibold text-amber-400 mb-2">🤖 AI 錯誤分析與修改建議</div>
             <div class="text-xs text-amber-700 leading-relaxed whitespace-pre-wrap">${_esc(result.error_analysis)}</div>
           </div>`
        : '';
      statusEl.innerHTML = `
        <div class="bg-red-500/10 border border-red-500/20 rounded-xl p-3">
          <p class="text-xs text-red-400 font-semibold mb-1">✗ 試跑失敗 (Tab ${tabN})</p>
          <pre class="text-xs text-red-300 whitespace-pre-wrap leading-relaxed">${_esc(result.error || '未知錯誤')}</pre>
        </div>
        ${analysis}`;

      // ── Phase 8.6 Self-Healing Engine ──────────────────────────
      const errorType = result.error_type;
      if (errorType === 'User_Prompt_Issue' && result.suggested_prompt) {
        const hint = `
          <div class="mt-3 bg-blue-500/10 border border-blue-500/20 rounded-xl p-3">
            <div class="text-xs font-semibold text-blue-400 mb-1">🔄 AI 自癒引擎：偵測到意圖問題，建議修改</div>
            <div class="text-xs text-indigo-600 leading-relaxed whitespace-pre-wrap mb-2">${_esc(result.suggested_prompt)}</div>
            <div class="text-xs text-slate-500 italic">即將自動開啟新試跑分頁 (Try ${_tryTabs.length + 1})…</div>
          </div>`;
        statusEl.insertAdjacentHTML('beforeend', hint);
        setTimeout(() => _addTryTab(result.suggested_prompt), 1200);
        if (tabObj) { tabObj.status = 'error'; _renderTryTabBar(); }
      } else {
        // System_Issue or unknown — show IT contact card + UDV error dump
        const uid = 'err-' + tabN + '-' + Date.now();
        const errorDump = {
          error: result.error,
          error_analysis: result.error_analysis,
          script: result.script,
        };
        const itCard = `
          <div class="mt-3 bg-slate-50 border border-slate-200 rounded-xl p-4">
            <div class="text-xs font-semibold text-slate-700 mb-1">🔧 系統錯誤 — 請聯繫 IT 支援</div>
            <div class="text-xs text-slate-400 mb-3">錯誤類型：系統層級問題（非意圖問題），請提交以下錯誤報告至 IT 部門。</div>
            ${_udv(errorDump, uid)}
          </div>`;
        statusEl.insertAdjacentHTML('beforeend', itCard);
        if (tabObj) { tabObj.status = 'error'; _renderTryTabBar(); }
      }
      return;
    }

    // Success — unlock save button, store result, update tab status
    _tryRunPassed = true;
    _tryRunResult = result;
    if (tabObj) { tabObj.status = 'done'; _renderTryTabBar(); }

    const saveBtn = document.getElementById('mcp-save-btn');
    if (saveBtn) { saveBtn.disabled = false; saveBtn.removeAttribute('style'); }

    statusEl.innerHTML = '<p class="text-xs text-green-400 bg-green-400/10 border border-green-400/20 rounded-lg px-3 py-2 mb-2">✓ 試跑成功！請檢視下方結果，確認後即可儲存。</p>';

    if (resultEl) {
      resultEl.innerHTML = _buildResultHtml(result, `(Tab ${tabN})`);
    }
  } catch (e) {
    statusEl.innerHTML = `<p class="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">✗ 請求失敗：${_esc(e.message)}</p>`;
    if (tabObj) { tabObj.status = 'error'; _renderTryTabBar(); }
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>✨</span> 重新試跑';
  }
}

// ── Standard Payload Rendering Engine ──────────────────────────────────────

/** Switch between 📊 Chart and 📋 Data tabs in a result pane. */
function _switchResultTab(tabId, pane, btn) {
  document.getElementById(tabId + '-chart')?.classList.toggle('hidden', pane !== 'chart');
  document.getElementById(tabId + '-data')?.classList.toggle('hidden',  pane !== 'data');
  const bar = btn?.closest('.result-tab-bar');
  if (bar) {
    bar.querySelectorAll('.result-tab-btn').forEach(b => {
      b.classList.toggle('bg-indigo-600',   b === btn);
      b.classList.toggle('text-white',     b === btn);
      b.classList.toggle('text-slate-400', b !== btn);
    });
  }
}

/**
 * Render a Try Run result using the Standard Payload format:
 *   output_data = { output_schema, dataset, ui_render: { type, chart_data } }
 * Falls back to legacy rendering for old-format results.
 * Returns { schemaHtml, dataHtml } where dataHtml may contain a chart/data tab widget.
 */
function _renderStandardPayload(result) {
  const outputData = result.output_data || {};
  const uiRender   = outputData.ui_render;
  const schema     = outputData.output_schema || result.output_schema || {};
  const dataset    = outputData.dataset;

  // ── Schema display ────────────────────────────────────────────
  let schemaHtml = '';
  const fields = schema.fields || [];
  if (fields.length > 0) {
    schemaHtml = `
      <div class="mb-4 bg-white border border-slate-200 rounded-xl p-4">
        <div class="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">📐 Output Schema</div>
        <table class="w-full text-xs">
          <thead>
            <tr class="text-slate-500 border-b border-slate-200">
              <th class="text-left py-1 pr-4">欄位名稱</th>
              <th class="text-left py-1 pr-4">型別</th>
              <th class="text-left py-1">說明</th>
            </tr>
          </thead>
          <tbody class="text-slate-700">
            ${fields.map(f => `
              <tr class="border-b border-slate-100">
                <td class="py-1 pr-4 font-mono text-indigo-600">${_esc(f.name)}</td>
                <td class="py-1 pr-4 text-yellow-600">${_esc(f.type)}</td>
                <td class="py-1 text-slate-500">${_esc(f.description || '')}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  // ── Data rendering ────────────────────────────────────────────
  let dataHtml = '';

  if (uiRender) {
    const type      = uiRender.type || 'table';
    // Normalize: backend may return chart_data as an already-parsed object
    const rawChartData = uiRender.chart_data;
    const chartData = (rawChartData && typeof rawChartData === 'object')
      ? JSON.stringify(rawChartData)
      : rawChartData;

    if (type === 'table' || !chartData) {
      // No chart — just show the data table
      dataHtml = _renderDatasetTable(dataset || outputData);
    } else {
      // Has chart — show Chart tab + Data tab
      const tabId     = 'rtab-' + Math.random().toString(36).slice(2, 8);
      const tableHtml = _renderDatasetTable(dataset || outputData);

      let chartPaneHtml;
      if (typeof chartData === 'string' && chartData.startsWith('data:image')) {
        // Matplotlib base64 PNG — inject directly
        chartPaneHtml = `<img src="${chartData}" style="max-width:100%;border-radius:8px;border:1px solid #334155;" alt="chart" />`;
      } else if (typeof chartData === 'string' && chartData.trim().startsWith('{')) {
        // Plotly JSON spec — render via Plotly.newPlot() (avoids innerHTML script-blocking)
        const plotId = tabId + '-plot';
        chartPaneHtml = `<div id="${plotId}" style="width:100%;min-height:420px;"></div>`;
        // Defer until after the HTML string is inserted into the DOM
        setTimeout(() => {
          const el = document.getElementById(plotId);
          if (!el || !window.Plotly) return;
          try {
            const spec = JSON.parse(chartData);
            const layout = Object.assign({
              paper_bgcolor: '#ffffff',
              plot_bgcolor:  '#f8fafc',
              font: { color: '#1e293b', size: 11 },
              margin: { t: 40, r: 20, b: 60, l: 60 },
            }, spec.layout || {});
            Plotly.newPlot(el, spec.data || [], layout, { responsive: true, displayModeBar: false });
          } catch(e) { el.innerHTML = `<p class="text-xs text-red-400 p-4">圖表渲染失敗：${e.message}</p>`; }
        }, 80);
      } else {
        // Legacy HTML string — re-execute scripts manually
        const legacyId = tabId + '-legacy';
        chartPaneHtml = `<div id="${legacyId}" style="width:100%;min-height:420px;"></div>`;
        setTimeout(() => {
          const el = document.getElementById(legacyId);
          if (!el) return;
          el.innerHTML = chartData;
          el.querySelectorAll('script').forEach(old => {
            const s = document.createElement('script');
            if (old.src) s.src = old.src; else s.text = old.textContent;
            old.replaceWith(s);
          });
        }, 80);
      }

      dataHtml = `
        <div class="result-tab-bar flex gap-1 mb-2">
          <button class="result-tab-btn text-xs px-3 py-1 rounded-md bg-indigo-600 text-white font-medium transition-colors"
                  onclick="_switchResultTab('${tabId}','chart',this)">📊 圖表</button>
          <button class="result-tab-btn text-xs px-3 py-1 rounded-md text-slate-500 font-medium transition-colors hover:text-slate-800"
                  onclick="_switchResultTab('${tabId}','data',this)">📋 資料</button>
        </div>
        <div id="${tabId}-chart">${chartPaneHtml}</div>
        <div id="${tabId}-data"  class="hidden">${tableHtml}</div>
      `;
    }
  } else {
    dataHtml = _renderDatasetTable(outputData);
  }

  return { schemaHtml, dataHtml };
}

/**
 * Build the full Step 4 result block HTML (used by both try-run success and saved-result restore).
 * label: optional suffix for the section header, e.g. "(Tab 1)" or "（已儲存）"
 */
function _buildResultHtml(result, label) {
  const { schemaHtml, dataHtml } = _renderStandardPayload(result);
  const uiType = result.output_data?.ui_render?.type || result.ui_render_config?.chart_type || 'table';
  return `
    <div class="mt-4">
      <div class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3 border-b border-slate-200 pb-1">
        Step 4 · 結果預覽 ${_esc(label || '')}
      </div>
      <div class="mb-2 text-xs text-slate-500 font-medium">📊 資料輸出 (${_esc(uiType)})</div>
      ${dataHtml}
      ${schemaHtml}
      <details class="mt-3">
        <summary class="text-xs text-slate-500 cursor-pointer hover:text-slate-700">🔍 查看生成的 Python 腳本</summary>
        <pre class="bg-slate-50 border border-slate-200 rounded-md p-3 text-xs text-slate-700 mt-2 overflow-auto max-h-48">${_esc(result.script || '')}</pre>
      </details>
    </div>
  `;
}

/**
 * Build a Plotly spec from a dataset array + ui_render_config.
 * Returns {data, layout} suitable for Plotly.newPlot(), or null if not possible.
 */
function _buildChartFromDataset(dataset, cfg) {
  if (!dataset || !dataset.length) return null;
  const first = dataset[0];
  const xKey = (cfg && cfg.x_axis) || '';
  const yKey = (cfg && cfg.y_axis) || '';
  const seriesKeys = (cfg && cfg.series) || [];

  const xVals = (xKey && first.hasOwnProperty(xKey))
    ? dataset.map(r => r[xKey])
    : dataset.map((_, i) => i);

  let keysToPlot = [];
  if (seriesKeys.length > 0) {
    keysToPlot = seriesKeys.filter(k => first.hasOwnProperty(k));
  } else if (yKey && first.hasOwnProperty(yKey)) {
    keysToPlot = [yKey];
  } else {
    keysToPlot = Object.keys(first)
      .filter(k => typeof first[k] === 'number' && k !== xKey)
      .slice(0, 4);
  }
  if (!keysToPlot.length) return null;

  const traces = keysToPlot.map(key => ({
    x: xVals,
    y: dataset.map(r => r[key]),
    type: 'scatter',
    mode: 'lines+markers',
    name: key,
  }));
  return { data: traces, layout: { margin: { l: 40, r: 20, t: 30, b: 40 }, height: 260 } };
}

/**
 * Restore the Step 4 result area from a saved MCP's sample_output (no re-run needed).
 * Called after _initTryTabs() when editing an existing MCP.
 * Always rebuilds chart from dataset + ui_render_config to avoid stale chart_data in DB.
 */
function _renderSavedTryRunResult(mcp) {
  const resultEl = document.getElementById('mcp-tryrun-result-1');
  const statusEl = document.getElementById('mcp-tryrun-status-1');
  if (!resultEl || !mcp.sample_output) return;

  // Deep-copy the sample_output so we don't mutate the MCP object
  const outputData = JSON.parse(JSON.stringify(mcp.sample_output));

  // Always regenerate chart(s) from dataset + ui_render_config to avoid stale chart_data
  const cfg = mcp.ui_render_config || {};
  const chartType = cfg.chart_type || 'table';
  const dataset = outputData.dataset;
  if (dataset && Array.isArray(dataset) && dataset.length > 0 && chartType !== 'table') {
    const freshSpec = _buildChartFromDataset(dataset, cfg);
    if (freshSpec) {
      const freshJson = JSON.stringify(freshSpec);
      outputData.ui_render = Object.assign({}, outputData.ui_render || {}, {
        chart_data: freshJson,
        charts: [freshJson],
        type: 'chart',
      });
    }
  } else if (!outputData.ui_render) {
    outputData.ui_render = { type: 'table', charts: [], chart_data: null };
  } else if (!Array.isArray((outputData.ui_render || {}).charts)) {
    // Backfill charts[] for older saved sample_output that only has chart_data
    const cd = (outputData.ui_render || {}).chart_data;
    outputData.ui_render = Object.assign({}, outputData.ui_render, { charts: cd ? [cd] : [] });
  }

  // Reconstruct a result-like object so _buildResultHtml can consume it
  const savedResult = {
    success:          true,
    script:           mcp.processing_script || '',
    output_data:      outputData,
    output_schema:    mcp.output_schema    || {},
    ui_render_config: cfg,
    input_definition: mcp.input_definition || {},
  };

  // Restore global try-run state so re-save works without a new try-run
  _tryRunResult = savedResult;
  _tryRunPassed = true;

  if (statusEl) {
    statusEl.innerHTML = '<p class="text-xs text-indigo-600 bg-indigo-50 border border-indigo-200 rounded-lg px-3 py-2 mb-2">📂 上次試跑結果（儲存快照）— 可直接儲存或重新試跑覆蓋</p>';
  }
  resultEl.innerHTML = _buildResultHtml(savedResult, '（已儲存）');
}

/**
 * Format a single cell value for display in a table.
 * Scalars are shown as-is; objects/arrays get a mini collapsible JSON block.
 */
function _cellHtml(val) {
  if (val === null || val === undefined) return '<span class="text-slate-600">—</span>';
  if (typeof val === 'object') {
    const json = JSON.stringify(val, null, 2);
    const preview = JSON.stringify(val).slice(0, 60);
    const isLong = json.length > 80;
    if (!isLong) {
      return `<span class="font-mono text-amber-300 text-xs">${_esc(JSON.stringify(val))}</span>`;
    }
    // Long nested object — show collapsible
    const uid = Math.random().toString(36).slice(2, 8);
    return `
      <span class="font-mono text-amber-300 text-xs cursor-pointer select-none"
            onclick="document.getElementById('cell-${uid}').classList.toggle('hidden')"
            title="點擊展開/收合">
        ${_esc(preview)}… ▾
      </span>
      <pre id="cell-${uid}" class="hidden bg-amber-50 border border-amber-200 rounded p-1 mt-1 text-xs text-amber-700 whitespace-pre overflow-auto max-h-40 max-w-xs">${_esc(json)}</pre>`;
  }
  return `<span class="font-mono">${_esc(String(val))}</span>`;
}

/**
 * Render a single record (dict) as a vertical key → value table.
 * Each field gets its own row; nested objects/arrays rendered via _cellHtml.
 */
function _renderRecordView(record) {
  const entries = Object.entries(record);
  if (entries.length === 0) return _renderGrid(record);
  return `
    <div class="overflow-auto max-h-80 border border-slate-200 rounded-xl">
      <table class="w-full text-xs border-collapse">
        <thead class="sticky top-0 bg-white z-10">
          <tr>
            <th class="text-left px-3 py-2 text-slate-500 border-b border-slate-200 font-medium w-1/3">欄位</th>
            <th class="text-left px-3 py-2 text-slate-500 border-b border-slate-200 font-medium">值</th>
          </tr>
        </thead>
        <tbody class="text-slate-700">
          ${entries.map(([k, v], i) => `
            <tr class="${i % 2 === 0 ? 'bg-slate-50' : 'bg-white'}">
              <td class="px-3 py-1.5 border-b border-slate-100 text-indigo-600 font-mono align-top whitespace-nowrap">${_esc(k)}</td>
              <td class="px-3 py-1.5 border-b border-slate-100 align-top">${_cellHtml(v)}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
  `;
}

/**
 * Smart renderer: picks the right display mode based on data shape.
 *
 *   Array of objects → horizontal table  (processed dataset, list results)
 *   Single dict      → vertical record   (raw API record, e.g. APC/Recipe/EC)
 *   Anything else    → _renderGrid       (pretty JSON fallback)
 *
 * Never silently drops top-level fields.
 */
function _renderDatasetTable(data) {
  // ── Array of dicts → horizontal table ────────────────────────
  if (Array.isArray(data)) {
    if (data.length === 0) return _renderGrid(data);
    if (typeof data[0] !== 'object' || data[0] === null) return _renderGrid(data);

    const cols      = Object.keys(data[0]);
    const maxRows   = 50;
    const displayed = data.slice(0, maxRows);

    return `
      <div class="overflow-auto max-h-80 border border-slate-200 rounded-xl">
        <table class="w-full text-xs border-collapse">
          <thead class="sticky top-0 bg-white z-10">
            <tr>
              ${cols.map(c => `<th class="text-left px-3 py-2 text-slate-500 border-b border-slate-200 whitespace-nowrap font-medium">${_esc(c)}</th>`).join('')}
            </tr>
          </thead>
          <tbody class="text-slate-700">
            ${displayed.map((row, i) => `
              <tr class="${i % 2 === 0 ? 'bg-slate-50' : 'bg-white'}">
                ${cols.map(c => `<td class="px-3 py-1.5 border-b border-slate-100 align-top max-w-xs">${_cellHtml(row[c])}</td>`).join('')}
              </tr>`).join('')}
            ${data.length > maxRows ? `
              <tr>
                <td colspan="${cols.length}" class="px-3 py-2 text-slate-500 text-center italic">
                  … 共 ${data.length} 筆，僅顯示前 ${maxRows} 筆
                </td>
              </tr>` : ''}
          </tbody>
        </table>
      </div>
    `;
  }

  // ── Single dict → vertical record view ───────────────────────
  if (data && typeof data === 'object') {
    return _renderRecordView(data);
  }

  // ── Fallback ──────────────────────────────────────────────────
  return _renderGrid(data);
}

/**
 * Render complex/deeply-nested data (e.g. APC raw payload) as a
 * scrollable pretty-printed JSON block — used when flat table isn't suitable.
 */
function _renderGrid(data) {
  const json = JSON.stringify(data, null, 2);
  return `
    <div class="border border-slate-200 rounded-xl overflow-hidden">
      <div class="bg-slate-50 px-3 py-1.5 text-xs text-slate-500 flex items-center gap-2">
        <span>📋 Raw Data Grid</span>
        <span class="ml-auto opacity-60">複雜/巢狀資料結構</span>
      </div>
      <pre class="bg-white p-3 text-xs text-slate-700 overflow-auto max-h-72 leading-relaxed">${_esc(json)}</pre>
    </div>`;
}

async function _triggerMcpGenerate(id) {
  const statusEl = document.getElementById('mcp-llm-status');
  const btn      = document.getElementById('mcp-generate-btn');
  if (!statusEl || !btn) return;

  btn.disabled = true;
  btn.innerHTML = '<span class="llm-spinner"></span> 生成中...';
  statusEl.innerHTML = '<div class="llm-loading"><div class="llm-spinner"></div><span>LLM 正在生成 Python 腳本、Output Schema、圖表建議與 Input 定義，請稍候（約 20~40 秒）...</span></div>';

  try {
    const result = await _api('POST', `/mcp-definitions/${id}/generate`);
    _mcpGenResult = result;
    statusEl.innerHTML = '<p class="text-xs text-green-400 bg-green-400/10 border border-green-400/20 rounded-lg px-3 py-2 mb-3">✓ LLM 生成完成！已自動儲存至 MCP。</p>';

    // Show results
    const mcp = { ...(await _api('GET', `/mcp-definitions/${id}`)) };
    const resultHtml = `<div class="mt-2">${_renderMcpGeneratedBlock(mcp)}</div>`;
    document.getElementById('drawer-body').insertAdjacentHTML('beforeend', resultHtml);

    // Refresh list
    _loadMcpDefs();
  } catch (e) {
    statusEl.innerHTML = `<p class="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">✗ 生成失敗：${_esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>✨</span> 重新生成';
  }
}

async function _saveMCP(id) {
  const name = document.getElementById('mcp-name').value.trim();
  const dsId = parseInt(document.getElementById('mcp-ds').value);
  if (!name || !dsId) { alert('請填寫名稱並選擇 DataSubject'); return; }

  const body = {
    name,
    description: document.getElementById('mcp-desc').value.trim(),
    data_subject_id: dsId,
    processing_intent: document.getElementById(`mcp-intent-${_activeTryTabN}`)?.value?.trim() || '',
  };
  // Always merge try-run artifacts when available (applies to both create and update)
  if (_tryRunResult && _tryRunResult.success) {
    body.processing_script = _tryRunResult.script;
    body.output_schema     = _tryRunResult.output_schema;
    body.ui_render_config  = _tryRunResult.ui_render_config;
    body.input_definition  = _tryRunResult.input_definition;
    body.sample_output     = _tryRunResult.output_data;
  }

  try {
    if (id) {
      // Update: one PATCH with all fields (basic + artifacts)
      await _api('PATCH', `/mcp-definitions/${id}`, body);
    } else {
      // Create: POST then PATCH artifacts if try-run was done
      const created = await _api('POST', '/mcp-definitions', {
        name: body.name,
        description: body.description,
        data_subject_id: body.data_subject_id,
        processing_intent: body.processing_intent,
      });
      if (_tryRunResult && _tryRunResult.success) {
        await _api('PATCH', `/mcp-definitions/${created.id}`, {
          processing_script: body.processing_script,
          output_schema:     body.output_schema,
          ui_render_config:  body.ui_render_config,
          input_definition:  body.input_definition,
          sample_output:     body.sample_output,
        });
      }
    }
    closeDrawer(true);
    _loadMcpDefs();
  } catch (e) { alert(`儲存失敗：${e.message}`); }
}

async function _deleteMCP(id) {
  if (!confirm('確定要刪除此 MCP？')) return;
  try {
    await _api('DELETE', `/mcp-definitions/${id}`);
    closeDrawer(true);
    _loadMcpDefs();
  } catch (e) { alert(`刪除失敗：${e.message}`); }
}

// ══════════════════════════════════════════════════════════════
// SKILL BUILDER
// ══════════════════════════════════════════════════════════════

async function _loadSkillDefs() {
  const container = document.getElementById('skill-list');
  try {
    _skillDefs = await _api('GET', '/skill-definitions') || [];
    if (_eventTypes.length === 0) _eventTypes = await _api('GET', '/event-types') || [];
    if (_mcpDefs.length === 0)    _mcpDefs    = await _api('GET', '/mcp-definitions') || [];
    if (_skillDefs.length === 0) {
      container.innerHTML = '<p class="text-center text-slate-600 py-12">尚無 Skill，點擊右上角新增</p>';
      return;
    }
    container.innerHTML = _skillDefs.map(sk => {
      const et = _eventTypes.find(e => e.id === sk.event_type_id);
      const hasDiag = !!(sk.diagnostic_prompt);
      const boundMcp = sk.mcp_id ? _mcpDefs.find(m => m.id === sk.mcp_id) : null;
      const mcpTag = boundMcp
        ? `<span class="builder-tag builder-tag-purple" title="${_esc(boundMcp.name)}">${_esc(boundMcp.name)}</span>`
        : `<span class="builder-tag text-slate-500">未綁定 MCP</span>`;
      return `
        <div class="builder-card" onclick="openDrawer('skill-edit', ${sk.id})">
          <div class="flex-1">
            <div class="builder-card-name">${_esc(sk.name)}</div>
            <div class="builder-card-desc">${_esc(sk.description || '（無說明）')}</div>
            <div class="builder-card-meta">
              <span class="builder-tag">${_esc(et?.name || `Event #${sk.event_type_id}`)}</span>
              ${mcpTag}
              ${hasDiag ? '<span class="builder-tag builder-tag-green">✓ 診斷邏輯</span>' : ''}
            </div>
          </div>
          <div class="text-slate-600 text-sm">›</div>
        </div>
      `;
    }).join('');
  } catch (e) {
    container.innerHTML = `<p class="text-center text-red-400 py-12">載入失敗：${_esc(e.message)}</p>`;
  }
}

// ── Phase 8.9.2 Skill Builder helpers (1-to-1) ──────────────────────────────

function _onSkillMcpChange(sel) {
  _selectedSkillMcp = parseInt(sel.value) || null;
  _skillMcpExecResult = null;
  _diagnosisRunResult = null;
  _renderSkillMcpCard();
}

function _renderSkillMcpCard() {
  const container = document.getElementById('skill-mcp-card');
  if (!container) return;
  if (!_selectedSkillMcp) {
    container.innerHTML = '<p class="text-xs text-slate-500 py-2 px-1 italic">請先選擇上方 MCP。</p>';
    return;
  }
  const mcp = _mcpDefs.find(m => m.id === _selectedSkillMcp);
  if (!mcp) return;
  const ds = _dataSubjects.find(d => d.id === mcp.data_subject_id);
  const inputFields = ds?.input_schema?.fields || [];

  const noScriptWarning = mcp.processing_script ? '' :
    `<p class="text-xs text-amber-400 mb-2">⚠ 此 MCP 尚未生成 Python 腳本，請先在 MCP Builder 完成試跑後再執行。</p>`;

  let paramRows = '';
  const hasParams = inputFields.length > 0;
  if (hasParams) {
    const headerRow = `<div class="grid text-xs text-slate-500 mb-1 px-0.5"
        style="grid-template-columns:1fr 18px 1fr;gap:4px;">
        <span>DS 輸入參數</span><span></span><span>Try Run 測試值</span>
      </div>`;
    const rows = inputFields.map(field => {
      const pn = field.name;
      const reqMark = field.required ? '<span class="text-red-400 ml-0.5">*</span>' : '';
      const ph = field.description?.slice(0, 30) || pn;
      return `<div class="grid items-center mb-1" style="grid-template-columns:1fr 18px 1fr;gap:4px;">
          <span class="font-mono text-xs text-green-600 truncate" title="${_esc(field.description||pn)}">${_esc(pn)}${reqMark}</span>
          <span class="text-slate-400 text-xs text-center">➔</span>
          <input id="mcp-test-${mcp.id}-${_esc(pn)}" type="text"
            class="text-xs bg-white border border-slate-300 rounded px-2 py-0.5 text-slate-700 w-full min-w-0"
            placeholder="${_esc(ph)}" />
        </div>`;
    }).join('');
    paramRows = headerRow + rows;
  } else {
    paramRows = '<p class="text-xs text-slate-500 italic">此 DataSubject 不需要輸入參數</p>';
  }

  container.innerHTML = `
    <div class="bg-white border border-slate-200 rounded-xl p-4 mb-3">
      <div class="flex items-center mb-3">
        <span class="text-sm font-semibold text-indigo-600">${_esc(mcp.name)}</span>
        <span class="text-xs text-slate-500 ml-2">${_esc(ds?.name || '')}</span>
      </div>
      ${noScriptWarning}
      <div class="mb-3">${paramRows}</div>
      ${hasParams ? `
      <button onclick="_executeSkillMcp()" id="mcp-exec-btn"
        class="w-full flex items-center justify-center gap-2 text-xs
               bg-indigo-700/50 hover:bg-indigo-600 border border-indigo-500/40
               rounded-lg px-3 py-2 text-indigo-200 transition-colors">
        ▶️ 執行 MCP 處理管線
      </button>` : ''}
      <div id="mcp-exec-status" class="mt-2"></div>
      <div id="mcp-exec-result" class="mt-2"></div>
    </div>`;
}

function _updateSaveButtonState() {
  // Param mapping validation removed — mappings are now set in the EventType editor.
  const saveBtn = document.getElementById('skill-save-btn');
  if (saveBtn) saveBtn.disabled = false;
  document.getElementById('skill-save-warning')?.classList.add('hidden');
}

async function _autoMapMcp() {
  const mcpId = _selectedSkillMcp;
  const etId = parseInt(document.getElementById('skill-et')?.value) || 0;
  if (!mcpId || !etId) return;
  // Small delay so DOM elements from _renderSkillMcpCard() exist
  await new Promise(r => setTimeout(r, 50));
  const statusEl = document.getElementById('mcp-exec-status');
  if (!statusEl) return;
  statusEl.innerHTML = '<p class="text-xs text-slate-400 italic flex items-center gap-1"><span class="llm-spinner" style="width:10px;height:10px;flex-shrink:0"></span> LLM 語意映射中...</p>';
  try {
    const result = await _api('POST', '/skill-definitions/auto-map', { mcp_id: mcpId, event_type_id: etId });
    const mappings = result.mapping || [];
    let applied = 0;
    for (const m of mappings) {
      if (!m.mapped_event_attribute) continue;
      const sel = document.getElementById(`mcp-map-${mcpId}-${m.mcp_input}`);
      if (sel) { sel.value = m.mapped_event_attribute; applied++; }
    }
    if (applied > 0) {
      const summary = mappings
        .filter(m => m.mapped_event_attribute)
        .map(m => `${m.mcp_input} ← ${m.mapped_event_attribute} [${m.confidence}]`)
        .join(' · ');
      statusEl.innerHTML = `<p class="text-xs text-indigo-300/80 italic">✨ LLM 建議映射：${_esc(summary)}。請確認後填入測試值。</p>`;
    } else {
      statusEl.innerHTML = '<p class="text-xs text-slate-500 italic">LLM 無法自動映射，請手動選擇。</p>';
    }
    _updateSaveButtonState();  // re-check after auto-map fills in values
  } catch (e) {
    statusEl.innerHTML = `<p class="text-xs text-slate-500 italic">LLM 映射失敗（${_esc(e.message)}），請手動選擇。</p>`;
  }
}

async function _executeSkillMcp() {
  const mcpId = _selectedSkillMcp;
  const mcp = _mcpDefs.find(m => m.id === mcpId);
  const statusEl = document.getElementById('mcp-exec-status');
  const resultEl = document.getElementById('mcp-exec-result');
  const btn      = document.getElementById('mcp-exec-btn');
  if (!mcp || !statusEl || !resultEl) return;

  if (!mcp.processing_script) {
    statusEl.innerHTML = '<p class="text-xs text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded-lg px-3 py-2">⚠ 此 MCP 尚未生成 Python 腳本，請先在 MCP Builder 完成試跑並儲存。</p>';
    return;
  }

  const ds = _dataSubjects.find(d => d.id === mcp.data_subject_id);
  if (!ds) {
    statusEl.innerHTML = '<p class="text-xs text-red-400">找不到對應的 DataSubject</p>';
    return;
  }

  // Collect test values from 3-column mapping rows
  const inputFields = ds.input_schema?.fields || [];
  const testValues = {};
  for (const { name: p } of inputFields) {
    const val = document.getElementById(`mcp-test-${mcpId}-${p}`)?.value?.trim() || '';
    if (val) testValues[p] = val;
  }

  const endpointUrl = ds.api_config?.endpoint_url;
  if (!endpointUrl) {
    statusEl.innerHTML = '<p class="text-xs text-red-400">DataSubject 缺少 endpoint_url 設定</p>';
    return;
  }

  if (btn) { btn.disabled = true; btn.textContent = '⏳ 載入中...'; }
  statusEl.innerHTML = '<div class="llm-loading"><div class="llm-spinner"></div><span>正在從 DataSubject 取得資料並執行腳本…</span></div>';
  resultEl.innerHTML = '';

  try {
    // Step 1: Fetch raw data from DataSubject API with test values
    const params = new URLSearchParams(testValues);
    const rawUrl = endpointUrl + (Object.keys(testValues).length > 0 ? '?' + params.toString() : '');
    const rawRes = await fetch(rawUrl, { headers: { 'Authorization': `Bearer ${_token}` } });
    if (!rawRes.ok) throw new Error(`DataSubject API 返回 HTTP ${rawRes.status}`);
    const rawJson = await rawRes.json();
    const rawData = rawJson.data !== undefined ? rawJson.data : rawJson;

    // Step 2: Run stored processing_script with fetched raw data
    const result = await _api('POST', `/mcp-definitions/${mcpId}/run-with-data`, { raw_data: rawData });
    _skillMcpExecResult = result;

    if (!result.success) {
      statusEl.innerHTML = `<p class="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">✗ 執行失敗：${_esc(result.error || '未知錯誤')}</p>`;
      return;
    }

    statusEl.innerHTML = '<p class="text-xs text-green-400 bg-green-400/10 border border-green-400/20 rounded-lg px-3 py-2">✓ MCP 數據載入成功！請查看下方結果，再撰寫診斷意圖。</p>';
    resultEl.innerHTML = _buildResultHtml(result, mcp.name);

    // Unlock Code 診斷 button now that MCP data is available
    const diagBtn  = document.getElementById('skill-code-diag-btn');
    const diagHint = document.getElementById('skill-code-diag-hint');
    if (diagBtn)  { diagBtn.disabled = false; }
    if (diagHint) { diagHint.classList.add('hidden'); }
  } catch (e) {
    statusEl.innerHTML = `<p class="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">✗ 失敗：${_esc(e.message)}</p>`;
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '▶️ 執行 MCP 處理管線'; }
  }
}

// ── Main drawer render ─────────────────────────────────────────────────────

async function _renderSkillDrawer(id) {
  if (_eventTypes.length === 0)   _eventTypes   = await _api('GET', '/event-types') || [];
  if (_mcpDefs.length === 0)      _mcpDefs      = await _api('GET', '/mcp-definitions') || [];
  if (_dataSubjects.length === 0) _dataSubjects = await _api('GET', '/data-subjects') || [];
  let sk = null;
  if (id) sk = _skillDefs.find(s => s.id === id) || await _api('GET', `/skill-definitions/${id}`);
  const title = id ? `編輯 Skill — ${_esc(sk?.name || '')}` : '新增 Skill';

  const etOptions = _eventTypes.map(et =>
    `<option value="${et.id}"${sk?.event_type_id === et.id ? ' selected' : ''}>${_esc(et.name)}</option>`
  ).join('');

  // 1-to-1: restore single bound MCP
  _selectedSkillMcp = sk?.mcp_id || null;
  _skillMcpExecResult = null;

  const mcpOptions = _mcpDefs.map(m => {
    const ds = _dataSubjects.find(d => d.id === m.data_subject_id);
    return `<option value="${m.id}"${_selectedSkillMcp === m.id ? ' selected' : ''}>${_esc(m.name)}${ds ? ' (' + _esc(ds.name) + ')' : ''}</option>`;
  }).join('');

  const body = `
    <!-- ── 基本設定 ─────────────────────────────────────────────── -->
    <div class="builder-field">
      <label class="builder-label required">Skill 名稱</label>
      <input id="skill-name" class="builder-input" value="${_esc(sk?.name || '')}" placeholder="e.g. Etch_APC_Diagnosis" />
    </div>
    <div class="builder-field">
      <label class="builder-label">說明</label>
      <textarea id="skill-desc" class="builder-textarea" rows="2" placeholder="Skill 用途說明">${_esc(sk?.description || '')}</textarea>
    </div>
    <!-- ══ Step 1: 選定 MCP ══════════════════════════════════════════ -->
    <div class="skill-step-header">
      <span class="skill-step-badge">Step 1</span>
      選定 MCP 與參數映射
    </div>

    <div class="builder-field">
      <label class="builder-label required">MCP（一個 Skill 綁定一個 MCP）</label>
      <select id="skill-mcp-select" class="builder-select" onchange="_onSkillMcpChange(this)">
        <option value="">— 請選擇 MCP —</option>
        ${mcpOptions}
      </select>
    </div>

    <!-- Single MCP param card: rendered by _renderSkillMcpCard() after MCP is chosen -->
    <div id="skill-mcp-card">
      <p class="text-xs text-slate-600 py-2 px-1 italic">請先選擇上方 MCP，系統將自動進行語意映射。</p>
    </div>

    <!-- ══ Step 2: 診斷邏輯與人為處置建議 ════════════════════════════ -->
    <div class="skill-step-header mt-4">
      <span class="skill-step-badge">Step 2</span>
      診斷邏輯與人為處置建議
    </div>

    <div class="builder-field">
      <label class="builder-label required">A. 異常判斷條件（Diagnostic Prompt）</label>
      <p class="text-xs text-slate-500 mb-2">描述「何種情況算<span class="text-yellow-400 font-medium">異常</span>」。符合條件 → ⚠ 警告；不符合 → ✓ 正常。請依上方 MCP Output 欄位名稱撰寫。</p>
      <textarea id="skill-diag-prompt" class="builder-textarea font-mono text-xs" rows="5"
        placeholder="例如：若 CHF3_Gas_Offset 的 param_update_time 距今超過 3 天，視為異常。">${_esc(sk?.diagnostic_prompt || '')}</textarea>
      <div class="mt-3 pt-3 border-t border-slate-100">
        <label class="builder-label text-xs text-slate-600">有問題的項目或物件</label>
        <input id="skill-problem-subject" class="builder-input mt-1"
          value="${_esc(sk?.problem_subject || '')}"
          placeholder="e.g. TETCH01 蝕刻機台、SPC OOC 批次、APC 製程參數偏移" />
        <p class="text-xs text-slate-400 mt-1">Code 診斷（Step 4）將以此物件為判斷目標</p>
      </div>
    </div>

    <div class="builder-field">
      <label class="builder-label">B. 專家建議處置（Human-Defined Next Action）</label>
      <p class="text-xs text-slate-500 mb-2">
        <span class="text-amber-400 font-semibold">⚠ 此欄位由領域專家親自撰寫，AI 不會生成處置建議。</span><br>
        填寫：若檢查發現異常時，應採取哪些具體行動。
      </p>
      <textarea id="skill-human-rec" class="builder-textarea text-sm" rows="4"
        placeholder="例如：若檢查發現異常，請聯絡設備工程師執行 Chamber 濕式清洗 (Wet Clean)，並將該批號 Hold 住，待工程師確認 APC 模型參數後再放行。">${_esc(sk?.human_recommendation || '')}</textarea>
    </div>

    <!-- ══ Step 3: Code 診斷 ═════════════════════════════════════════ -->
    <div class="skill-step-header mt-4">
      <span class="skill-step-badge">Step 3</span>
      Code 診斷（LLM 生成 Python 判斷邏輯）
    </div>
    <p class="text-xs text-slate-500 mb-3">LLM 根據「異常判斷條件」與「有問題的物件」生成 Python 診斷函式，執行後取得判斷結果，再由 LLM 生成診斷訊息。</p>
    <button id="skill-code-diag-btn" class="builder-btn-llm w-full justify-center"
      onclick="_generateCodeDiagnosis()" style="background:#6d28d9;"
      ${_skillMcpExecResult ? '' : 'disabled'}>
      🐍 生成 Code 診斷
    </button>
    <p id="skill-code-diag-hint" class="text-xs text-amber-500 text-center mt-1.5 ${_skillMcpExecResult ? 'hidden' : ''}">
      ⬆ 請先完成上方「▶️ 執行 MCP 處理管線」取得資料後，才能生成 Code 診斷
    </p>
    <div id="skill-code-diag-status" class="mt-2"></div>
    <div id="skill-code-diag-result" class="mt-2"></div>
  `;

  const footer = `
    <div class="w-full">
      <p id="skill-save-warning" class="hidden text-xs text-red-400 text-center mb-2">
        * 參數映射未完成，無法儲存此 Skill。
      </p>
      <div class="flex gap-2 justify-end">
        <button class="builder-btn-secondary" onclick="closeDrawer()">取消</button>
        ${id ? `<button class="builder-btn-danger" onclick="_deleteSkill(${id})">刪除</button>` : ''}
        <button id="skill-save-btn" class="builder-btn-primary" onclick="_saveSkill(${id || 'null'})">
          ${id ? '更新' : '建立 Skill'}
        </button>
      </div>
    </div>
  `;
  _setDrawerContent(title, body, footer);

  // Pre-display previously saved diagnosis result (if any)
  if (sk?.last_diagnosis_result) {
    _diagnosisRunResult = sk.last_diagnosis_result;
    // Enable the Code 診斷 button (skipping the "must run MCP first" gate)
    const diagBtn  = document.getElementById('skill-code-diag-btn');
    const diagHint = document.getElementById('skill-code-diag-hint');
    if (diagBtn)  diagBtn.disabled = false;
    if (diagHint) diagHint.classList.add('hidden');
    // Render after DOM is settled
    setTimeout(() => _showDiagnosisResult(_diagnosisRunResult, { isPreload: true }), 50);
  }

  // If editing an existing skill that already has a bound MCP, render the card
  if (_selectedSkillMcp) {
    _renderSkillMcpCard();
  }
}

// Called when user clicks "✨ 套用後執行診斷" — applies to textarea then immediately runs
// Apply improved prompt to textarea then immediately run diagnosis.
// Data is read from window._pending* to avoid inline-onclick escaping issues.
async function _applyAndRunDiagnosis() {
  const improved = window._pendingImprovedPrompt || '';
  const ta = document.getElementById('skill-diag-prompt');
  if (ta && improved) ta.value = improved;   // sync back to Step 2A textarea
  await _runDiagnosisNow();
}

// Called when user clicks "▶ 仍用原 Prompt 執行" — skip the improved-prompt step.
// Data is read from window._pending* to avoid inline-onclick escaping issues.
async function _runDiagnosisNow() {
  const mcpSampleOutputs = window._pendingMcpSampleOutputs || {};
  const diagPrompt = document.getElementById('skill-diag-prompt')?.value?.trim();
  const statusEl   = document.getElementById('skill-diag-status');
  const resultEl   = document.getElementById('skill-diag-result');
  const btn        = document.getElementById('skill-diag-btn');
  btn.disabled = true;
  if (resultEl) resultEl.innerHTML = '';
  await _runDiagnosis(diagPrompt, mcpSampleOutputs, statusEl, resultEl, btn);
}

async function _tryDiagnosisSkill() {
  const diagPrompt = document.getElementById('skill-diag-prompt')?.value?.trim();
  const statusEl   = document.getElementById('skill-diag-status');
  const resultEl   = document.getElementById('skill-diag-result');
  const btn        = document.getElementById('skill-diag-btn');

  if (!diagPrompt) { alert('請先填寫診斷邏輯 Prompt'); return; }
  if (!_selectedSkillMcp) { alert('請先在 Step 1 選擇 MCP'); return; }

  // Build MCP sample outputs
  const mcp = _mcpDefs.find(m => m.id === _selectedSkillMcp);
  const mcpSampleOutputs = {};
  if (mcp) {
    const outputData = _skillMcpExecResult?.output_data || mcp.sample_output;
    if (outputData && Object.keys(outputData).length > 0) {
      mcpSampleOutputs[mcp.name] = outputData;
    }
  }
  if (Object.keys(mcpSampleOutputs).length === 0) {
    alert('無可用輸出資料。請先點擊「▶️ 執行 MCP 處理管線」或確認 MCP 已有試跑樣本資料。');
    return;
  }

  btn.disabled = true;
  if (resultEl) resultEl.innerHTML = '';

  // ── Phase 1: LLM改寫 Prompt ──────────────────────────────────────────────
  btn.textContent = '⏳ LLM 改寫診斷 Prompt 中...';
  statusEl.innerHTML = '<div class="llm-loading"><div class="llm-spinner"></div><span>LLM 正在分析並改寫診斷 Prompt...</span></div>';

  let improvedPrompt = '';
  let changes = '';
  let isAlreadyClear = true;
  let questions = [];

  try {
    const firstKey = Object.keys(mcpSampleOutputs)[0];
    const check = await _api('POST', '/skill-definitions/check-diagnosis-intent', {
      diagnostic_prompt: diagPrompt,
      mcp_output_sample: firstKey ? mcpSampleOutputs[firstKey] : {},
    });
    improvedPrompt = check.improved_prompt || check.suggested_prompt || '';
    changes        = check.changes || '';
    isAlreadyClear = check.is_clear !== false;
    questions      = check.questions || [];
  } catch (_e) {
    // Non-fatal — skip to diagnosis directly
    await _runDiagnosis(diagPrompt, mcpSampleOutputs, statusEl, resultEl, btn);
    return;
  }

  // Always show the improved prompt card (even if already clear)
  if (improvedPrompt && improvedPrompt !== diagPrompt) {
    const questionsHtml = questions.map(q =>
      `<li class="text-xs text-slate-400 list-disc ml-4">${_esc(q)}</li>`
    ).join('');

    const headerHtml = isAlreadyClear
      ? `<p class="text-xs text-indigo-300 font-semibold">✨ LLM 為您改寫了更精確的診斷 Prompt${changes ? `（${_esc(changes)}）` : ''}：</p>`
      : `<div>
           <p class="text-xs text-amber-300 font-semibold mb-1">⚠ LLM 發現診斷 Prompt 尚不夠具體${changes ? `（${_esc(changes)}）` : ''}，建議先確認：</p>
           ${questionsHtml ? `<ul class="space-y-0.5 mb-2">${questionsHtml}</ul>` : ''}
           <p class="text-xs text-indigo-300 font-semibold">✨ 改寫後的診斷 Prompt：</p>
         </div>`;

    // Store in window-scope to avoid escaping issues in onclick attributes
    window._pendingImprovedPrompt    = improvedPrompt;
    window._pendingMcpSampleOutputs  = mcpSampleOutputs;

    statusEl.innerHTML = `
      <div class="rounded-lg border border-indigo-500/30 bg-indigo-500/5 px-4 py-3 space-y-3">
        ${headerHtml}
        <div class="bg-slate-50 border border-slate-200 rounded px-3 py-2.5">
          <p class="text-xs text-slate-700 whitespace-pre-wrap leading-relaxed">${_esc(improvedPrompt)}</p>
        </div>
        <div class="flex gap-2">
          <button onclick="_applyAndRunDiagnosis()"
            class="text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded px-3 py-1.5 font-medium transition-colors">
            ✨ 套用改寫並執行診斷
          </button>
          <button onclick="_runDiagnosisNow()"
            class="text-xs bg-slate-600 hover:bg-slate-500 text-white rounded px-3 py-1.5 font-medium transition-colors">
            ▶ 仍用原 Prompt 執行
          </button>
        </div>
      </div>
    `;
    btn.disabled = false;
    btn.textContent = '▶ 模擬診斷';
    return;
  }

  // ── Phase 2: No improvement available — run diagnosis directly ───────────
  await _runDiagnosis(diagPrompt, mcpSampleOutputs, statusEl, resultEl, btn);
}

async function _runDiagnosis(diagPrompt, mcpSampleOutputs, statusEl, resultEl, btn) {
  btn.textContent = '⏳ LLM 模擬診斷中...';
  statusEl.innerHTML = '<div class="llm-loading"><div class="llm-spinner"></div><span>LLM 正在根據樣本資料推論診斷結果，約 10~30 秒...</span></div>';

  try {
    const result = await _api('POST', '/skill-definitions/try-diagnosis', {
      diagnostic_prompt: diagPrompt,
      mcp_sample_outputs: mcpSampleOutputs,
    });

    if (!result.success) {
      statusEl.innerHTML = `<p class="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">✗ 模擬診斷失敗：${_esc(result.error || '未知錯誤')}</p>`;
      return;
    }

    statusEl.innerHTML = '<p class="text-xs text-green-400 bg-green-400/10 border border-green-400/20 rounded-lg px-3 py-2 mb-2">✓ 模擬診斷成功！請確認結果後儲存 Skill。</p>';

    const humanRec   = document.getElementById('skill-human-rec')?.value?.trim() || '';
    const status     = result.status || 'NORMAL';
    const conclusion = result.conclusion || result.summary || '';
    const evidence   = Array.isArray(result.evidence) ? result.evidence : [];
    const summary    = result.summary || '';

    // Binary status styles: NORMAL = green, ABNORMAL = yellow warning
    const isNormal = status === 'NORMAL';
    const sev = isNormal
      ? { wrap: 'border-green-500/40 bg-green-500/10',   badge: 'bg-green-500 text-white',      dot: 'bg-green-400',  icon: '✓', label: '正常' }
      : { wrap: 'border-yellow-500/40 bg-yellow-500/10', badge: 'bg-yellow-400 text-slate-900', dot: 'bg-yellow-400', icon: '⚠', label: '警告' };

    const evidenceHtml = evidence.map(e => `
      <li class="flex gap-2 items-start">
        <span class="mt-1.5 shrink-0 w-1.5 h-1.5 rounded-full ${sev.dot}"></span>
        <span class="text-xs text-slate-700 leading-relaxed">${_esc(e)}</span>
      </li>`).join('');

    if (resultEl) {
      resultEl.innerHTML = `
        <div class="rounded-lg border ${sev.wrap} overflow-hidden mt-2">
          <!-- Severity badge + conclusion headline -->
          <div class="flex items-start gap-3 px-4 py-3">
            <span class="shrink-0 mt-0.5 inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold ${sev.badge}">
              ${sev.icon}&nbsp;${sev.label}
            </span>
            <p class="text-sm font-semibold text-slate-800 leading-snug">${_esc(conclusion)}</p>
          </div>
          <!-- Evidence bullets -->
          ${evidenceHtml ? `
          <div class="border-t border-white/10 px-4 py-3">
            <p class="text-xs text-slate-500 uppercase tracking-wider mb-2">觀察依據</p>
            <ul class="space-y-1.5">${evidenceHtml}</ul>
          </div>` : ''}
          <!-- Detailed summary (only if different from conclusion) -->
          ${summary && summary !== conclusion ? `
          <div class="border-t border-white/10 px-4 py-3">
            <p class="text-xs text-slate-500 uppercase tracking-wider mb-1">診斷說明</p>
            <p class="text-xs text-slate-600 leading-relaxed">${_esc(summary)}</p>
          </div>` : ''}
          <!-- Human recommendation (expert-authored, always shown) -->
          <div class="border-t border-white/10 px-4 py-3">
            <p class="text-xs text-amber-400/80 uppercase tracking-wider mb-1">⚠ 專家建議處置（Human-Defined）</p>
            ${humanRec
              ? `<p class="text-xs text-slate-600 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">${_esc(humanRec)}</p>`
              : `<p class="text-xs text-slate-500 italic">尚未填寫（請至 Step 2 B 欄位填寫）</p>`
            }
          </div>
        </div>
      `;
    }
  } catch (e) {
    statusEl.innerHTML = `<p class="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">✗ 請求失敗：${_esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ 重新模擬診斷';
  }
}

async function _generateCodeDiagnosis() {
  const diagPrompt     = document.getElementById('skill-diag-prompt')?.value?.trim();
  const problemSubject = document.getElementById('skill-problem-subject')?.value?.trim() || null;
  const statusEl       = document.getElementById('skill-code-diag-status');
  const resultEl       = document.getElementById('skill-code-diag-result');
  const btn            = document.getElementById('skill-code-diag-btn');

  if (!diagPrompt) { alert('請先填寫「異常判斷條件（Diagnostic Prompt）」'); return; }
  if (!_selectedSkillMcp) { alert('請先在 Step 1 選擇 MCP'); return; }

  // Build MCP sample outputs
  const mcp = _mcpDefs.find(m => m.id === _selectedSkillMcp);
  const mcpSampleOutputs = {};
  if (mcp) {
    const outputData = _skillMcpExecResult?.output_data || mcp.sample_output;
    if (outputData && Object.keys(outputData).length > 0) {
      mcpSampleOutputs[mcp.name] = outputData;
    }
  }
  if (Object.keys(mcpSampleOutputs).length === 0) {
    alert('無可用輸出資料。請先點擊「▶️ 執行 MCP 處理管線」或確認 MCP 已有試跑樣本資料。');
    return;
  }

  // Get event type attributes for context
  const etId = parseInt(document.getElementById('skill-event-type')?.value || '0');
  const et   = etId ? (_eventTypes||[]).find(e => e.id === etId) : null;
  let eventAttrs = [];
  if (et?.attributes) {
    try { eventAttrs = typeof et.attributes === 'string' ? JSON.parse(et.attributes) : (et.attributes || []); } catch {}
  }

  btn.disabled = true;
  if (resultEl) resultEl.innerHTML = '';

  // ── Phase 1: Check prompt + problem_subject clarity ──────────────────────
  btn.textContent = '⏳ LLM 檢查診斷配置中...';
  statusEl.innerHTML = '<div class="llm-loading"><div class="llm-spinner"></div><span>LLM 正在評估診斷條件與有問題的物件...</span></div>';

  let check;
  try {
    const firstKey = Object.keys(mcpSampleOutputs)[0];
    check = await _api('POST', '/skill-definitions/check-code-diagnosis-intent', {
      diagnostic_prompt: diagPrompt,
      problem_subject:   problemSubject,
      mcp_output_sample: firstKey ? mcpSampleOutputs[firstKey] : {},
      event_attributes:  eventAttrs,
    });
  } catch (_e) {
    // Non-fatal — skip check and generate directly
    await _runCodeDiagnosis(diagPrompt, problemSubject, mcpSampleOutputs, eventAttrs);
    return;
  }

  const suggestedPrompt  = check.suggested_prompt  || diagPrompt;
  const suggestedSubject = check.suggested_problem_subject || problemSubject || '';
  const changes          = check.changes || '';
  const questions        = check.questions || [];
  const isAlreadyClear   = check.is_clear !== false;

  const promptChanged  = suggestedPrompt  !== diagPrompt;
  const subjectChanged = suggestedSubject !== (problemSubject || '');

  // Store for button callbacks
  window._pendingCodeDiagData = {
    origPrompt: diagPrompt, origSubject: problemSubject,
    suggestedPrompt, suggestedSubject,
    mcpSampleOutputs, eventAttrs,
  };

  if (promptChanged || subjectChanged) {
    const questionsHtml = questions.map(q =>
      `<li class="text-xs text-slate-400 list-disc ml-4">${_esc(q)}</li>`
    ).join('');
    const headerHtml = isAlreadyClear
      ? `<p class="text-xs text-indigo-300 font-semibold">✨ LLM 提供了更精確的診斷配置${changes ? `（${_esc(changes)}）` : ''}：</p>`
      : `<div>
           <p class="text-xs text-amber-300 font-semibold mb-1">⚠ 診斷配置尚不夠具體${changes ? `（${_esc(changes)}）` : ''}，建議確認以下問題：</p>
           ${questionsHtml ? `<ul class="space-y-0.5 mb-2">${questionsHtml}</ul>` : ''}
           <p class="text-xs text-indigo-300 font-semibold">✨ 建議的配置：</p>
         </div>`;

    statusEl.innerHTML = `
      <div class="rounded-lg border border-indigo-500/30 bg-indigo-500/5 px-4 py-3 space-y-3">
        ${headerHtml}
        ${promptChanged ? `
        <div>
          <p class="text-xs text-slate-400 mb-1">診斷條件</p>
          <div class="bg-slate-50 border border-slate-200 rounded px-3 py-2">
            <p class="text-xs text-slate-700 whitespace-pre-wrap leading-relaxed">${_esc(suggestedPrompt)}</p>
          </div>
        </div>` : ''}
        ${subjectChanged ? `
        <div>
          <p class="text-xs text-slate-400 mb-1">有問題的物件</p>
          <div class="bg-slate-50 border border-slate-200 rounded px-3 py-2">
            <p class="text-xs text-slate-700">${_esc(suggestedSubject)}</p>
          </div>
        </div>` : ''}
        <div class="flex gap-2">
          <button onclick="_applyAndRunCodeDiagnosis()"
            class="text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded px-3 py-1.5 font-medium transition-colors">
            ✨ 套用建議並生成
          </button>
          <button onclick="_runCodeDiagnosisNow()"
            class="text-xs bg-slate-600 hover:bg-slate-500 text-white rounded px-3 py-1.5 font-medium transition-colors">
            → 使用原始版本生成
          </button>
        </div>
      </div>
    `;
    btn.disabled = false;
    btn.textContent = '🐍 生成 Code 診斷';
    return;
  }

  // Prompt already clear and no changes — proceed directly
  await _runCodeDiagnosis(diagPrompt, problemSubject, mcpSampleOutputs, eventAttrs);
}

async function _applyAndRunCodeDiagnosis() {
  const d = window._pendingCodeDiagData;
  if (!d) return;
  // Optionally update form fields with suggested values
  const promptEl  = document.getElementById('skill-diag-prompt');
  const subjectEl = document.getElementById('skill-problem-subject');
  if (promptEl  && d.suggestedPrompt)  promptEl.value  = d.suggestedPrompt;
  if (subjectEl && d.suggestedSubject) subjectEl.value = d.suggestedSubject;
  await _runCodeDiagnosis(d.suggestedPrompt, d.suggestedSubject || null, d.mcpSampleOutputs, d.eventAttrs);
}

async function _runCodeDiagnosisNow() {
  const d = window._pendingCodeDiagData;
  if (!d) return;
  await _runCodeDiagnosis(d.origPrompt, d.origSubject, d.mcpSampleOutputs, d.eventAttrs);
}

/// ─── helper: render MCP output data as a standalone table section ────────────
function _renderMcpOutputSection(mcpSampleOutputs, probObj) {
  if (!mcpSampleOutputs || Object.keys(mcpSampleOutputs).length === 0) return '';
  const problemVals = _collectProblemValues(probObj);
  const sections = [];
  for (const [mcpName, outputData] of Object.entries(mcpSampleOutputs)) {
    if (!outputData || typeof outputData !== 'object') continue;

    // ── Output Schema section ──────────────────────────────────────────────
    const schemaFields = outputData.output_schema?.fields || [];
    const schemaHtml = schemaFields.length > 0 ? `
      <div class="border-b border-slate-200">
        <div class="px-4 py-2 bg-blue-50 flex items-center gap-2">
          <span class="text-xs font-semibold text-blue-700 uppercase tracking-wider">▲ Output Schema</span>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-xs border-collapse">
            <thead>
              <tr class="bg-slate-50">
                <th class="px-3 py-1.5 text-left text-slate-500 font-medium border-b border-slate-200 w-32">欄位名稱</th>
                <th class="px-3 py-1.5 text-left text-slate-500 font-medium border-b border-slate-200 w-24">型別</th>
                <th class="px-3 py-1.5 text-left text-slate-500 font-medium border-b border-slate-200">說明</th>
              </tr>
            </thead>
            <tbody>
              ${schemaFields.map((f, i) => `
                <tr class="${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}">
                  <td class="px-3 py-1 text-blue-700 font-semibold border-b border-slate-100 whitespace-nowrap">${_esc(f.name || '')}</td>
                  <td class="px-3 py-1 text-amber-600 border-b border-slate-100 whitespace-nowrap">${_esc(f.type || '')}</td>
                  <td class="px-3 py-1 text-slate-600 border-b border-slate-100">${_esc(f.description || '')}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    ` : '';

    // ── Dataset section ────────────────────────────────────────────────────
    let dataset = null;
    if (Array.isArray(outputData.dataset) && outputData.dataset.length > 0) {
      dataset = outputData.dataset;
    } else if (Array.isArray(outputData) && outputData.length > 0) {
      dataset = outputData;
    }

    let dataHtml = '';
    if (dataset) {
      const cols = schemaFields.length > 0 ? schemaFields.map(f => f.name) : Object.keys(dataset[0]);
      const rows = dataset.slice(0, 20);
      const isProblematicRow = (row) =>
        problemVals.size > 0 &&
        cols.some(c => problemVals.has(String(row[c] ?? '')));
      dataHtml = `
        <div class="overflow-x-auto max-h-52 overflow-y-auto">
          <table class="w-full text-xs border-collapse">
            <thead>
              <tr class="bg-slate-50 sticky top-0">
                ${cols.map(c => `<th class="px-2 py-1 text-left text-slate-600 font-medium border-b border-slate-200 whitespace-nowrap">${_esc(String(c))}</th>`).join('')}
              </tr>
            </thead>
            <tbody>
              ${rows.map((row, i) => {
                const hit = isProblematicRow(row);
                const rowCls = hit ? 'bg-amber-50 border-l-2 border-amber-400' : (i % 2 === 0 ? 'bg-white' : 'bg-slate-50');
                const cellCls = hit ? 'text-amber-800 font-medium' : 'text-slate-700';
                return `<tr class="${rowCls}" title="${hit ? '⚠ 異常物件' : ''}">
                  ${cols.map(c => `<td class="px-2 py-1 ${cellCls} border-b border-slate-100 whitespace-nowrap">${_esc(String(row[c] ?? ''))}</td>`).join('')}
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>
        ${dataset.length > 20 ? `<p class="text-xs text-slate-400 px-4 py-1 bg-slate-50 border-t border-slate-200">顯示前 20 筆，共 ${dataset.length} 筆</p>` : ''}
      `;
    }

    if (!schemaHtml && !dataHtml) continue;

    sections.push(`
      <div class="rounded-lg border border-slate-300 bg-white overflow-hidden mt-2">
        <div class="px-4 py-2 bg-slate-100 border-b border-slate-200 flex items-center gap-2">
          <span class="text-xs font-medium text-slate-600">📊 MCP 輸出資料：<strong>${_esc(mcpName)}</strong></span>
        </div>
        ${schemaHtml}
        ${dataHtml}
      </div>
    `);
  }
  return sections.join('');
}

// ─── helper: collect all leaf string/number values from problem_object ────────
function _collectProblemValues(obj) {
  const vals = new Set();
  if (obj === null || obj === undefined || obj === '') return vals;
  if (typeof obj === 'string' || typeof obj === 'number') {
    vals.add(String(obj));
  } else if (Array.isArray(obj)) {
    for (const v of obj) for (const x of _collectProblemValues(v)) vals.add(x);
  } else if (typeof obj === 'object') {
    for (const v of Object.values(obj)) for (const x of _collectProblemValues(v)) vals.add(x);
  }
  return vals;
}

// ─── helper: render problem_object — str / list / dict ───────────────────────
function _renderProblemObject(obj) {
  if (obj === null || obj === undefined || obj === '') {
    return '<span class="text-xs text-slate-400 italic">無</span>';
  }
  if (typeof obj === 'string' || typeof obj === 'number' || typeof obj === 'boolean') {
    return `<span class="text-xs font-semibold bg-yellow-100 text-yellow-800 border border-yellow-300 rounded px-2 py-0.5">${_esc(String(obj))}</span>`;
  }
  if (Array.isArray(obj)) {
    if (obj.length === 0) return '<span class="text-xs text-slate-400 italic">無</span>';
    // Flat list of scalars → badge row
    if (obj.every(v => typeof v !== 'object' || v === null)) {
      return `<div class="flex flex-wrap gap-1">${obj.map(v => `<span class="text-xs font-semibold bg-yellow-100 text-yellow-800 border border-yellow-300 rounded px-2 py-0.5">${_esc(String(v))}</span>`).join('')}</div>`;
    }
    // Array of objects → JSON pre
    return `<pre class="bg-amber-50 border border-amber-200 text-amber-900 text-xs rounded px-2 py-2 overflow-x-auto max-h-32 overflow-y-auto">${_esc(JSON.stringify(obj, null, 2))}</pre>`;
  }
  if (typeof obj === 'object') {
    const entries = Object.entries(obj);
    if (entries.length === 0) return '<span class="text-xs text-slate-400 italic">無</span>';
    const rows = entries.map(([k, v]) => {
      let cellHtml;
      if (v === null || v === undefined) {
        cellHtml = '<span class="text-slate-400 italic">—</span>';
      } else if (Array.isArray(v)) {
        if (v.every(x => typeof x !== 'object' || x === null)) {
          // Flat scalar array → inline badges
          cellHtml = `<div class="flex flex-wrap gap-0.5">${v.map(x => `<span class="inline-block bg-yellow-100 text-yellow-800 border border-yellow-300 rounded px-1.5">${_esc(String(x))}</span>`).join('')}</div>`;
        } else {
          cellHtml = `<pre class="text-xs text-amber-900 whitespace-pre-wrap">${_esc(JSON.stringify(v, null, 2))}</pre>`;
        }
      } else if (typeof v === 'object') {
        cellHtml = `<pre class="text-xs text-amber-900 whitespace-pre-wrap">${_esc(JSON.stringify(v, null, 2))}</pre>`;
      } else {
        cellHtml = `<span class="text-amber-800 font-semibold">${_esc(String(v))}</span>`;
      }
      return `<tr>
        <td class="py-0.5 pr-3 text-slate-500 font-medium whitespace-nowrap align-top">${_esc(k)}</td>
        <td class="py-0.5 align-top">${cellHtml}</td>
      </tr>`;
    }).join('');
    return `<table class="text-xs w-full border-collapse mt-1">${rows}</table>`;
  }
  return `<span class="text-xs font-semibold bg-yellow-100 text-yellow-800 border border-yellow-300 rounded px-2 py-0.5">${_esc(String(obj))}</span>`;
}

// ── helper: build check_output_schema badge HTML ─────────────────────────────
function _renderSchemaBadges(chkSchema) {
  if (!chkSchema?.fields?.length) return '';
  const fieldBadges = chkSchema.fields.map(f => {
    // status field gets special styling — it's a fixed standard output
    const isStatus = f.name === 'status';
    return `<span class="inline-flex items-center gap-1 px-2 py-0.5 ${isStatus ? 'bg-violet-50 border-violet-300' : 'bg-white border-slate-200'} border rounded text-slate-600">
      <span class="${isStatus ? 'text-violet-700' : 'text-blue-600'} font-semibold">${_esc(f.name)}</span>
      <span class="text-slate-400">·</span>
      <span class="text-amber-600">${_esc(f.type)}</span>
    </span>`;
  }).join('');
  return `<div class="mt-1.5 flex flex-wrap items-center gap-1.5">
    <span class="text-xs text-slate-400">Output Schema：</span>
    ${fieldBadges}
  </div>`;
}

// ── helper: render a saved diagnosis result into statusEl + resultEl ──────────
function _showDiagnosisResult(saved, { isPreload = false } = {}) {
  const statusEl = document.getElementById('skill-code-diag-status');
  const resultEl = document.getElementById('skill-code-diag-result');
  if (!statusEl || !resultEl || !saved) return;

  const skillStatus = (saved.status || 'ABNORMAL').toUpperCase();
  const diagMsg     = saved.diagnosis_message   || '';
  const probObj     = saved.problem_object;
  const genCode     = saved.generated_code      || '';
  const chkSchema   = saved.check_output_schema || null;
  const ts          = saved.timestamp ? new Date(saved.timestamp).toLocaleString('zh-TW', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' }) : '';
  const hasProb     = probObj !== null && probObj !== undefined &&
                      !(typeof probObj === 'string' && probObj === '') &&
                      !(typeof probObj === 'object' && !Array.isArray(probObj) && Object.keys(probObj).length === 0);

  // Status badge — most prominent element
  const isAbnormal    = skillStatus === 'ABNORMAL';
  const statusBadge   = isAbnormal
    ? `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-red-100 border border-red-300 text-red-700 font-bold text-xs">⚠ ABNORMAL</span>`
    : `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-green-100 border border-green-300 text-green-700 font-bold text-xs">✓ NORMAL</span>`;

  const label = isPreload
    ? `📋 上次記錄的診斷結果${ts ? `（${ts}）` : ''}　<button onclick="_clearDiagnosisResult()" class="text-xs text-slate-400 hover:text-red-400 underline ml-2">清除</button>`
    : `✓ Code 診斷完成，結果已記錄`;
  const statusColor = isPreload ? 'bg-slate-100 border-slate-200' : 'bg-green-400/10 border-green-400/20';
  const textColor   = isPreload ? 'text-slate-600' : 'text-green-400 font-medium';

  statusEl.innerHTML = `
    <div class="text-xs ${statusColor} border rounded-lg px-3 py-2 mb-2">
      <div class="flex items-center gap-2 mb-1">
        ${statusBadge}
        <p class="${textColor}">${label}</p>
      </div>
      ${_renderSchemaBadges(chkSchema)}
    </div>`;

  const borderColor = isAbnormal ? 'border-red-300/50 bg-red-50/30' : 'border-green-300/50 bg-green-50/30';
  resultEl.innerHTML = `
    <div class="rounded-lg border ${borderColor} overflow-hidden">
      <div class="px-4 py-3 border-b border-slate-200/50">
        <p class="text-xs text-slate-500 uppercase tracking-wider mb-1">診斷訊息</p>
        <p class="text-sm text-slate-700 leading-relaxed">${_esc(diagMsg)}</p>
      </div>
      <div class="px-4 py-3">
        <p class="text-xs text-slate-500 uppercase tracking-wider mb-2">異常物件</p>
        ${hasProb ? _renderProblemObject(probObj) : '<span class="text-xs text-slate-400 italic">無（正常）</span>'}
      </div>
    </div>
    <div class="rounded-lg border border-slate-200 bg-white overflow-hidden mt-2">
      <div class="px-4 py-3">
        <p class="text-xs text-slate-500 uppercase tracking-wider mb-2 cursor-pointer hover:text-purple-500"
           onclick="this.nextElementSibling.classList.toggle('hidden')">
          🐍 生成的 PYTHON 函式（點擊展開 / 收起）
        </p>
        <pre class="hidden bg-slate-900 text-green-300 text-xs rounded-lg px-3 py-3 overflow-x-auto whitespace-pre-wrap max-h-64 overflow-y-auto"><code>${_esc(genCode)}</code></pre>
      </div>
    </div>`;
}

// ── clear pre-loaded diagnosis result ────────────────────────────────────────
function _clearDiagnosisResult() {
  _diagnosisRunResult = null;
  const statusEl = document.getElementById('skill-code-diag-status');
  const resultEl = document.getElementById('skill-code-diag-result');
  if (statusEl) statusEl.innerHTML = '';
  if (resultEl) resultEl.innerHTML = '';
  // Persist clear to backend if editing existing skill
  if (_editingId) {
    _api('PATCH', `/skill-definitions/${_editingId}`, { last_diagnosis_result: null }).catch(() => {});
  }
}

async function _runCodeDiagnosis(prompt, subject, mcpSampleOutputs, eventAttrs) {
  const statusEl = document.getElementById('skill-code-diag-status');
  const resultEl = document.getElementById('skill-code-diag-result');
  const btn      = document.getElementById('skill-code-diag-btn');

  btn.disabled = true;
  if (resultEl) resultEl.innerHTML = '';
  statusEl.innerHTML = '<div class="llm-loading"><div class="llm-spinner"></div><span>LLM 正在生成 Python 診斷函式，約 15~40 秒...</span></div>';

  try {
    const result = await _api('POST', '/skill-definitions/generate-code-diagnosis', {
      diagnostic_prompt:  prompt,
      problem_subject:    subject,
      mcp_sample_outputs: mcpSampleOutputs,
      event_attributes:   eventAttrs || [],
    });

    if (!result.success) {
      statusEl.innerHTML = `<p class="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">✗ 生成失敗：${_esc(result.error || '未知錯誤')}</p>`;
      return;
    }

    _diagnosisRunResult = {
      status:              result.status              || 'ABNORMAL',
      diagnosis_message:   result.diagnosis_message   || '',
      problem_object:      result.problem_object,
      generated_code:      result.generated_code      || '',
      check_output_schema: result.check_output_schema || null,
      timestamp:           new Date().toISOString(),
    };

    _showDiagnosisResult(_diagnosisRunResult, { isPreload: false });

    // Auto-save to backend for existing skills
    if (_editingId) {
      _api('PATCH', `/skill-definitions/${_editingId}`, { last_diagnosis_result: _diagnosisRunResult }).catch(() => {});
    }
  } catch (e) {
    statusEl.innerHTML = `<p class="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">✗ 請求失敗：${_esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '🐍 重新生成 Code 診斷';
  }
}

async function _saveSkill(id) {
  const name = document.getElementById('skill-name').value.trim();
  if (!name) { alert('請填寫 Skill 名稱'); return; }

  const diagPromptEl = document.getElementById('skill-diag-prompt');
  const humanRecEl  = document.getElementById('skill-human-rec');
  const payload = {
    name,
    description: document.getElementById('skill-desc').value.trim(),
    problem_subject: document.getElementById('skill-problem-subject')?.value.trim() || null,
    mcp_id: _selectedSkillMcp || null,
    diagnostic_prompt: diagPromptEl ? diagPromptEl.value.trim() : '',
    human_recommendation: humanRecEl ? humanRecEl.value.trim() : '',
  };

  try {
    if (id) await _api('PATCH', `/skill-definitions/${id}`, payload);
    else    await _api('POST', '/skill-definitions', payload);
    closeDrawer(true);
    _loadSkillDefs();
  } catch (e) { alert(`儲存失敗：${e.message}`); }
}

async function _deleteSkill(id) {
  if (!confirm('確定要刪除此 Skill？')) return;
  try {
    await _api('DELETE', `/skill-definitions/${id}`);
    closeDrawer(true);
    _loadSkillDefs();
  } catch (e) { alert(`刪除失敗：${e.message}`); }
}

// ══════════════════════════════════════════════════════════════
// Phase 8.5 — Settings (System Parameters / Prompt Management)
// ══════════════════════════════════════════════════════════════

async function _loadSettings() {
  const body = document.getElementById('settings-body');
  if (!body) return;
  body.innerHTML = '<div class="text-center text-slate-500 py-10 text-sm">載入中…</div>';
  try {
    _systemParams = await _api('GET', '/system-parameters');
    _renderSettingsView();
  } catch (e) {
    body.innerHTML = `<p class="text-red-400 text-sm px-4">載入失敗：${_esc(e.message)}</p>`;
  }
}

function _renderSettingsView() {
  const body = document.getElementById('settings-body');
  if (!body) return;

  const LABELS = {
    PROMPT_MCP_GENERATE:   { title: 'MCP 生成 Prompt (PROMPT_MCP_GENERATE)',   hint: '用於 LLM 生成 script / output_schema / UI config / input_params，支援 {data_subject_name}、{data_subject_output_schema}、{processing_intent} 佔位符。' },
    PROMPT_MCP_TRY_RUN:    { title: 'MCP Try-Run 系統 Prompt (PROMPT_MCP_TRY_RUN)',  hint: '約束 LLM 生成 Try-Run 執行腳本的系統指令，包含沙盒規則與 Standard Payload 格式。' },
    PROMPT_SKILL_DIAGNOSIS: { title: 'Skill 診斷系統 Prompt (PROMPT_SKILL_DIAGNOSIS)', hint: '約束 LLM 產生 Skill 模擬診斷結果的系統指令，需輸出 JSON。' },
  };

  if (!Array.isArray(_systemParams) || _systemParams.length === 0) {
    body.innerHTML = '<p class="text-slate-500 text-sm px-4 py-6">目前沒有可管理的系統參數。</p>';
    return;
  }

  const cards = _systemParams.map(p => {
    const meta = LABELS[p.key] || { title: p.key, hint: p.description || '' };
    return `
      <div class="bg-white border border-slate-200 rounded-xl p-5 flex flex-col gap-3">
        <div>
          <h3 class="text-sm font-semibold text-slate-800">${_esc(meta.title)}</h3>
          ${meta.hint ? `<p class="text-xs text-slate-500 mt-1">${_esc(meta.hint)}</p>` : ''}
        </div>
        <textarea
          id="sp-textarea-${_esc(p.key)}"
          rows="10"
          class="w-full bg-white border border-slate-300 rounded-lg px-3 py-2 text-xs text-slate-800 font-mono resize-y focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >${_esc(p.value || '')}</textarea>
        <div class="flex items-center gap-3">
          <button
            id="sp-save-btn-${_esc(p.key)}"
            onclick="_savePrompt('${_esc(p.key)}')"
            class="px-4 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors"
          >儲存</button>
          <span id="sp-status-${_esc(p.key)}" class="text-xs text-slate-500"></span>
        </div>
      </div>
    `;
  }).join('');

  body.innerHTML = `
    <div class="flex flex-col gap-6 p-6">
      <div class="flex items-start gap-3 bg-amber-500/10 border border-amber-500/20 rounded-xl px-4 py-3">
        <span class="text-amber-400 text-lg">⚠️</span>
        <p class="text-xs text-amber-300 leading-relaxed">
          此頁面供 IT Admin 管理 LLM Prompt 模板。修改後立即生效，無需重啟服務。
          若誤改導致功能異常，請聯繫系統管理員或清空欄位讓系統使用預設 Prompt。
        </p>
      </div>
      ${cards}
    </div>
  `;
}

async function _savePrompt(key) {
  const textarea = document.getElementById(`sp-textarea-${key}`);
  const btn      = document.getElementById(`sp-save-btn-${key}`);
  const statusEl = document.getElementById(`sp-status-${key}`);
  if (!textarea || !btn) return;

  const newValue = textarea.value.trim();
  if (!newValue) {
    statusEl.textContent = '⚠️ 內容不得為空';
    statusEl.className = 'text-xs text-amber-400';
    return;
  }

  btn.disabled = true;
  btn.textContent = '儲存中…';
  statusEl.textContent = '';

  try {
    await _api('PATCH', `/system-parameters/${encodeURIComponent(key)}`, { value: newValue });
    // Update local cache
    const idx = _systemParams.findIndex(p => p.key === key);
    if (idx !== -1) _systemParams[idx].value = newValue;
    statusEl.textContent = '✓ 已儲存';
    statusEl.className = 'text-xs text-emerald-400';
    setTimeout(() => { statusEl.textContent = ''; }, 3000);
  } catch (e) {
    statusEl.textContent = `✗ 儲存失敗：${e.message}`;
    statusEl.className = 'text-xs text-red-400';
  } finally {
    btn.disabled = false;
    btn.textContent = '儲存';
  }
}

// Reference data is loaded lazily on first switchView() call to each panel.

// ══════════════════════════════════════════════════════════════
// Phase 8.6 — Universal Data Viewer (UDV)
// ══════════════════════════════════════════════════════════════

/**
 * _udv(data, uid) — returns HTML for a 3-tab data viewer (Tree / Grid / Raw).
 * uid must be unique per instance to avoid DOM conflicts.
 */
function _udv(data, uid) {
  const json = _prettyJson(data);
  return `
    <div class="udv-container" id="udv-${uid}">
      <div class="udv-tab-bar">
        <button class="udv-tab udv-tab-active" onclick="_uvSwitch('${uid}','tree')">Tree</button>
        <button class="udv-tab" onclick="_uvSwitch('${uid}','grid')">Grid</button>
        <button class="udv-tab" onclick="_uvSwitch('${uid}','raw')">Raw</button>
        <button class="udv-copy-btn" onclick="_uvCopy('${uid}')" title="複製 JSON">📋</button>
      </div>
      <div id="udv-panel-tree-${uid}" class="udv-panel">
        <div class="udv-tree-root">${_uvTreeNode(data, 0)}</div>
      </div>
      <div id="udv-panel-grid-${uid}" class="udv-panel hidden">
        ${_uvGrid(data)}
      </div>
      <div id="udv-panel-raw-${uid}" class="udv-panel hidden">
        <pre class="udv-raw-text">${_esc(json)}</pre>
      </div>
      <textarea id="udv-json-${uid}" class="hidden" aria-hidden="true">${_esc(json)}</textarea>
    </div>
  `;
}

function _uvSwitch(uid, tab) {
  const tabs = ['tree', 'grid', 'raw'];
  for (const t of tabs) {
    const panel = document.getElementById(`udv-panel-${t}-${uid}`);
    if (panel) panel.classList.toggle('hidden', t !== tab);
  }
  const container = document.getElementById(`udv-${uid}`);
  if (!container) return;
  container.querySelectorAll('.udv-tab').forEach((btn, i) => {
    btn.classList.toggle('udv-tab-active', ['tree', 'grid', 'raw'][i] === tab);
  });
}

/** Render a leaf (primitive) value as an inline span. */
function _uvLeaf(v) {
  if (v === null)             return '<span class="udv-null">null</span>';
  if (typeof v === 'boolean') return `<span class="udv-bool">${v}</span>`;
  if (typeof v === 'number')  return `<span class="udv-number">${v}</span>`;
  if (typeof v === 'string')  return `<span class="udv-string">"${_esc(v)}"</span>`;
  return `<span>${_esc(String(v))}</span>`;
}

/**
 * Render the children rows of an object/array.
 * Every row is a <div> — no inline/block mixing.
 */
function _uvChildren(data, depth) {
  const isArr = Array.isArray(data);
  const entries = isArr ? data.map((v, i) => [String(i), v]) : Object.entries(data);
  const maxShow = 50;
  let html = '';

  for (const [k, v] of entries.slice(0, maxShow)) {
    const keyHtml = isArr
      ? `<span class="udv-idx">${k}</span>`
      : `<span class="udv-key">"${_esc(k)}"</span>`;

    if (v !== null && typeof v === 'object') {
      const isVArr  = Array.isArray(v);
      const ob      = isVArr ? '[' : '{';
      const cb      = isVArr ? ']' : '}';
      const vLen    = isVArr ? v.length : Object.keys(v).length;
      const uid     = 'uvt' + Math.random().toString(36).slice(2, 8);

      if (vLen === 0) {
        html += `<div class="udv-tree-row" style="padding-left:${depth * 14}px">${keyHtml}<span class="udv-sep">: </span><span class="udv-bracket">${ob}${cb}</span></div>`;
      } else {
        html += `
          <div class="udv-tree-row udv-row-toggle" style="padding-left:${depth * 14}px"
               onclick="const el=document.getElementById('${uid}');el.classList.toggle('hidden');this.querySelector('.uvtgl').textContent=el.classList.contains('hidden')?'▸':'▾'">
            ${keyHtml}<span class="udv-sep">: </span><span class="uvtgl udv-toggle">▾</span><span class="udv-bracket"> ${ob}</span>
          </div>
          <div id="${uid}">
            ${_uvChildren(v, depth + 1)}
            <div class="udv-tree-row" style="padding-left:${depth * 14}px"><span class="udv-bracket">${cb}</span></div>
          </div>`;
      }
    } else {
      html += `<div class="udv-tree-row" style="padding-left:${depth * 14}px">${keyHtml}<span class="udv-sep">: </span>${_uvLeaf(v)}</div>`;
    }
  }

  if (entries.length > maxShow) {
    html += `<div class="udv-more" style="padding-left:${depth * 14}px">… 共 ${entries.length} 項，僅顯示前 ${maxShow}</div>`;
  }
  return html;
}

/**
 * Render the root node of the tree (no parent key context).
 * Returns full block HTML — all rows are <div> elements.
 */
function _uvTreeNode(data, depth) {
  if (data === null || typeof data !== 'object') {
    return `<div class="udv-tree-row">${_uvLeaf(data)}</div>`;
  }

  const isArr = Array.isArray(data);
  const ob    = isArr ? '[' : '{';
  const cb    = isArr ? ']' : '}';
  const len   = isArr ? data.length : Object.keys(data).length;

  if (len === 0) {
    return `<div class="udv-tree-row"><span class="udv-bracket">${ob}${cb}</span></div>`;
  }

  const uid = 'uvt' + Math.random().toString(36).slice(2, 8);
  return `
    <div class="udv-tree-row udv-row-toggle"
         onclick="const el=document.getElementById('${uid}');el.classList.toggle('hidden');this.querySelector('.uvtgl').textContent=el.classList.contains('hidden')?'▸':'▾'">
      <span class="uvtgl udv-toggle">▾</span><span class="udv-bracket"> ${ob}</span>
    </div>
    <div id="${uid}">
      ${_uvChildren(data, 1)}
      <div class="udv-tree-row"><span class="udv-bracket">${cb}</span></div>
    </div>`;
}

/**
 * Grid tab: arrays → horizontal table, dicts → key-value record.
 * For array-of-objects this renders a proper column table.
 */
function _uvGrid(data) {
  if (Array.isArray(data)) {
    // Array: delegate to smart table renderer (horizontal if array-of-dicts)
    return _renderDatasetTable(data);
  }
  if (data !== null && typeof data === 'object') {
    // Dict: key-value record view
    return _renderRecordView(data);
  }
  return _renderGrid(data);
}

function _uvCopy(uid) {
  const ta = document.getElementById(`udv-json-${uid}`);
  if (!ta) return;
  navigator.clipboard?.writeText(ta.value).then(() => {
    const btn = document.querySelector(`#udv-${uid} .udv-copy-btn`);
    if (btn) {
      const orig = btn.textContent;
      btn.textContent = '✓';
      setTimeout(() => { btn.textContent = orig; }, 1200);
    }
  });
}

// ══════════════════════════════════════════════════════════════
// Phase 8.6 — MCP Try-Session Multi-Tab
// ══════════════════════════════════════════════════════════════

function _initTryTabs(initialIntent) {
  _tryTabs = [];
  _activeTryTabN = 1;
  _addTryTab(initialIntent, true);
}

function _addTryTab(intent, isInitial) {
  const n = _tryTabs.length + 1;
  _tryTabs.push({ n, intent: intent || '', status: 'idle' });
  _activeTryTabN = n;
  _renderTryTabBar();
  _renderActiveTryTab();
}

function _switchTryTab(n) {
  _activeTryTabN = n;
  _renderTryTabBar();
  _renderActiveTryTab();
}

function _renderTryTabBar() {
  const bar = document.getElementById('try-tab-bar');
  if (!bar) return;
  const statusIcon = { idle: '', running: ' ⏳', done: ' ✓', error: ' ✗' };
  const tabBtns = _tryTabs.map(t => {
    const icon = statusIcon[t.status] || '';
    const isActive = t.n === _activeTryTabN;
    return `<button class="try-tab-btn${isActive ? ' active-try' : ''}" onclick="_switchTryTab(${t.n})">Try ${t.n}${icon}</button>`;
  }).join('');
  const addBtn = `<button class="try-tab-btn try-tab-new" onclick="_addTryTab('')" title="新增試跑分頁">+ New</button>`;
  bar.innerHTML = tabBtns + addBtn;
}

function _renderActiveTryTab() {
  const content = document.getElementById('try-tab-content');
  if (!content) return;
  const tab = _tryTabs.find(t => t.n === _activeTryTabN);
  if (!tab) return;
  const n = tab.n;
  content.innerHTML = `
    <div class="builder-field">
      <label class="builder-label required">加工意圖（自然語言）— Try ${n}</label>
      <textarea id="mcp-intent-${n}" class="builder-textarea" rows="3"
        placeholder="例如：列出所有補償參數的名稱與數值，以長條圖呈現">${_esc(tab.intent)}</textarea>
      <p class="text-xs text-slate-500 mt-1">LLM 將根據真實樣本與意圖生成 Python 腳本並立即試跑</p>
    </div>
    <div class="text-xs font-semibold text-slate-400 uppercase tracking-widest mt-4 mb-2 border-b border-slate-200 pb-1">
      Step 3 · 試跑 (Try Run) — Tab ${n}
    </div>
    <button id="mcp-tryrun-btn-${n}" class="builder-btn-llm w-full justify-center mt-1" onclick="_tryRunMCP(${n})">
      <span>✨</span> 執行試跑 (Try Run)
    </button>
    <div id="mcp-tryrun-status-${n}" class="mt-2"></div>
    <div id="mcp-tryrun-result-${n}"></div>
  `;
}


// ══════════════════════════════════════════════════════════════
// Phase 11 — Routine Check CRUD
// ══════════════════════════════════════════════════════════════

let _routineChecks = [];
let _editingRoutineCheck = null;  // null = create mode, int = edit mode

async function _loadRoutineChecks() {
  const el = document.getElementById('routine-check-list');
  if (!el) return;
  try {
    _routineChecks = await _api('GET', '/routine-checks');
    _renderRoutineChecks();
  } catch(e) {
    el.innerHTML = `<div class="text-red-500 text-sm py-6 text-center">載入失敗：${e.message}</div>`;
  }
}

function _renderRoutineChecks() {
  const el = document.getElementById('routine-check-list');
  if (!el) return;

  if (!_routineChecks.length) {
    el.innerHTML = `
      <div class="flex flex-col items-center justify-center py-16 text-slate-400">
        <svg class="w-12 h-12 mb-3 opacity-40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
        </svg>
        <p class="text-sm font-medium">尚無排程巡檢</p>
        <p class="text-xs mt-1">點擊右上角「新增排程」開始設定</p>
      </div>`;
    return;
  }

  const intervalLabel = { '30m': '每30分鐘', '1h': '每1小時', '4h': '每4小時',
                           '8h': '每8小時', '12h': '每12小時', 'daily': '每天' };
  const statusBadge = s =>
    s === 'NORMAL'   ? '<span class="px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700 border border-green-200">NORMAL</span>' :
    s === 'ABNORMAL' ? '<span class="px-2 py-0.5 rounded-full text-xs bg-orange-100 text-orange-700 border border-orange-200">ABNORMAL</span>' :
    s === 'ERROR'    ? '<span class="px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700 border border-red-200">ERROR</span>' :
    '<span class="text-slate-400 text-xs">—</span>';

  el.innerHTML = `
    <div class="space-y-3">
      ${_routineChecks.map(rc => {
        const skill = (_skillDefs||[]).find(s => s.id === rc.skill_id);
        const skillName = skill ? skill.name : `Skill #${rc.skill_id}`;
        const lastRun = rc.last_run_at ? rc.last_run_at.replace('T',' ').substring(0,16) : '未執行';
        return `
        <div class="bg-white border border-slate-200 rounded-xl p-4 shadow-sm hover:shadow transition-shadow">
          <div class="flex items-start justify-between gap-3">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-semibold text-sm text-slate-900">${_esc(rc.name)}</span>
                <span class="px-2 py-0.5 rounded-full text-xs ${rc.is_active ? 'bg-indigo-100 text-indigo-700 border border-indigo-200' : 'bg-slate-100 text-slate-500 border border-slate-200'}">
                  ${rc.is_active ? '● 啟用' : '○ 停用'}
                </span>
                <span class="text-xs text-slate-500">${intervalLabel[rc.schedule_interval] || rc.schedule_interval}</span>
              </div>
              <p class="text-xs text-slate-500 mt-1">Skill: <span class="font-medium text-slate-700">${_esc(skillName)}</span></p>
              <div class="flex items-center gap-3 mt-1">
                <span class="text-xs text-slate-400">上次執行：${lastRun}</span>
                ${statusBadge(rc.last_run_status)}
              </div>
              ${Object.keys(rc.skill_input || {}).length ? `
                <div class="mt-1 text-xs text-slate-500 font-mono bg-slate-50 rounded px-2 py-1 border border-slate-100 inline-block">
                  ${Object.entries(rc.skill_input).map(([k,v]) => `${k}=${v}`).join(' | ')}
                </div>` : ''}
            </div>
            <div class="flex gap-2 flex-shrink-0">
              <button onclick="_runNowRoutineCheck(${rc.id})"
                class="text-xs px-2.5 py-1.5 rounded-lg bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100 transition-colors font-medium">
                ▶ 立即執行
              </button>
              <button onclick="openDrawer('routine-check-edit', ${rc.id})"
                class="text-xs px-2.5 py-1.5 rounded-lg bg-slate-50 text-slate-600 border border-slate-200 hover:bg-slate-100 transition-colors">
                編輯
              </button>
            </div>
          </div>
        </div>`;
      }).join('')}
    </div>`;
}

async function _runNowRoutineCheck(id) {
  const btn = event?.target;
  if (btn) btn.disabled = true;
  try {
    const result = await _api('POST', `/routine-checks/${id}/run-now`);
    const statusMap = { NORMAL: '✅ NORMAL', ABNORMAL: '⚠️ ABNORMAL', ERROR: '❌ ERROR' };
    const statusLabel = statusMap[result.status] || result.status;
    let msg = `執行完成：${statusLabel}`;
    if (result.conclusion) msg += `\n結論：${result.conclusion}`;
    if (result.generated_event_id) msg += `\n✨ 已自動生成警報 ID #${result.generated_event_id}`;
    if (result.error) msg += `\n錯誤：${result.error}`;
    alert(msg);
    await _loadRoutineChecks();
  } catch(e) {
    alert(`執行失敗：${e.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

/**
 * Build the event-format preview section for the RoutineCheck form.
 * For CREATE: shows editable event_name + read-only description + field badges.
 * For EDIT with existing trigger_event_id: shows read-only "already created" info.
 */
function _buildRcEventPreview(skill, scheduleName, existingEtId) {
  // Edit mode — EventType already exists
  if (existingEtId) {
    const et = (_eventTypes||[]).find(e => e.id === existingEtId);
    const etName = et ? et.name : `EventType #${existingEtId}`;
    return `
      <div class="border border-emerald-200 rounded-lg p-3 bg-emerald-50/30">
        <div class="text-xs font-semibold text-emerald-700 mb-1">📋 異常時觸發的 Event</div>
        <div class="flex items-center gap-2">
          <span class="text-xs text-slate-600">已建立：</span>
          <span class="text-xs font-medium text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded">${_esc(etName)}</span>
        </div>
        <p class="text-xs text-slate-400 mt-1">此 EventType 已建立，排程異常時將自動觸發</p>
      </div>`;
  }

  // Create mode — derive from Skill's last_diagnosis_result
  const ldr = skill?.last_diagnosis_result || null;
  const fields = (ldr?.check_output_schema?.fields) || [];
  const diagMsg = ldr?.diagnosis_message || '';
  const defaultEventName = scheduleName ? `${scheduleName} 異常警報` : '';

  if (!fields.length) {
    return `
      <div class="border border-amber-200 rounded-lg p-3 bg-amber-50/40">
        <div class="text-xs font-semibold text-amber-700 mb-1">📋 異常時建立的 Event 格式</div>
        <p class="text-xs text-amber-600">
          ⚠ 此 Skill 尚未執行過「🐍 生成 Code 診斷」，無法預覽 Event 格式。<br>
          請先在 Skill Builder 執行一次診斷模擬，系統才能自動產生 Event Schema。
        </p>
        <input id="rc-event-name" type="hidden" value="">
      </div>`;
  }

  const fieldBadges = fields.map(f => {
    const isStatus = f.name === 'status';
    return `<span class="inline-flex items-center gap-1 px-2 py-0.5 ${isStatus ? 'bg-violet-50 border-violet-200' : 'bg-slate-100 border-slate-200'} border rounded text-xs text-slate-500">
      <span class="${isStatus ? 'text-violet-600' : 'text-blue-500'} font-medium">${_esc(f.name)}</span>
      <span class="text-slate-400">·</span>
      <span class="text-amber-500">${_esc(f.type || 'string')}</span>
    </span>`;
  }).join('');

  return `
    <div class="border border-emerald-200 rounded-lg p-3 bg-emerald-50/30 space-y-3">
      <div class="text-xs font-semibold text-emerald-700">📋 異常時建立的 Event 格式</div>
      <p class="text-xs text-slate-500 -mt-1">Skill 回傳 <span class="font-semibold text-red-600">ABNORMAL</span> 時，系統自動建立此格式的 Event，儲存排程時將自動建立對應 EventType</p>

      <div>
        <label class="text-xs font-medium text-slate-700 block mb-0.5">Event 名稱 <span class="text-red-500">*</span></label>
        <input id="rc-event-name" type="text" class="builder-input text-sm"
          value="${_esc(defaultEventName)}"
          placeholder="例如：SPC 巡檢異常警報">
      </div>

      <div>
        <label class="text-xs text-slate-500 block mb-0.5">說明（自動帶入，不可修改）</label>
        <div class="text-xs text-slate-400 bg-slate-50 border border-slate-200 rounded px-3 py-1.5 italic select-none">
          ${_esc(diagMsg || '由排程巡檢自動觸發')}
        </div>
      </div>

      <div>
        <label class="text-xs text-slate-500 block mb-1">Event 欄位（Skill 標準 Output，不可修改）</label>
        <div class="flex flex-wrap gap-1.5">
          ${fieldBadges}
        </div>
      </div>
    </div>`;
}

function _buildRoutineCheckForm(rc) {
  const intervalLabel = { '30m': '每30分鐘', '1h': '每1小時', '4h': '每4小時',
                           '8h': '每8小時', '12h': '每12小時', 'daily': '每天' };

  const selectedSkillId = rc?.skill_id || null;
  const skill = selectedSkillId ? (_skillDefs||[]).find(s => s.id === selectedSkillId) : null;
  const skillInputFields = _buildSkillInputFields(selectedSkillId, rc?.skill_input || {});
  const eventPreview = skill
    ? _buildRcEventPreview(skill, rc?.name || '', rc?.trigger_event_id || null)
    : `<div class="text-xs text-slate-400 py-2 pl-1">← 請先選擇 Skill，系統將自動預覽 Event 格式</div>`;

  return `
    <div class="space-y-4">
      <div class="builder-field">
        <label class="builder-label required">排程名稱</label>
        <input id="rc-name" type="text" class="builder-input" placeholder="例如：TETCH01 每小時 APC 巡檢"
          value="${_esc(rc?.name || '')}">
      </div>

      <div class="builder-field">
        <label class="builder-label required">選擇 Skill</label>
        <select id="rc-skill-id" class="builder-select w-full" onchange="_onRcSkillChange(this.value)">
          <option value="">— 請選擇 Skill —</option>
          ${(_skillDefs||[]).map(s => `<option value="${s.id}" ${rc?.skill_id==s.id?'selected':''}>${_esc(s.name)}</option>`).join('')}
        </select>
      </div>

      <div id="rc-skill-input-section">
        ${skillInputFields}
      </div>

      <div class="builder-field">
        <label class="builder-label">異常時觸發的 Event（LLM 自動建立）</label>
        <div id="rc-event-preview-section">
          ${eventPreview}
        </div>
      </div>

      <div class="builder-field">
        <label class="builder-label">巡檢頻率</label>
        <select id="rc-interval" class="builder-select w-full">
          ${Object.entries(intervalLabel).map(([v,l]) =>
            `<option value="${v}" ${(rc?.schedule_interval||'1h')==v?'selected':''}>${l}</option>`
          ).join('')}
        </select>
      </div>

      <div class="builder-field">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" id="rc-active" class="w-4 h-4 rounded" ${!rc || rc.is_active ? 'checked' : ''}>
          <span class="builder-label mb-0">啟用排程</span>
        </label>
      </div>
    </div>
  `;
}

/** Build dynamic skill_input fields from the Skill's MCP → DataSubject input_schema. */
function _buildSkillInputFields(skillId, currentValues) {
  if (!skillId) {
    return `<div class="text-xs text-slate-400 py-2">← 請先選擇 Skill，系統將自動顯示 DataSubject 查詢參數欄位</div>`;
  }

  const skill = (_skillDefs||[]).find(s => s.id == skillId);
  if (!skill) return '';

  // Resolve first MCP from skill.mcp_ids (or fallback to skill.mcp_id)
  let mcpIdList = [];
  try { mcpIdList = JSON.parse(skill.mcp_ids || '[]'); } catch {}
  if (!Array.isArray(mcpIdList)) mcpIdList = mcpIdList ? [mcpIdList] : [];
  if (mcpIdList.length === 0 && skill.mcp_id) mcpIdList = [skill.mcp_id];
  const mcpId = mcpIdList[0] || null;

  if (!mcpId) {
    return `<div class="text-xs text-slate-400 py-2">此 Skill 尚未設定 MCP，無法顯示執行參數</div>`;
  }

  const mcp = (_mcpDefs||[]).find(m => m.id === mcpId);
  if (!mcp) {
    return `<div class="text-xs text-slate-400 py-2">找不到此 Skill 的 MCP 定義</div>`;
  }

  // Get DataSubject input_schema fields (the real named query params)
  const ds = (_dataSubjects||[]).find(d => d.id === mcp.data_subject_id);
  if (!ds?.input_schema) {
    return `<div class="text-xs text-slate-400 py-2">找不到此 MCP 對應的 DataSubject 查詢參數定義</div>`;
  }

  let fields = [];
  try {
    const schema = typeof ds.input_schema === 'string'
      ? JSON.parse(ds.input_schema) : ds.input_schema;
    fields = schema.fields || [];
  } catch {}

  if (!fields.length) {
    return `<div class="text-xs text-slate-400 py-2">此 DataSubject 無需輸入參數</div>`;
  }

  return `
    <div class="border border-indigo-200 rounded-lg p-3 bg-indigo-50/50">
      <div class="text-xs font-semibold text-indigo-700 mb-2">
        📋 Skill 執行參數（DataSubject: ${_esc(ds.name || '')}）
      </div>
      <div class="space-y-2">
        ${fields.map(f => `
          <div>
            <label class="text-xs font-medium text-slate-600 block mb-0.5">
              ${_esc(f.name)}
              ${f.description ? `<span class="text-slate-400 font-normal ml-1">（${_esc(f.description)}）</span>` : ''}
              ${f.required ? '<span class="text-red-500 ml-0.5">*</span>' : ''}
            </label>
            <input class="builder-input text-sm rc-skill-input-field"
              data-field="${_esc(f.name)}"
              value="${_esc(String(currentValues[f.name] ?? ''))}"
              placeholder="${_esc(f.type === 'number' ? '數字' : f.name)}">
          </div>`).join('')}
      </div>
    </div>
  `;
}

/** Called when user changes the Skill dropdown — re-render skill_input + event preview. */
async function _onRcSkillChange(skillId) {
  const section = document.getElementById('rc-skill-input-section');
  if (section) {
    section.innerHTML = _buildSkillInputFields(skillId ? parseInt(skillId) : null, {});
  }
  // Refresh event format preview
  const previewSection = document.getElementById('rc-event-preview-section');
  if (previewSection) {
    const skill = skillId ? (_skillDefs||[]).find(s => s.id == skillId) : null;
    const scheduleName = document.getElementById('rc-name')?.value?.trim() || '';
    previewSection.innerHTML = skill
      ? _buildRcEventPreview(skill, scheduleName, null)
      : `<div class="text-xs text-slate-400 py-2 pl-1">← 請先選擇 Skill，系統將自動預覽 Event 格式</div>`;
  }
}

// ── RoutineCheck — Trigger Event Param Mapping ───────────────

/** Called when trigger event dropdown changes. */
async function _onRcTriggerEventChange(etId) {
  const section = document.getElementById('rc-event-mapping-section');
  if (!section) return;
  if (!etId) {
    section.innerHTML = '';
    return;
  }
  const skillId = parseInt(document.getElementById('rc-skill-id')?.value) || null;
  await _renderRcEventMappingRows(parseInt(etId), skillId, null);
}

/**
 * Render the event_param_mappings panel.
 * etId: trigger EventType id
 * skillId: selected Skill id (for resolving MCP output fields)
 * existingMappings: [{event_field, mcp_field}] or null
 */
async function _renderRcEventMappingRows(etId, skillId, existingMappings) {
  const section = document.getElementById('rc-event-mapping-section');
  if (!section) return;

  // Get ET attributes
  const et = (_eventTypes||[]).find(e => e.id === etId);
  if (!et) { section.innerHTML = ''; return; }

  let attrs = [];
  try {
    attrs = typeof et.attributes === 'string' ? JSON.parse(et.attributes) : (et.attributes || []);
  } catch {}

  if (!attrs.length) {
    section.innerHTML = `<div class="text-xs text-slate-400 py-2">此 EventType 無屬性需映射</div>`;
    return;
  }

  // Get MCP output fields: skill → MCP → DataSubject.output_schema.fields
  let outputFields = [];
  if (skillId) {
    // Ensure data-subjects are loaded
    if (!_dataSubjects || _dataSubjects.length === 0) {
      try { _dataSubjects = await _api('GET', '/data-subjects') || []; } catch {}
    }
    const skill = (_skillDefs||[]).find(s => s.id === skillId);
    if (skill) {
      let mcpIdList = [];
      try { mcpIdList = JSON.parse(skill.mcp_ids || '[]'); } catch {}
      if (!Array.isArray(mcpIdList)) mcpIdList = mcpIdList ? [mcpIdList] : [];
      if (mcpIdList.length === 0 && skill.mcp_id) mcpIdList = [skill.mcp_id];
      const mcpId = mcpIdList[0] || null;
      const mcp = mcpId ? (_mcpDefs||[]).find(m => m.id === mcpId) : null;
      const ds = mcp ? (_dataSubjects||[]).find(d => d.id === mcp.data_subject_id) : null;
      if (ds?.output_schema) {
        try {
          const schema = typeof ds.output_schema === 'string' ? JSON.parse(ds.output_schema) : ds.output_schema;
          outputFields = (schema.fields || []).map(f => f.name).filter(Boolean);
        } catch {}
      }
    }
  }

  // Build existing mapping lookup {event_field → mcp_field}
  const existingLookup = {};
  if (Array.isArray(existingMappings)) {
    for (const m of existingMappings) {
      if (m.event_field) existingLookup[m.event_field] = m.mcp_field || '';
    }
  }

  const rows = attrs.map(attr => {
    const attrName = typeof attr === 'string' ? attr : (attr.name || '');
    if (!attrName) return '';
    const sel = existingLookup[attrName] || '';
    const opts = outputFields.length
      ? ['', ...outputFields].map(f => `<option value="${_esc(f)}" ${f===sel?'selected':''}>${f || '— 未映射 —'}</option>`).join('')
      : `<option value="">（請先選擇 Skill）</option>`;
    return `
      <div class="flex items-center gap-2">
        <span class="text-xs font-medium text-slate-700 w-28 shrink-0 truncate" title="${_esc(attrName)}">${_esc(attrName)}</span>
        <span class="text-slate-400 text-xs">←</span>
        <select class="builder-select text-xs flex-1 rc-event-map-select" data-event-field="${_esc(attrName)}">
          ${opts}
        </select>
      </div>`;
  }).join('');

  section.innerHTML = `
    <div class="border border-amber-200 rounded-lg p-3 bg-amber-50/40">
      <div class="flex items-center justify-between mb-2">
        <div class="text-xs font-semibold text-amber-700">⚡ Event 觸發參數映射</div>
        <button type="button" class="builder-btn-secondary text-xs py-0.5 px-2"
          onclick="_autoMapRcEventParams()">✨ LLM 自動映射</button>
      </div>
      <p class="text-xs text-slate-500 mb-2">
        將 Skill MCP 的輸出欄位對應到 EventType 屬性，排程觸發警報時自動填入
      </p>
      <div id="rc-event-mapping-rows" class="space-y-1.5">
        ${rows || '<div class="text-xs text-slate-400">無可映射屬性</div>'}
      </div>
      <div id="rc-event-map-status" class="mt-2"></div>
    </div>
  `;
}

/** LLM auto-map: EventType attributes ← MCP output fields. */
async function _autoMapRcEventParams() {
  const statusEl = document.getElementById('rc-event-map-status');
  if (statusEl) statusEl.innerHTML = '<p class="text-xs text-indigo-500 italic">LLM 語意映射中...</p>';

  // Build event_schema from ET attributes
  const etId = parseInt(document.getElementById('rc-trigger-event-id')?.value) || null;
  const et = etId ? (_eventTypes||[]).find(e => e.id === etId) : null;
  if (!et) return;

  let attrs = [];
  try { attrs = typeof et.attributes === 'string' ? JSON.parse(et.attributes) : (et.attributes || []); } catch {}

  const event_schema = {};
  for (const attr of attrs) {
    const name = typeof attr === 'string' ? attr : (attr.name || '');
    const type = typeof attr === 'object' ? (attr.type || 'string') : 'string';
    const desc = typeof attr === 'object' ? (attr.description || name) : name;
    if (name) event_schema[name] = { type, description: desc };
  }

  // Build tool_input_schema from MCP output fields
  const skillId = parseInt(document.getElementById('rc-skill-id')?.value) || null;
  const skill = skillId ? (_skillDefs||[]).find(s => s.id === skillId) : null;
  let outputFields = [];
  if (skill) {
    let mcpIdList = [];
    try { mcpIdList = JSON.parse(skill.mcp_ids || '[]'); } catch {}
    if (!Array.isArray(mcpIdList)) mcpIdList = mcpIdList ? [mcpIdList] : [];
    if (mcpIdList.length === 0 && skill.mcp_id) mcpIdList = [skill.mcp_id];
    const mcpId = mcpIdList[0] || null;
    const mcp = mcpId ? (_mcpDefs||[]).find(m => m.id === mcpId) : null;
    const ds = mcp ? (_dataSubjects||[]).find(d => d.id === mcp.data_subject_id) : null;
    if (ds?.output_schema) {
      try {
        const schema = typeof ds.output_schema === 'string' ? JSON.parse(ds.output_schema) : ds.output_schema;
        outputFields = schema.fields || [];
      } catch {}
    }
  }

  if (!Object.keys(event_schema).length || !outputFields.length) {
    if (statusEl) statusEl.innerHTML = '<p class="text-xs text-slate-400">無足夠資訊進行自動映射（請確認已選擇 Skill 並設定 DataSubject output schema）</p>';
    return;
  }

  const properties = {};
  const required = [];
  for (const f of outputFields) {
    if (!f.name) continue;
    properties[f.name] = { type: f.type || 'string', description: f.description || f.name };
    if (f.required) required.push(f.name);
  }
  const tool_input_schema = { type: 'object', properties, required };

  try {
    const result = await _api('POST', '/builder/auto-map', { event_schema, tool_input_schema });
    const mappings = result.mappings || [];
    let applied = 0;
    for (const m of mappings) {
      if (!m.event_field) continue;
      const sel = document.querySelector(
        `#rc-event-mapping-rows .rc-event-map-select[data-event-field="${m.event_field}"]`
      );
      if (sel) {
        sel.value = m.tool_param || '';
        if (sel.value) applied++;
      }
    }
    if (statusEl) statusEl.innerHTML = applied > 0
      ? `<p class="text-xs text-green-600">✅ ${applied} 個參數已映射。${_esc(result.summary || '')}</p>`
      : `<p class="text-xs text-slate-400">LLM 無法自動映射，請手動選擇。</p>`;
  } catch (e) {
    if (statusEl) statusEl.innerHTML = `<p class="text-xs text-red-500">LLM 映射失敗：${_esc(e.message)}</p>`;
  }
}

// Called by drawer 'routine-check-create' / 'routine-check-edit'
async function _openRoutineCheckDrawer(id) {
  // Lazy-load dependencies
  if (!_skillDefs || _skillDefs.length === 0) {
    try { _skillDefs = await _api('GET', '/skill-definitions') || []; } catch {}
  }
  if (!_mcpDefs || _mcpDefs.length === 0) {
    try { _mcpDefs = await _api('GET', '/mcp-definitions'); } catch {}
  }
  if (!_dataSubjects || _dataSubjects.length === 0) {
    try { _dataSubjects = await _api('GET', '/data-subjects'); } catch {}
  }
  // Load EventTypes for displaying existing ET name in edit mode
  if (!_eventTypes || _eventTypes.length === 0) {
    try { _eventTypes = await _api('GET', '/event-types') || []; } catch {}
  }

  _editingRoutineCheck = id || null;
  const rc = id ? _routineChecks.find(r => r.id === id) : null;
  const title = rc ? '編輯排程巡檢' : '新增排程巡檢';
  const body = _buildRoutineCheckForm(rc);
  const footer = `
    <div class="flex gap-2 justify-end w-full">
      <button class="builder-btn-secondary" onclick="closeDrawer()">取消</button>
      ${id ? `<button class="builder-btn-danger" onclick="_deleteRoutineCheck(${id})">刪除</button>` : ''}
      <button class="builder-btn-primary" onclick="_saveRoutineCheck(${id||'null'})">
        ${id ? '更新' : '建立排程'}
      </button>
    </div>`;
  _setDrawerContent(title, body, footer);
}

async function _saveRoutineCheck(id) {
  const name = document.getElementById('rc-name')?.value.trim();
  const skillId = parseInt(document.getElementById('rc-skill-id')?.value);
  const interval = document.getElementById('rc-interval')?.value;
  const isActive = document.getElementById('rc-active')?.checked;

  if (!name) { alert('請填寫排程名稱'); return; }
  if (!skillId) { alert('請選擇 Skill'); return; }

  // Collect skill_input from dynamic fields rendered by _buildSkillInputFields()
  const skill_input = {};
  document.querySelectorAll('.rc-skill-input-field').forEach(f => {
    const key = f.dataset.field;
    const val = f.value.trim();
    if (key && val !== '') skill_input[key] = val;
  });

  // Collect event name for auto-creating EventType (create mode only)
  const generated_event_name = document.getElementById('rc-event-name')?.value?.trim() || null;

  const payload = {
    name, skill_id: skillId, skill_input,
    generated_event_name,
    schedule_interval: interval, is_active: isActive,
  };

  try {
    if (id) await _api('PUT', `/routine-checks/${id}`, payload);
    else    await _api('POST', '/routine-checks', payload);
    closeDrawer(true);
    await _loadRoutineChecks();
  } catch(e) { alert(`儲存失敗：${e.message}`); }
}

async function _deleteRoutineCheck(id) {
  if (!confirm('確定要刪除此排程巡檢？')) return;
  try {
    await _api('DELETE', `/routine-checks/${id}`);
    closeDrawer(true);
    await _loadRoutineChecks();
  } catch(e) { alert(`刪除失敗：${e.message}`); }
}


// ══════════════════════════════════════════════════════════════
// Phase 11 — Generated Events (Auto-Alarms)
// ══════════════════════════════════════════════════════════════

let _generatedEvents = [];

async function _loadGeneratedEvents() {
  const el = document.getElementById('generated-events-list');
  if (!el) return;
  try {
    _generatedEvents = await _api('GET', '/generated-events');
    _renderGeneratedEvents();
  } catch(e) {
    el.innerHTML = `<div class="text-red-500 text-sm py-6 text-center">載入失敗：${e.message}</div>`;
  }
}

function _renderGeneratedEvents() {
  const el = document.getElementById('generated-events-list');
  if (!el) return;

  if (!_generatedEvents.length) {
    el.innerHTML = `
      <div class="flex flex-col items-center justify-center py-16 text-slate-400">
        <svg class="w-12 h-12 mb-3 opacity-40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
          <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
        </svg>
        <p class="text-sm font-medium">尚無自動生成警報</p>
        <p class="text-xs mt-1">當 Skill 偵測到異常並完成 LLM 映射後，警報將自動出現在這裡</p>
      </div>`;
    return;
  }

  const statusBadge = s =>
    s === 'pending'      ? '<span class="px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700 border border-red-200 font-medium">● 待處理</span>' :
    s === 'acknowledged' ? '<span class="px-2 py-0.5 rounded-full text-xs bg-amber-100 text-amber-700 border border-amber-200">✓ 已確認</span>' :
    s === 'resolved'     ? '<span class="px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700 border border-green-200">✓ 已解決</span>' :
    `<span class="text-xs text-slate-500">${_esc(s)}</span>`;

  el.innerHTML = `
    <div class="space-y-3">
      ${_generatedEvents.map(ev => {
        const et = (_eventTypes||[]).find(e => e.id === ev.event_type_id);
        const etName = et ? et.name : `EventType #${ev.event_type_id}`;
        const skill = (_skillDefs||[]).find(s => s.id === ev.source_skill_id);
        const skillName = skill ? skill.name : `Skill #${ev.source_skill_id}`;
        const ts = ev.created_at ? ev.created_at.replace('T',' ').substring(0,16) : '';
        const params = Object.entries(ev.mapped_parameters || {})
          .filter(([k]) => !k.startsWith('_'))
          .map(([k,v]) => `<tr><td class="pr-4 text-slate-500 font-medium whitespace-nowrap">${_esc(k)}</td><td class="text-slate-900">${_esc(String(v??''))}</td></tr>`)
          .join('');

        return `
        <div class="bg-white border ${ev.status==='pending'?'border-red-200':'border-slate-200'} rounded-xl shadow-sm overflow-hidden">
          <div class="flex items-start justify-between gap-3 p-4">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-semibold text-sm text-slate-900">#${ev.id} ${_esc(etName)}</span>
                ${statusBadge(ev.status)}
              </div>
              <p class="text-xs text-slate-500 mt-0.5">來源 Skill: <span class="font-medium">${_esc(skillName)}</span>  ·  ${ts}</p>
              ${ev.skill_conclusion ? `<p class="text-xs text-slate-600 mt-1 italic">${_esc(ev.skill_conclusion)}</p>` : ''}
              ${params ? `<table class="mt-2 text-xs"><tbody>${params}</tbody></table>` : ''}
            </div>
            <div class="flex gap-2 flex-shrink-0 flex-col">
              ${ev.status === 'pending' ? `
                <button onclick="_updateAlarmStatus(${ev.id},'acknowledged')"
                  class="text-xs px-2.5 py-1.5 rounded-lg bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100 transition-colors whitespace-nowrap">
                  ✓ 確認
                </button>` : ''}
              ${ev.status !== 'resolved' ? `
                <button onclick="_updateAlarmStatus(${ev.id},'resolved')"
                  class="text-xs px-2.5 py-1.5 rounded-lg bg-green-50 text-green-700 border border-green-200 hover:bg-green-100 transition-colors whitespace-nowrap">
                  ✓ 解決
                </button>` : ''}
            </div>
          </div>
        </div>`;
      }).join('')}
    </div>`;
}

async function _updateAlarmStatus(id, newStatus) {
  try {
    await _api('PATCH', `/generated-events/${id}/status`, { status: newStatus });
    await _loadGeneratedEvents();
  } catch(e) { alert(`更新失敗：${e.message}`); }
}
