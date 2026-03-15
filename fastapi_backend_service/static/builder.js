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

async function _api(method, path, body, signal) {
  const opts = {
    method,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${_token}`,
    },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  if (signal) opts.signal = signal;
  const res = await fetch(`/api/v1${path}`, opts);
  let json;
  try {
    json = await res.json();
  } catch (e) {
    // Server returned non-JSON (e.g. HTML error page from nginx/proxy)
    throw new Error(`伺服器回傳非 JSON 回應 (HTTP ${res.status})，後端服務可能重啟中，請稍後再試。`);
  }
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
  if (name === 'dashboard')        _loadDashboard();
  if (name === 'nested-builder')   _nbInitView();
  if (name === 'data-subjects')    _loadDataSubjects();
  if (name === 'system-mcps')     _loadSystemMcps();
  if (name === 'event-types')      _loadEventTypes();
  if (name === 'mcp-builder') {
    // Ensure MCE overlay is closed and list is visible
    document.getElementById('mcp-editor')?.classList.add('hidden');
    document.getElementById('mcp-editor')?.classList.remove('flex');
    _loadMcpDefs();
  }
  if (name === 'skill-builder') {
    // Ensure SK editor is closed and list is visible
    document.getElementById('sk-editor')?.classList.add('hidden');
    document.getElementById('sk-editor')?.classList.remove('flex');
    document.getElementById('sk-list-state')?.classList.remove('hidden');
    _loadSkillDefs();
  }
  if (name === 'settings')         _loadSettings();
  if (name === 'simulator') {
    // Lazy-load the iframe: set src only on first visit to avoid pre-loading
    const iframe = document.getElementById('simulator-iframe');
    if (iframe && !iframe.dataset.loaded) {
      iframe.src = '/simulator/';
      iframe.dataset.loaded = '1';
    }
  }
  if (name === 'routine-checks')       _loadRoutineChecks();
  if (name === 'generated-events')     _loadGeneratedEvents();
  if (name === 'event-link-builder')   _elInitView();
  if (name === 'mock-data-studio')     _mdsLoadList();
  if (name === 'agent-brain')      { _brainLoadSoul(); _brainLoadPref(); _brainLoadMemories(); }
  if (name === 'arsenal')          _arsenalLoad();
  if (name === 'tool-catalog')     _toolCatalogLoad();

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
    case 'smc-create':
    case 'smc-edit':
      await _renderSystemMcpDrawer(id);
      break;
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
    case 'mds-edit':
      _mdsRenderDrawer();
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
// SYSTEM MCPs  (IT Sponsor — Phase 2)
// ══════════════════════════════════════════════════════════════

async function _loadSystemMcps() {
  const container = document.getElementById('smc-list');
  if (!container) return;
  try {
    const items = await _api('GET', '/mcp-definitions?type=system') || [];
    if (items.length === 0) {
      container.innerHTML = '<p class="text-center text-slate-600 py-12">尚無 System MCP，點擊右上角新增</p>';
      return;
    }
    container.innerHTML = items.map(smc => {
      const cfg = smc.api_config || {};
      const inSchema = smc.input_schema || {};
      const fieldCount = (inSchema.fields || []).length;
      return `
      <div class="builder-card" onclick="openDrawer('smc-edit', ${smc.id})">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="builder-card-name">${_esc(smc.name)}</span>
            <span class="builder-tag bg-blue-100 text-blue-700 border-blue-200">system</span>
            <span class="builder-tag">${_esc(cfg.method || 'GET')}</span>
          </div>
          <div class="builder-card-desc">${_esc(smc.description || '（無說明）')}</div>
          <div class="builder-card-meta flex gap-2 flex-wrap">
            <span class="builder-tag truncate max-w-xs">${_esc(cfg.endpoint_url || '未設定 endpoint')}</span>
            ${fieldCount ? `<span class="builder-tag">${fieldCount} 個查詢欄位</span>` : ''}
          </div>
        </div>
        <div class="text-slate-600 text-sm">›</div>
      </div>`;
    }).join('');
  } catch (e) {
    container.innerHTML = `<p class="text-center text-red-400 py-12">載入失敗：${_esc(e.message)}</p>`;
  }
}

/** Render the System MCP drawer — used for both create and edit. */
async function _renderSystemMcpDrawer(id) {
  let smc = null;
  if (id) {
    smc = await _api('GET', `/mcp-definitions/${id}`);
  }
  const title = id ? `編輯 System MCP — ${_esc(smc?.name || '')}` : '新增 System MCP';
  // Store the MCP id so _smcTestConnection can use run-with-data (server-side proxy)
  window._smcCurrentId = id || null;
  const cfg       = smc?.api_config  || { endpoint_url: '', method: 'GET', headers: {} };
  const inSchema  = smc?.input_schema || { fields: [] };
  const inFields  = inSchema.fields || [];

  // Render dynamic input field rows
  const fieldsHtml = inFields.map((f, i) => _smcFieldRow(i, f)).join('');

  const body = `
    <div class="builder-field">
      <label class="builder-label required">名稱</label>
      <input id="smc-name" class="builder-input" value="${_esc(smc?.name || '')}"
             placeholder="e.g. APC_Data" />
    </div>
    <div class="builder-field">
      <label class="builder-label">說明</label>
      <textarea id="smc-desc" class="builder-textarea" rows="2"
                placeholder="此 System MCP 提供的資料說明">${_esc(smc?.description || '')}</textarea>
    </div>

    <div class="text-xs font-bold text-slate-500 uppercase tracking-widest mt-4 mb-2">API 連線設定</div>

    <div class="builder-field">
      <label class="builder-label required">Endpoint URL</label>
      <input id="smc-url" class="builder-input font-mono text-sm"
             value="${_esc(cfg.endpoint_url || '')}"
             placeholder="/api/v1/mock-data/apc" />
    </div>
    <div class="builder-field">
      <label class="builder-label">HTTP Method</label>
      <select id="smc-method" class="builder-select">
        <option value="GET"  ${cfg.method !== 'POST' ? 'selected' : ''}>GET</option>
        <option value="POST" ${cfg.method === 'POST' ? 'selected' : ''}>POST</option>
      </select>
    </div>
    <div class="builder-field">
      <label class="builder-label">Headers (JSON，選填)</label>
      <textarea id="smc-headers" class="builder-textarea font-mono text-xs" rows="2"
                placeholder='{"Authorization": "Bearer token"}'>${_esc(_prettyJson(cfg.headers || {}))}</textarea>
    </div>

    <div class="text-xs font-bold text-slate-500 uppercase tracking-widest mt-4 mb-2 flex items-center justify-between">
      <span>查詢參數 (Input Schema)</span>
      <button type="button" onclick="_smcAddField()"
              class="text-xs px-2 py-0.5 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 text-indigo-700 rounded-md font-semibold">
        + 新增欄位
      </button>
    </div>
    <div id="smc-fields-container" class="space-y-2 mb-3">
      ${fieldsHtml || '<p id="smc-no-fields" class="text-xs text-slate-400 italic">目前無查詢參數，此 MCP 不需要輸入值即可呼叫</p>'}
    </div>

    <!-- Test connection panel -->
    <div class="mt-4 border border-slate-200 rounded-lg overflow-hidden">
      <div class="flex items-center justify-between bg-slate-50 px-3 py-2 border-b border-slate-200">
        <span class="text-xs font-semibold text-slate-600">🔌 測試連線</span>
        <button type="button" onclick="_smcTestConnection()"
                class="text-xs px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-md font-semibold">
          ▶ 測試
        </button>
      </div>
      <div id="smc-test-result" class="p-3 text-xs text-slate-400 italic min-h-[48px]">
        儲存後填入查詢參數並點擊「測試」，確認 API 連線正常。
      </div>
    </div>
  `;

  const footer = `
    <button class="builder-btn-secondary" onclick="closeDrawer()">取消</button>
    ${id ? `<button class="builder-btn-danger mr-auto" onclick="_deleteSystemMcp(${id})">刪除</button>` : ''}
    <button class="builder-btn-primary" onclick="_saveSystemMcp(${id || 'null'})">
      ${id ? '更新' : '建立'}
    </button>
  `;

  _setDrawerContent(title, body, footer);
  _smcFieldIndex = inFields.length;
}

/** Counter for dynamic field rows */
let _smcFieldIndex = 0;

/** Render one input-schema field row */
function _smcFieldRow(i, f = {}) {
  return `
    <div id="smc-field-${i}" class="flex items-center gap-1.5 bg-slate-50 border border-slate-200 rounded-lg px-2 py-1.5">
      <input class="builder-input text-xs flex-1 min-w-0" placeholder="欄位名稱 (e.g. lot_id)"
             id="smc-fname-${i}" value="${_esc(f.name || '')}">
      <select class="builder-select text-xs w-24 shrink-0" id="smc-ftype-${i}">
        <option value="string"  ${(f.type||'string') === 'string'  ? 'selected' : ''}>string</option>
        <option value="number"  ${f.type === 'number'  ? 'selected' : ''}>number</option>
        <option value="boolean" ${f.type === 'boolean' ? 'selected' : ''}>boolean</option>
      </select>
      <input class="builder-input text-xs flex-1 min-w-0" placeholder="說明"
             id="smc-fdesc-${i}" value="${_esc(f.description || '')}">
      <label class="flex items-center gap-1 text-xs text-slate-500 shrink-0 cursor-pointer">
        <input type="checkbox" id="smc-freq-${i}" ${f.required ? 'checked' : ''} class="accent-indigo-600"> 必填
      </label>
      <button type="button" onclick="_smcRemoveField(${i})"
              class="text-slate-400 hover:text-red-500 text-sm font-bold shrink-0 px-1">✕</button>
    </div>`;
}

function _smcAddField() {
  const container = document.getElementById('smc-fields-container');
  if (!container) return;
  const noFields = document.getElementById('smc-no-fields');
  if (noFields) noFields.remove();
  const div = document.createElement('div');
  div.innerHTML = _smcFieldRow(_smcFieldIndex);
  container.appendChild(div.firstElementChild);
  _smcFieldIndex++;
}

function _smcRemoveField(i) {
  document.getElementById(`smc-field-${i}`)?.remove();
  if (!document.getElementById('smc-fields-container')?.children.length) {
    document.getElementById('smc-fields-container').innerHTML =
      '<p id="smc-no-fields" class="text-xs text-slate-400 italic">目前無查詢參數</p>';
  }
}

/** Collect all input-schema field rows from the drawer */
function _smcCollectFields() {
  const fields = [];
  const container = document.getElementById('smc-fields-container');
  if (!container) return fields;
  for (let i = 0; i < _smcFieldIndex; i++) {
    const nameEl = document.getElementById(`smc-fname-${i}`);
    if (!nameEl || !document.getElementById(`smc-field-${i}`)) continue; // removed
    const name = nameEl.value.trim();
    if (!name) continue;
    fields.push({
      name,
      type: document.getElementById(`smc-ftype-${i}`)?.value || 'string',
      description: document.getElementById(`smc-fdesc-${i}`)?.value.trim() || '',
      required: document.getElementById(`smc-freq-${i}`)?.checked || false,
    });
  }
  return fields;
}

async function _saveSystemMcp(id) {
  const name = document.getElementById('smc-name')?.value.trim();
  if (!name) { alert('請填寫名稱'); return; }
  const url = document.getElementById('smc-url')?.value.trim();
  if (!url) { alert('請填寫 Endpoint URL'); return; }

  let headers = {};
  try { headers = JSON.parse(document.getElementById('smc-headers')?.value || '{}'); } catch {}

  const payload = {
    name,
    description: document.getElementById('smc-desc')?.value.trim() || '',
    mcp_type: 'system',
    api_config: {
      endpoint_url: url,
      method: document.getElementById('smc-method')?.value || 'GET',
      headers,
    },
    input_schema: { fields: _smcCollectFields() },
  };

  try {
    if (id) {
      await _api('PATCH', `/mcp-definitions/${id}`, payload);
    } else {
      await _api('POST', '/mcp-definitions', payload);
    }
    // Invalidate system MCP cache so dropdowns refresh
    _dataSubjects = [];
    closeDrawer(true);
    _loadSystemMcps();
  } catch (e) {
    alert(`儲存失敗：${e.message}`);
  }
}

async function _deleteSystemMcp(id) {
  if (!confirm('確定要刪除此 System MCP？相依的 Custom MCP 將失去資料來源。')) return;
  try {
    await _api('DELETE', `/mcp-definitions/${id}`);
    _dataSubjects = [];
    closeDrawer(true);
    _loadSystemMcps();
  } catch (e) { alert(`刪除失敗：${e.message}`); }
}

async function _smcTestConnection() {
  const resultEl = document.getElementById('smc-test-result');
  const mcpId    = window._smcCurrentId;

  // System MCP endpoints are on localhost:8001 — cannot be called directly from
  // the browser. Route through the AIOps backend (run-with-data) which acts as
  // a server-side proxy. Requires the MCP to already be saved (has an id).
  if (!mcpId) {
    if (resultEl) resultEl.innerHTML = '<span class="text-amber-500">請先儲存此 System MCP，再進行測試。</span>';
    return;
  }

  if (resultEl) resultEl.innerHTML = '<span class="animate-pulse text-slate-400">連線測試中…</span>';

  // Collect any filled-in param test values from field rows
  const params = {};
  for (let i = 0; i < _smcFieldIndex; i++) {
    if (!document.getElementById(`smc-field-${i}`)) continue;
    const nameEl = document.getElementById(`smc-fname-${i}`);
    const valEl  = document.getElementById(`smc-test-param-${i}`);
    if (nameEl?.value.trim() && valEl?.value.trim()) {
      params[nameEl.value.trim()] = valEl.value.trim();
    }
  }

  // Inject test-value inputs next to field rows if not yet present
  const container = document.getElementById('smc-fields-container');
  let hasTestInputs = !!document.getElementById('smc-test-param-0');
  if (!hasTestInputs && container && _smcFieldIndex > 0) {
    for (let i = 0; i < _smcFieldIndex; i++) {
      const row = document.getElementById(`smc-field-${i}`);
      if (!row || document.getElementById(`smc-test-param-${i}`)) continue;
      const inp = document.createElement('input');
      inp.id = `smc-test-param-${i}`;
      inp.className = 'builder-input text-xs w-24 shrink-0 border-dashed';
      inp.placeholder = '測試值';
      row.insertBefore(inp, row.querySelector('button'));
    }
    if (resultEl) resultEl.innerHTML = '<span class="text-slate-400">請在各欄位旁填入測試值，再點擊測試。</span>';
    return;
  }

  try {
    // Call run-with-data — backend proxies to localhost:8001 server-side
    const data = await _api('POST', `/mcp-definitions/${mcpId}/run-with-data`, { raw_data: params });
    const preview = JSON.stringify(data?.dataset ?? data, null, 2).slice(0, 800);
    if (resultEl) resultEl.innerHTML = `
      <div class="text-emerald-600 font-semibold mb-1">✓ 連線成功</div>
      <pre class="text-xs text-slate-600 whitespace-pre-wrap leading-relaxed max-h-40 overflow-y-auto">${_esc(preview)}${preview.length >= 800 ? '\n…（截斷）' : ''}</pre>`;
  } catch (e) {
    if (resultEl) resultEl.innerHTML = `<span class="text-red-500">✗ 連線失敗：${_esc(e.message)}</span>`;
  }
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
    const dataSourceId = mcp?.system_mcp_id || mcp?.data_subject_id;
    if (dataSourceId) {
      // Lazy-load system MCPs if needed
      if (_dataSubjects.length === 0) {
        try { _dataSubjects = await _api('GET', '/mcp-definitions?type=system') || []; } catch {}
      }
      const ds = _dataSubjects.find(d => d.id === dataSourceId);
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
    container.innerHTML = '<p class="text-xs text-slate-500 text-center py-2">找不到此 Skill MCP 對應的 System MCP 查詢參數</p>';
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

  // Build tool_input_schema from System MCP input_schema (not mcp.input_definition)
  let tool_input_schema = {};
  const _dsId = mcp.system_mcp_id || mcp.data_subject_id;
  if (_dsId) {
    if (_dataSubjects.length === 0) {
      try { _dataSubjects = await _api('GET', '/mcp-definitions?type=system') || []; } catch {}
    }
    const ds = _dataSubjects.find(d => d.id === _dsId);
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
    _mcpDefs = await _api('GET', '/mcp-definitions?type=custom') || [];
    // Always reload system MCPs so newly promoted mock sources appear in the dropdown
    _dataSubjects = await _api('GET', '/mcp-definitions?type=system') || [];
    if (_mcpDefs.length === 0) {
      container.innerHTML = '<p class="text-center text-slate-600 py-12">尚無 MCP，點擊右上角新增</p>';
      return;
    }
    container.innerHTML = _mcpDefs.map(mcp => {
      const ds = _dataSubjects.find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id));
      const hasGenerated = !!(mcp.processing_script);
      return `
        <div class="builder-card group" onclick="_mcpOpenEditor(${mcp.id})">
          <div class="flex-1">
            <div class="builder-card-name">${_esc(mcp.name)}</div>
            <div class="builder-card-desc">${_esc(mcp.description || '（無說明）')}</div>
            <div class="builder-card-meta">
              <span class="builder-tag">${_esc(ds?.name || `DS #${mcp.system_mcp_id || mcp.data_subject_id}`)}</span>
              ${hasGenerated ? '<span class="builder-tag builder-tag-green">✓ LLM 已生成</span>' : '<span class="builder-tag builder-tag-amber">待 LLM 生成</span>'}
            </div>
          </div>
          <button onclick="event.stopPropagation();_deleteMCP(${mcp.id})"
            class="opacity-0 group-hover:opacity-100 transition-opacity ml-2 px-2 py-1 text-xs text-red-500 hover:bg-red-50 rounded-lg">
            🗑
          </button>
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

  if (_dataSubjects.length === 0) _dataSubjects = await _api('GET', '/mcp-definitions?type=system') || [];
  let mcp = null;
  if (id) mcp = _mcpDefs.find(m => m.id === id) || await _api('GET', `/mcp-definitions/${id}`);
  const title = id ? `編輯 MCP — ${_esc(mcp?.name || '')}` : '新增 MCP';

  // Resolve system_mcp_id — prefer the direct FK; fall back to name-matching via old data_subject
  let selectedSysMcpId = mcp?.system_mcp_id || null;
  if (!selectedSysMcpId && mcp?.data_subject_id) {
    try {
      const oldDs = await _api('GET', `/data-subjects/${mcp.data_subject_id}`);
      if (oldDs?.name) {
        const matched = _dataSubjects.find(d => d.name === oldDs.name);
        if (matched) selectedSysMcpId = matched.id;
      }
    } catch {}
  }
  const dsOptions = _dataSubjects.map(ds =>
    `<option value="${ds.id}" ${selectedSysMcpId === ds.id ? 'selected' : ''}>${_esc(ds.name)}</option>`
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
      <label class="builder-label required">選定 System MCP (資料源)</label>
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
  if (!dsId)        { alert('請先選定 System MCP (資料源)'); return; }
  if (!_sampleData) { alert('請先點擊「撈取樣本資料」取得真實資料'); return; }

  btn.disabled = true;

  // ── Step 0: Semantic check — verify intent is clear before heavy LLM call ─
  btn.textContent = '⏳ 分析意圖語意...';
  statusEl.innerHTML = '<div class="llm-loading"><div class="llm-spinner"></div><span>AI 正在分析加工意圖是否明確，約 5~10 秒…</span></div>';

  try {
    const check = await _api('POST', '/mcp-definitions/check-intent', {
      processing_intent: intent,
      system_mcp_id: dsId,
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
  btn.textContent = '⏳ AI 深度編譯中...';
  if (resultEl) resultEl.innerHTML = '';

  const _inputRows = Array.isArray(_sampleData) ? _sampleData.length
    : (typeof _sampleData === 'object' && _sampleData ? Object.values(_sampleData).reduce((s,v) => s + (Array.isArray(v) ? v.length : 1), 0) : 0);

  // ── SSE streaming try-run (防止 proxy 504 timeout) ─────────────────────────
  let _sseAbort = new AbortController();
  let _tickInterval = null;

  function _updateProgress(msg, elapsed) {
    statusEl.innerHTML = `
      <div class="llm-loading">
        <div class="llm-spinner"></div>
        <span>${msg} <span class="text-slate-400 font-mono">(已等待 ${elapsed}s)</span></span>
      </div>`;
  }

  _updateProgress('🧠 LLM 生成腳本中', 0);
  let _elapsedDisplay = 0;
  let _currentMsg = '🧠 LLM 生成腳本中';
  _tickInterval = setInterval(() => {
    _elapsedDisplay++;
    _updateProgress(_currentMsg, _elapsedDisplay);
  }, 1000);

  let result = null;
  let sseError = null;

  try {
    const resp = await fetch('/api/v1/mcp-definitions/try-run-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${_token}` },
      body: JSON.stringify({ processing_intent: intent, system_mcp_id: dsId, sample_data: _sampleData }),
      signal: _sseAbort.signal,
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;
        try {
          const ev = JSON.parse(line.slice(5).trim());
          if (ev.type === 'progress') {
            _currentMsg = ev.message || _currentMsg;
            _elapsedDisplay = ev.elapsed_s ?? _elapsedDisplay;
            _updateProgress(_currentMsg, _elapsedDisplay);
          } else if (ev.type === 'done') {
            result = ev.result;
          } else if (ev.type === 'error') {
            sseError = ev.message;
          }
        } catch {}
      }
    }
  } catch (fetchErr) {
    clearInterval(_tickInterval);
    const msg = fetchErr.name === 'AbortError'
      ? '⏱ 請求已中止。'
      : `✗ 請求失敗：${_esc(fetchErr.message)}`;
    statusEl.innerHTML = `<p class="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">${msg}</p>`;
    if (tabObj) { tabObj.status = 'error'; _renderTryTabBar(); }
    btn.disabled = false;
    btn.innerHTML = '<span>▶</span> 執行試跑 (Try Run)';
    return;
  }

  clearInterval(_tickInterval);

  if (sseError || !result) {
    statusEl.innerHTML = `<p class="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">✗ ${_esc(sseError || '未收到結果')}</p>`;
    if (tabObj) { tabObj.status = 'error'; _renderTryTabBar(); }
    btn.disabled = false;
    btn.innerHTML = '<span>▶</span> 執行試跑 (Try Run)';
    return;
  }

  // ── from here, `result` is the MCPTryRunResponse ─────────────────────────
  try {
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

    // Performance summary line
    const _outRows = result.output_records ?? (result.output_data?.dataset?.length ?? 0);
    const _perfLine = [
      `📊 Input: ${result.input_records ?? _inputRows} rows`,
      result.llm_elapsed_s ? `🧠 LLM: ${result.llm_elapsed_s}s` : null,
      result.sandbox_elapsed_s ? `⚙ Exec: ${result.sandbox_elapsed_s}s` : null,
      `📤 Output: ${_outRows} rows`,
    ].filter(Boolean).join(' | ');

    statusEl.innerHTML = `
      <p class="text-xs text-green-400 bg-green-400/10 border border-green-400/20 rounded-lg px-3 py-2 mb-1">✓ 試跑成功！請檢視下方結果，確認後即可儲存。</p>
      <p class="text-xs text-slate-500 font-mono px-1">${_perfLine}</p>`;

    if (resultEl) {
      resultEl.innerHTML = _buildResultHtml(result, `(Tab ${tabN})`);
    }
  } catch (e) {
    clearInterval(_tickInterval);
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
    const type = uiRender.type || 'table';
    // Build charts array: prefer charts[] (multi-chart support), fall back to chart_data
    const _normChart = c => (c && typeof c === 'object') ? JSON.stringify(c) : c;
    const rawCharts  = Array.isArray(uiRender.charts) ? uiRender.charts : [];
    const chartsArr  = rawCharts.length > 0
      ? rawCharts.map(_normChart).filter(Boolean)
      : (uiRender.chart_data ? [_normChart(uiRender.chart_data)] : []);

    if (type === 'table' || chartsArr.length === 0) {
      // No chart — just show the data table
      dataHtml = _renderDatasetTable(dataset || outputData);
    } else {
      // Has chart(s) — show Chart tab + Data tab
      const tabId     = 'rtab-' + Math.random().toString(36).slice(2, 8);
      const tableHtml = _renderDatasetTable(dataset || outputData);

      // Render each chart — all stacked inside a single "Chart" tab pane
      const chartsPanesHtml = chartsArr.map((chartData, idx) => {
        if (typeof chartData === 'string' && chartData.startsWith('data:image')) {
          // Matplotlib base64 PNG
          return `<div class="mb-3"><img src="${chartData}" style="max-width:100%;border-radius:8px;border:1px solid #334155;" alt="chart" /></div>`;
        } else if (typeof chartData === 'string' && chartData.trim().startsWith('{')) {
          // Plotly JSON — render via Plotly.newPlot() (the only supported JSON path)
          const plotId = `${tabId}-plot-${idx}`;
          setTimeout(() => {
            const el = document.getElementById(plotId);
            if (!el || !window.Plotly) return;
            try {
              const spec = JSON.parse(chartData);
              const specLayout = spec.layout || {};
              const mergedMargin = Object.assign({ t: 40, r: 20, b: 60, l: 60 }, specLayout.margin || {});
              if (specLayout.title && mergedMargin.t < 55) mergedMargin.t = 55;
              const hasHorizLegend = specLayout.legend?.orientation === 'h';
              if (hasHorizLegend && mergedMargin.b < 100) mergedMargin.b = 100;
              const legendOverride = hasHorizLegend ? { legend: { ...specLayout.legend, y: -0.28, x: 0, xanchor: 'left' } } : {};
              const layout = Object.assign({
                height: 360,
                paper_bgcolor: '#ffffff',
                plot_bgcolor:  '#f8fafc',
                font: { color: '#1e293b', size: 11 },
              }, specLayout, { height: specLayout.height || 360, margin: mergedMargin }, legendOverride);
              Plotly.newPlot(el, spec.data || [], layout, { responsive: true, displayModeBar: false });
            } catch(e) { el.innerHTML = `<p class="text-xs text-red-400 p-4">圖表渲染失敗：${e.message}</p>`; }
          }, 80);
          return `<div class="mb-3"><div id="${plotId}" style="width:100%;height:360px;"></div></div>`;
        } else {
          // Unsupported format — HTML output (fig.to_html) is blocked
          return `<div class="mb-3 p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-700">
            ⚠️ 圖表格式不支援。請確認腳本使用 <code>json.dumps(fig.to_dict())</code> 產生圖表，不可使用 fig.to_html()。
          </div>`;
        }
      }).join('');

      const chartLabel = chartsArr.length > 1 ? `📊 圖表 (${chartsArr.length})` : '📊 圖表';
      dataHtml = `
        <div class="result-tab-bar flex gap-1 mb-2">
          <button class="result-tab-btn text-xs px-3 py-1 rounded-md bg-indigo-600 text-white font-medium transition-colors"
                  onclick="_switchResultTab('${tabId}','chart',this)">${chartLabel}</button>
          <button class="result-tab-btn text-xs px-3 py-1 rounded-md text-slate-500 font-medium transition-colors hover:text-slate-800"
                  onclick="_switchResultTab('${tabId}','data',this)">📋 資料</button>
        </div>
        <div id="${tabId}-chart">${chartsPanesHtml}</div>
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
        <pre class="bg-slate-50 border border-slate-200 rounded-md p-3 text-xs text-slate-700 mt-2 overflow-x-auto overflow-y-scroll max-h-[480px] whitespace-pre-wrap leading-relaxed">${_esc(result.script || '')}</pre>
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
  if (!name || !dsId) { alert('請填寫名稱並選擇 System MCP (資料源)'); return; }

  const body = {
    name,
    description: document.getElementById('mcp-desc').value.trim(),
    system_mcp_id: dsId,
    processing_intent: document.getElementById(`mcp-intent-${_activeTryTabN}`)?.value?.trim() || '',
  };
  // Always merge try-run artifacts when available (applies to both create and update)
  if (_tryRunResult && _tryRunResult.success) {
    body.processing_script = _tryRunResult.script;
    body.output_schema     = _tryRunResult.output_schema;
    body.ui_render_config  = _tryRunResult.ui_render_config;
    body.input_definition  = _tryRunResult.input_definition;
    // Cap sample_output to 20 rows to prevent DB/LLM token bloat
    const _od = _tryRunResult.output_data || {};
    body.sample_output = { ..._od, dataset: (_od.dataset || []).slice(0, 20), _raw_dataset: undefined };
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
        system_mcp_id: body.system_mcp_id,
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
    if (_eventTypes.length === 0)    _eventTypes    = await _api('GET', '/event-types') || [];
    if (_mcpDefs.length === 0)       _mcpDefs       = await _api('GET', '/mcp-definitions') || [];
    if (_dataSubjects.length === 0)  _dataSubjects  = await _api('GET', '/mcp-definitions?type=system') || [];
    if (_skillDefs.length === 0) {
      container.innerHTML = '<p class="text-center text-slate-600 py-12">尚無 Skill，點擊右上角新增</p>';
      return;
    }
    container.innerHTML = _skillDefs.map(sk => {
      const et = _eventTypes.find(e => e.id === sk.event_type_id);
      let ldr = null;
      try { const r = sk.last_diagnosis_result; ldr = r ? (typeof r === 'string' ? JSON.parse(r) : r) : null; } catch {}
      const hasCode = !!(ldr?.generated_code || sk.generated_code);
      const hasDiag = !!(sk.diagnostic_prompt);
      const boundMcp = sk.mcp_id ? _mcpDefs.find(m => m.id === sk.mcp_id) : null;
      const mcpTag = boundMcp
        ? `<span class="builder-tag builder-tag-purple" title="${_esc(boundMcp.name)}">${_esc(boundMcp.name)}</span>`
        : `<span class="builder-tag text-slate-500">未綁定 MCP</span>`;
      const diagTag = hasCode
        ? '<span class="builder-tag builder-tag-green">🐍 Code 診斷</span>'
        : hasDiag
          ? '<span class="builder-tag" style="background:#fef3c7;color:#92400e;" title="有診斷邏輯但缺少 Python 碼，需重新生成">⚠ 需重生成</span>'
          : '';
      return `
        <div class="builder-card" onclick="_skOpenEditor(${sk.id})">
          <div class="flex-1">
            <div class="builder-card-name">${_esc(sk.name)}</div>
            <div class="builder-card-desc">${_esc(sk.description || '（無說明）')}</div>
            <div class="builder-card-meta">
              <span class="builder-tag">${sk.event_type_id ? _esc(et?.name || `Event #${sk.event_type_id}`) : '<span style="color:#94a3b8">未設定 Event</span>'}</span>
              ${mcpTag}
              ${diagTag}
            </div>
          </div>
          <div class="flex items-center gap-2">
            <div class="text-slate-600 text-sm">›</div>
            <button onclick="event.stopPropagation(); _skDelete(${sk.id}, '${_esc(sk.name).replace(/'/g, "\\'")}')"
                    title="刪除 Skill"
                    class="w-7 h-7 flex items-center justify-center rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50 transition-colors">
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/>
              </svg>
            </button>
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    container.innerHTML = `<p class="text-center text-red-400 py-12">載入失敗：${_esc(e.message)}</p>`;
  }
}

async function _skDelete(id, name) {
  if (!confirm(`確定要刪除 Skill「${name}」嗎？此動作無法復原。`)) return;
  try {
    await _api('DELETE', `/skill-definitions/${id}`);
    // Remove card from DOM instantly
    const cards = document.getElementById('sk-list-cards');
    if (cards) {
      const all = cards.querySelectorAll('.builder-card');
      all.forEach(el => { if (el.innerHTML.includes(`_skOpenEditor(${id})`)) el.remove(); });
    }
    // Reload list to keep counts/state consistent
    _renderSkillList();
  } catch (e) {
    alert('刪除失敗：' + e.message);
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
  const ds = _dataSubjects.find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id));
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
    paramRows = '<p class="text-xs text-slate-500 italic">此 System MCP 不需要輸入參數</p>';
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

  const ds = _dataSubjects.find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id));
  if (!ds) {
    statusEl.innerHTML = '<p class="text-xs text-red-400">找不到對應的 System MCP / DataSubject</p>';
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
    statusEl.innerHTML = '<p class="text-xs text-red-400">System MCP 缺少 endpoint_url 設定</p>';
    return;
  }

  if (btn) { btn.disabled = true; btn.textContent = '⏳ 載入中...'; }
  statusEl.innerHTML = '<div class="llm-loading"><div class="llm-spinner"></div><span>正在從 System MCP 取得資料並執行腳本…</span></div>';
  resultEl.innerHTML = '';

  try {
    // Step 1: Fetch raw data from System MCP API with test values
    const params = new URLSearchParams(testValues);
    const rawUrl = endpointUrl + (Object.keys(testValues).length > 0 ? '?' + params.toString() : '');
    const rawRes = await fetch(rawUrl, { headers: { 'Authorization': `Bearer ${_token}` } });
    if (!rawRes.ok) throw new Error(`System MCP API 返回 HTTP ${rawRes.status}`);
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
  if (_mcpDefs.length === 0)      _mcpDefs      = await _api('GET', '/mcp-definitions?type=custom') || [];
  if (_dataSubjects.length === 0) _dataSubjects = await _api('GET', '/mcp-definitions?type=system') || [];
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
    const ds = _dataSubjects.find(d => d.id === (m.system_mcp_id || m.data_subject_id));
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

  // Include last_diagnosis_result (generated_code) so Agent can execute this Skill
  if (_diagnosisRunResult) payload.last_diagnosis_result = _diagnosisRunResult;

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
        const skillDesc = skill?.description ? `<span class="text-slate-400 ml-1">·</span> <span class="text-slate-500">${_esc(skill.description)}</span>` : '';
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
              <p class="text-xs text-slate-500 mt-1">Skill: <span class="font-medium text-slate-700">${_esc(skillName)}</span>${skillDesc}</p>
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

function _buildRoutineCheckForm(rc, prefill) {
  // prefill overrides rc for agent-draft pre-population
  const d = { ...(rc || {}), ...(prefill || {}) };
  const intervalLabel = { '30m': '每30分鐘', '1h': '每1小時', '4h': '每4小時',
                           '8h': '每8小時', '12h': '每12小時', 'daily': '每天 (指定時間)' };

  const selectedSkillId = d.skill_id || null;
  const skill = selectedSkillId ? (_skillDefs||[]).find(s => s.id === selectedSkillId) : null;
  const skillInput = d.skill_input || {};
  // skill_input may come as JSON string from draft payload
  const skillInputObj = typeof skillInput === 'string' ? (()=>{ try{return JSON.parse(skillInput);}catch{return{};} })() : skillInput;
  const skillInputFields = _buildSkillInputFields(selectedSkillId, skillInputObj);
  const eventPreview = skill
    ? _buildRcEventPreview(skill, d.name || '', d.trigger_event_id || null)
    : `<div class="text-xs text-slate-400 py-2 pl-1">← 請先選擇 Skill，系統將自動預覽 Event 格式</div>`;

  const curInterval = d.schedule_interval || '1h';
  const isDailySelected = curInterval === 'daily';

  return `
    <div class="space-y-4">
      <div class="builder-field">
        <label class="builder-label required">排程名稱</label>
        <input id="rc-name" type="text" class="builder-input" placeholder="例如：TETCH01 每小時 APC 巡檢"
          value="${_esc(d.name || '')}">
      </div>

      <div class="builder-field">
        <label class="builder-label required">選擇 Skill</label>
        <select id="rc-skill-id" class="builder-select w-full" onchange="_onRcSkillChange(this.value)">
          <option value="">— 請選擇 Skill —</option>
          ${(_skillDefs||[]).map(s => `<option value="${s.id}" ${d.skill_id==s.id?'selected':''}>${_esc(s.name)}</option>`).join('')}
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
        <select id="rc-interval" class="builder-select w-full" onchange="_onRcIntervalChange(this.value)">
          ${Object.entries(intervalLabel).map(([v,l]) =>
            `<option value="${v}" ${curInterval==v?'selected':''}>${l}</option>`
          ).join('')}
        </select>
      </div>

      <div id="rc-daily-time-row" class="builder-field ${isDailySelected ? '' : 'hidden'}">
        <label class="builder-label">每日執行時間</label>
        <input id="rc-schedule-time" type="time" class="builder-input w-32"
          value="${_esc(d.schedule_time || '08:00')}">
        <p class="text-[10px] text-slate-400 mt-1">格式 HH:MM，伺服器依此時間觸發 (UTC+8)</p>
      </div>

      <div class="builder-field">
        <label class="builder-label">效期（到期後自動停用）</label>
        <input id="rc-expire-at" type="date" class="builder-input w-44"
          value="${_esc(d.expire_at || '')}">
        <p class="text-[10px] text-slate-400 mt-1">留空代表永久有效</p>
      </div>

      <div class="builder-field">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" id="rc-active" class="w-4 h-4 rounded" ${d.is_active !== false ? 'checked' : ''}>
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

  // Get System MCP input_schema fields (the real named query params)
  const ds = (_dataSubjects||[]).find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id));
  if (!ds?.input_schema) {
    return `<div class="text-xs text-slate-400 py-2">找不到此 MCP 對應的 System MCP 查詢參數定義</div>`;
  }

  let fields = [];
  try {
    const schema = typeof ds.input_schema === 'string'
      ? JSON.parse(ds.input_schema) : ds.input_schema;
    fields = schema.fields || [];
  } catch {}

  if (!fields.length) {
    return `<div class="text-xs text-slate-400 py-2">此 System MCP 無需輸入參數</div>`;
  }

  return `
    <div class="border border-indigo-200 rounded-lg p-3 bg-indigo-50/50">
      <div class="text-xs font-semibold text-indigo-700 mb-2">
        📋 Skill 執行參數（System MCP: ${_esc(ds.name || '')}）
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
async function _onRcSkillChange(skillId, prefillValues) {
  const section = document.getElementById('rc-skill-input-section');
  if (section) {
    section.innerHTML = _buildSkillInputFields(skillId ? parseInt(skillId) : null, prefillValues || {});
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
    // Ensure system MCPs are loaded
    if (!_dataSubjects || _dataSubjects.length === 0) {
      try { _dataSubjects = await _api('GET', '/mcp-definitions?type=system') || []; } catch {}
    }
    const skill = (_skillDefs||[]).find(s => s.id === skillId);
    if (skill) {
      let mcpIdList = [];
      try { mcpIdList = JSON.parse(skill.mcp_ids || '[]'); } catch {}
      if (!Array.isArray(mcpIdList)) mcpIdList = mcpIdList ? [mcpIdList] : [];
      if (mcpIdList.length === 0 && skill.mcp_id) mcpIdList = [skill.mcp_id];
      const mcpId = mcpIdList[0] || null;
      const mcp = mcpId ? (_mcpDefs||[]).find(m => m.id === mcpId) : null;
      const ds = mcp ? (_dataSubjects||[]).find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id)) : null;
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
    const ds = mcp ? (_dataSubjects||[]).find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id)) : null;
    if (ds?.output_schema) {
      try {
        const schema = typeof ds.output_schema === 'string' ? JSON.parse(ds.output_schema) : ds.output_schema;
        outputFields = schema.fields || [];
      } catch {}
    }
  }

  if (!Object.keys(event_schema).length || !outputFields.length) {
    if (statusEl) statusEl.innerHTML = '<p class="text-xs text-slate-400">無足夠資訊進行自動映射（請確認已選擇 Skill 並設定 System MCP output schema）</p>';
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
function _onRcIntervalChange(val) {
  const row = document.getElementById('rc-daily-time-row');
  if (row) row.classList.toggle('hidden', val !== 'daily');
}

/** Pre-fill and open the RoutineCheck drawer from an agent draft payload. */
async function _openRoutineCheckDrawerFromDraft(payload) {
  // Ensure data is loaded
  if (!_skillDefs || _skillDefs.length === 0) {
    try { _skillDefs = await _api('GET', '/skill-definitions') || []; } catch {}
  }
  if (!_mcpDefs || _mcpDefs.length === 0) {
    try { _mcpDefs = await _api('GET', '/mcp-definitions'); } catch {}
  }
  if (!_dataSubjects || _dataSubjects.length === 0) {
    try { _dataSubjects = await _api('GET', '/mcp-definitions?type=system'); } catch {}
  }
  // skill_input may be object from draft
  const skillInputObj = payload.skill_input || {};
  const prefill = {
    name: payload.name || '',
    skill_id: payload.skill_id || null,
    skill_input: skillInputObj,
    schedule_interval: payload.schedule_interval || '1h',
    schedule_time: payload.schedule_time || '',
    expire_at: payload.expire_at || '',
    is_active: false,
  };
  _editingRoutineCheck = null;
  const title = '新增排程巡檢（草稿預填）';
  const body = _buildRoutineCheckForm(null, prefill);
  const footer = `
    <div class="flex gap-2 justify-end w-full">
      <button class="builder-btn-secondary" onclick="closeDrawer()">取消</button>
      <button class="builder-btn-primary" onclick="_saveRoutineCheck(null)">建立排程</button>
    </div>`;
  // Open drawer directly (bypasses _renderDrawerContent which would overwrite content)
  _currentDrawer = 'routine-check-create';
  _editingId = null;
  _drawerDirty = false;
  document.getElementById('drawer-overlay')?.classList.remove('hidden');
  document.getElementById('drawer')?.classList.add('drawer-open');
  _setDrawerContent(title, body, footer);
  // After DOM settles, trigger skill change to populate input fields with pre-fill values
  if (prefill.skill_id) {
    setTimeout(() => _onRcSkillChange(String(prefill.skill_id), skillInputObj), 300);
  }
}

async function _openRoutineCheckDrawer(id) {
  // Lazy-load dependencies
  if (!_skillDefs || _skillDefs.length === 0) {
    try { _skillDefs = await _api('GET', '/skill-definitions') || []; } catch {}
  }
  if (!_mcpDefs || _mcpDefs.length === 0) {
    try { _mcpDefs = await _api('GET', '/mcp-definitions'); } catch {}
  }
  if (!_dataSubjects || _dataSubjects.length === 0) {
    try { _dataSubjects = await _api('GET', '/mcp-definitions?type=system'); } catch {}
  }
  // Load EventTypes for displaying existing ET name in edit mode
  if (!_eventTypes || _eventTypes.length === 0) {
    try { _eventTypes = await _api('GET', '/event-types') || []; } catch {}
  }

  _editingRoutineCheck = id || null;
  const rc = id ? (_routineChecks.find(r => r.id === id) || await _api('GET', `/routine-checks/${id}`)) : null;
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
  // Show the drawer panel
  document.getElementById('drawer-overlay')?.classList.remove('hidden');
  document.getElementById('drawer')?.classList.add('drawer-open');
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

  // Collect expire_at + schedule_time
  const expireAt = document.getElementById('rc-expire-at')?.value?.trim() || null;
  const scheduleTime = interval === 'daily'
    ? (document.getElementById('rc-schedule-time')?.value?.trim() || null)
    : null;

  const payload = {
    name, skill_id: skillId, skill_input,
    generated_event_name,
    schedule_interval: interval, is_active: isActive,
    expire_at: expireAt || undefined,
    schedule_time: scheduleTime || undefined,
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


// ══════════════════════════════════════════════════════════════
// v12 — Mission Control Dashboard
// ══════════════════════════════════════════════════════════════

async function _loadDashboard() {
  const content = document.getElementById('dashboard-content');
  if (!content) return;
  try {
    // Parallel fetch: routine checks + generated events + skill/mcp defs for tag resolution
    const [rcs, events] = await Promise.all([
      _api('GET', '/routine-checks'),
      _api('GET', '/generated-events').catch(() => []),
    ]);
    // Ensure local caches are populated for tag resolution
    if (!_skillDefs.length) {
      try { _skillDefs = await _api('GET', '/skill-definitions'); } catch(_) {}
    }
    if (!_mcpDefs.length) {
      try { _mcpDefs = await _api('GET', '/mcp-definitions'); } catch(_) {}
    }

    // Derive 24H subset
    const now = Date.now();
    const events24h = events.filter(e => {
      if (!e.created_at) return false;
      return (now - new Date(e.created_at).getTime()) < 86400000;
    });
    const abnormals = events24h.filter(e => e.status === 'pending');

    // KPIs
    const activeRcs = rcs.filter(r => r.is_active);
    _setKpi('kpi-active-tasks', activeRcs.length);
    _setKpi('kpi-exec-count', events24h.length);
    _setKpi('kpi-abnormals', abnormals.length);

    // Resource share rate: unique MCPs referenced by >1 routine check / total MCPs
    const mcpRefs = rcs.flatMap(rc => {
      const skill = _skillDefs.find(s => s.id === rc.skill_id);
      if (!skill) return [];
      try { return JSON.parse(skill.mcp_ids || '[]'); } catch(_) { return []; }
    });
    const totalMcps = _mcpDefs.length;
    const uniqueRef = new Set(mcpRefs).size;
    const reuseRate = totalMcps > 0 ? Math.round((uniqueRef / totalMcps) * 100) : 0;
    _setKpi('kpi-reuse-rate', reuseRate + '%');

    // Render panels
    _renderDashboardActiveTasks(rcs);
    _renderDashboardExecLog(events24h);
  } catch(e) {
    const el = document.getElementById('dashboard-active-tasks');
    if (el) el.innerHTML = `<div class="text-red-500 text-sm py-4">載入失敗：${_esc(e.message)}</div>`;
  }
}

function _setKpi(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function _renderDashboardActiveTasks(rcs) {
  const el = document.getElementById('dashboard-active-tasks');
  if (!el) return;
  if (!rcs.length) {
    el.innerHTML = `
      <div class="flex flex-col items-center justify-center py-10 text-slate-400 text-center">
        <p class="text-sm font-medium">尚無排程巡檢</p>
        <p class="text-xs mt-1">點擊右上角「+ 新增排程」開始設定</p>
      </div>`;
    return;
  }
  const intervalLabel = { '30m':'每30分', '1h':'每1h', '4h':'每4h',
                           '8h':'每8h', '12h':'每12h', 'daily':'每天' };
  el.innerHTML = rcs.map(rc => {
    const skill = _skillDefs.find(s => s.id === rc.skill_id);
    const skillName = skill ? skill.name : `Skill #${rc.skill_id}`;
    const mcpIds = skill ? (JSON.parse(skill.mcp_ids || '[]').catch ? [] : (() => { try { return JSON.parse(skill.mcp_ids || '[]'); } catch(_) { return []; } })()) : [];
    const mcpNames = mcpIds.map(mid => {
      const m = _mcpDefs.find(m => m.id === mid);
      return m ? m.name : `MCP #${mid}`;
    });
    const isAbn = rc.last_run_status === 'ABNORMAL';
    const borderCls = isAbn ? 'border-l-red-500' : rc.is_active ? 'border-l-blue-400' : 'border-l-slate-300';
    const statusDot = rc.is_active
      ? '<span class="w-1.5 h-1.5 rounded-full bg-blue-400 inline-block"></span>'
      : '<span class="w-1.5 h-1.5 rounded-full bg-slate-300 inline-block"></span>';
    return `
    <div class="bg-white border border-slate-200 border-l-4 ${borderCls} rounded-xl p-4 shadow-sm
                hover:shadow-md transition-shadow cursor-pointer"
         onclick="_openRoutineCheckDrawer(${rc.id})">
      <div class="flex items-start justify-between gap-2 mb-2">
        <div class="flex items-center gap-1.5 min-w-0">
          ${statusDot}
          <span class="font-semibold text-sm text-slate-900 truncate">${_esc(rc.name)}</span>
        </div>
        <span class="text-xs text-slate-400 flex-shrink-0">${intervalLabel[rc.schedule_interval || rc.check_interval] || rc.schedule_interval || rc.check_interval}</span>
      </div>
      <div class="flex flex-wrap gap-1.5 mt-1">
        <span class="text-xs px-2 py-0.5 rounded-full bg-purple-100 text-purple-700
                     border border-purple-200 font-medium">
          🧠 ${_esc(skillName)}
        </span>
        ${mcpNames.map(n => `
          <span class="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700
                       border border-emerald-200 font-medium">
            ⚙ ${_esc(n)}
          </span>`).join('')}
      </div>
      ${isAbn ? `
        <div class="mt-2 text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1">
          ⚠ 上次執行：ABNORMAL
        </div>` : ''}
    </div>`;
  }).join('');
}

function _renderDashboardExecLog(events) {
  const el = document.getElementById('dashboard-exec-log');
  if (!el) return;
  if (!events.length) {
    el.innerHTML = `
      <div class="flex flex-col items-center justify-center py-10 text-slate-400 text-center">
        <p class="text-sm font-medium">24H 內尚無執行記錄</p>
      </div>`;
    return;
  }
  // Sort newest first
  const sorted = [...events].sort((a, b) =>
    new Date(b.created_at || 0) - new Date(a.created_at || 0));
  el.innerHTML = sorted.map(ev => {
    const isAbn = ev.status === 'pending';
    const skill = _skillDefs.find(s => s.id === ev.source_skill_id);
    const skillName = skill ? skill.name : `Skill #${ev.source_skill_id}`;
    const ts = ev.created_at ? ev.created_at.replace('T',' ').substring(11,16) : '';
    const diagMsg = (() => {
      try {
        const d = JSON.parse(ev.diagnosis_result || '{}');
        return d.diagnosis_message || '';
      } catch(_) { return ''; }
    })();
    const actionMsg = (() => {
      try {
        const d = JSON.parse(ev.diagnosis_result || '{}');
        return d.recommended_action || '';
      } catch(_) { return ''; }
    })();
    return `
    <div class="bg-white border ${isAbn ? 'border-red-200 bg-red-50/20' : 'border-slate-200'}
                rounded-xl p-3 flex gap-3 items-start shadow-sm">
      <div class="text-xs text-slate-400 pt-0.5 flex-shrink-0 w-10 text-right">${ts}</div>
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 mb-0.5 flex-wrap">
          <span class="font-semibold text-sm text-slate-900">${_esc(skillName)}</span>
          ${isAbn
            ? `<span class="text-xs font-bold text-red-600 bg-red-100 border border-red-200
                           px-2 py-0.5 rounded-full">⚠ ABNORMAL</span>`
            : `<span class="text-xs font-medium text-green-700 bg-green-100 border border-green-200
                           px-2 py-0.5 rounded-full">✓ NORMAL</span>`}
        </div>
        ${diagMsg ? `<p class="text-xs text-slate-600 mt-0.5 line-clamp-2">${_esc(diagMsg)}</p>` : ''}
        ${isAbn && actionMsg ? `
          <p class="text-xs text-red-600 mt-1 font-medium flex items-start gap-1">
            <span>↳ 處置：</span><span class="line-clamp-1">${_esc(actionMsg)}</span>
          </p>` : ''}
      </div>
    </div>`;
  }).join('');
}


// ══════════════════════════════════════════════════════════════
// v12 — Nested Builder (Task > Skill > MCP)
// ══════════════════════════════════════════════════════════════

let _nbSkillMode       = 'select';  // 'select' | 'new'
let _nbMcpMode         = 'select';  // 'select' | 'new'
let _nbTryRunResult    = null;      // last MCP try-run result for the console
let _nbSkillLiveResult = null;      // last Skill live-diagnosis result (from generate-code-diagnosis)
let _nbRightTab        = 'logs';    // 'logs' | 'report'

// ── Right panel tab switching ─────────────────────────────────
function _nbSwitchRightTab(tab) {
  _nbRightTab = tab;
  ['logs', 'report'].forEach(t => {
    const content = document.getElementById(`nb-rtab-${t}`);
    const btn     = document.getElementById(`nb-rtab-btn-${t}`);
    if (content) content.classList.toggle('hidden', t !== tab);
    if (btn) {
      btn.className = t === tab
        ? 'px-5 py-3 text-xs font-bold text-blue-700 border-b-2 border-blue-600 transition-colors'
        : 'px-5 py-3 text-xs font-medium text-slate-500 border-b-2 border-transparent hover:text-slate-700 transition-colors';
    }
  });
}

// Legacy expand/collapse — now just switches to logs tab and shows the log block
function _nbExpandConsole() {
  _nbSwitchRightTab('logs');
  document.getElementById('nb-console-placeholder')?.classList.add('hidden');
  document.getElementById('nb-exec-log')?.classList.remove('hidden');
}

function _nbCollapseConsole() {
  document.getElementById('nb-console-placeholder')?.classList.remove('hidden');
  document.getElementById('nb-exec-log')?.classList.add('hidden');
  document.getElementById('nb-skill-result')?.classList.add('hidden');
  document.getElementById('nb-mcp-result')?.classList.add('hidden');
}

// ── Fetch & Preview: pull DS sample data and render Data/Format Review grids ──
async function _nbFetchPreview() {
  let ds = null;
  let formParams = {};
  let mcpOutputSchema = null;

  if (_nbMcpMode === 'new') {
    const dsId = parseInt(document.getElementById('nb-mcp-ds')?.value || '0');
    ds = dsId ? _dataSubjects.find(d => d.id === dsId) : null;
    formParams = _nbCollectFormParams();
  } else {
    const sel = document.getElementById('nb-mcp-select');
    const mcpId = sel ? parseInt(sel.value) : null;
    const mcp = mcpId ? _mcpDefs.find(m => m.id === mcpId) : null;
    ds = (mcp?.system_mcp_id || mcp?.data_subject_id) ? _dataSubjects.find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id)) : null;
    mcpOutputSchema = mcp?.output_schema || null;
    for (const f of (ds?.input_schema?.fields || [])) {
      const el = document.getElementById(`nb-mcp-select-param-${f.name}`);
      if (el && el.value.trim()) formParams[f.name] = el.value.trim();
    }
  }

  if (!ds) { alert('請先選擇 System MCP'); return; }

  const drEl  = document.getElementById('nb-data-review');
  const frEl  = document.getElementById('nb-format-review');
  const drDet = document.getElementById('nb-data-review-details');
  const frDet = document.getElementById('nb-format-review-details');
  if (drEl) drEl.innerHTML = '<p class="text-xs text-slate-400 italic p-3 animate-pulse">撈取中…</p>';
  if (drDet) drDet.open = true;
  if (frDet) frDet.open = true;

  try {
    const rawUrl = ds.api_config?.endpoint_url || '';
    if (!rawUrl) throw new Error('System MCP 沒有設定 API endpoint');
    const path = rawUrl.replace(/^\/api\/v1/, '');
    const method = (ds.api_config?.method || 'GET').toUpperCase();
    const qp = new URLSearchParams(formParams);
    const fullPath = method === 'GET' ? `${path}?${qp}` : path;
    const token = localStorage.getItem('token') || sessionStorage.getItem('token');
    const resp = await fetch(`/api/v1${fullPath}`, {
      method,
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: method !== 'GET' ? JSON.stringify(formParams) : undefined,
    });
    const json = await resp.json();
    const rows = Array.isArray(json) ? json
      : (json.data ? (Array.isArray(json.data) ? json.data : [json.data]) : [json]);

    // Render Data Review as grid table
    if (drEl) _nbRenderDataGrid(drEl, rows, '無資料回傳');

    // Render Format Review: prefer MCP output_schema, fallback to inferred schema
    if (frEl) {
      const schema = mcpOutputSchema || ds.output_schema || _nbInferSchemaFromRows(rows);
      _nbRenderSchemaGrid(frEl, schema);
    }
  } catch(e) {
    if (drEl) drEl.innerHTML = `<p class="text-xs text-red-500 p-3">撈取失敗：${_esc(e.message)}</p>`;
  }
}

// Render a schema object as a professional grid table (field | type | description)
function _nbRenderSchemaGrid(el, schema) {
  if (!schema) {
    el.innerHTML = '<p class="text-xs text-slate-400 italic p-3">無 Schema 資訊</p>';
    return;
  }
  let fields = [];
  if (Array.isArray(schema)) {
    fields = schema.map(f => typeof f === 'object'
      ? { name: f.name || f.key || '?', type: f.type || 'any', desc: f.description || f.desc || '' }
      : { name: String(f), type: 'any', desc: '' });
  } else if (schema.fields && Array.isArray(schema.fields)) {
    fields = schema.fields.map(f => ({ name: f.name || f.key || '?', type: f.type || 'any', desc: f.description || '' }));
  } else {
    fields = Object.entries(schema).map(([k, v]) => ({
      name: k,
      type: typeof v === 'object' ? (v.type || 'object') : String(v),
      desc: typeof v === 'object' ? (v.description || '') : '',
    }));
  }
  if (!fields.length) {
    el.innerHTML = '<p class="text-xs text-slate-400 italic p-3">Schema 為空</p>';
    return;
  }
  el.innerHTML = `
    <table class="text-xs w-full border-collapse">
      <thead class="bg-emerald-50 sticky top-0">
        <tr>
          <th class="text-left text-emerald-700 font-bold border-b border-emerald-200 px-3 py-2 uppercase tracking-wide whitespace-nowrap">欄位</th>
          <th class="text-left text-emerald-700 font-bold border-b border-emerald-200 px-3 py-2 uppercase tracking-wide whitespace-nowrap">型態</th>
          <th class="text-left text-emerald-700 font-bold border-b border-emerald-200 px-3 py-2 uppercase tracking-wide">說明</th>
        </tr>
      </thead>
      <tbody class="bg-white">
        ${fields.map((f, i) => `
          <tr class="${i % 2 ? 'bg-slate-50/70' : ''} hover:bg-emerald-50/40 transition-colors">
            <td class="font-mono font-semibold text-slate-800 border-b border-slate-100 px-3 py-1.5 whitespace-nowrap">${_esc(f.name)}</td>
            <td class="border-b border-slate-100 px-3 py-1.5 whitespace-nowrap">
              <span class="bg-blue-50 text-blue-700 border border-blue-100 px-1.5 py-0.5 rounded text-[10px] font-semibold">${_esc(f.type)}</span>
            </td>
            <td class="text-slate-500 border-b border-slate-100 px-3 py-1.5">${_esc(f.desc)}</td>
          </tr>`).join('')}
      </tbody>
    </table>`;
}

// Infer lightweight schema from the first data row
function _nbInferSchemaFromRows(rows) {
  if (!rows.length) return null;
  return Object.entries(rows[0]).filter(([k]) => !k.startsWith('_')).map(([k, v]) => ({
    name: k, type: v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v, desc: '',
  }));
}

async function _nbPreFillFromDraft(payload) {
  // Switch to nested-builder and pre-fill form fields from agent draft payload
  await _nbInitView();

  // Task name
  const nameEl = document.getElementById('nb-task-name');
  if (nameEl && payload.name) { nameEl.value = payload.name; }

  // Schedule interval
  const intervalEl = document.getElementById('nb-task-interval');
  if (intervalEl && payload.schedule_interval) {
    intervalEl.value = payload.schedule_interval;
    _nbOnTaskIntervalChange(payload.schedule_interval);
  }

  // Daily time
  if (payload.schedule_time) {
    const timeEl = document.getElementById('nb-task-schedule-time');
    if (timeEl) timeEl.value = payload.schedule_time;
  }

  // Expire at
  if (payload.expire_at) {
    const expEl = document.getElementById('nb-task-expire-at');
    if (expEl) expEl.value = payload.expire_at.substring(0, 10);
  }

  // Skill: existing skill_id vs new skill_draft
  if (payload.skill_id) {
    _nbSetSkillMode('select');
    const skillSel = document.getElementById('nb-skill-select');
    if (skillSel) {
      skillSel.value = String(payload.skill_id);
      _nbOnSkillSelect();  // triggers skill summary + MCP auto-lock + event preview
    }
    // Pre-fill skill_input into dynamic nb-mcp-select-param-{name} fields
    if (payload.skill_input) {
      const skillInput = typeof payload.skill_input === 'string'
        ? (() => { try { return JSON.parse(payload.skill_input); } catch { return {}; } })()
        : payload.skill_input;
      setTimeout(() => {
        Object.entries(skillInput).forEach(([k, v]) => {
          const el = document.getElementById(`nb-mcp-select-param-${k}`);
          if (el) el.value = v;
        });
      }, 500);
    }
  } else if (payload.skill_draft) {
    const sd = payload.skill_draft;
    _nbSetSkillMode('new');
    const setV = (id, val) => { const el = document.getElementById(id); if (el && val != null) el.value = val; };
    setV('nb-skill-name',   sd.name || '');
    setV('nb-skill-prompt', sd.diagnostic_prompt || '');
    setV('nb-skill-target', sd.problem_subject || '');
    setV('nb-skill-action', sd.human_recommendation || '');
    // Pre-select MCP if mcp_ids provided
    const mcp_ids = sd.mcp_ids || (sd.mcp_id ? [sd.mcp_id] : []);
    if (mcp_ids.length) {
      _nbSetMcpMode('select');
      const mcpSel = document.getElementById('nb-mcp-select');
      if (mcpSel) {
        mcpSel.value = String(mcp_ids[0]);
        _nbOnMcpSelect();
        // Pre-fill skill_input into nb-mcp-select-param-{name} fields
        if (payload.skill_input) {
          const skillInput = typeof payload.skill_input === 'string'
            ? (() => { try { return JSON.parse(payload.skill_input); } catch { return {}; } })()
            : payload.skill_input;
          setTimeout(() => {
            Object.entries(skillInput).forEach(([k, v]) => {
              const el = document.getElementById(`nb-mcp-select-param-${k}`);
              if (el) el.value = v;
            });
          }, 500);
        }
      }
    }
  }

  _nbUpdateEventPreview();
}

async function _nbInitView() {
  // Ensure console starts collapsed when entering the view
  _nbCollapseConsole();

  // Populate skill and MCP dropdowns
  if (!_skillDefs.length) {
    try { _skillDefs = await _api('GET', '/skill-definitions'); } catch(_) {}
  }
  if (!_mcpDefs.length) {
    try { _mcpDefs = await _api('GET', '/mcp-definitions'); } catch(_) {}
  }
  if (!_dataSubjects.length) {
    try { _dataSubjects = await _api('GET', '/mcp-definitions?type=system'); } catch(_) {}
  }

  // Populate Skill select
  const skillSel = document.getElementById('nb-skill-select');
  if (skillSel) {
    skillSel.innerHTML = '<option value="">— 請選擇 —</option>' +
      _skillDefs.map(s => `<option value="${s.id}">${_esc(s.name)}</option>`).join('');
  }

  // Populate MCP select
  const mcpSel = document.getElementById('nb-mcp-select');
  if (mcpSel) {
    mcpSel.innerHTML = '<option value="">— 請選擇 —</option>' +
      _mcpDefs.map(m => `<option value="${m.id}">${_esc(m.name)}</option>`).join('');
  }

  // Populate System MCP select in "build new" panel
  const dsSel = document.getElementById('nb-mcp-ds');
  if (dsSel) {
    dsSel.innerHTML = '<option value="">— 請選擇 —</option>' +
      _dataSubjects.map(d => `<option value="${d.id}">${_esc(d.name)}</option>`).join('');
  }

  // Apply initial mode states and reset right panel to Logs tab
  _nbSetSkillMode(_nbSkillMode);
  _nbSetMcpMode(_nbMcpMode);
  _nbSwitchRightTab('logs');
}

function _nbSetSkillMode(mode) {
  _nbSkillMode = mode;
  document.getElementById('nb-skill-select-panel').classList.toggle('hidden', mode !== 'select');
  document.getElementById('nb-skill-new-panel').classList.toggle('hidden', mode !== 'new');
  const _ACTIVE_S   = 'px-4 py-1.5 text-xs font-bold transition-colors bg-purple-600 text-white';
  const _INACTIVE_S = 'px-4 py-1.5 text-xs font-medium transition-colors bg-white text-slate-600 hover:bg-slate-50';
  document.getElementById('nb-skill-mode-select').className = mode === 'select' ? _ACTIVE_S : _INACTIVE_S;
  document.getElementById('nb-skill-mode-new').className    = mode === 'new'    ? _ACTIVE_S : _INACTIVE_S;
}

function _nbSetMcpMode(mode) {
  _nbMcpMode = mode;
  document.getElementById('nb-mcp-select-panel').classList.toggle('hidden', mode !== 'select');
  document.getElementById('nb-mcp-new-panel').classList.toggle('hidden', mode !== 'new');
  const _ACTIVE_M   = 'px-4 py-1.5 text-xs font-bold transition-colors bg-emerald-600 text-white';
  const _INACTIVE_M = 'px-4 py-1.5 text-xs font-medium transition-colors bg-white text-slate-600 hover:bg-slate-50';
  document.getElementById('nb-mcp-mode-select').className = mode === 'select' ? _ACTIVE_M : _INACTIVE_M;
  document.getElementById('nb-mcp-mode-new').className    = mode === 'new'    ? _ACTIVE_M : _INACTIVE_M;
}

function _nbOnSkillSelect() {
  const sel = document.getElementById('nb-skill-select');
  const skillId = sel ? parseInt(sel.value) : null;
  const skill = skillId ? _skillDefs.find(s => s.id === skillId) : null;
  const checkEl = document.getElementById('nb-skill-system-check');
  if (!checkEl) return;
  if (!skill) {
    checkEl.innerHTML = '<p class="text-slate-400 italic">選擇 Skill 後顯示設定摘要</p>';
    // Reset MCP lock when skill is cleared
    const mcpSel = document.getElementById('nb-mcp-select');
    const hint   = document.getElementById('nb-mcp-params-hint');
    if (mcpSel) { mcpSel.disabled = false; mcpSel.value = ''; }
    if (hint)   hint.innerHTML = '';
    return;
  }

  const mcpIds = (() => { try { return JSON.parse(skill.mcp_ids || '[]'); } catch(_) { return []; } })();
  const mcpNames = mcpIds.map(id => {
    const m = _mcpDefs.find(m => m.id === id);
    return m ? m.name : `MCP #${id}`;
  });

  checkEl.innerHTML = `
    <div class="grid grid-cols-2 gap-1">
      <span class="text-slate-500">診斷提示詞：</span>
      <span class="text-slate-700 truncate">${skill.diagnostic_prompt ? '✓ 已設定' : '⚠ 未設定'}</span>
      <span class="text-slate-500">綁定 MCP：</span>
      <span class="text-emerald-700">${mcpNames.length ? mcpNames.join(', ') : '— 未綁定'}</span>
      <span class="text-slate-500">上次診斷：</span>
      <span class="${skill.last_diagnosis_result ? 'text-blue-700' : 'text-slate-400'}">
        ${skill.last_diagnosis_result ? '✓ 有記錄' : '— 未執行'}
      </span>
    </div>`;

  // Auto-lock the bound MCP in L3 when skill has bindings
  const mcpSel  = document.getElementById('nb-mcp-select');
  const badge   = document.getElementById('nb-mcp-lock-badge');
  if (mcpIds.length && mcpSel) {
    // Fix: option values are strings, mcpIds are numbers
    mcpSel.value = String(mcpIds[0]);
    mcpSel.disabled = true;  // lock — driven by Skill binding
    _nbOnMcpSelect();        // renders query params into nb-mcp-params-hint

    // Show "auto-loaded" badge in separate element (does NOT overwrite params)
    if (badge) {
      badge.classList.remove('hidden');
      badge.innerHTML = `
        <div class="flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50
                    border border-emerald-200 rounded-lg px-3 py-1.5">
          <svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M13 10V3L4 14h7v7l9-11h-7z"/>
          </svg>
          <span>已由 Skill 自動帶入：<strong>${_esc(mcpNames[0] || 'MCP #' + mcpIds[0])}</strong></span>
          <button onclick="_nbUnlockMcp()" class="ml-auto text-emerald-500 hover:text-emerald-700
                                                   underline text-[10px]">手動更換</button>
        </div>`;
    }
  } else if (mcpSel) {
    // No binding — unlock dropdown so user can freely select
    mcpSel.disabled = false;
    if (badge) { badge.classList.add('hidden'); badge.innerHTML = ''; }
    const hint = document.getElementById('nb-mcp-params-hint');
    if (hint) hint.innerHTML = '';
  }

  _nbUpdateEventPreview();
}

function _nbUnlockMcp() {
  const mcpSel = document.getElementById('nb-mcp-select');
  const hint   = document.getElementById('nb-mcp-params-hint');
  const badge  = document.getElementById('nb-mcp-lock-badge');
  if (mcpSel) { mcpSel.disabled = false; mcpSel.value = ''; }
  if (hint)   hint.innerHTML = '';
  if (badge)  { badge.classList.add('hidden'); badge.innerHTML = ''; }
}

function _nbOnTaskIntervalChange(val) {
  document.getElementById('nb-task-daily-row')?.classList.toggle('hidden', val !== 'daily');
}

function _nbUpdateEventPreview() {
  const el = document.getElementById('nb-event-preview-section');
  if (!el) return;
  const skillId = parseInt(document.getElementById('nb-skill-select')?.value || '0') || null;
  const name = document.getElementById('nb-task-name')?.value?.trim() || '';
  const skill = skillId ? (_skillDefs || []).find(s => s.id === skillId) : null;
  if (!skill) {
    el.innerHTML = `<div class="text-xs text-slate-400 italic px-1">← 請先選擇 Skill，以預覽 ABNORMAL 時建立的 Event 格式</div>`;
    return;
  }
  el.innerHTML = _buildRcEventPreview(skill, name, null);
}

// Dynamic param form when DS is selected in "建立全新" MCP mode
function _nbOnDsChange() {
  const sel    = document.getElementById('nb-mcp-ds');
  const formEl = document.getElementById('nb-mcp-sample-form');
  if (!sel || !formEl) return;

  const dsId = parseInt(sel.value);
  if (!dsId) { formEl.innerHTML = ''; return; }
  const ds = _dataSubjects.find(d => d.id === dsId);
  if (!ds) { formEl.innerHTML = ''; return; }

  const inFields = (ds.input_schema?.fields) || [];
  if (inFields.length === 0) { formEl.innerHTML = ''; return; }

  const inputs = inFields.map(f => `
    <div class="flex items-center gap-2 mb-1.5">
      <label class="text-xs text-slate-500 w-32 shrink-0">${_esc(f.name)}${f.required ? ' <span class="text-red-400">*</span>' : ''}</label>
      <input id="nb-mcp-param-${_esc(f.name)}"
             class="input-field flex-1 text-xs py-1"
             placeholder="${_esc(f.description || f.name)}"
             value="${_esc(_defaultSampleValue(f.name))}" />
    </div>`).join('');

  formEl.innerHTML = `
    <label class="text-xs text-slate-500 font-medium">測試參數</label>
    <div class="mt-1 bg-slate-50 border border-slate-200 rounded-lg p-3">${inputs}</div>`;
}

// Collect params from the dynamic form fields into a plain object
function _nbCollectFormParams() {
  const sel = document.getElementById('nb-mcp-ds');
  const dsId = sel ? parseInt(sel.value) : null;
  const ds = dsId ? _dataSubjects.find(d => d.id === dsId) : null;
  const params = {};
  for (const f of (ds?.input_schema?.fields || [])) {
    const el = document.getElementById(`nb-mcp-param-${f.name}`);
    if (el && el.value.trim()) params[f.name] = el.value.trim();
  }
  return params;
}

// Collect skill_input for RoutineCheck: reads from whichever param form is active
function _nbCollectSkillInput() {
  if (_nbMcpMode === 'new') {
    // New MCP mode: read from the dynamic sample form (nb-mcp-param-{name})
    return _nbCollectFormParams();
  }
  // Select mode: read from the nb-mcp-select-param-{name} inputs
  const sel = document.getElementById('nb-mcp-select');
  const mcpId = sel ? parseInt(sel.value) : null;
  const mcp = mcpId ? _mcpDefs.find(m => m.id === mcpId) : null;
  const ds = (mcp?.system_mcp_id || mcp?.data_subject_id) ? _dataSubjects.find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id)) : null;
  const params = {};
  for (const f of (ds?.input_schema?.fields || [])) {
    const el = document.getElementById(`nb-mcp-select-param-${f.name}`);
    if (el && el.value.trim()) params[f.name] = el.value.trim();
  }
  return params;
}

function _nbOnMcpSelect() {
  const sel = document.getElementById('nb-mcp-select');
  const mcpId = sel ? parseInt(sel.value) : null;
  const mcp = mcpId ? _mcpDefs.find(m => m.id === mcpId) : null;
  const hint = document.getElementById('nb-mcp-params-hint');
  if (!hint) return;
  if (!mcp) { hint.innerHTML = ''; return; }

  // Render System MCP input form from the MCP's bound System MCP
  const ds = (mcp.system_mcp_id || mcp.data_subject_id) ? _dataSubjects.find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id)) : null;
  const fields = ds?.input_schema?.fields || [];

  if (!fields.length) {
    hint.innerHTML = `
      <div class="mt-2 text-xs text-slate-400 italic">此 MCP 無需額外查詢參數</div>`;
    return;
  }

  hint.innerHTML = `
    <div class="mt-3 bg-blue-50 border border-blue-200 rounded-lg p-3">
      <p class="text-[11px] font-bold text-blue-700 uppercase tracking-widest mb-2.5 flex items-center gap-1.5">
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
        </svg>
        System MCP 查詢參數 — ${_esc(ds.name)}
      </p>
      <div class="space-y-2.5">
        ${fields.map(f => `
          <div>
            <label class="text-[11px] font-bold text-slate-500 uppercase tracking-widest mb-1 block">
              ${_esc(f.label || f.name)}${f.required ? ' <span class="text-red-500">*</span>' : ''}
            </label>
            <input id="nb-mcp-select-param-${_esc(f.name)}"
                   type="${f.type === 'number' ? 'number' : 'text'}"
                   placeholder="${_esc(f.description || f.name)}"
                   value="${f.default_value !== undefined && f.default_value !== null ? _esc(String(f.default_value)) : ''}"
                   class="w-full bg-white border border-slate-300 rounded-md px-3 py-2 text-sm
                          font-medium text-slate-800 shadow-sm focus:outline-none
                          focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow">
          </div>`).join('')}
      </div>
    </div>`;
}

async function _tryRunNestedBuilder() {
  // ── Pre-run validation ────────────────────────────────────
  const errors = [];
  if (!document.getElementById('nb-task-name')?.value?.trim())
    errors.push('請填寫「任務名稱」');

  if (_nbSkillMode === 'new') {
    if (!document.getElementById('nb-skill-name')?.value?.trim())
      errors.push('請填寫「Skill 名稱」');
    if (!document.getElementById('nb-skill-prompt')?.value?.trim())
      errors.push('請填寫「異常判斷條件 (Diagnostic Prompt)」');
  } else {
    if (!document.getElementById('nb-skill-select')?.value)
      errors.push('請選擇現有 Skill');
  }

  if (_nbMcpMode === 'new') {
    if (!document.getElementById('nb-mcp-name')?.value?.trim())
      errors.push('請填寫「MCP 名稱」');
    if (!document.getElementById('nb-mcp-ds')?.value)
      errors.push('請選擇 Data Subject');
    if (!document.getElementById('nb-mcp-intent')?.value?.trim())
      errors.push('請填寫「加工意圖 (Processing Intent)」');
  } else {
    if (!document.getElementById('nb-mcp-select')?.value)
      errors.push('請選擇現有 MCP');
  }

  if (errors.length) {
    alert('請先完成以下設定：\n\n' + errors.map(e => '• ' + e).join('\n'));
    return;
  }

  // Switch to Logs tab and prepare state
  _nbSwitchRightTab('logs');

  const headerBtn = document.getElementById('nb-header-run-btn');
  const placeholder = document.getElementById('nb-console-placeholder');
  const skillResult = document.getElementById('nb-skill-result');
  const mcpResult   = document.getElementById('nb-mcp-result');
  const dot = document.getElementById('nb-console-status-dot');

  // Show running state (header button only)
  if (headerBtn) { headerBtn.disabled = true; headerBtn.textContent = '⏳ 執行中...'; }
  if (dot) dot.classList.remove('hidden');
  if (placeholder) placeholder.classList.add('hidden');
  if (skillResult) skillResult.classList.add('hidden');
  if (mcpResult) mcpResult.classList.add('hidden');
  _nbLogClear();
  document.getElementById('nb-exec-log')?.classList.remove('hidden');
  _nbLogLine('▶', '開始執行 Try Run');
  // Reset saved results from previous try-run
  _nbSkillLiveResult = null;

  try {
    // ── Step 1: Resolve Skill + MCP ──────────────────────────
    let skillObj = null;
    let mcpId    = null;

    if (_nbSkillMode === 'select') {
      const sel = document.getElementById('nb-skill-select');
      skillObj = sel && sel.value ? _skillDefs.find(s => s.id === parseInt(sel.value)) : null;
      if (skillObj) {
        _nbLogLine('📋', `已選 Skill：${skillObj.name}`);
        // Skill selected — derive MCP from its bindings
        const mcpIds = (() => { try { return JSON.parse(skillObj.mcp_ids || '[]'); } catch(_) { return []; } })();
        mcpId = mcpIds[0] || null;
      }
    }

    // MCP select panel can override/set mcpId
    if (_nbMcpMode === 'select') {
      const sel = document.getElementById('nb-mcp-select');
      if (sel && sel.value) mcpId = parseInt(sel.value);
    }

    if (mcpId) {
      const mcp = _mcpDefs.find(m => m.id === mcpId);
      if (mcp) _nbLogLine('🔧', `已選 MCP：${mcp.name}`);
    }

    // ── Step 2: Run MCP Try-Run ───────────────────────────────
    let mcpTryResult = null;

    if (_nbMcpMode === 'new') {
      // "建立全新" mode — fetch real sample data then run try-run
      const dsId   = parseInt(document.getElementById('nb-mcp-ds')?.value || '0');
      const intent = document.getElementById('nb-mcp-intent')?.value?.trim() || '';
      if (!dsId)   throw new Error('請選擇 System MCP');
      if (!intent) throw new Error('請填寫加工意圖 (Processing Intent)');

      const ds = _dataSubjects.find(d => d.id === dsId);
      if (!ds) throw new Error('找不到所選的 System MCP');

      // Fetch raw data from DS endpoint using form params (same as _fetchSample())
      let sampleData = null;
      const rawUrl = ds.api_config?.endpoint_url || '';
      if (rawUrl) {
        _nbLogLine('📡', `正在撈取 System MCP 樣本資料：${ds.name}…`);
        const formParams = _nbCollectFormParams();
        const method = (ds.api_config?.method || 'GET').toUpperCase();
        const path = rawUrl.replace(/^\/api\/v1/, '');
        const qp = new URLSearchParams(formParams);
        const fullPath = method === 'GET' && qp.toString() ? `${path}?${qp}` : path;
        const body = method !== 'GET' ? formParams : undefined;
        try {
          sampleData = await _api(method, fullPath, body);
          _nbLogLine('✓', '樣本資料撈取成功', 'text-emerald-600');
        } catch(fetchErr) {
          throw new Error(`撈取樣本資料失敗：${fetchErr.message}`);
        }
      }

      _nbLogLine('⚙', 'LLM 生成 MCP 處理腳本並沙箱執行中…');
      mcpTryResult = await _api('POST', '/mcp-definitions/try-run', {
        processing_intent: intent,
        system_mcp_id:     dsId,
        sample_data:       sampleData,
      });
      _nbTryRunResult = mcpTryResult;
      _nbLogLine('✓', 'MCP Try Run 完成', 'text-emerald-600');
      _renderLearningEvents('nb-exec-log-lines', mcpTryResult.learning_events);

    } else if (mcpId) {
      // "選擇現有" mode — run stored processing_script directly (NO LLM)
      const mcp = _mcpDefs.find(m => m.id === mcpId);
      if (!mcp) throw new Error(`找不到 MCP #${mcpId}`);

      const ds = (mcp.system_mcp_id || mcp.data_subject_id) ? _dataSubjects.find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id)) : null;
      const dsFields = ds?.input_schema?.fields || [];

      // Validate all required System MCP input fields are filled
      const missingRequired = dsFields.filter(f => {
        if (!f.required) return false;
        const el = document.getElementById(`nb-mcp-select-param-${f.name}`);
        return !el || !el.value.trim();
      });
      if (missingRequired.length) {
        throw new Error(`請先填寫 System MCP 查詢參數：${missingRequired.map(f => f.label || f.name).join('、')}`);
      }

      // Collect form params and fetch real System MCP data
      let rawData = null;
      const rawUrl = ds?.api_config?.endpoint_url || '';
      if (ds && rawUrl) {
        _nbLogLine('📡', `正在撈取 System MCP 資料：${ds.name}…`);
        const formParams = {};
        for (const f of dsFields) {
          const el = document.getElementById(`nb-mcp-select-param-${f.name}`);
          if (el && el.value.trim()) formParams[f.name] = el.value.trim();
        }
        const method = (ds.api_config?.method || 'GET').toUpperCase();
        const path = rawUrl.replace(/^\/api\/v1/, '');
        const qp = new URLSearchParams(formParams);
        const fullPath = method === 'GET' && qp.toString() ? `${path}?${qp}` : path;
        const body = method !== 'GET' ? formParams : undefined;
        try {
          rawData = await _api(method, fullPath, body);
          _nbLogLine('✓', 'System MCP 資料撈取成功', 'text-emerald-600');
        } catch(fetchErr) {
          throw new Error(`撈取 System MCP 資料失敗：${fetchErr.message}`);
        }
      } else if (!ds) {
        throw new Error('此 MCP 未綁定 System MCP，無法取得資料');
      }

      if (!rawData) throw new Error('DS 回傳空資料，請確認查詢參數是否正確');

      _nbLogLine('⚙', `執行 MCP：${mcp.name}（直接執行已存 Python）…`);
      mcpTryResult = await _api('POST', `/mcp-definitions/${mcpId}/run-with-data`, {
        raw_data: rawData,
      });
      _nbTryRunResult = mcpTryResult;
      _nbLogLine('✓', 'MCP 執行完成', 'text-emerald-600');

    } else if (!skillObj) {
      throw new Error('請選擇 Skill 或設定 MCP 後再執行');
    }

    // Update Data Review and Format Review with grid tables
    if (mcpTryResult) {
      const outputData = mcpTryResult.output_data || mcpTryResult;
      const rawEl = document.getElementById('nb-data-review');
      if (rawEl) {
        const rows = outputData._raw_dataset
          || (Array.isArray(outputData.dataset) ? outputData.dataset : []);
        _nbRenderDataGrid(rawEl, rows, '無原始資料');
        document.getElementById('nb-data-review-details')?.setAttribute('open', '');
      }
      const schemaEl = document.getElementById('nb-format-review');
      if (schemaEl && mcpTryResult.output_schema) {
        _nbRenderSchemaGrid(schemaEl, mcpTryResult.output_schema);
        document.getElementById('nb-format-review-details')?.setAttribute('open', '');
      }
    }

    // ── Step 3: If new Skill mode + MCP output → generate Skill code & run diagnosis ──
    let skillLiveResult = null;
    if (_nbSkillMode === 'new' && mcpTryResult) {
      const diagPrompt   = document.getElementById('nb-skill-prompt')?.value?.trim() || '';
      const probSubject  = document.getElementById('nb-skill-target')?.value?.trim() || '';
      const expertAction = document.getElementById('nb-skill-action')?.value?.trim() || '';
      if (!diagPrompt) throw new Error('請填寫異常判斷條件 (Diagnostic Prompt)');

      // Identify the MCP name to use as key in mcp_sample_outputs
      let mcpNameForKey = 'mcp';
      if (_nbMcpMode === 'select' && mcpId) {
        const mcp = _mcpDefs.find(m => m.id === mcpId);
        if (mcp) mcpNameForKey = mcp.name;
      } else if (_nbMcpMode === 'new') {
        mcpNameForKey = document.getElementById('nb-mcp-name')?.value?.trim() || 'mcp';
      }

      _nbLogLine('🧠', 'LLM 生成 Skill 診斷 Python 程式碼…');
      const skillCodeResult = await _api('POST', '/skill-definitions/generate-code-diagnosis', {
        diagnostic_prompt:  diagPrompt,
        problem_subject:    probSubject || null,
        mcp_sample_outputs: { [mcpNameForKey]: mcpTryResult.output_data || mcpTryResult },
        event_attributes:   [],
      });

      if (!skillCodeResult.success) {
        throw new Error(skillCodeResult.error || 'Skill 診斷碼生成失敗');
      }

      _renderLearningEvents('nb-exec-log-lines', skillCodeResult.learning_events);
      const resultStatus = skillCodeResult.status || 'UNKNOWN';
      const statusIcon = resultStatus === 'ABNORMAL' ? '⚠' : resultStatus === 'NORMAL' ? '✓' : '—';
      const statusColor = resultStatus === 'ABNORMAL' ? 'text-red-600' : resultStatus === 'NORMAL' ? 'text-emerald-600' : 'text-slate-500';
      _nbLogLine(statusIcon, `Skill 診斷完成 → ${resultStatus}`, statusColor);

      // Attach display helpers for _nbRenderSkillDiagnosis
      skillLiveResult = {
        ...skillCodeResult,
        skillName:   document.getElementById('nb-skill-name')?.value?.trim() || '新建 Skill',
        expertAction,
      };
      _nbSkillLiveResult = skillLiveResult;  // persist for save step
    }

    // ── Step 4: Show Skill Diagnosis Layer ──────────────────
    _nbLogLine('📊', '渲染診斷結果…');
    _nbRenderSkillDiagnosis(skillObj, skillLiveResult);

    // ── Step 5: Show MCP Evidence Layer ──────────────────────
    if (mcpTryResult) _nbRenderMcpEvidence(mcpTryResult);
    _nbLogLine('✓', 'Try Run 完成 — 正在切換至報告…', 'text-emerald-600');

    // Auto-switch to Report tab after a brief pause so user sees the final log line
    setTimeout(() => _nbSwitchRightTab('report'), 700);

  } catch(e) {
    _nbLogLine('✗', `執行失敗：${e.message}`, 'text-red-600');
    if (placeholder) {
      placeholder.classList.remove('hidden');
      placeholder.innerHTML = `
        <div class="text-center">
          <p class="text-red-600 font-semibold text-sm mb-1">✗ 執行失敗</p>
          <p class="text-red-500 text-xs">${_esc(e.message)}</p>
        </div>`;
    }
  } finally {
    if (headerBtn) { headerBtn.disabled = false; headerBtn.textContent = '▶ Try Run'; }
    if (dot) dot.classList.add('hidden');
  }
}

// liveResult: result from generate-code-diagnosis (takes priority over skillObj.last_diagnosis_result)
function _nbRenderSkillDiagnosis(skillObj, liveResult = null) {
  const resultEl = document.getElementById('nb-skill-result');
  const cardEl   = document.getElementById('nb-skill-diagnosis-card');
  if (!resultEl || !cardEl) return;

  // Priority: liveResult (from fresh LLM run) > skillObj.last_diagnosis_result > empty state
  let savedResult = liveResult || null;
  if (!savedResult && skillObj?.last_diagnosis_result) {
    const raw = skillObj.last_diagnosis_result;
    try { savedResult = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch(_) {}
  }

  const status  = savedResult?.status || (skillObj ? 'UNKNOWN' : 'UNKNOWN');
  const diagMsg = savedResult?.diagnosis_message
    || (skillObj ? '已載入 Skill 設定，診斷數據需實際執行後產生' : '請選擇一個 Skill');
  const probObj = savedResult?.problem_object;
  const isAbn   = status === 'ABNORMAL';

  const statusBadge = isAbn
    ? `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full
                    bg-red-100 border border-red-300 text-red-700 font-bold text-xs">⚠ ABNORMAL</span>`
    : status === 'NORMAL'
    ? `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full
                    bg-emerald-100 border border-emerald-300 text-emerald-700 font-bold text-xs">✓ NORMAL</span>`
    : `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full
                    bg-slate-100 border border-slate-300 text-slate-500 font-bold text-xs">— ${_esc(status)}</span>`;

  const probHtml = probObj && typeof probObj === 'object' && Object.keys(probObj).length
    ? `<div class="mt-1 space-y-1">` +
        Object.entries(probObj).map(([k, v]) =>
          `<div class="flex gap-2 text-xs">
             <span class="text-slate-500 min-w-24 font-medium">${_esc(k)}：</span>
             <span class="text-slate-700 font-semibold">${_esc(String(v))}</span>
           </div>`).join('') +
        `</div>`
    : `<p class="text-xs text-slate-400 italic mt-1">無異常物件</p>`;

  // Light report card style: ABNORMAL = red-tinted, NORMAL = green-tinted, UNKNOWN = neutral
  const cardBg     = isAbn ? 'bg-red-50 border border-red-200 border-l-4 border-l-red-500'
                   : status === 'NORMAL' ? 'bg-emerald-50 border border-emerald-200 border-l-4 border-l-emerald-500'
                   : 'bg-slate-50 border border-slate-200 border-l-4 border-l-slate-400';
  const msgColor   = isAbn ? 'text-red-900' : status === 'NORMAL' ? 'text-emerald-900' : 'text-slate-700';
  const labelColor = isAbn ? 'text-red-500'  : status === 'NORMAL' ? 'text-emerald-600' : 'text-slate-500';

  cardEl.innerHTML = `
    <div class="${cardBg} rounded-xl p-4">
      <div class="flex items-center gap-2 mb-3">
        ${statusBadge}
        <span class="text-xs text-slate-500 font-medium">${liveResult?.skillName || (skillObj ? _esc(skillObj.name) : '未選擇')}</span>
      </div>
      <p class="text-sm ${msgColor} leading-relaxed mb-3 font-medium">${_esc(diagMsg)}</p>
      <div class="text-[11px] font-bold ${labelColor} uppercase tracking-widest mb-1.5">異常物件</div>
      ${probHtml}
      ${isAbn && (liveResult?.expertAction || skillObj?.human_recommendation) ? `
        <div class="mt-3 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5">
          <p class="text-[11px] font-bold text-amber-700 uppercase tracking-widest mb-1">↳ 專家建議處置</p>
          <p class="text-sm text-amber-800">${_esc(liveResult?.expertAction || skillObj?.human_recommendation)}</p>
        </div>` : ''}
    </div>`;

  resultEl.classList.remove('hidden');
}

function _nbRenderMcpEvidence(result) {
  const resultEl = document.getElementById('nb-mcp-result');
  if (!resultEl) return;
  resultEl.classList.remove('hidden');
  _nbSwitchMcpTab('charting');

  // Data lives inside output_data (MCPTryRunResponse envelope)
  const outputData = result.output_data || result;
  const uiRender   = outputData.ui_render || outputData.ui_render_config || {};
  const charts     = uiRender.charts || (uiRender.chart_data ? [uiRender.chart_data] : []);
  const dataset    = outputData.dataset || [];
  const rawDataset = outputData._raw_dataset || [];

  // ── Charting tab ────────────────────────────────────────────
  const chartEl = document.getElementById('nb-mcp-tab-charting');
  if (chartEl) {
    if (charts.length) {
      chartEl.innerHTML = '';
      charts.forEach((chartJson) => {
        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'height:380px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;margin-bottom:8px;';
        chartEl.appendChild(wrapper);
        try {
          const figData = typeof chartJson === 'string' ? JSON.parse(chartJson) : chartJson;
          const figLayout = figData.layout || {};
          const mergedMargin = Object.assign({ l: 50, r: 20, t: 40, b: 40 }, figLayout.margin || {});
          if (figLayout.title && mergedMargin.t < 55) mergedMargin.t = 55;
          const hasHorizLegend = figLayout.legend?.orientation === 'h';
          if (hasHorizLegend && mergedMargin.b < 100) mergedMargin.b = 100;
          const legendOverride = hasHorizLegend ? { legend: { ...figLayout.legend, y: -0.28, x: 0, xanchor: 'left' } } : {};
          const layoutOverride = {
            paper_bgcolor: '#f8fafc', plot_bgcolor: '#ffffff',
            font: { color: '#334155', size: 11 },
            xaxis: { gridcolor: '#e2e8f0', linecolor: '#cbd5e1' },
            yaxis: { gridcolor: '#e2e8f0', linecolor: '#cbd5e1' },
          };
          Plotly.newPlot(wrapper, figData.data || [], { ...figLayout, ...layoutOverride, margin: mergedMargin, ...legendOverride }, { responsive: true });
        } catch(e) {
          wrapper.innerHTML = `<p class="text-xs text-red-500 p-3">圖表渲染失敗：${_esc(e.message)}</p>`;
        }
      });
    } else {
      chartEl.innerHTML = `<div class="flex items-center justify-center h-24 text-slate-400 text-sm">無圖表資料</div>`;
    }
  }

  // ── Summary tab (processed dataset as grid) ─────────────────
  const sumEl = document.getElementById('nb-mcp-tab-summary');
  if (sumEl) _nbRenderDataGrid(sumEl, dataset, '無摘要資料');

  // ── Raw Data tab (original DS data as grid) ──────────────────
  const rawEl = document.getElementById('nb-mcp-tab-raw');
  if (rawEl) {
    const rawRows = Array.isArray(rawDataset) ? rawDataset
      : (rawDataset && typeof rawDataset === 'object' ? [rawDataset] : []);
    _nbRenderDataGrid(rawEl, rawRows, '無原始資料');
  }
}

// Shared grid renderer for Summary and Raw Data tabs
function _nbRenderDataGrid(el, rows, emptyMsg) {
  if (!Array.isArray(rows)) rows = [];   // guard: string / object / null-ish → empty
  if (!rows.length) {
    el.innerHTML = `<p class="text-slate-400 italic text-sm py-4">${emptyMsg}</p>`;
    return;
  }
  // Filter out internal _prefixed keys from display
  const keys = Object.keys(rows[0] || {}).filter(k => !k.startsWith('_'));
  if (!keys.length) {
    el.innerHTML = `<p class="text-slate-400 italic text-sm py-4">${emptyMsg}</p>`;
    return;
  }
  el.innerHTML = `
    <div class="overflow-x-auto rounded-lg border border-slate-200">
      <table class="text-xs w-full border-collapse">
        <thead class="bg-slate-100 sticky top-0">
          <tr>${keys.map(k => `<th class="text-left text-slate-600 font-bold border-b border-slate-200 px-3 py-2 uppercase tracking-wide whitespace-nowrap">${_esc(k)}</th>`).join('')}</tr>
        </thead>
        <tbody class="bg-white">
          ${rows.slice(0, 50).map((row, ri) =>
            `<tr class="${ri % 2 === 1 ? 'bg-slate-50' : 'bg-white'} hover:bg-blue-50 transition-colors">
               ${keys.map(k => `<td class="text-slate-700 border-b border-slate-100 px-3 py-1.5 whitespace-nowrap">${_esc(String(row[k] ?? ''))}</td>`).join('')}
             </tr>`).join('')}
        </tbody>
      </table>
      ${rows.length > 50 ? `<p class="text-slate-400 italic px-3 py-2 text-[11px]">⋯ 僅顯示前 50 筆（共 ${rows.length} 筆）</p>` : ''}
    </div>`;
}

function _nbSwitchMcpTab(tab) {
  ['charting', 'summary', 'raw'].forEach(t => {
    const btn     = document.getElementById(`nb-tab-${t}`);
    const content = document.getElementById(`nb-mcp-tab-${t}`);
    const isActive = t === tab;
    if (btn) {
      btn.className = `text-xs px-4 py-2 border-b-2 transition-colors ` +
        (isActive ? 'text-emerald-700 border-emerald-600 font-bold' : 'text-slate-500 border-transparent hover:text-slate-700 font-medium');
    }
    if (content) content.classList.toggle('hidden', !isActive);
  });
}

// ── Unified Execution Console Helpers (v14.2) ─────────────────
// type: 'default' | 'success' | 'error' | 'warning' | 'muted' | 'learn'
function _consoleLog(linesId, icon, text, type = 'default') {
  const lines = document.getElementById(linesId);
  if (!lines) return;
  const ts = new Date().toLocaleTimeString('zh-TW', { hour12: false });
  const row = document.createElement('div');

  if (type === 'learn') {
    row.className = 'flex items-start gap-2 py-1 -mx-4 px-4 bg-violet-50 border-l-2 border-violet-400';
    row.innerHTML = `<span class="text-slate-400 shrink-0 select-none font-mono">${ts}</span>
                     <span class="text-violet-700 font-semibold flex-1">${icon} ${_esc(text)}</span>`;
  } else {
    const colorMap = {
      default: 'text-slate-600',
      success: 'text-emerald-600',
      error:   'text-red-600',
      warning: 'text-amber-600',
      muted:   'text-slate-400',
    };
    const cls = colorMap[type] || 'text-slate-600';
    row.className = 'flex items-start gap-2 py-0.5';
    row.innerHTML = `<span class="text-slate-400 shrink-0 select-none font-mono">${ts}</span>
                     <span class="${cls}">${icon} ${_esc(text)}</span>`;
  }
  lines.appendChild(row);
  lines.scrollTop = lines.scrollHeight;
}

// ── Per-console shims (keep old call sites unchanged) ──────────
function _nbLogClear() {
  const el = document.getElementById('nb-exec-log');
  const lines = document.getElementById('nb-exec-log-lines');
  if (el) el.classList.remove('hidden');
  if (lines) lines.innerHTML = '';
}

function _nbLogLine(icon, text, colorOrType = 'text-slate-600') {
  // Translate legacy Tailwind color class → type token
  const type = _colorToType(colorOrType);
  _consoleLog('nb-exec-log-lines', icon, text, type);
}

// ── Render a batch of self-learning events from API response ───
function _renderLearningEvents(linesId, events) {
  if (!Array.isArray(events) || events.length === 0) return;
  // Separator line
  const lines = document.getElementById(linesId);
  if (lines) {
    const sep = document.createElement('div');
    sep.className = 'border-t border-violet-200 my-1 -mx-4';
    lines.appendChild(sep);
  }
  for (const ev of events) {
    _consoleLog(linesId, '💡', ev, 'learn');
  }
}

function _colorToType(c) {
  if (!c || c === 'text-slate-600' || c === 'text-slate-700') return 'default';
  if (c === 'text-emerald-600') return 'success';
  if (c === 'text-red-600' || c === 'text-red-500') return 'error';
  if (c === 'text-amber-600' || c === 'text-amber-500') return 'warning';
  if (c === 'text-slate-400' || c === 'text-slate-500') return 'muted';
  return 'default';
}

async function _nbSaveRoutineCheck() {
  const name     = document.getElementById('nb-task-name')?.value?.trim();
  const interval = document.getElementById('nb-task-interval')?.value;
  if (!name) { alert('請填寫任務名稱'); return; }

  const saveBtn = document.getElementById('nb-save-btn');
  if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = '儲存中…'; }
  _nbExpandConsole();

  try {
    // ── Step 1: Save MCP (if building new) ───────────────────────
    let mcpId = null;
    if (_nbMcpMode === 'new') {
      if (!_nbTryRunResult) {
        alert('請先執行 Try Run 以產生 MCP 腳本');
        return;
      }
      _nbLogLine('💾', '儲存 MCP 定義…');
      const mcpName = document.getElementById('nb-mcp-name')?.value?.trim() || `${name} MCP`;
      const mcpDesc = document.getElementById('nb-mcp-desc')?.value?.trim() || '';
      const dsId    = parseInt(document.getElementById('nb-mcp-ds')?.value || '0');
      const intent  = document.getElementById('nb-mcp-intent')?.value?.trim() || '';

      const mcpCreateRes = await _api('POST', '/mcp-definitions', {
        name: mcpName,
        description: mcpDesc,
        system_mcp_id: dsId,
        processing_intent: intent,
      });
      mcpId = mcpCreateRes.id;

      // Patch in the generated script + schemas from the try-run result
      await _api('PATCH', `/mcp-definitions/${mcpId}`, {
        processing_script: _nbTryRunResult.script || '',
        output_schema:     _nbTryRunResult.output_schema || {},
        ui_render_config:  _nbTryRunResult.ui_render_config || {},
        input_definition:  _nbTryRunResult.input_definition || {},
        sample_output:     _nbTryRunResult.output_data || {},
      });
      _nbLogLine('✓', `MCP「${mcpName}」已儲存（id=${mcpId}）`, 'text-emerald-600');

    } else {
      const sel = document.getElementById('nb-mcp-select');
      mcpId = sel && sel.value ? parseInt(sel.value) : null;
    }

    // ── Step 2: Save Skill (if building new) ─────────────────────
    let skillId = null;
    if (_nbSkillMode === 'new') {
      if (!_nbSkillLiveResult) {
        alert('請先執行 Try Run 以產生 Skill 診斷碼');
        return;
      }
      _nbLogLine('💾', '儲存 Skill 定義…');
      const skillName   = document.getElementById('nb-skill-name')?.value?.trim() || `${name} Skill`;
      const diagPrompt  = document.getElementById('nb-skill-prompt')?.value?.trim() || '';
      const probSubject = document.getElementById('nb-skill-target')?.value?.trim() || '';
      const expertAct   = document.getElementById('nb-skill-action')?.value?.trim() || '';

      const skillCreateRes = await _api('POST', '/skill-definitions', {
        name:                 skillName,
        description:          '',
        diagnostic_prompt:    diagPrompt,
        problem_subject:      probSubject || null,
        mcp_id:               mcpId,
        human_recommendation: expertAct || null,
      });
      skillId = skillCreateRes.id;

      // Patch in generated code + last_diagnosis_result
      const lastDiag = {
        status:              _nbSkillLiveResult.status || 'UNKNOWN',
        diagnosis_message:   _nbSkillLiveResult.diagnosis_message || '',
        problem_object:      _nbSkillLiveResult.problem_object || {},
        generated_code:      _nbSkillLiveResult.generated_code || '',
        check_output_schema: _nbSkillLiveResult.check_output_schema || {},
        timestamp:           new Date().toISOString(),
      };
      await _api('PATCH', `/skill-definitions/${skillId}`, {
        last_diagnosis_result: lastDiag,
      });
      _nbLogLine('✓', `Skill「${skillName}」已儲存（id=${skillId}）`, 'text-emerald-600');

    } else {
      const sel = document.getElementById('nb-skill-select');
      skillId = sel && sel.value ? parseInt(sel.value) : null;
    }

    if (!skillId) {
      alert('無法取得 Skill ID，請重新選擇或建立 Skill');
      return;
    }

    // ── Step 3: Create RoutineCheck ───────────────────────────────
    _nbLogLine('💾', '建立巡檢排程…');
    const scheduleTime   = document.getElementById('nb-task-schedule-time')?.value?.trim() || null;
    const expireAt       = document.getElementById('nb-task-expire-at')?.value?.trim() || null;
    const eventNameInput = document.getElementById('rc-event-name')?.value?.trim();
    const generatedEventName = eventNameInput || `${name} 自動警報`;
    const rcPayload = {
      name,
      skill_id:             skillId,
      skill_input:          _nbCollectSkillInput(),
      schedule_interval:    interval,
      is_active:            true,
      generated_event_name: generatedEventName,
    };
    if (interval === 'daily' && scheduleTime) rcPayload.schedule_time = scheduleTime;
    if (expireAt) rcPayload.expire_at = expireAt;
    await _api('POST', '/routine-checks', rcPayload);
    _nbLogLine('✓', `排程「${name}」已建立！`, 'text-emerald-600');

    setTimeout(() => {
      // Close any open draft workspace tabs (routine_check type)
      if (typeof _closeWorkspaceTab === 'function' && typeof _workspaceTabs !== 'undefined') {
        Object.keys(_workspaceTabs).forEach(tabId => {
          if (tabId.startsWith('draft-')) _closeWorkspaceTab(tabId);
        });
      }
      switchView('dashboard');
      // Non-blocking success toast
      const toast = document.createElement('div');
      toast.className = 'fixed bottom-6 right-6 bg-emerald-600 text-white text-sm font-medium px-5 py-3 rounded-xl shadow-lg z-50';
      toast.style.transition = 'opacity 0.4s';
      toast.textContent = `✓ 任務「${name}」已成功建立`;
      document.body.appendChild(toast);
      setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 400); }, 2500);
    }, 400);

  } catch(e) {
    _nbLogLine('✗', `儲存失敗：${e.message}`, 'text-red-500');
    alert(`儲存失敗：${e.message}`);
  } finally {
    if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '儲存排程'; }
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// SKILL BUILDER — Full-page L/R Editor (Change B)
// ══════════════════════════════════════════════════════════════════════════════

let _skRightTab = 'logs';
let _skTryRunMcpResult = null;
let _skMcpSampleParams = null;  // DS query params collected for the selected MCP
let _skLastDiagnosisResult = null;  // Saved after successful _skTryRun
let _skLastMcpSampleOutputs = null;  // keyed by mcp.name, for feedback re-run

// ── Tab switching ─────────────────────────────────────────────
function _skSwitchRightTab(tab) {
  _skRightTab = tab;
  ['logs', 'report'].forEach(t => {
    document.getElementById(`sk-rtab-${t}`)?.classList.toggle('hidden', t !== tab);
    const btn = document.getElementById(`sk-rtab-btn-${t}`);
    if (btn) btn.className = t === tab
      ? 'px-5 py-3 text-xs font-bold text-blue-700 border-b-2 border-blue-600 transition-colors'
      : 'px-5 py-3 text-xs font-medium text-slate-500 border-b-2 border-transparent hover:text-slate-700 transition-colors';
  });
  // Feedback bar only shows on Report tab when result exists
  const fb = document.getElementById('sk-feedback-section');
  if (fb && _skLastDiagnosisResult) {
    fb.classList.toggle('hidden', tab !== 'report');
  }
}

function _skSwitchMcpTab(tab) {
  ['charting', 'summary', 'raw'].forEach(t => {
    const btn = document.getElementById(`sk-tab-${t}`);
    const content = document.getElementById(`sk-mcp-tab-${t}`);
    if (btn) btn.className = `text-xs px-4 py-2 border-b-2 transition-colors ` +
      (t === tab ? 'text-emerald-700 border-emerald-600 font-bold' : 'text-slate-500 border-transparent hover:text-slate-700 font-medium');
    content?.classList.toggle('hidden', t !== tab);
  });
}

function _skLogLine(icon, text, colorOrType = 'text-slate-600') {
  _consoleLog('sk-exec-log-lines', icon, text, _colorToType(colorOrType));
}

// ── Open / close editor ───────────────────────────────────────
async function _skOpenEditor(id, draftData) {
  if (_mcpDefs.length === 0)    _mcpDefs    = await _api('GET', '/mcp-definitions?type=custom') || [];
  if (_dataSubjects.length === 0) _dataSubjects = await _api('GET', '/mcp-definitions?type=system') || [];

  // Switch to editor state
  document.getElementById('sk-list-state')?.classList.add('hidden');
  const editor = document.getElementById('sk-editor');
  if (editor) { editor.classList.remove('hidden'); editor.classList.add('flex'); }

  // Reset right panel
  _skSwitchRightTab('logs');
  document.getElementById('sk-exec-log')?.classList.add('hidden');
  document.getElementById('sk-exec-log-lines').innerHTML = '';
  const ph = document.getElementById('sk-console-placeholder');
  if (ph) {
    ph.classList.remove('hidden');
    ph.innerHTML = `
      <svg class="w-10 h-10 mb-3 opacity-25" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
              d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
      </svg>
      <p class="text-sm font-medium text-slate-500">點擊 ▶ Try Run 執行診斷模擬</p>
      <p class="text-xs mt-1 text-slate-400">先設定左側 Skill 與 MCP 後再執行</p>`;
  }
  document.getElementById('sk-skill-result')?.classList.add('hidden');
  document.getElementById('sk-mcp-result')?.classList.add('hidden');
  _skTryRunMcpResult = null;
  _skMcpSampleParams = null;
  _skLastDiagnosisResult = null;

  // Populate MCP dropdown — custom MCPs only (these have processing_script)
  const mcpSel = document.getElementById('sk-edit-mcp-select');
  if (mcpSel) {
    const opts = _mcpDefs.map(m => {
      const ds = _dataSubjects.find(d => d.id === (m.system_mcp_id || m.data_subject_id));
      return `<option value="${m.id}">${_esc(m.name)}${ds ? ' (' + _esc(ds.name) + ')' : ''}</option>`;
    }).join('');
    mcpSel.innerHTML = '<option value="">— 請選擇已有的 MCP —</option>' + opts;
  }

  if (!id) {
    // New Skill (possibly pre-filled from agent draft)
    const isDraft = !!draftData;
    document.getElementById('sk-editor-title').textContent = isDraft ? '草稿審核 — 新增 Skill' : '新增 Skill';
    document.getElementById('sk-edit-id').value = '';
    document.getElementById('sk-edit-name').value        = draftData?.name || '';
    document.getElementById('sk-edit-desc').value        = draftData?.description || '';
    document.getElementById('sk-edit-prompt').value      = draftData?.diagnostic_prompt || '';
    document.getElementById('sk-edit-subject').value     = draftData?.problematic_target || '';
    document.getElementById('sk-edit-action').value      = draftData?.expert_action || '';
    if (mcpSel) {
      const mcpRef = draftData?.mcp_id || (draftData?.mcp_ids?.[0]);
      mcpSel.value = mcpRef != null ? String(mcpRef) : '';
      if (mcpRef) _skOnMcpChange();
    }
    document.getElementById('sk-edit-mcp-hint').innerHTML = '';
    // If from draft, store draft_id for publish button
    if (isDraft && draftData._draft_id) {
      document.getElementById('sk-editor').dataset.draftId = draftData._draft_id;
    }
    _skSetMode('visual'); _skSetMcpMode('existing'); // always reset to Visual mode on open
    return;
  }

  // Load existing Skill
  let sk = _skillDefs.find(s => s.id === id) || await _api('GET', `/skill-definitions/${id}`);
  document.getElementById('sk-editor-title').textContent = sk?.name || `Skill #${id}`;
  document.getElementById('sk-edit-id').value = id;
  document.getElementById('sk-edit-name').value = sk?.name || '';
  document.getElementById('sk-edit-desc').value = sk?.description || '';
  document.getElementById('sk-edit-prompt').value = sk?.diagnostic_prompt || '';
  document.getElementById('sk-edit-subject').value = sk?.problem_subject || '';
  document.getElementById('sk-edit-action').value = sk?.human_recommendation || '';
  if (mcpSel && sk?.mcp_id) {
    mcpSel.value = sk.mcp_id;
    _skOnMcpChange();
  }
  _skSetMode('visual'); // always reset to Visual mode on open
}

function _skBackToList() {
  document.getElementById('sk-editor')?.classList.add('hidden');
  document.getElementById('sk-editor')?.classList.remove('flex');
  // If opened from Agent draft, return to chat instead of Skill list
  if (window._draftReturnView) {
    const target = window._draftReturnView;
    window._draftReturnView = null;
    switchView(target);
    return;
  }
  document.getElementById('sk-list-state')?.classList.remove('hidden');
  _loadSkillDefs();
}

// ── MCP mode toggle (select existing vs create new) ───────────
function _skSetMcpMode(mode) {
  const isNew = mode === 'new';
  document.getElementById('sk-mcp-panel-existing').classList.toggle('hidden', isNew);
  document.getElementById('sk-mcp-panel-new').classList.toggle('hidden', !isNew);
  const btnExisting = document.getElementById('sk-mcp-mode-existing');
  const btnNew = document.getElementById('sk-mcp-mode-new');
  if (btnExisting) btnExisting.className = isNew
    ? 'flex-1 px-3 py-1.5 rounded-md text-slate-500 hover:text-slate-700 transition-all'
    : 'flex-1 px-3 py-1.5 rounded-md bg-white text-emerald-700 shadow-sm transition-all';
  if (btnNew) btnNew.className = isNew
    ? 'flex-1 px-3 py-1.5 rounded-md bg-white text-emerald-700 shadow-sm transition-all'
    : 'flex-1 px-3 py-1.5 rounded-md text-slate-500 hover:text-slate-700 transition-all';

  if (isNew) {
    // Populate the system MCP dropdown
    const sel = document.getElementById('sk-new-mcp-sys-select');
    if (sel && _dataSubjects.length) {
      sel.innerHTML = '<option value="">— 選擇資料來源 —</option>' +
        _dataSubjects.map(m => `<option value="${m.id}">${_esc(m.name)}</option>`).join('');
    }
  }
}

async function _skCreateInlineMcp() {
  const name    = document.getElementById('sk-new-mcp-name')?.value.trim();
  const sysId   = parseInt(document.getElementById('sk-new-mcp-sys-select')?.value) || null;
  const intent  = document.getElementById('sk-new-mcp-intent')?.value.trim() || '';
  const statusEl = document.getElementById('sk-new-mcp-status');

  if (!name) { alert('請輸入 MCP 名稱'); return; }
  if (!sysId) { alert('請選擇資料來源 (System MCP)'); return; }

  if (statusEl) { statusEl.textContent = '建立中…'; statusEl.classList.remove('hidden', 'text-red-500'); statusEl.classList.add('text-slate-500'); }

  try {
    const result = await _api('POST', '/mcp-definitions', {
      name,
      description: intent,
      mcp_type: 'custom',
      system_mcp_id: sysId,
      processing_intent: intent,
      visibility: 'private',
    });
    const newId = result?.data?.id || result?.id;
    if (!newId) throw new Error(result?.message || '建立失敗');

    // Add to _mcpDefs and refresh dropdown
    const newMcp = result?.data || result;
    if (!_mcpDefs.find(m => m.id === newId)) _mcpDefs.push(newMcp);
    const sel = document.getElementById('sk-edit-mcp-select');
    if (sel) {
      const opt = document.createElement('option');
      opt.value = newId;
      opt.textContent = name;
      sel.appendChild(opt);
      sel.value = newId;
    }

    // Switch back to "existing" mode (the new MCP is now selected)
    _skSetMcpMode('existing');
    _skOnMcpChange();

    if (statusEl) { statusEl.textContent = `✓ MCP「${name}」已建立並綁定。如需生成腳本請到 MCP Builder 執行 Try Run。`; statusEl.classList.remove('hidden', 'text-slate-500'); statusEl.classList.add('text-emerald-600'); }
  } catch (e) {
    if (statusEl) { statusEl.textContent = `建立失敗：${e.message}`; statusEl.classList.remove('hidden', 'text-slate-500'); statusEl.classList.add('text-red-500'); }
  }
}

// ── MCP selection change ───────────────────────────────────────
async function _skOnMcpChange() {
  const mcpId = parseInt(document.getElementById('sk-edit-mcp-select')?.value) || null;
  // Look in both custom and system lists
  const mcp = mcpId ? (_mcpDefs.find(m => m.id === mcpId) || _dataSubjects.find(m => m.id === mcpId)) : null;
  const hint = document.getElementById('sk-edit-mcp-hint');
  _skMcpSampleParams = null;
  if (!hint) return;
  if (!mcp) { hint.innerHTML = ''; return; }

  // Resolve the data source: system MCP = itself; custom MCP = look up parent
  const isSysMcp = mcp.mcp_type === 'system';
  let ds = isSysMcp ? mcp : (_dataSubjects.find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id)) || null);
  // Fallback: old custom MCPs have legacy data_subject_id — resolve by name
  if (!ds && !isSysMcp && mcp.data_subject_id) {
    try {
      const oldDs = await _api('GET', `/data-subjects/${mcp.data_subject_id}`);
      if (oldDs?.name) ds = _dataSubjects.find(d => d.name === oldDs.name) || null;
    } catch {}
  }

  // Show "no processing script" banner if MCP has never been through Try Run
  const hasScript = !!(mcp.processing_script && mcp.processing_script.trim());
  const noScriptBanner = (!isSysMcp && !hasScript)
    ? `<div class="mt-2 mb-1 bg-amber-50 border border-amber-300 rounded-lg px-3 py-2 flex items-start gap-2">
        <span class="text-amber-500 text-base leading-none mt-0.5">⚠</span>
        <div class="flex-1">
          <p class="text-[11px] font-bold text-amber-700">此 MCP 尚未完成 Try Run</p>
          <p class="text-[11px] text-amber-600 mt-0.5">請先在 MCP Builder 完成試跑，否則 Skill Try Run 將無法執行。</p>
          <button onclick="window._openMcpBuilderForId(${mcp.id})"
                  class="mt-1.5 text-[11px] font-semibold text-white bg-amber-500 hover:bg-amber-400
                         rounded px-2.5 py-1 transition-colors">
            → 前往 MCP Builder 完成試跑
          </button>
        </div>
      </div>`
    : '';

  const inputSchema = isSysMcp ? (mcp.input_schema || null) : (ds?.input_schema || null);
  const fields = (typeof inputSchema === 'string' ? JSON.parse(inputSchema || '{}') : (inputSchema || {}))?.fields || [];

  // Custom MCP's own manual params (source='manual'|'event', not 'data_subject')
  const inputDef = !isSysMcp ? (typeof mcp.input_definition === 'string'
    ? JSON.parse(mcp.input_definition || '{}') : (mcp.input_definition || {})) : {};
  const manualParams = (inputDef?.params || []).filter(p => p.source !== 'data_subject' && p.name !== 'raw_data');

  const _renderFields = (flds, idPrefix, sectionTitle, sectionColor) => {
    if (!flds.length) return '';
    const borderColor = sectionColor === 'green' ? 'border-green-200' : 'border-blue-200';
    const bgColor     = sectionColor === 'green' ? 'bg-green-50' : 'bg-blue-50';
    const titleColor  = sectionColor === 'green' ? 'text-green-700' : 'text-blue-700';
    const inputBorder = sectionColor === 'green' ? 'border-green-300 focus:ring-green-500 focus:border-green-500' : 'border-blue-300 focus:ring-blue-500 focus:border-blue-500';
    const subtitleColor = sectionColor === 'green' ? 'text-green-500' : 'text-blue-500';
    return `
    <div class="mt-3 ${bgColor} ${borderColor} border rounded-lg p-3">
      <p class="text-[11px] font-bold ${titleColor} uppercase tracking-widest mb-2.5">${sectionTitle}</p>
      <p class="text-[10px] ${subtitleColor} mb-2">請填入查詢條件後點擊「撈取與預覽樣本」</p>
      <div class="space-y-2.5">
        ${flds.map(f => `
          <div>
            <label class="text-[11px] font-bold text-slate-600 uppercase tracking-widest mb-1 block">
              ${_esc(f.label || f.name)}${f.required ? ' <span class="text-red-500">*</span>' : ' <span class="text-slate-400">(選填)</span>'}
            </label>
            <input id="${idPrefix}${_esc(f.name)}"
                   type="${f.type === 'number' ? 'number' : 'text'}"
                   placeholder="${_esc(f.description || f.name)}"
                   value="${f.default_value !== undefined && f.default_value !== null ? _esc(String(f.default_value)) : ''}"
                   class="w-full bg-white border ${inputBorder} rounded-md px-3 py-2 text-sm
                          font-medium text-slate-800 shadow-sm focus:outline-none
                          focus:ring-2 transition-shadow">
          </div>`).join('')}
      </div>
    </div>`;
  };

  const dsName = ds?.name || mcp.name;
  const fetchSection  = _renderFields(fields, 'sk-mcp-param-', `🔑 系統 MCP 查詢參數 — ${_esc(dsName)}`, 'blue');
  const manualSection = _renderFields(manualParams, 'sk-mcp-manual-', `⚙️ MCP 運算參數 — ${_esc(mcp.name)}`, 'green');

  if (!fetchSection && !manualSection) {
    hint.innerHTML = noScriptBanner + '<div class="mt-2 text-xs text-slate-400 italic">此 MCP 無需額外查詢參數</div>';
    return;
  }
  hint.innerHTML = noScriptBanner + fetchSection + manualSection;
}

// Open the MCP Builder and load the specified MCP for editing
window._openMcpBuilderForId = async function(mcpId) {
  // Switch to MCP Builder view
  switchView('mcp');
  await new Promise(r => setTimeout(r, 300));
  const mcp = _mcpDefs.find(m => m.id === mcpId);
  if (mcp) _nbOpenEditor(mcpId);
};

// ── Fetch & Preview for the Skill editor's L3 MCP card ────────
async function _skFetchPreview() {
  const mcpId = parseInt(document.getElementById('sk-edit-mcp-select')?.value) || null;
  // Look in both custom and system lists
  const mcp = mcpId ? (_mcpDefs.find(m => m.id === mcpId) || _dataSubjects.find(m => m.id === mcpId)) : null;
  if (!mcp) { alert('請先選擇 MCP'); return; }

  // Resolve data source: system MCP = itself; custom MCP = look up parent system MCP
  const isSysMcp = mcp.mcp_type === 'system';
  let ds = isSysMcp ? mcp : (_dataSubjects.find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id)) || null);
  // Fallback: old custom MCPs have data_subject_id (IDs 1-5) pointing to old data_subjects table.
  // _dataSubjects now holds system MCPs (IDs 6+). Resolve by name via legacy API.
  if (!ds && !isSysMcp && mcp.data_subject_id) {
    try {
      const oldDs = await _api('GET', `/data-subjects/${mcp.data_subject_id}`);
      if (oldDs?.name) ds = _dataSubjects.find(d => d.name === oldDs.name) || null;
    } catch {}
  }
  if (!ds) { alert('此 Custom MCP 未綁定 System MCP，請先在 MCP Builder 設定資料來源'); return; }

  const rawInputSchema = typeof ds.input_schema === 'string' ? JSON.parse(ds.input_schema || '{}') : (ds.input_schema || {});
  const fields = rawInputSchema?.fields || [];
  const formParams = {};
  for (const f of fields) {
    const el = document.getElementById(`sk-mcp-param-${f.name}`);
    if (el && el.value.trim()) formParams[f.name] = el.value.trim();
  }
  _skMcpSampleParams = formParams;

  const drEl  = document.getElementById('sk-data-review');
  const frEl  = document.getElementById('sk-format-review');
  if (drEl) drEl.innerHTML = '<p class="text-xs text-slate-400 italic p-3 animate-pulse">撈取中…</p>';
  document.getElementById('sk-data-review-details')?.setAttribute('open', '');
  document.getElementById('sk-format-review-details')?.setAttribute('open', '');

  try {
    const rawApiConfig = typeof ds.api_config === 'string' ? JSON.parse(ds.api_config || '{}') : (ds.api_config || {});
    const rawUrl = rawApiConfig?.endpoint_url || '';
    if (!rawUrl) throw new Error('System MCP 沒有設定 API endpoint');
    const path = rawUrl.replace(/^\/api\/v1/, '');
    const method = (rawApiConfig?.method || 'GET').toUpperCase();
    const qp = new URLSearchParams(formParams);
    const fullPath = method === 'GET' ? `${path}?${qp}` : path;
    const token = localStorage.getItem('token') || sessionStorage.getItem('token');
    const resp = await fetch(`/api/v1${fullPath}`, {
      method,
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: method !== 'GET' ? JSON.stringify(formParams) : undefined,
    });
    const json = await resp.json();
    const rows = Array.isArray(json) ? json
      : (json.data ? (Array.isArray(json.data) ? json.data : [json.data]) : [json]);
    if (drEl) _nbRenderDataGrid(drEl, rows, '無資料回傳');
    if (frEl) {
      const schema = mcp.output_schema || ds.output_schema || _nbInferSchemaFromRows(rows);
      _nbRenderSchemaGrid(frEl, schema);
    }
  } catch(e) {
    if (drEl) drEl.innerHTML = `<p class="text-xs text-red-500 p-3">撈取失敗：${_esc(e.message)}</p>`;
  }
}

// ── Render Skill diagnosis in right panel ────────────────────
function _skRenderDiagnosis(liveResult) {
  const resultEl = document.getElementById('sk-skill-result');
  const cardEl   = document.getElementById('sk-skill-diagnosis-card');
  if (!resultEl || !cardEl) return;
  const status  = liveResult?.status || 'UNKNOWN';
  const diagMsg = liveResult?.diagnosis_message || '診斷完成。';
  const probObj = liveResult?.problem_object;
  const isAbn   = status === 'ABNORMAL';
  const statusBadge = isAbn
    ? `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-red-100 border border-red-300 text-red-700 font-bold text-xs">⚠ ABNORMAL</span>`
    : status === 'NORMAL'
    ? `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-emerald-100 border border-emerald-300 text-emerald-700 font-bold text-xs">✓ NORMAL</span>`
    : `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-slate-100 border border-slate-300 text-slate-500 font-bold text-xs">— ${_esc(status)}</span>`;
  const probHtml = probObj && typeof probObj === 'object' && Object.keys(probObj).length
    ? `<div class="mt-1 space-y-1">` + Object.entries(probObj).map(([k, v]) =>
        `<div class="flex gap-2 text-xs"><span class="text-slate-500 min-w-24 font-medium">${_esc(k)}：</span><span class="text-slate-700 font-semibold">${_esc(String(v))}</span></div>`
      ).join('') + `</div>`
    : `<p class="text-xs text-slate-400 italic mt-1">無異常物件</p>`;
  const cardBg = isAbn ? 'bg-red-50 border border-red-200 border-l-4 border-l-red-500'
               : status === 'NORMAL' ? 'bg-emerald-50 border border-emerald-200 border-l-4 border-l-emerald-500'
               : 'bg-slate-50 border border-slate-200 border-l-4 border-l-slate-400';
  const msgColor = isAbn ? 'text-red-900' : status === 'NORMAL' ? 'text-emerald-900' : 'text-slate-700';
  cardEl.innerHTML = `
    <div class="${cardBg} rounded-xl p-4">
      <div class="flex items-center gap-2 mb-3">${statusBadge}<span class="text-xs text-slate-500 font-medium">${_esc(liveResult?.skillName || 'Skill')}</span></div>
      <p class="text-sm ${msgColor} leading-relaxed mb-3 font-medium">${_esc(diagMsg)}</p>
      <div class="text-[11px] font-bold uppercase tracking-widest mb-1.5 ${isAbn ? 'text-red-500' : 'text-emerald-600'}">異常物件</div>
      ${probHtml}
      ${isAbn && liveResult?.expertAction ? `<div class="mt-3 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5"><p class="text-[11px] font-bold text-amber-700 uppercase tracking-widest mb-1">↳ 專家建議處置</p><p class="text-sm text-amber-800">${_esc(liveResult.expertAction)}</p></div>` : ''}
    </div>
    ${liveResult?.generated_code ? `
    <div class="mt-3">
      <p class="text-[11px] font-bold text-slate-500 uppercase tracking-widest cursor-pointer hover:text-purple-600 select-none flex items-center gap-1"
         onclick="this.nextElementSibling.classList.toggle('hidden')">
        🐍 生成的 Python 診斷函式 <span class="text-slate-400 normal-case font-normal">(點擊展開 / 收起)</span>
      </p>
      <pre class="hidden mt-1 bg-slate-900 text-green-300 text-xs rounded-lg px-3 py-3 overflow-x-auto overflow-y-scroll whitespace-pre-wrap max-h-[480px] leading-relaxed">${_esc(liveResult.generated_code)}</pre>
    </div>` : ''}`;
  resultEl.classList.remove('hidden');
}

// ── Render MCP evidence in right panel ────────────────────────
function _skRenderMcpEvidence(result) {
  const resultEl = document.getElementById('sk-mcp-result');
  if (!resultEl) return;
  resultEl.classList.remove('hidden');
  _skSwitchMcpTab('charting');
  const outputData = result.output_data || result;
  const uiRender   = outputData.ui_render || outputData.ui_render_config || {};
  const charts     = uiRender.charts || (uiRender.chart_data ? [uiRender.chart_data] : []);
  const dataset    = outputData.dataset || [];
  const rawDataset = outputData._raw_dataset || [];

  const chartEl = document.getElementById('sk-mcp-tab-charting');
  if (chartEl) {
    if (charts.length) {
      chartEl.innerHTML = '';
      charts.forEach(chartJson => {
        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'height:380px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;margin-bottom:8px;';
        chartEl.appendChild(wrapper);
        try {
          const figData = typeof chartJson === 'string' ? JSON.parse(chartJson) : chartJson;
          const figLayout = figData.layout || {};
          const mergedMargin = Object.assign({ l: 50, r: 20, t: 40, b: 40 }, figLayout.margin || {});
          if (figLayout.title && mergedMargin.t < 55) mergedMargin.t = 55;
          const hasHorizLegend = figLayout.legend?.orientation === 'h';
          if (hasHorizLegend && mergedMargin.b < 100) mergedMargin.b = 100;
          const legendOverride = hasHorizLegend ? { legend: { ...figLayout.legend, y: -0.28, x: 0, xanchor: 'left' } } : {};
          Plotly.newPlot(wrapper, figData.data || [], { ...figLayout,
            paper_bgcolor: '#f8fafc', plot_bgcolor: '#ffffff',
            font: { color: '#334155', size: 11 }, margin: mergedMargin, ...legendOverride }, { responsive: true });
        } catch(e) { wrapper.innerHTML = `<p class="text-xs text-red-500 p-3">圖表渲染失敗：${_esc(e.message)}</p>`; }
      });
    } else {
      chartEl.innerHTML = `<div class="flex items-center justify-center h-24 text-slate-400 text-sm">無圖表資料</div>`;
    }
  }
  const sumEl = document.getElementById('sk-mcp-tab-summary');
  if (sumEl) _nbRenderDataGrid(sumEl, dataset, '無摘要資料');
  const rawEl = document.getElementById('sk-mcp-tab-raw');
  if (rawEl) _nbRenderDataGrid(rawEl, Array.isArray(rawDataset) ? rawDataset : (rawDataset ? [rawDataset] : []), '無原始資料');
}

// ── Try Run ───────────────────────────────────────────────────
async function _skTryRun() {
  const diagPrompt = document.getElementById('sk-edit-prompt')?.value?.trim();
  const mcpId = parseInt(document.getElementById('sk-edit-mcp-select')?.value) || null;
  if (!diagPrompt) { alert('請先填寫「異常判斷條件 (Diagnostic Prompt)」'); return; }
  if (!mcpId)      { alert('請先選擇 MCP'); return; }

  _skSwitchRightTab('logs');
  const runBtn = document.getElementById('sk-run-btn');
  const ph     = document.getElementById('sk-console-placeholder');
  const dot    = document.getElementById('sk-console-status-dot');
  if (runBtn) { runBtn.disabled = true; runBtn.textContent = '⏳ 執行中...'; }
  if (dot) dot.classList.remove('hidden');
  if (ph) ph.classList.add('hidden');
  document.getElementById('sk-exec-log')?.classList.remove('hidden');
  document.getElementById('sk-exec-log-lines').innerHTML = '';
  document.getElementById('sk-skill-result')?.classList.add('hidden');
  document.getElementById('sk-mcp-result')?.classList.add('hidden');

  try {
    const mcp = _mcpDefs.find(m => m.id === mcpId);
    if (!mcp) throw new Error(`找不到 MCP #${mcpId}`);
    _skLogLine('▶', '開始執行 Skill Try Run');
    _skLogLine('🔧', `使用 MCP：${mcp.name}`);

    // Step 1: run MCP to get fresh output
    let mcpTryResult = null;
    let ds = (mcp.system_mcp_id || mcp.data_subject_id) ? _dataSubjects.find(d => d.id === (mcp.system_mcp_id || mcp.data_subject_id)) : null;
    // Fallback: legacy MCPs use old data_subject_id — resolve by name
    if (!ds && mcp.data_subject_id) {
      try {
        const oldDs = await _api('GET', `/data-subjects/${mcp.data_subject_id}`);
        if (oldDs?.name) ds = _dataSubjects.find(d => d.name === oldDs.name) || null;
      } catch {}
    }
    const rawUrl = ds?.api_config?.endpoint_url || (typeof ds?.api_config === 'string' ? JSON.parse(ds.api_config||'{}').endpoint_url : '');
    if (ds && rawUrl) {
      _skLogLine('📡', `正在撈取 System MCP 資料：${ds.name}…`);
      const formParams = _skMcpSampleParams || {};
      const method = (ds.api_config?.method || 'GET').toUpperCase();
      const path = rawUrl.replace(/^\/api\/v1/, '');
      const qp = new URLSearchParams(formParams);
      const fullPath = method === 'GET' && qp.toString() ? `${path}?${qp}` : path;
      try {
        const rawData = await _api(method, fullPath, method !== 'GET' ? formParams : undefined);
        _skLogLine('✓', 'System MCP 資料撈取成功', 'text-emerald-600');
        _skLogLine('⚙', `執行 MCP 處理…`);
        mcpTryResult = await _api('POST', `/mcp-definitions/${mcpId}/run-with-data`, { raw_data: rawData });
        _skTryRunMcpResult = mcpTryResult;
        _skLogLine('✓', 'MCP 執行完成', 'text-emerald-600');
      } catch(fetchErr) {
        const msg = fetchErr.message || '';
        if (msg.includes('尚未生成 Python 腳本') || msg.includes('processing_script')) {
          // MCP was never through Try Run in MCP Builder — surface actionable error
          throw new Error(`此 MCP「${mcp.name}」尚未完成 Try Run，無法執行。請先前往 MCP Builder 對該 MCP 執行試跑後再回此處。`);
        }
        _skLogLine('⚠', `MCP 執行失敗，改用已存樣本資料：${msg}`, 'text-amber-600');
      }
    }

    // Fallback to stored sample_output
    const mcpOutput = (mcpTryResult?.output_data) || mcp.sample_output || {};
    if (!mcpTryResult && Object.keys(mcpOutput).length === 0) {
      const hasScript = !!(mcp.processing_script && mcp.processing_script.trim());
      if (!hasScript)
        throw new Error(`此 MCP「${mcp.name}」尚未在 MCP Builder 完成 Try Run（無 Python 腳本）。\n請先前往 MCP Builder → 選擇此 MCP → 點擊 Try Run 完成試跑。`);
      throw new Error('MCP 無可用輸出資料，請先填入查詢參數並執行上方「撈取與預覽樣本」');
    }

    if (mcpTryResult) _skRenderMcpEvidence(mcpTryResult);

    // Step 2: generate Skill code diagnosis
    const probSubject = document.getElementById('sk-edit-subject')?.value?.trim() || null;
    const _mcpOutRows = (mcpOutput?.dataset || []).length || (Array.isArray(mcpOutput) ? mcpOutput.length : 0);
    _skLogLine('📊', `MCP 輸出：${_mcpOutRows} rows`);
    _skLogLine('🧠', 'LLM 生成 Skill 診斷 Python 程式碼…');
    const _t0Llm = Date.now();
    const result = await _api('POST', '/skill-definitions/generate-code-diagnosis', {
      diagnostic_prompt:  diagPrompt,
      problem_subject:    probSubject,
      mcp_sample_outputs: { [mcp.name]: mcpOutput },
      event_attributes:   [],
    });
    if (!result.success) throw new Error(result.error || 'Skill 診斷碼生成失敗');

    const _perfParts = [
      result.llm_elapsed_s  ? `🧠 LLM: ${result.llm_elapsed_s}s`  : `🧠 LLM: ${((Date.now()-_t0Llm)/1000).toFixed(1)}s`,
      result.exec_elapsed_s ? `⚙ Exec: ${result.exec_elapsed_s}s` : null,
      result.input_records  ? `📊 Input: ${result.input_records} rows` : null,
    ].filter(Boolean);
    _skLogLine('⏱', _perfParts.join(' | '), 'text-slate-500');
    _renderLearningEvents('sk-exec-log-lines', result.learning_events);

    const status = result.status || 'UNKNOWN';
    _skLogLine(status === 'ABNORMAL' ? '⚠' : '✓', `Skill 診斷完成 → ${status}`,
               status === 'ABNORMAL' ? 'text-red-600' : 'text-emerald-600');
    _skRenderDiagnosis({
      ...result,
      skillName:   document.getElementById('sk-edit-name')?.value?.trim() || 'Skill',
      expertAction: document.getElementById('sk-edit-action')?.value?.trim() || '',
    });

    // Auto-save last_diagnosis_result so list badge shows "🐍 Code 診斷"
    const skId = parseInt(document.getElementById('sk-edit-id')?.value) || null;
    // Capture mcp_sample_outputs for feedback re-run (set here so mcp is in scope)
    _skLastMcpSampleOutputs = { [mcp.name]: mcpOutput };

    if (result.generated_code) {
      _skLastDiagnosisResult = {
        status:              result.status              || 'ABNORMAL',
        diagnosis_message:   result.diagnosis_message   || '',
        problem_object:      result.problem_object       || {},
        generated_code:      result.generated_code,
        check_output_schema: result.check_output_schema  || null,
        timestamp:           new Date().toISOString(),
      };
      if (skId) {
        try {
          await _api('PATCH', `/skill-definitions/${skId}`, { last_diagnosis_result: _skLastDiagnosisResult });
          _skLogLine('💾', '診斷碼已自動儲存 ✓', 'text-emerald-600');
          // Update local cache so list badge refreshes without re-fetch
          const localSk = _skillDefs.find(s => s.id === skId);
          if (localSk) localSk.last_diagnosis_result = JSON.stringify(_skLastDiagnosisResult);
        } catch(saveErr) {
          _skLogLine('⚠', `自動儲存失敗：${saveErr.message}`, 'text-amber-600');
        }
      }
    }

    // Save state for Detail Inspector + Feedback
    _skLastMcpSampleOutputs = { [mcp.name]: mcpOutput };
    const skFeedbackSection = document.getElementById('sk-feedback-section');
    if (skFeedbackSection) skFeedbackSection.classList.remove('hidden');
    const skDetailBtn = document.getElementById('sk-detail-btn');
    if (skDetailBtn) skDetailBtn.classList.remove('hidden');

    _skLogLine('✓', 'Try Run 完成 — 切換至報告…', 'text-emerald-600');
    setTimeout(() => _skSwitchRightTab('report'), 700);

  } catch(e) {
    _skLogLine('✗', `執行失敗：${e.message}`, 'text-red-600');
    if (ph) {
      ph.classList.remove('hidden');
      ph.innerHTML = `<div class="text-center"><p class="text-red-600 font-semibold text-sm mb-1">✗ 執行失敗</p><p class="text-red-500 text-xs">${_esc(e.message)}</p></div>`;
    }
  } finally {
    if (runBtn) { runBtn.disabled = false; runBtn.textContent = '▶ Try Run'; }
    if (dot) dot.classList.add('hidden');
  }
}

// ── AgenticRawEditor (PRD v12.5 §4.5.1) ─────────────────────────────────

let _skRawTimer = null;

/**
 * Toggle between Visual form mode and ⌨️ Raw Markdown editor mode.
 * @param {'visual'|'raw'} mode
 */
function _skSetMode(mode) {
  const isRaw = mode === 'raw';
  const leftPanel = document.getElementById('sk-builder-left');
  const rawPanel  = document.getElementById('sk-raw-panel');
  if (!leftPanel || !rawPanel) return;

  leftPanel.classList.toggle('hidden', isRaw);
  rawPanel.classList.toggle('hidden', !isRaw);
  rawPanel.classList.toggle('flex', isRaw);

  const btnVisual = document.getElementById('sk-mode-visual');
  const btnRaw    = document.getElementById('sk-mode-raw');
  if (btnVisual) btnVisual.className = isRaw
    ? 'px-3 py-1.5 rounded-md text-slate-500 hover:text-slate-700 transition-all'
    : 'px-3 py-1.5 rounded-md bg-white text-purple-700 shadow-sm transition-all';
  if (btnRaw) btnRaw.className = isRaw
    ? 'px-3 py-1.5 rounded-md bg-slate-700 text-purple-300 shadow-sm transition-all'
    : 'px-3 py-1.5 rounded-md text-slate-500 hover:text-slate-700 transition-all';

  if (isRaw) {
    const ta = document.getElementById('sk-raw-textarea');
    if (ta) ta.value = _skGenerateRawMarkdown();
  }
}

/**
 * Generate OpenClaw-compatible Markdown from current form field values.
 * Mirrors the format produced by backend agent_router._build_tool_markdown().
 */
function _skGenerateRawMarkdown() {
  const skillId = document.getElementById('sk-edit-id')?.value || '';
  const name    = document.getElementById('sk-edit-name')?.value  || '';
  const desc    = document.getElementById('sk-edit-desc')?.value  || '';
  const prompt  = document.getElementById('sk-edit-prompt')?.value || '';
  const subject = document.getElementById('sk-edit-subject')?.value || '';
  const action  = document.getElementById('sk-edit-action')?.value || '';
  const apiPath = skillId
    ? `/api/v1/execute/skill/${skillId}`
    : '/api/v1/execute/skill/{skill_id}';

  return [
    '---',
    `name: ${name}`,
    `description: 本技能是一套完整的自動化診斷管線。${desc}`,
    '---',
    '## 1. 執行規劃與優先級 (Planning Guidance)',
    '- **優先使用**：當意圖符合時，直接呼叫本技能。絕對不要要求使用者先提供 raw_data。',
    '',
    '## 2. 依賴參數與介面 (Interface)',
    `- API: \`POST ${apiPath}\``,
    '- ⚠️ **邊界鐵律**: 呼叫 API 後，僅允許讀取 `llm_readable_data`。絕對禁止解析 `ui_render_payload`。',
    '',
    '## 3. 判斷邏輯與防呆處置 (Reasoning Rules)',
    '請嚴格遵循以下 `<rules>` 標籤內的指示撰寫最終報告：',
    '<rules>',
    `  <condition>${prompt}</condition>`,
    `  <target_extraction>${subject}</target_extraction>`,
    '  <expert_action>',
    '    ⚠️ 若狀態為 ABNORMAL，必須強制在報告結尾附加處置建議：',
    `    Action: ${action}`,
    '  </expert_action>',
    '</rules>',
  ].join('\n');
}

/** Debounce handler for the raw textarea — triggers two-way sync after 600ms. */
function _skRawDebounce() {
  clearTimeout(_skRawTimer);
  _skRawTimer = setTimeout(_skSyncFromRaw, 600);
}

/**
 * Parse the raw Markdown textarea and sync extracted values back to the form.
 * Two-way binding: Markdown → form fields.
 */
function _skSyncFromRaw() {
  const md = document.getElementById('sk-raw-textarea')?.value || '';

  const _extract = (pattern, flags) => {
    const m = md.match(flags ? new RegExp(pattern, flags) : new RegExp(pattern));
    return m ? m[1].trim() : null;
  };

  const nameVal  = _extract('^name:\\s*(.+)$', 'm');
  const descVal  = _extract('^description:\\s*本技能是一套完整的自動化診斷管線。(.*)$', 'm')
                || _extract('^description:\\s*(.+)$', 'm');
  const condVal  = _extract('<condition>([\\s\\S]*?)<\\/condition>');
  const subjVal  = _extract('<target_extraction>([\\s\\S]*?)<\\/target_extraction>');

  // expert_action: find "Action: ..." inside the block
  const actBlockM = md.match(/<expert_action>([\s\S]*?)<\/expert_action>/);
  let actionVal = null;
  if (actBlockM) {
    const actLineM = actBlockM[1].match(/Action:\s*([\s\S]*?)$/m);
    actionVal = actLineM ? actLineM[1].trim() : actBlockM[1].trim();
  }

  const set = (id, val) => { if (val !== null) { const el = document.getElementById(id); if (el) el.value = val; } };
  set('sk-edit-name',    nameVal);
  set('sk-edit-desc',    descVal);
  set('sk-edit-prompt',  condVal);
  set('sk-edit-subject', subjVal);
  set('sk-edit-action',  actionVal);
}

/** Apply raw Markdown changes to form and switch back to Visual mode. */
function _skApplyRaw() {
  _skSyncFromRaw();
  _skSetMode('visual');
}

// ── Save Skill ───────────────────────────────────────────────
async function _skSave() {
  const id   = parseInt(document.getElementById('sk-edit-id')?.value) || null;
  const name = document.getElementById('sk-edit-name')?.value?.trim();
  if (!name) { alert('請填寫 Skill 名稱'); return; }

  const mcpId = parseInt(document.getElementById('sk-edit-mcp-select')?.value) || null;
  const payload = {
    name,
    description:       document.getElementById('sk-edit-desc')?.value?.trim() || '',
    diagnostic_prompt: document.getElementById('sk-edit-prompt')?.value?.trim() || null,
    problem_subject:   document.getElementById('sk-edit-subject')?.value?.trim() || null,
    human_recommendation: document.getElementById('sk-edit-action')?.value?.trim() || null,
  };
  if (mcpId) {
    // Merge into mcp_ids (single MCP)
    payload.mcp_id = mcpId;
  }
  // Include last_diagnosis_result from current session Try Run
  if (_skLastDiagnosisResult) {
    payload.last_diagnosis_result = _skLastDiagnosisResult;
  }

  try {
    if (id) {
      await _api('PATCH', `/skill-definitions/${id}`, payload);
    } else {
      await _api('POST', '/skill-definitions', payload);
    }
    alert(`Skill「${name}」已儲存`);
    _skBackToList();
  } catch(e) {
    alert(`儲存失敗：${e.message}`);
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// MCP BUILDER — Full-page L/R Editor (Change C)
// ══════════════════════════════════════════════════════════════════════════════

let _mceRightTab = 'logs';
let _mceCurrentMcp = null;  // full MCP object loaded in editor (null = new MCP)
let _mceLastTryRunResult = null;  // MCPTryRunResponse from latest try-run (for Detail Inspector + Feedback)
let _mceLastRawData = null;       // raw_data used in latest run (for feedback re-run)

// ── Tab switching ─────────────────────────────────────────────
function _mceSwitchRightTab(tab) {
  _mceRightTab = tab;
  ['logs', 'report'].forEach(t => {
    document.getElementById(`mce-rtab-${t}`)?.classList.toggle('hidden', t !== tab);
    const btn = document.getElementById(`mce-rtab-btn-${t}`);
    if (btn) btn.className = t === tab
      ? 'px-5 py-3 text-xs font-bold text-blue-700 border-b-2 border-blue-600 transition-colors'
      : 'px-5 py-3 text-xs font-medium text-slate-500 border-b-2 border-transparent hover:text-slate-700 transition-colors';
  });
  // Feedback bar only shows when on Report tab AND a result exists
  const fb = document.getElementById('mce-feedback-section');
  if (fb && !fb.classList.contains('hidden') === false) {
    // if already hidden (no result yet), keep hidden regardless of tab
  } else if (fb && _mceLastTryRunResult) {
    fb.classList.toggle('hidden', tab !== 'report');
  }
}

function _mceSwitchMcpTab(tab) {
  ['charting', 'summary', 'raw'].forEach(t => {
    const btn = document.getElementById(`mce-tab-${t}`);
    const content = document.getElementById(`mce-mcp-tab-${t}`);
    if (btn) btn.className = `text-xs px-4 py-2 border-b-2 transition-colors ` +
      (t === tab ? 'text-emerald-700 border-emerald-600 font-bold' : 'text-slate-500 border-transparent hover:text-slate-700 font-medium');
    content?.classList.toggle('hidden', t !== tab);
  });
}

function _mceLogLine(icon, text, colorOrType = 'text-slate-600') {
  _consoleLog('mce-exec-log-lines', icon, text, _colorToType(colorOrType));
}

// ── Open / close editor ───────────────────────────────────────
async function _mcpOpenEditor(id, draftData) {
  if (_dataSubjects.length === 0) _dataSubjects = await _api('GET', '/mcp-definitions?type=system') || [];

  // Switch to editor state
  document.getElementById('mce-list-state')?.classList.add('hidden');
  const editor = document.getElementById('mcp-editor');
  if (editor) { editor.classList.remove('hidden'); editor.classList.add('flex'); }

  // Reset right panel
  _mceSwitchRightTab('logs');
  document.getElementById('mce-exec-log')?.classList.add('hidden');
  document.getElementById('mce-exec-log-lines').innerHTML = '';
  const ph = document.getElementById('mce-console-placeholder');
  if (ph) {
    ph.classList.remove('hidden');
    ph.innerHTML = `
      <svg class="w-10 h-10 mb-3 opacity-25" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
              d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
      </svg>
      <p class="text-sm font-medium text-slate-500">點擊 ▶ Try Run 執行 MCP 加工</p>
      <p class="text-xs mt-1 text-slate-400">先填寫左側 MCP 設定後再執行</p>`;
  }
  document.getElementById('mce-mcp-result')?.classList.add('hidden');

  // Populate System MCP dropdown
  const dsSel = document.getElementById('mce-edit-ds');
  if (dsSel) {
    dsSel.innerHTML = '<option value="">— 請選擇 —</option>' +
      _dataSubjects.map(d => `<option value="${d.id}">${_esc(d.name)}</option>`).join('');
  }

  if (!id) {
    // New MCP (possibly pre-filled from agent draft)
    _mceCurrentMcp = null;
    const isDraft = !!draftData;
    document.getElementById('mcp-editor-title').textContent = isDraft ? '草稿審核 — 新增 MCP' : '新增 MCP';
    document.getElementById('mce-edit-id').value = '';
    document.getElementById('mce-edit-name').value    = draftData?.name || '';
    document.getElementById('mce-edit-desc').value    = draftData?.description || '';
    document.getElementById('mce-edit-intent').value  = draftData?.processing_intent || '';
    document.getElementById('mce-edit-sample-form').innerHTML = '';
    if (dsSel) {
      // Try system_mcp_id first (numeric ID), then data_subject (name or id)
      const systemMcpId = draftData?.system_mcp_id;
      const dsRef = systemMcpId || draftData?.data_subject;
      if (dsRef) {
        const ds = typeof dsRef === 'number'
          ? _dataSubjects.find(d => d.id === dsRef)
          : _dataSubjects.find(d => d.name === dsRef || String(d.id) === String(dsRef));
        if (ds) { dsSel.value = ds.id; _mceOnDsChange(); }
        else dsSel.value = '';
      } else {
        dsSel.value = '';
      }
    }
    if (isDraft && draftData._draft_id) {
      document.getElementById('mcp-editor').dataset.draftId = draftData._draft_id;
    }
    return;
  }

  // Load existing MCP
  let mcp = _mcpDefs.find(m => m.id === id) || await _api('GET', `/mcp-definitions/${id}`);
  _mceCurrentMcp = mcp;
  document.getElementById('mcp-editor-title').textContent = mcp?.name || `MCP #${id}`;
  document.getElementById('mce-edit-id').value = id;
  document.getElementById('mce-edit-name').value = mcp?.name || '';
  document.getElementById('mce-edit-desc').value = mcp?.description || '';
  document.getElementById('mce-edit-intent').value = mcp?.processing_intent || '';

  // Resolve system_mcp_id — prefer the direct FK; fall back to name-matching via old data_subject
  let resolvedDsId = mcp?.system_mcp_id || null;
  if (!resolvedDsId && mcp?.data_subject_id) {
    try {
      const oldDs = await _api('GET', `/data-subjects/${mcp.data_subject_id}`);
      if (oldDs?.name) {
        const matched = _dataSubjects.find(d => d.name === oldDs.name);
        if (matched) resolvedDsId = matched.id;
      }
    } catch {}
  }
  if (dsSel && resolvedDsId) {
    dsSel.value = resolvedDsId;
    _mceOnDsChange();
  }
}

function _mcpBackToList() {
  document.getElementById('mcp-editor')?.classList.add('hidden');
  document.getElementById('mcp-editor')?.classList.remove('flex');
  const backBtn = document.getElementById('mcp-back-btn');
  if (backBtn) backBtn.textContent = '← MCP 列表';
  // If opened from Agent draft, return to chat instead of MCP list
  if (window._draftReturnView) {
    const target = window._draftReturnView;
    window._draftReturnView = null;
    switchView(target);
    return;
  }
  document.getElementById('mce-list-state')?.classList.remove('hidden');
  _loadMcpDefs();
}

// ── DS change → render sample form ───────────────────────────
function _mceOnDsChange() {
  const dsId = parseInt(document.getElementById('mce-edit-ds')?.value) || null;
  const ds = dsId ? _dataSubjects.find(d => d.id === dsId) : null;
  const formEl = document.getElementById('mce-edit-sample-form');
  if (!formEl) return;
  if (!ds) { formEl.innerHTML = ''; return; }
  const fields = ds.input_schema?.fields || [];
  if (!fields.length) { formEl.innerHTML = ''; return; }
  formEl.innerHTML = `
    <div class="bg-blue-50 border border-blue-200 rounded-lg p-3">
      <p class="text-[11px] font-bold text-blue-700 uppercase tracking-widest mb-2.5">System MCP 查詢參數</p>
      <div class="space-y-2.5">
        ${fields.map(f => `
          <div>
            <label class="text-[11px] font-bold text-slate-500 uppercase tracking-widest mb-1 block">
              ${_esc(f.label || f.name)}${f.required ? ' <span class="text-red-500">*</span>' : ''}
            </label>
            <input id="mce-ds-param-${_esc(f.name)}"
                   type="${f.type === 'number' ? 'number' : 'text'}"
                   placeholder="${_esc(f.description || f.name)}"
                   value="${f.default_value !== undefined && f.default_value !== null ? _esc(String(f.default_value)) : ''}"
                   class="w-full bg-white border border-slate-300 rounded-md px-3 py-2 text-sm
                          font-medium text-slate-800 shadow-sm focus:outline-none
                          focus:ring-2 focus:ring-blue-500 transition-shadow">
          </div>`).join('')}
      </div>
    </div>`;
}

// ── Fetch & Preview for MCP editor ───────────────────────────
async function _mceFetchPreview() {
  const dsId = parseInt(document.getElementById('mce-edit-ds')?.value) || null;
  const ds = dsId ? _dataSubjects.find(d => d.id === dsId) : null;
  if (!ds) { alert('請先選擇 Data Subject'); return; }

  const fields = ds.input_schema?.fields || [];
  const formParams = {};
  for (const f of fields) {
    const el = document.getElementById(`mce-ds-param-${f.name}`);
    if (el && el.value.trim()) formParams[f.name] = el.value.trim();
  }

  const drEl  = document.getElementById('mce-data-review');
  const frEl  = document.getElementById('mce-format-review');
  if (drEl) drEl.innerHTML = '<p class="text-xs text-slate-400 italic p-3 animate-pulse">撈取中…</p>';
  document.getElementById('mce-data-review-details')?.setAttribute('open', '');
  document.getElementById('mce-format-review-details')?.setAttribute('open', '');

  try {
    const rawUrl = ds.api_config?.endpoint_url || '';
    if (!rawUrl) throw new Error('System MCP 沒有設定 API endpoint');
    const path = rawUrl.replace(/^\/api\/v1/, '');
    const method = (ds.api_config?.method || 'GET').toUpperCase();
    const qp = new URLSearchParams(formParams);
    const fullPath = method === 'GET' ? `${path}?${qp}` : path;
    const token = localStorage.getItem('token') || sessionStorage.getItem('token');
    const resp = await fetch(`/api/v1${fullPath}`, {
      method,
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: method !== 'GET' ? JSON.stringify(formParams) : undefined,
    });
    const json = await resp.json();
    const rows = Array.isArray(json) ? json
      : (json.data ? (Array.isArray(json.data) ? json.data : [json.data]) : [json]);
    if (drEl) _nbRenderDataGrid(drEl, rows, '無資料回傳');
    if (frEl) _nbRenderSchemaGrid(frEl, ds.output_schema || _nbInferSchemaFromRows(rows));
  } catch(e) {
    if (drEl) drEl.innerHTML = `<p class="text-xs text-red-500 p-3">撈取失敗：${_esc(e.message)}</p>`;
  }
}

// ── Try Run (generate script + execute) ───────────────────────
async function _mcpTryRun() {
  const dsId   = parseInt(document.getElementById('mce-edit-ds')?.value) || null;
  const intent = document.getElementById('mce-edit-intent')?.value?.trim();
  if (!dsId)   { alert('請先選擇 System MCP'); return; }
  if (!intent) { alert('請先填寫加工意圖 (Processing Intent)'); return; }

  _mceSwitchRightTab('logs');
  const runBtn = document.getElementById('mce-run-btn');
  const ph     = document.getElementById('mce-console-placeholder');
  const dot    = document.getElementById('mce-console-status-dot');
  if (runBtn) { runBtn.disabled = true; runBtn.textContent = '⏳ 執行中...'; }
  if (dot) dot.classList.remove('hidden');
  if (ph) ph.classList.add('hidden');
  document.getElementById('mce-exec-log')?.classList.remove('hidden');
  document.getElementById('mce-exec-log-lines').innerHTML = '';
  document.getElementById('mce-mcp-result')?.classList.add('hidden');

  try {
    const ds = _dataSubjects.find(d => d.id === dsId);
    if (!ds) throw new Error('找不到所選 System MCP');

    _mceLogLine('▶', '開始執行 MCP Try Run');

    // Collect form params and fetch sample data
    let sampleData = null;
    let formParams = {};
    const rawUrl = ds.api_config?.endpoint_url || '';
    if (rawUrl) {
      _mceLogLine('📡', `正在撈取 System MCP 資料：${ds.name}…`);
      const fields = ds.input_schema?.fields || [];
      for (const f of fields) {
        const el = document.getElementById(`mce-ds-param-${f.name}`);
        if (el && el.value.trim()) formParams[f.name] = el.value.trim();
      }
      const method = (ds.api_config?.method || 'GET').toUpperCase();
      const path = rawUrl.replace(/^\/api\/v1/, '');
      const qp = new URLSearchParams(formParams);
      const fullPath = method === 'GET' && qp.toString() ? `${path}?${qp}` : path;
      sampleData = await _api(method, fullPath, method !== 'GET' ? formParams : undefined);
      _mceLogLine('✓', '樣本資料撈取成功', 'text-emerald-600');
    }

    // If MCP already has a processing_script (e.g., promoted from analyze_data),
    // execute it directly via run-with-data — skip LLM generation entirely.
    const mcpId = parseInt(document.getElementById('mce-edit-id')?.value) || null;
    const hasScript = !!(mcpId && _mceCurrentMcp?.processing_script);
    let result;
    if (hasScript) {
      _mceLogLine('⚡', '已有 processing_script — 直接執行（跳過 LLM）', 'text-blue-500');
      // Pass form params as raw_data — backend re-fetches dataset and runs existing script
      result = await _api('POST', `/mcp-definitions/${mcpId}/run-with-data`, {
        raw_data: formParams,
      });
      // Backend returns script=obj.processing_script; guard just in case
      if (result && !result.script) result = { ...result, script: _mceCurrentMcp.processing_script };
    } else {
      _mceLogLine('⚙', 'LLM 生成 MCP 處理腳本並沙箱執行中…');
      result = await _api('POST', '/mcp-definitions/try-run', {
        processing_intent: intent,
        system_mcp_id:     dsId,
        sample_data:       sampleData,
      });
    }

    // Capture raw data for feedback re-run
    _mceLastRawData = formParams;

    if (!result.success) {
      _mceLogLine('✗', `執行失敗：${result.error || '未知錯誤'}`, 'text-red-600');
      if (ph) {
        ph.classList.remove('hidden');
        ph.innerHTML = `<div class="text-center"><p class="text-red-600 font-semibold text-sm mb-1">✗ 執行失敗</p><p class="text-red-500 text-xs">${_esc(result.error_analysis || result.error || '')}</p></div>`;
      }
      return;
    }

    _mceLogLine('✓', 'MCP 執行完成', 'text-emerald-600');
    _renderLearningEvents('mce-exec-log-lines', result.learning_events);

    // Show Python script in terminal (stored script for run-with-data; LLM-generated for try-run)
    if (result.script) {
      const lines = document.getElementById('mce-exec-log-lines');
      if (lines) {
        const scriptBlock = document.createElement('div');
        scriptBlock.className = 'mt-3';
        const scriptLabel = hasScript ? '📦 已儲存的 Python 腳本（直接執行）' : '🐍 生成的 Python 腳本';
        scriptBlock.innerHTML = `
          <div class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">${scriptLabel}</div>
          <pre class="bg-slate-50 border border-slate-200 rounded p-3 text-[11px] text-slate-700 overflow-x-auto overflow-y-scroll whitespace-pre-wrap leading-relaxed max-h-[500px]">${_esc(result.script)}</pre>`;
        lines.appendChild(scriptBlock);
      }
    }

    // Update Data / Format Review
    const outputData = result.output_data || {};
    const rawEl = document.getElementById('mce-data-review');
    const schemaEl = document.getElementById('mce-format-review');
    if (rawEl) {
      const rows = Array.isArray(outputData._raw_dataset) ? outputData._raw_dataset
                 : Array.isArray(outputData.dataset) ? outputData.dataset : [];
      _nbRenderDataGrid(rawEl, rows, '無原始資料');
      document.getElementById('mce-data-review-details')?.setAttribute('open', '');
    }
    if (schemaEl && result.output_schema) {
      _nbRenderSchemaGrid(schemaEl, result.output_schema);
      document.getElementById('mce-format-review-details')?.setAttribute('open', '');
    }

    // Render MCP evidence in right panel
    const resultEl = document.getElementById('mce-mcp-result');
    if (resultEl) {
      resultEl.classList.remove('hidden');
      _mceSwitchMcpTab('charting');
      const uiRender = outputData.ui_render || outputData.ui_render_config || {};
      const charts   = uiRender.charts || (uiRender.chart_data ? [uiRender.chart_data] : []);
      const dataset  = Array.isArray(outputData.dataset) ? outputData.dataset : [];

      const chartEl = document.getElementById('mce-mcp-tab-charting');
      if (chartEl) {
        if (charts.length) {
          chartEl.innerHTML = '';
          charts.forEach(chartJson => {
            const wrapper = document.createElement('div');
            wrapper.style.cssText = 'height:380px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;margin-bottom:8px;';
            chartEl.appendChild(wrapper);
            try {
              const figData = typeof chartJson === 'string' ? JSON.parse(chartJson) : chartJson;
              const figLayout = figData.layout || {};
              const mergedMargin = Object.assign({ l: 50, r: 20, t: 40, b: 40 }, figLayout.margin || {});
              if (figLayout.title && mergedMargin.t < 55) mergedMargin.t = 55;
              const hasHorizLegend = figLayout.legend?.orientation === 'h';
              if (hasHorizLegend && mergedMargin.b < 100) mergedMargin.b = 100;
              const legendOverride = hasHorizLegend ? { legend: { ...figLayout.legend, y: -0.28, x: 0, xanchor: 'left' } } : {};
              Plotly.newPlot(wrapper, figData.data || [], { ...figLayout,
                paper_bgcolor: '#f8fafc', plot_bgcolor: '#ffffff',
                font: { color: '#334155', size: 11 }, margin: mergedMargin, ...legendOverride }, { responsive: true });
            } catch(e) { wrapper.innerHTML = `<p class="text-xs text-red-500 p-3">圖表渲染失敗：${_esc(e.message)}</p>`; }
          });
        } else {
          chartEl.innerHTML = `<div class="flex items-center justify-center h-24 text-slate-400 text-sm">無圖表資料</div>`;
        }
      }
      const sumEl = document.getElementById('mce-mcp-tab-summary');
      if (sumEl) _nbRenderDataGrid(sumEl, dataset, '無摘要資料');
      const rawTabEl = document.getElementById('mce-mcp-tab-raw');
      const rawRows = outputData._raw_dataset || [];
      if (rawTabEl) _nbRenderDataGrid(rawTabEl, Array.isArray(rawRows) ? rawRows : [], '無原始資料');
    }

    _mceLogLine('✓', 'Try Run 完成 — 切換至報告…', 'text-emerald-600');

    // Save result state for Detail Inspector + Feedback
    _mceLastTryRunResult = result;
    const feedbackSection = document.getElementById('mce-feedback-section');
    if (feedbackSection) feedbackSection.classList.remove('hidden');
    const detailBtn = document.getElementById('mce-detail-btn');
    if (detailBtn) detailBtn.classList.remove('hidden');

    // Auto-save script to MCP if editing existing (skip if run-with-data — script already in DB)
    if (mcpId && result.script && !hasScript) {
      try {
        await _api('PATCH', `/mcp-definitions/${mcpId}`, {
          processing_script: result.script,
          output_schema:     result.output_schema || null,
          ui_render_config:  result.ui_render_config || null,
          input_definition:  result.input_definition || null,
          sample_output:     outputData,
        });
        _mceLogLine('💾', 'MCP 腳本已自動儲存', 'text-emerald-600');
      } catch(_) {}
    }

    setTimeout(() => _mceSwitchRightTab('report'), 700);

  } catch(e) {
    _mceLogLine('✗', `執行失敗：${e.message}`, 'text-red-600');
    if (ph) {
      ph.classList.remove('hidden');
      ph.innerHTML = `<div class="text-center"><p class="text-red-600 font-semibold text-sm mb-1">✗ 執行失敗</p><p class="text-red-500 text-xs">${_esc(e.message)}</p></div>`;
    }
  } finally {
    if (runBtn) { runBtn.disabled = false; runBtn.textContent = '▶ Try Run'; }
    if (dot) dot.classList.add('hidden');
  }
}

// ── Save MCP ─────────────────────────────────────────────────
async function _mcpSave() {
  const id   = parseInt(document.getElementById('mce-edit-id')?.value) || null;
  const name = document.getElementById('mce-edit-name')?.value?.trim();
  const dsId = parseInt(document.getElementById('mce-edit-ds')?.value) || null;
  if (!name) { alert('請填寫 MCP 名稱'); return; }
  if (!dsId) { alert('請選擇 System MCP'); return; }

  const payload = {
    name,
    description:       document.getElementById('mce-edit-desc')?.value?.trim() || '',
    processing_intent: document.getElementById('mce-edit-intent')?.value?.trim() || '',
  };

  try {
    if (id) {
      await _api('PATCH', `/mcp-definitions/${id}`, payload);
    } else {
      await _api('POST', '/mcp-definitions', { ...payload, system_mcp_id: dsId });
    }
    alert(`MCP「${name}」已儲存`);
    _mcpBackToList();
  } catch(e) {
    alert(`儲存失敗：${e.message}`);
  }
}


// ══════════════════════════════════════════════════════════════════════════════
// EVENT → SKILL LINK BUILDER  (V13 Final Feature)
// ══════════════════════════════════════════════════════════════════════════════

let _elMode        = 'event_skill_link';  // 'event_skill_link' | 'routine_check'
let _elEtMode      = 'existing';          // 'existing' | 'new'
let _elSkillMode   = 'existing';          // 'existing' | 'new'
let _elRcSkillMode = 'existing';          // 'existing' | 'new'
let _elDraftId     = null;               // set when opened from a draft

/** Called by switchView('event-link-builder') */
async function _elInitView() {
  _elMode        = 'event_skill_link';
  _elEtMode      = 'existing';
  _elSkillMode   = 'existing';
  _elRcSkillMode = 'existing';

  _elApplyModeUI();

  // Populate dropdowns in parallel
  try {
    const [ets, skills, mcps] = await Promise.all([
      _api('GET', '/event-types'),
      _api('GET', '/skill-definitions'),
      _api('GET', '/mcp-definitions?type=custom'),
    ]);
    _elPopulateEtSelect(ets || []);
    _elPopulateSkillSelects(skills || []);
    _elPopulateMcpSelects(mcps || []);
  } catch(e) {
    console.error('_elInitView error:', e);
  }
}

function _elSetMode(mode) {
  _elMode = mode;
  _elApplyModeUI();
}

function _elApplyModeUI() {
  const isLink = _elMode === 'event_skill_link';
  document.getElementById('el-form-event-skill')?.classList.toggle('hidden', !isLink);
  document.getElementById('el-form-routine')?.classList.toggle('hidden', isLink);

  const btnLink    = document.getElementById('el-mode-event-skill');
  const btnRoutine = document.getElementById('el-mode-routine');
  if (btnLink) btnLink.className = `w-full text-left px-3 py-3 rounded-lg border text-xs font-semibold transition-colors ${isLink ? 'border-indigo-300 bg-indigo-50 text-indigo-700' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'}`;
  if (btnRoutine) btnRoutine.className = `w-full text-left px-3 py-3 rounded-lg border text-xs font-semibold transition-colors ${!isLink ? 'border-indigo-300 bg-indigo-50 text-indigo-700' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'}`;
}

function _elSetEtMode(mode) {
  _elEtMode = mode;
  const ex = document.getElementById('el-et-existing-row');
  const nw = document.getElementById('el-et-new-row');
  ex?.classList.toggle('hidden', mode === 'new');
  nw?.classList.toggle('hidden', mode === 'existing');
  document.getElementById('el-et-mode-existing').className = `text-xs px-3 py-1.5 rounded-lg font-semibold transition-colors ${mode === 'existing' ? 'bg-indigo-600 text-white' : 'bg-white border border-slate-300 text-slate-600 hover:bg-slate-50'}`;
  document.getElementById('el-et-mode-new').className = `text-xs px-3 py-1.5 rounded-lg font-semibold transition-colors ${mode === 'new' ? 'bg-indigo-600 text-white' : 'bg-white border border-slate-300 text-slate-600 hover:bg-slate-50'}`;
}

function _elSetSkillMode(mode) {
  _elSkillMode = mode;
  document.getElementById('el-skill-existing-row')?.classList.toggle('hidden', mode === 'new');
  document.getElementById('el-skill-new-row')?.classList.toggle('hidden', mode === 'existing');
  document.getElementById('el-skill-mode-existing').className = `text-xs px-3 py-1.5 rounded-lg font-semibold transition-colors ${mode === 'existing' ? 'bg-indigo-600 text-white' : 'bg-white border border-slate-300 text-slate-600 hover:bg-slate-50'}`;
  document.getElementById('el-skill-mode-new').className = `text-xs px-3 py-1.5 rounded-lg font-semibold transition-colors ${mode === 'new' ? 'bg-indigo-600 text-white' : 'bg-white border border-slate-300 text-slate-600 hover:bg-slate-50'}`;
}

function _elSetRcSkillMode(mode) {
  _elRcSkillMode = mode;
  document.getElementById('el-rc-skill-existing-row')?.classList.toggle('hidden', mode === 'new');
  document.getElementById('el-rc-skill-new-row')?.classList.toggle('hidden', mode === 'existing');
  document.getElementById('el-rc-skill-mode-existing').className = `text-xs px-3 py-1.5 rounded-lg font-semibold transition-colors ${mode === 'existing' ? 'bg-indigo-600 text-white' : 'bg-white border border-slate-300 text-slate-600 hover:bg-slate-50'}`;
  document.getElementById('el-rc-skill-mode-new').className = `text-xs px-3 py-1.5 rounded-lg font-semibold transition-colors ${mode === 'new' ? 'bg-indigo-600 text-white' : 'bg-white border border-slate-300 text-slate-600 hover:bg-slate-50'}`;
}

function _elPopulateEtSelect(ets) {
  const sel = document.getElementById('el-et-select');
  if (!sel) return;
  sel.innerHTML = '<option value="">-- 選擇 EventType --</option>' +
    ets.map(e => `<option value="${e.id}">${_escapeHtml(e.name)}</option>`).join('');
}

function _elPopulateSkillSelects(skills) {
  const opts = '<option value="">-- 選擇 Skill --</option>' +
    skills.map(s => `<option value="${s.id}">${_escapeHtml(s.name)}</option>`).join('');
  const s1 = document.getElementById('el-skill-select');
  const s2 = document.getElementById('el-rc-skill-select');
  if (s1) s1.innerHTML = opts;
  if (s2) s2.innerHTML = opts;
}

function _elPopulateMcpSelects(mcps) {
  const opts = '<option value="">-- 選擇 MCP --</option>' +
    mcps.map(m => `<option value="${m.id}">${_escapeHtml(m.name)}</option>`).join('');
  ['el-skill-new-mcp', 'el-rc-skill-new-mcp'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = opts;
  });
}

/** Build payload for event_skill_link mode */
function _elBuildEventSkillPayload() {
  const etId   = _elEtMode === 'existing' ? parseInt(document.getElementById('el-et-select')?.value || '0') : null;
  const etName = _elEtMode === 'new'      ? (document.getElementById('el-et-new-name')?.value || '').trim() : null;
  let skillId   = null;
  let skillDraft = null;
  if (_elSkillMode === 'existing') {
    skillId = parseInt(document.getElementById('el-skill-select')?.value || '0') || null;
  } else {
    const mcpId = parseInt(document.getElementById('el-skill-new-mcp')?.value || '0') || null;
    skillDraft = {
      name: (document.getElementById('el-skill-new-name')?.value || '').trim(),
      description: (document.getElementById('el-skill-new-desc')?.value || '').trim(),
      mcp_ids: mcpId ? [mcpId] : [],
      diagnostic_prompt: (document.getElementById('el-skill-new-prompt')?.value || '').trim(),
    };
  }
  return { event_type_id: etId || null, event_type_name: etName || '', skill_id: skillId, skill_draft: skillDraft };
}

/** Build payload for routine_check mode */
function _elBuildRoutinePayload() {
  const name     = (document.getElementById('el-rc-name')?.value || '').trim();
  const interval = document.getElementById('el-rc-interval')?.value || '1h';
  let skillId    = null;
  let skillDraft = null;
  if (_elRcSkillMode === 'existing') {
    skillId = parseInt(document.getElementById('el-rc-skill-select')?.value || '0') || null;
  } else {
    const mcpId = parseInt(document.getElementById('el-rc-skill-new-mcp')?.value || '0') || null;
    skillDraft = {
      name: (document.getElementById('el-rc-skill-new-name')?.value || '').trim(),
      mcp_ids: mcpId ? [mcpId] : [],
      diagnostic_prompt: (document.getElementById('el-rc-skill-new-prompt')?.value || '').trim(),
    };
  }
  let skillInput = {};
  try { skillInput = JSON.parse(document.getElementById('el-rc-skill-input')?.value || '{}'); } catch {}
  const scheduleTime = document.getElementById('el-rc-schedule-time')?.value || '';
  const expireAt = document.getElementById('el-rc-expire-at')?.value || '';
  const genEventName = document.getElementById('el-rc-generated-event-name')?.value?.trim() || '';
  return {
    name,
    skill_id: skillId,
    skill_draft: skillDraft,
    schedule_interval: interval,
    skill_input: skillInput,
    ...(scheduleTime && interval === 'daily' ? { schedule_time: scheduleTime } : {}),
    ...(expireAt ? { expire_at: expireAt } : {}),
    ...(genEventName ? { generated_event_name: genEventName } : {}),
  };
}

function _elShowResult(msg, isError = false) {
  const el = document.getElementById('el-result-banner');
  if (!el) return;
  el.className = `mt-2 p-3 rounded-lg text-xs ${isError ? 'bg-red-50 border border-red-200 text-red-700' : 'bg-green-50 border border-green-200 text-green-700'}`;
  el.textContent = msg;
  el.classList.remove('hidden');
}

/** Directly publish to registry */
async function _elSave() {
  try {
    if (_elMode === 'event_skill_link') {
      const p = _elBuildEventSkillPayload();
      if (!p.event_type_id && !p.event_type_name) { alert('請選擇或輸入 EventType'); return; }
      if (!p.skill_id && !p.skill_draft?.name)     { alert('請選擇或填寫 Skill'); return; }
      // Create draft then immediately publish
      const draft = await _api('POST', '/agent/draft/event_skill_link', p);
      const draftId = draft.draft_id || draft.data?.draft_id;
      if (!draftId) throw new Error('無法取得草稿 ID');
      await _api('POST', `/agent/draft/${draftId}/publish`);
      _elShowResult('✅ Event→Skill 連結已發佈！');
    } else {
      const p = _elBuildRoutinePayload();
      if (!p.name) { alert('請填寫排程名稱'); return; }
      if (!p.skill_id && !p.skill_draft?.name) { alert('請選擇或填寫 Skill'); return; }
      const draft = await _api('POST', '/agent/draft/routine_check', p);
      const draftId = draft.draft_id || draft.data?.draft_id;
      if (!draftId) throw new Error('無法取得草稿 ID');
      await _api('POST', `/agent/draft/${draftId}/publish`);
      _elShowResult('✅ 排程巡檢已發佈！');
    }
  } catch(e) {
    _elShowResult('❌ 發佈失敗：' + e.message, true);
  }
}

/** Save as agent draft (for review) */
async function _elSaveDraft() {
  try {
    let draft;
    if (_elMode === 'event_skill_link') {
      const p = _elBuildEventSkillPayload();
      draft = await _api('POST', '/agent/draft/event_skill_link', p);
    } else {
      const p = _elBuildRoutinePayload();
      draft = await _api('POST', '/agent/draft/routine_check', p);
    }
    const draftId = draft.draft_id || draft.data?.draft_id;
    _elShowResult(`📋 草稿已建立 (${draftId?.slice(0, 8) || '?'}…)，可在 Agent 對話中審核發佈。`);
  } catch(e) {
    _elShowResult('❌ 草稿儲存失敗：' + e.message, true);
  }
}

/** Pre-fill form from agent draft payload (called by _openDraftEditor) */
async function _elPreFillFromDraft(payload, draftId, draftType) {
  _elDraftId = draftId;

  // Show draft banner
  const banner = document.getElementById('el-draft-banner');
  const draftDisplay = document.getElementById('el-draft-id-display');
  if (banner) banner.classList.remove('hidden');
  if (draftDisplay) draftDisplay.textContent = draftId || '';

  // Determine mode from explicit draftType, then fall back to payload fields
  const isEventSkillLink = draftType === 'event_skill_link'
    || (!draftType && (payload.event_type_id || payload.event_type_name));

  if (isEventSkillLink) {
    _elSetMode('event_skill_link');

    if (payload.event_type_id) {
      _elSetEtMode('existing');
      const sel = document.getElementById('el-et-select');
      if (sel) sel.value = String(payload.event_type_id);
    } else if (payload.event_type_name) {
      _elSetEtMode('new');
      const inp = document.getElementById('el-et-new-name');
      if (inp) inp.value = payload.event_type_name;
    }

    if (payload.skill_id) {
      _elSetSkillMode('existing');
      const sel = document.getElementById('el-skill-select');
      if (sel) sel.value = String(payload.skill_id);
    } else if (payload.skill_draft) {
      _elSetSkillMode('new');
      const sd = payload.skill_draft;
      _setVal('el-skill-new-name', sd.name || '');
      _setVal('el-skill-new-desc', sd.description || '');
      _setVal('el-skill-new-prompt', sd.diagnostic_prompt || '');
      if (sd.mcp_ids?.[0]) {
        const sel = document.getElementById('el-skill-new-mcp');
        if (sel) sel.value = String(sd.mcp_ids[0]);
      }
    }
  } else {
    _elSetMode('routine_check');

    _setVal('el-rc-name', payload.name || '');
    const ivSel = document.getElementById('el-rc-interval');
    if (ivSel && payload.schedule_interval) ivSel.value = payload.schedule_interval;
    if (payload.skill_input) {
      _setVal('el-rc-skill-input', JSON.stringify(payload.skill_input, null, 2));
    }

    if (payload.skill_id) {
      _elSetRcSkillMode('existing');
      const sel = document.getElementById('el-rc-skill-select');
      if (sel) sel.value = String(payload.skill_id);
    } else if (payload.skill_draft) {
      _elSetRcSkillMode('new');
      const sd = payload.skill_draft;
      _setVal('el-rc-skill-new-name', sd.name || '');
      _setVal('el-rc-skill-new-prompt', sd.diagnostic_prompt || '');
      if (sd.mcp_ids?.[0]) {
        const sel = document.getElementById('el-rc-skill-new-mcp');
        if (sel) sel.value = String(sd.mcp_ids[0]);
      }
    }
    // Pre-fill new fields
    if (payload.schedule_time) {
      _setVal('el-rc-schedule-time', payload.schedule_time);
      _elOnRcIntervalChange(document.getElementById('el-rc-interval')?.value || '');
    }
    if (payload.expire_at) _setVal('el-rc-expire-at', payload.expire_at);
    if (payload.generated_event_name) _setVal('el-rc-generated-event-name', payload.generated_event_name);
    // Trigger event preview update
    setTimeout(_elUpdateRcEventPreview, 100);
  }
}

function _setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function _elOnRcIntervalChange(val) {
  const row = document.getElementById('el-rc-schedule-time-row');
  if (row) row.classList.toggle('hidden', val !== 'daily');
}

function _elUpdateRcEventPreview() {
  const previewEl = document.getElementById('el-rc-event-preview');
  if (!previewEl) return;
  const skillId = parseInt(document.getElementById('el-rc-skill-select')?.value || '0') || null;
  const scheduleName = document.getElementById('el-rc-name')?.value?.trim() || '';
  const skill = skillId ? (_skillDefs || []).find(s => s.id === skillId) : null;
  if (!skill) {
    previewEl.innerHTML = '<div class="border border-slate-200 rounded-lg p-3 bg-slate-50/40 text-xs text-slate-400">← 請先選擇 Skill，系統將自動預覽異常時觸發的 Event 格式</div>';
    return;
  }
  previewEl.innerHTML = _buildRcEventPreview(skill, scheduleName, null)
    .replace('id="rc-event-name"', 'id="el-rc-generated-event-name"');
}


// ══════════════════════════════════════════════════════════════
// MOCK DATA STUDIO
// ══════════════════════════════════════════════════════════════

let _mdsList = [];
let _mdsEditingId = null;
let _mdsGenerating = false;
let _mdsRunning = false;
let _mdsFormCache = {}; // { [id|'new']: unsaved form values }

function _mdsCaptureFormState() {
  const key = _mdsEditingId != null ? _mdsEditingId : 'new';
  _mdsFormCache[key] = {
    name:    document.getElementById('mds-name')?.value ?? null,
    desc:    document.getElementById('mds-desc')?.value ?? null,
    genDesc: document.getElementById('mds-gen-desc')?.value ?? null,
    params:  document.getElementById('mds-gen-params')?.value ?? null,
    code:    document.getElementById('mds-python-code')?.value ?? null,
    schema:  document.getElementById('mds-input-schema')?.value ?? null,
    active:  document.getElementById('mds-active')?.checked ?? null,
  };
}

function _mdsRestoreFormState() {
  const key = _mdsEditingId != null ? _mdsEditingId : 'new';
  const s = _mdsFormCache[key];
  if (!s) return;
  const setVal = (id, val) => { if (val !== null && val !== undefined) { const el = document.getElementById(id); if (el) el.value = val; } };
  const setBool = (id, val) => { if (val !== null && val !== undefined) { const el = document.getElementById(id); if (el) el.checked = val; } };
  setVal('mds-name', s.name);
  setVal('mds-desc', s.desc);
  setVal('mds-gen-desc', s.genDesc);
  setVal('mds-gen-params', s.params);
  setVal('mds-python-code', s.code);
  setVal('mds-input-schema', s.schema);
  setBool('mds-active', s.active);
}

function _mdsToast(msg, type = 'success') {
  const colors = { success: 'bg-emerald-600', error: 'bg-red-600', info: 'bg-blue-600' };
  const t = document.createElement('div');
  t.className = `fixed bottom-6 right-6 ${colors[type] || 'bg-slate-700'} text-white text-sm font-medium px-5 py-3 rounded-xl shadow-lg z-[200]`;
  t.style.transition = 'opacity 0.4s';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 400); }, 2800);
}

async function _mdsLoadList() {
  const listEl = document.getElementById('mds-list');
  if (!listEl) return;
  listEl.innerHTML = '<div class="text-center text-slate-400 py-12 text-sm">載入中...</div>';
  try {
    const r = await _api('GET', '/mock-data');
    _mdsList = Array.isArray(r) ? r : (r.data || r || []);
    _mdsRenderList();
  } catch (e) {
    listEl.innerHTML = `<div class="text-center text-red-500 py-12 text-sm">載入失敗: ${e.message}</div>`;
  }
}

function _mdsRenderList() {
  const listEl = document.getElementById('mds-list');
  if (!listEl) return;
  if (!_mdsList.length) {
    listEl.innerHTML = `
      <div class="text-center py-20">
        <div class="text-4xl mb-3">🧪</div>
        <p class="text-slate-500 text-sm">尚無 Mock 資料源</p>
        <p class="text-slate-400 text-xs mt-1">點擊「+ 新增 Mock 資料源」，用自然語言描述需求，AI 自動生成 Python 模擬邏輯</p>
      </div>`;
    return;
  }
  listEl.innerHTML = _mdsList.map(m => `
    <div class="bg-white border border-slate-200 rounded-xl p-4 flex items-start gap-4 hover:border-emerald-300 transition-colors">
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2">
          <span class="font-semibold text-sm text-slate-800">${m.name}</span>
          <span class="px-1.5 py-0.5 rounded text-[10px] font-medium ${m.is_active ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-slate-100 text-slate-500 border border-slate-200'}">
            ${m.is_active ? '● 啟用' : '○ 停用'}
          </span>
          ${m.python_code ? '<span class="px-1.5 py-0.5 rounded text-[10px] bg-blue-50 text-blue-600 border border-blue-200">有程式碼</span>' : '<span class="px-1.5 py-0.5 rounded text-[10px] bg-yellow-50 text-yellow-600 border border-yellow-200">⚠ 無程式碼</span>'}
        </div>
        <p class="text-xs text-slate-500 mt-1 line-clamp-1">${m.description || '(無說明)'}</p>
        <p class="text-[10px] text-slate-400 mt-1 font-mono">POST /api/v1/mock-data/${m.id}/run</p>
      </div>
      <div class="flex gap-2 flex-shrink-0">
        <button onclick="_mdsOpenEdit(${m.id})"
          class="text-xs px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-lg transition-colors">
          編輯
        </button>
        <button onclick="_mdsTestRun(${m.id})"
          class="text-xs px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition-colors">
          ▶ 試執行
        </button>
      </div>
    </div>`).join('');
}

function _mdsOpenCreate() {
  _mdsEditingId = null;
  openDrawer('mds-edit');
}

function _mdsOpenEdit(id) {
  _mdsEditingId = id;
  openDrawer('mds-edit');
}

// Called by renderDrawerContent dispatcher
function _mdsRenderDrawer() {
  const item = _mdsEditingId ? _mdsList.find(m => m.id === _mdsEditingId) : null;
  const title = item ? `編輯 Mock 資料源：${item.name}` : '新增 Mock 資料源';
  const hasCode = !!(item?.python_code);

  let inputSchemaVal = '';
  if (item?.input_schema) {
    try { inputSchemaVal = JSON.stringify(JSON.parse(item.input_schema), null, 2); }
    catch { inputSchemaVal = item.input_schema; }
  }

  // Inline preview (shown after generation or if sample_output exists)
  const previewHtml = item?.sample_output ? _mdsBuildInlinePreview(item.sample_output, item.id) : '';

  const body = `
    <div class="space-y-4">

      <!-- 名稱 + 啟用 -->
      <div class="flex gap-3 items-end">
        <div class="flex-1">
          <label class="label-sm">名稱 *</label>
          <input id="mds-name" type="text" class="input-field" value="${_esc(item?.name || '')}" placeholder="e.g. SPC_Mock_Data"/>
        </div>
        <label class="flex items-center gap-2 cursor-pointer mb-2">
          <input id="mds-active" type="checkbox" class="w-4 h-4 rounded" ${item?.is_active !== false ? 'checked' : ''}/>
          <span class="text-xs font-medium text-slate-600">啟用</span>
        </label>
      </div>

      <!-- 描述 + 生成按鈕 -->
      <div>
        <label class="label-sm">描述這份 Mock 資料 *
          <span class="font-normal text-slate-400 ml-1">— AI 依此生成 Python 腳本</span>
        </label>
        <textarea id="mds-gen-desc" rows="3" class="input-field font-normal text-sm resize-none"
          placeholder="e.g. Recipe offset 資料，包含 recipe_header 摘要列和 recipe_param 明細列，每個 recipe 約 25 個參數，其中 4 個異常"
          >${_esc(item?.description || '')}</textarea>
        <div class="flex gap-2 mt-2">
          <input id="mds-gen-params" type="text" class="input-field flex-1 text-xs"
            placeholder='測試參數（可選）：{"recipe_name": "rcp01"}'/>
          <button id="mds-gen-btn" onclick="_mdsGenAndPreview()"
            class="text-sm px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-semibold transition-colors whitespace-nowrap">
            ${hasCode ? '🔄 重新生成' : '🤖 AI 生成 + 預覽'}
          </button>
        </div>
      </div>

      <!-- 預覽結果（生成後顯示） -->
      <div id="mds-inline-result" class="${previewHtml ? '' : 'hidden'}">
        ${previewHtml}
      </div>

      <!-- 進階設定（折疊） -->
      <details class="border border-slate-200 rounded-lg overflow-hidden">
        <summary class="px-3 py-2 text-xs font-semibold text-slate-500 cursor-pointer hover:bg-slate-50 select-none">
          ⚙️ 進階設定${hasCode ? ' · <span class="text-emerald-600">✓ 已有程式碼</span>' : ''}
        </summary>
        <div class="p-3 space-y-3 border-t border-slate-200">
          <div>
            <label class="label-sm">Input Schema (JSON)</label>
            <textarea id="mds-input-schema" rows="3" class="input-field font-mono text-xs resize-none"
              placeholder='{"fields": [{"name": "lot_id", "type": "string", "required": true}]}'
              >${_esc(inputSchemaVal)}</textarea>
          </div>
          <div>
            <label class="label-sm flex justify-between">
              <span>Python 程式碼</span>
              <span class="font-normal text-slate-400">generate(params: dict) -> list</span>
            </label>
            <textarea id="mds-python-code" rows="12" class="input-field font-mono text-xs resize-none"
              style="background:#0f172a;color:#86efac;border-color:#334155"
              placeholder="def generate(params: dict) -> list:&#10;    ..."
              >${_esc(item?.python_code || '')}</textarea>
          </div>
        </div>
      </details>

    </div>
  `;

  const footer = `
    <button onclick="closeDrawer()" class="builder-btn-secondary text-sm px-4 py-2">取消</button>
    <button onclick="_mdsSave()" class="builder-btn-primary text-sm px-4 py-2">💾 儲存</button>
    ${hasCode ? `<button onclick="_mdsSaveAndTestRun()" class="text-sm px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl font-semibold">▶ 儲存並試執行</button>` : ''}
  `;

  _setDrawerContent(title, body, footer);
  requestAnimationFrame(_mdsRestoreFormState);
}

function _mdsBuildInlinePreview(sampleOutputJson, mockId) {
  let rows = [];
  try { rows = JSON.parse(sampleOutputJson); } catch { return ''; }
  if (!Array.isArray(rows) || !rows.length) return '';
  const preview = rows.slice(0, 5);
  const cols = Object.keys(preview[0]);
  const thead = `<tr>${cols.map(c => `<th class="px-2 py-1 text-left text-[10px] font-semibold text-slate-500 border-b border-slate-200 whitespace-nowrap">${_esc(c)}</th>`).join('')}</tr>`;
  const tbody = preview.map(row =>
    `<tr class="hover:bg-slate-50">${cols.map(c => {
      const v = row[c];
      const isAnomaly = row.anomaly_flag === true || row.out_of_spec === true ||
        (typeof v === 'number' && row.UCL !== undefined && (v > row.UCL || v < row.LCL));
      return `<td class="px-2 py-1 text-[10px] ${isAnomaly ? 'text-red-600 font-semibold' : 'text-slate-700'} border-b border-slate-100 whitespace-nowrap">${v ?? ''}</td>`;
    }).join('')}</tr>`
  ).join('');
  return `
    <div class="rounded-lg border border-emerald-200 bg-emerald-50/30 overflow-hidden">
      <div class="flex items-center justify-between px-3 py-2 bg-emerald-50 border-b border-emerald-200">
        <span class="text-xs font-semibold text-emerald-700">✅ 資料預覽（前 ${preview.length} 筆，共 ${rows.length} 筆）</span>
        ${mockId ? `<button onclick="_mdsShowPlayground(${mockId})" class="text-[10px] px-2 py-1 bg-purple-600 text-white rounded hover:bg-purple-500">🔬 設計 MCP 處理邏輯</button>` : ''}
      </div>
      <div class="overflow-auto max-h-48">
        <table class="w-full text-xs">
          <thead class="bg-slate-50 sticky top-0">${thead}</thead>
          <tbody>${tbody}</tbody>
        </table>
      </div>
    </div>`;
}

// Combined: auto-save → generate code → run → show inline preview
async function _mdsGenAndPreview() {
  if (_mdsGenerating) return;
  _mdsCaptureFormState();
  const desc = document.getElementById('mds-gen-desc')?.value?.trim();
  const name = document.getElementById('mds-name')?.value?.trim();
  if (!desc) { _mdsToast('請先填寫描述', 'error'); return; }
  if (!name) { _mdsToast('請先填寫名稱', 'error'); return; }

  const btn = document.getElementById('mds-gen-btn');
  const resultDiv = document.getElementById('mds-inline-result');
  _mdsGenerating = true;
  if (btn) { btn.disabled = true; btn.textContent = '⏳ AI 生成中...'; }
  if (resultDiv) { resultDiv.className = ''; resultDiv.innerHTML = '<div class="text-xs text-slate-400 animate-pulse py-2">⏳ AI 正在生成 Python 腳本...</div>'; }

  // Step 1: ensure record exists
  if (!_mdsEditingId) {
    const created = await _mdsSaveAndGetId();
    if (!created) { _mdsGenerating = false; if (btn) { btn.disabled = false; btn.textContent = '🤖 AI 生成 + 預覽'; } return; }
  }

  let sampleParams = null;
  try { sampleParams = JSON.parse(document.getElementById('mds-gen-params')?.value || 'null'); } catch {}

  try {
    // Step 2: generate code
    if (resultDiv) resultDiv.innerHTML = '<div class="text-xs text-slate-400 animate-pulse py-2">⏳ AI 生成程式碼中（約 15-30 秒）...</div>';
    const gr = await _api('POST', `/mock-data/${_mdsEditingId}/generate-code`, { description: desc, sample_params: sampleParams });
    const genItem = gr?.mock_data_source || gr?.data?.mock_data_source;
    if (genItem) {
      const idx = _mdsList.findIndex(m => m.id === _mdsEditingId);
      if (idx >= 0) _mdsList[idx] = genItem; else _mdsList.unshift(genItem);
      // Sync code/schema to advanced textareas if open
      const codeEl = document.getElementById('mds-python-code');
      if (codeEl && genItem.python_code) codeEl.value = genItem.python_code;
      const schemaEl = document.getElementById('mds-input-schema');
      if (schemaEl && genItem.input_schema) {
        try { schemaEl.value = JSON.stringify(JSON.parse(genItem.input_schema), null, 2); } catch { schemaEl.value = genItem.input_schema; }
      }
    }

    // Step 3: run to get real data
    if (resultDiv) resultDiv.innerHTML = '<div class="text-xs text-slate-400 animate-pulse py-2">▶ 執行 generate() 取得資料...</div>';
    const params = sampleParams || {};
    const rr = await _api('POST', `/mock-data/${_mdsEditingId}/run`, { params });
    const dataset = rr?.dataset || rr?.data?.dataset;
    const rows = Array.isArray(dataset) ? dataset : (dataset ? [dataset] : []);

    // Update cache + show preview
    const idx = _mdsList.findIndex(m => m.id === _mdsEditingId);
    if (idx >= 0) _mdsList[idx].sample_output = JSON.stringify(rows.slice(0, 20));
    if (resultDiv) {
      resultDiv.className = '';
      resultDiv.innerHTML = _mdsBuildInlinePreview(JSON.stringify(rows), _mdsEditingId);
    }
    // Refresh footer to show ▶ 儲存並試執行 button
    _mdsRenderDrawer();
    _mdsToast('✅ 生成完成！', 'success');
  } catch (e) {
    _mdsToast(`生成失敗: ${e.message}`, 'error');
    if (resultDiv) { resultDiv.className = ''; resultDiv.innerHTML = `<div class="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg p-3">❌ ${_esc(e.message)}</div>`; }
  } finally {
    _mdsGenerating = false;
    if (btn) { btn.disabled = false; btn.textContent = '🔄 重新生成'; }
  }
}

// Save then test run, show result inline
async function _mdsSaveAndTestRun() {
  await _mdsSave();
  if (!_mdsEditingId) return;
  const item = _mdsList.find(m => m.id === _mdsEditingId);
  if (!item) return;
  let params = {};
  try {
    const p = document.getElementById('mds-gen-params')?.value;
    if (p) params = JSON.parse(p);
  } catch {}
  _mdsToast('▶ 執行中...', 'info');
  try {
    const r = await _api('POST', `/mock-data/${_mdsEditingId}/run`, { params });
    const dataset = r?.dataset || r?.data?.dataset;
    const rows = Array.isArray(dataset) ? dataset : (dataset ? [dataset] : []);
    const idx = _mdsList.findIndex(m => m.id === _mdsEditingId);
    if (idx >= 0) _mdsList[idx].sample_output = JSON.stringify(rows.slice(0, 20));
    _mdsToast(`✅ 執行成功 — ${rows.length} 筆資料`, 'success');
    _mdsRenderDrawer();
  } catch (e) {
    _mdsToast(`執行失敗: ${e.message}`, 'error');
  }
}

function _mdsFormatJson(s) {
  try { return JSON.stringify(JSON.parse(s), null, 2); } catch { return s; }
}

function _mdsFormatJsonPreview(s, maxRows = 3) {
  try {
    const arr = JSON.parse(s);
    const preview = Array.isArray(arr) ? arr.slice(0, maxRows) : arr;
    return JSON.stringify(preview, null, 2);
  } catch { return s; }
}

// Quick Sample: ask LLM to generate sample rows directly as JSON (no Python code needed)
async function _mdsQuickSample() {
  _mdsCaptureFormState();
  const desc = document.getElementById('mds-gen-desc')?.value?.trim();
  if (!desc) { _mdsToast('請先填寫描述', 'error'); return; }
  if (!_mdsEditingId) {
    const name = document.getElementById('mds-name')?.value?.trim();
    if (!name) { _mdsToast('請先填寫名稱', 'error'); return; }
    const created = await _mdsSaveAndGetId();
    if (!created) return;
  }

  const btn = document.getElementById('mds-quick-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 生成中...'; }
  _mdsToast('📊 AI 正在生成假資料...', 'info');

  try {
    const r = await _api('POST', `/mock-data/${_mdsEditingId}/quick-sample`, { description: desc, count: 20 });
    const rows = r?.rows || r?.data?.rows || [];
    const cols = r?.columns || r?.data?.columns || (rows[0] ? Object.keys(rows[0]) : []);

    // Update list cache sample_output
    const idx = _mdsList.findIndex(m => m.id === _mdsEditingId);
    if (idx >= 0) _mdsList[idx].sample_output = JSON.stringify(rows.slice(0, 50));

    _mdsShowQuickSampleResult(rows, cols, desc);
  } catch (e) {
    _mdsToast(`預覽失敗: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '📊 預覽假資料'; }
  }
}

function _mdsShowQuickSampleResult(rows, cols, description) {
  if (!rows.length) { _mdsToast('LLM 未回傳資料', 'error'); return; }

  // Build table HTML (first 10 rows)
  const preview = rows.slice(0, 10);
  const thead = `<tr>${cols.map(c => `<th class="px-2 py-1 text-left text-[10px] font-semibold text-slate-500 border-b border-slate-200">${c}</th>`).join('')}</tr>`;
  const tbody = preview.map(row =>
    `<tr class="hover:bg-slate-50">${cols.map(c => {
      const v = row[c];
      const isNum = typeof v === 'number';
      const isOoc = isNum && (row.UCL !== undefined && v > row.UCL) || (row.LCL !== undefined && v < row.LCL);
      return `<td class="px-2 py-1 text-[10px] ${isOoc ? 'text-red-600 font-semibold' : 'text-slate-700'} border-b border-slate-100">${v ?? ''}</td>`;
    }).join('')}</tr>`
  ).join('');

  const tableHtml = `
    <div class="overflow-auto max-h-64 rounded-lg border border-slate-200">
      <table class="w-full text-xs">
        <thead class="bg-slate-50 sticky top-0">${thead}</thead>
        <tbody>${tbody}</tbody>
      </table>
    </div>
    <p class="text-[10px] text-slate-400 mt-1">顯示前 ${preview.length} 筆（共 ${rows.length} 筆） · 紅色 = OOC</p>
  `;

  _setDrawerContent(
    `📊 假資料預覽 — ${rows.length} 筆 (${cols.length} 欄)`,
    `<div class="space-y-4">
      <div class="p-3 bg-blue-50 border border-blue-200 rounded-xl">
        <p class="text-xs text-blue-700 font-medium">✅ AI 成功生成 ${rows.length} 筆假資料！</p>
        <p class="text-[10px] text-blue-500 mt-0.5">欄位：${cols.join(' · ')}</p>
      </div>
      ${tableHtml}
      <div class="p-3 bg-purple-50 border border-purple-200 rounded-xl">
        <p class="text-xs text-purple-700 font-semibold">🔬 下一步：模擬 MCP 處理</p>
        <p class="text-[10px] text-purple-500 mt-0.5">基於這份假資料，讓 AI 幫你設計計算邏輯與視覺化（等同 MCP Builder 的 try-run）</p>
      </div>
    </div>`,
    `<button onclick="_mdsOpenEdit(${_mdsEditingId})" class="builder-btn-secondary text-sm px-4 py-2">← 回到編輯</button>
     <button onclick="_mdsShowPlayground(${_mdsEditingId})" class="text-sm px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-xl font-semibold">🔬 模擬 MCP 處理</button>
     <button onclick="_mdsGenerateCodeFromPreview('${(description || '').replace(/'/g, "\\'")}'); _mdsOpenEdit(${_mdsEditingId})" class="builder-btn-primary text-sm px-4 py-2">🤖 生成 Python 程式碼</button>`
  );
}

async function _mdsGenerateCodeFromPreview(desc) {
  // Trigger generate-code using the cached description
  const descEl = document.getElementById('mds-gen-desc');
  if (descEl && desc) descEl.value = desc;
  await _mdsGenerateCode();
}

// Playground: show raw data + MCP-style design interface
async function _mdsShowPlayground(id) {
  _mdsCaptureFormState();
  const item = _mdsList.find(m => m.id === id) || { id, name: '', description: '' };
  let rows = [];
  let dataSource = '';

  // Prefer Python generate() over LLM quick-sample
  if (item.python_code) {
    _mdsToast('⏳ 執行 Python generate()...', 'info');
    try {
      // Use params from the gen-params field if still available in cache
      const cachedParams = _mdsFormCache[id]?.params;
      let params = {};
      if (cachedParams) { try { params = JSON.parse(cachedParams); } catch {} }
      const r = await _api('POST', `/mock-data/${id}/run`, { params });
      const dataset = r?.dataset || r?.data?.dataset;
      rows = Array.isArray(dataset) ? dataset : (dataset ? [dataset] : []);
      dataSource = '🐍 Python generate()';
      const idx = _mdsList.findIndex(m => m.id === id);
      if (idx >= 0) _mdsList[idx].sample_output = JSON.stringify(rows.slice(0, 50));
    } catch (e) {
      _mdsToast(`Python 執行失敗: ${e.message}，改用快速預覽`, 'error');
    }
  }

  // Fallback: sample_output cache
  if (!rows.length && item.sample_output) {
    try { rows = JSON.parse(item.sample_output); dataSource = '📋 快取資料'; } catch {}
  }

  // Last resort: quick-sample
  if (!rows.length) {
    _mdsToast('⏳ AI 生成假資料中...', 'info');
    try {
      const desc = item.description || '';
      const r = await _api('POST', `/mock-data/${id}/quick-sample`, { description: desc, count: 20 });
      rows = r?.rows || r?.data?.rows || [];
      dataSource = '🤖 AI 快速預覽';
      const idx = _mdsList.findIndex(m => m.id === id);
      if (idx >= 0) _mdsList[idx].sample_output = JSON.stringify(rows);
    } catch (e) {
      _mdsToast(`無法取得資料: ${e.message}`, 'error');
      return;
    }
  }

  const cols = rows.length > 0 ? Object.keys(rows[0]) : [];
  const rawJson = JSON.stringify(rows.slice(0, 5), null, 2);

  _setDrawerContent(
    `🔬 MCP 模擬沙盒 — ${item.name || 'Mock Data'}`,
    `<div class="space-y-4">
      <div class="p-3 bg-slate-800 rounded-xl">
        <div class="flex items-center justify-between mb-2">
          <p class="text-[10px] font-bold text-slate-300 uppercase tracking-widest">Raw Data (前 5 筆)</p>
          <span class="text-[10px] text-slate-400">${dataSource} · ${rows.length} 筆</span>
        </div>
        <pre class="text-green-300 font-mono text-[10px] overflow-auto max-h-40">${rawJson}</pre>
      </div>

      <div class="p-3 bg-amber-50 border border-amber-200 rounded-xl">
        <p class="text-xs font-semibold text-amber-800 mb-1">💬 告訴 AI 你想怎麼處理這份資料</p>
        <p class="text-[10px] text-amber-600 mb-2">例如：「計算每台機台的平均值，標示 OOC 點，畫出趨勢圖」</p>
        <textarea id="mds-playground-intent" rows="3" class="input-field text-sm resize-none"
          placeholder="計算統計摘要（mean, std, OOC count），並畫出 SPC 趨勢圖..."></textarea>
        <button id="mds-playground-btn" onclick="_mdsRunPlayground(${id})"
          class="mt-2 w-full text-sm py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-lg font-semibold transition-colors">
          🤖 AI 設計 MCP 處理邏輯 + 預覽圖表
        </button>
      </div>

      <div id="mds-playground-result" class="hidden"></div>
    </div>`,
    `<button onclick="_mdsOpenEdit(${id})" class="builder-btn-secondary text-sm px-4 py-2">← 回到編輯</button>
     <button onclick="_mdsPromoteToSystemMcp(${id})" class="text-sm px-3 py-2 bg-orange-600 hover:bg-orange-500 text-white rounded-xl font-semibold">⬆ 升級為 System MCP</button>
     <button onclick="_mdsSaveAsCustomMcp(${id})" class="builder-btn-primary text-sm px-4 py-2">💾 儲存為 Custom MCP</button>`
  );

  // Make drawer visible if not already
  document.getElementById('drawer-overlay')?.classList.remove('hidden');
  document.getElementById('drawer')?.classList.add('drawer-open');
}

async function _mdsRunPlayground(id) {
  const intent = document.getElementById('mds-playground-intent')?.value?.trim();
  if (!intent) { _mdsToast('請填寫處理意圖', 'error'); return; }
  const item = _mdsList.find(m => m.id === id);
  const btn = document.getElementById('mds-playground-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ AI 設計中...'; }

  let rows = [];
  if (item?.sample_output) {
    try { rows = JSON.parse(item.sample_output); } catch {}
  }

  try {
    // Use dedicated playground endpoint — no DataSubject DB lookup required
    const r = await _api('POST', `/mock-data/${id}/playground`, {
      processing_intent: intent,
      params: {},
    });

    const resultEl = document.getElementById('mds-playground-result');
    if (!resultEl) return;
    resultEl.classList.remove('hidden');

    // Check for failure
    if (r?.success === false || r?.data?.success === false) {
      const errMsg = r?.data?.error || r?.message || '未知錯誤';
      resultEl.innerHTML = `<div class="p-3 bg-red-50 border border-red-200 rounded-xl"><p class="text-xs font-semibold text-red-700">❌ 執行失敗</p><p class="text-[10px] text-red-500 mt-1 font-mono">${errMsg}</p></div>`;
      return;
    }

    // Show generated code + result
    const code = r?.script || r?.data?.script || '';
    const outputData = r?.output_data || r?.data?.output_data || {};
    const chartData = outputData?.ui_render?.chart_data
      || (outputData?.ui_render?.charts?.[0]) || null;
    const dataset = outputData?.dataset || [];

    // Build dataset table HTML
    let tableHtml = '';
    if (dataset.length > 0) {
      const cols = Object.keys(dataset[0]);
      tableHtml = `
        <div class="mt-2">
          <p class="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">
            輸出資料 (${dataset.length} 筆)
          </p>
          <div class="overflow-auto max-h-64 border border-slate-200 rounded-lg">
            <table class="text-[10px] w-full border-collapse">
              <thead class="bg-slate-100 sticky top-0">
                <tr>${cols.map(c => `<th class="px-2 py-1.5 text-left font-bold text-slate-600 border-b border-slate-200 whitespace-nowrap">${_esc(c)}</th>`).join('')}</tr>
              </thead>
              <tbody>
                ${dataset.map((row, i) => `
                  <tr class="${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}">
                    ${cols.map(c => {
                      const v = row[c];
                      const display = v === null || v === undefined ? '' : (typeof v === 'object' ? JSON.stringify(v) : String(v));
                      return `<td class="px-2 py-1 border-b border-slate-100 text-slate-700 whitespace-nowrap max-w-[200px] truncate" title="${_esc(display)}">${_esc(display)}</td>`;
                    }).join('')}
                  </tr>`).join('')}
              </tbody>
            </table>
          </div>
        </div>`;
    }

    resultEl.innerHTML = `
      <div class="space-y-3">
        <div class="p-3 bg-emerald-50 border border-emerald-200 rounded-xl">
          <p class="text-xs font-semibold text-emerald-700">✅ AI 設計完成！</p>
        </div>
        ${chartData ? `<div id="mds-pg-chart" class="bg-white border border-slate-200 rounded-xl p-2" style="height:300px"></div>` : ''}
        ${tableHtml}
        ${code ? `
        <details>
          <summary class="text-xs text-slate-500 cursor-pointer hover:text-slate-700">查看生成的 Processing Script</summary>
          <pre class="mt-2 bg-slate-900 text-green-300 rounded-lg p-3 text-[10px] font-mono overflow-auto max-h-48">${_esc(code)}</pre>
        </details>` : ''}
        <div id="mds-save-mcp-payload" class="hidden"
          data-intent="${(intent||'').replace(/"/g,'&quot;')}"
          data-code="${(code||'').replace(/"/g,'&quot;')}"
          data-mock-id="${id}"></div>
      </div>
    `;

    // Render chart if available
    if (chartData && window.Plotly) {
      try {
        const fig = typeof chartData === 'string' ? JSON.parse(chartData) : chartData;
        Plotly.react('mds-pg-chart', fig.data || [], fig.layout || {}, { responsive: true, displayModeBar: false });
      } catch {}
    }

    _mdsToast('✅ MCP 設計完成！', 'success');
  } catch (e) {
    _mdsToast(`設計失敗: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🤖 AI 設計 MCP 處理邏輯 + 預覽圖表'; }
  }
}

async function _mdsPromoteToSystemMcp(mockId) {
  _mdsToast('⬆ 升級為 System MCP 中...', 'info');
  try {
    const r = await _api('POST', `/mock-data/${mockId}/promote-to-system-mcp`, {});
    const d = r?.data || r;
    const updated = d?.updated;
    const name = d?.name || '';
    const sysId = d?.system_mcp_id;
    _mdsToast(
      updated
        ? `✅ System MCP「${name}」已更新 (id=${sysId})`
        : `✅ System MCP「${name}」建立成功 (id=${sysId})！可在 MCP Builder 中選用`,
      'success'
    );
    // Update list cache
    const idx = _mdsList.findIndex(m => m.id === mockId);
    if (idx >= 0) _mdsList[idx]._systemMcpId = sysId;
  } catch (e) {
    _mdsToast(`升級失敗: ${e.message}`, 'error');
  }
}

async function _mdsSaveAsCustomMcp(mockId) {
  const payloadEl = document.getElementById('mds-save-mcp-payload');
  if (!payloadEl) { _mdsToast('請先執行 AI 設計', 'error'); return; }
  const intent = payloadEl.dataset.intent;
  const code = payloadEl.dataset.code;
  const item = _mdsList.find(m => m.id === mockId);
  if (!intent || !code) { _mdsToast('請先執行 AI 設計', 'error'); return; }

  _mdsToast('💾 儲存 Custom MCP 中...', 'info');

  // This requires a System MCP to exist for this mock source
  // For now, navigate to MCP Builder with pre-filled data
  closeDrawer();
  switchView('mcp-builder');
  _mdsToast('✅ 請在 MCP Builder 中貼上意圖以完成設計', 'success');
}

async function _mdsGenerateCode() {
  if (_mdsGenerating) return;
  _mdsCaptureFormState();
  const descEl = document.getElementById('mds-gen-desc');
  const paramsEl = document.getElementById('mds-gen-params');
  const btn = document.getElementById('mds-gen-btn');
  const desc = descEl?.value?.trim();
  if (!desc) { _mdsToast('請先填寫描述', 'error'); return; }

  // If no id yet, we need to create first or generate on a temp basis
  if (!_mdsEditingId) {
    const name = document.getElementById('mds-name')?.value?.trim();
    if (!name) { _mdsToast('請先填寫名稱', 'error'); return; }
    // Auto-save to get an id
    const created = await _mdsSaveAndGetId();
    if (!created) return;
  }

  _mdsGenerating = true;
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 生成中...'; }

  let sampleParams = null;
  try { sampleParams = JSON.parse(paramsEl?.value || 'null'); } catch {}

  try {
    const r = await _api('POST', `/mock-data/${_mdsEditingId}/generate-code`, { description: desc, sample_params: sampleParams });
    const item = r?.mock_data_source || r?.data?.mock_data_source;
    if (item?.python_code) {
      const codeEl = document.getElementById('mds-python-code');
      if (codeEl) codeEl.value = item.python_code;
    }
    if (item?.input_schema) {
      const schemaEl = document.getElementById('mds-input-schema');
      if (schemaEl) {
        try { schemaEl.value = JSON.stringify(JSON.parse(item.input_schema), null, 2); }
        catch { schemaEl.value = item.input_schema; }
      }
    }
    // Update list cache
    const idx = _mdsList.findIndex(m => m.id === _mdsEditingId);
    if (idx >= 0) _mdsList[idx] = item;
    else _mdsList.unshift(item);

    _mdsToast('✨ AI 程式碼生成完成！請檢視後儲存', 'success');
    const sampleParamsResult = r?.sample_params || r?.data?.sample_params;
    if (sampleParamsResult) {
      const sp = JSON.stringify(sampleParamsResult);
      if (paramsEl) paramsEl.value = sp;
    }
  } catch (e) {
    _mdsToast(`生成失敗: ${e.message}`, 'error');
  } finally {
    _mdsGenerating = false;
    if (btn) { btn.disabled = false; btn.textContent = '🤖 AI 生成'; }
  }
}

async function _mdsSaveAndGetId() {
  const name = document.getElementById('mds-name')?.value?.trim();
  const genDesc = document.getElementById('mds-gen-desc')?.value?.trim();
  const desc = genDesc || document.getElementById('mds-desc')?.value?.trim() || '';
  if (!name) { _mdsToast('請填寫名稱', 'error'); return null; }
  try {
    const r = await _api('POST', '/mock-data', { name, description: desc, is_active: true });
    const item = r?.id ? r : r?.data;
    // Transfer any 'new' cache to the real id
    if (_mdsFormCache['new']) { _mdsFormCache[item.id] = _mdsFormCache['new']; delete _mdsFormCache['new']; }
    _mdsEditingId = item.id;
    _mdsList.unshift(item);
    return item;
  } catch (e) {
    _mdsToast(`建立失敗: ${e.message}`, 'error');
    return null;
  }
}

async function _mdsSave() {
  const name = document.getElementById('mds-name')?.value?.trim();
  // Prefer Step 1 AI-description textarea; fall back to the brief 說明 field
  const genDesc = document.getElementById('mds-gen-desc')?.value?.trim();
  const shortDesc = document.getElementById('mds-desc')?.value?.trim();
  const desc = genDesc || shortDesc || '';
  const isActive = document.getElementById('mds-active')?.checked ?? true;
  const inputSchema = document.getElementById('mds-input-schema')?.value?.trim() || null;
  const pythonCode = document.getElementById('mds-python-code')?.value?.trim() || null;

  if (!name) { _mdsToast('請填寫名稱', 'error'); return; }

  const payload = { name, description: desc, is_active: isActive, input_schema: inputSchema, python_code: pythonCode };

  try {
    let r;
    if (_mdsEditingId) {
      r = await _api('PATCH', `/mock-data/${_mdsEditingId}`, payload);
      const item = r?.id ? r : r?.data;
      const idx = _mdsList.findIndex(m => m.id === _mdsEditingId);
      if (idx >= 0) _mdsList[idx] = item;
    } else {
      r = await _api('POST', '/mock-data', payload);
      const item = r?.id ? r : r?.data;
      _mdsList.unshift(item);
    }
    _mdsToast('✅ 儲存成功', 'success');
    // Clear form cache on successful save
    delete _mdsFormCache[_mdsEditingId != null ? _mdsEditingId : 'new'];
    closeDrawer();
    _mdsRenderList();
  } catch (e) {
    _mdsToast(`儲存失敗: ${e.message}`, 'error');
  }
}

async function _mdsTestRun(id) {
  if (_mdsRunning) return;
  const item = _mdsList.find(m => m.id === id);
  if (!item) return;

  // Build params from input_schema
  let params = {};
  if (item.input_schema) {
    try {
      const schema = JSON.parse(item.input_schema);
      // Prompt user for required params if any
      const required = (schema.fields || []).filter(f => f.required);
      if (required.length > 0) {
        const paramsStr = prompt(
          `請輸入測試參數 JSON:\n必填欄位: ${required.map(f => f.name).join(', ')}\n\n範例: ${JSON.stringify(Object.fromEntries(required.map(f => [f.name, 'test_value'])))}`,
          JSON.stringify(Object.fromEntries(required.map(f => [f.name, ''])))
        );
        if (paramsStr === null) return;
        try { params = JSON.parse(paramsStr); } catch { _mdsToast('JSON 格式錯誤', 'error'); return; }
      }
    } catch {}
  }

  _mdsRunning = true;
  _mdsToast('▶ 執行中...', 'info');

  try {
    const r = await _api('POST', `/mock-data/${id}/run`, { params });
    const dataset = r?.dataset || r?.data?.dataset;
    const rows = Array.isArray(dataset) ? dataset : [dataset];

    // Update sample_output in list cache
    const idx = _mdsList.findIndex(m => m.id === id);
    if (idx >= 0) _mdsList[idx].sample_output = JSON.stringify(rows.slice(0, 20));

    // Show result in a new drawer
    _mdsEditingId = id;
    _setDrawerContent(
      `▶ 試執行結果：${item.name}`,
      `<div class="space-y-4">
        <div class="flex items-center gap-3 p-3 bg-emerald-50 border border-emerald-200 rounded-xl">
          <span class="text-emerald-700 text-sm font-semibold">✅ 執行成功 — ${rows.length} 筆資料</span>
        </div>
        <div>
          <label class="label-sm">Endpoint URL</label>
          <code class="block text-xs bg-slate-900 text-green-300 rounded-lg px-3 py-2 font-mono"
            >POST /api/v1/mock-data/${id}/run</code>
        </div>
        <div>
          <label class="label-sm">輸出資料（前 10 筆）</label>
          <pre class="bg-slate-900 text-green-300 rounded-lg p-3 text-[10px] font-mono overflow-auto max-h-96 border border-slate-700">${JSON.stringify(rows.slice(0, 10), null, 2)}</pre>
        </div>
      </div>`,
      `<button onclick="closeDrawer()" class="builder-btn-secondary text-sm px-4 py-2">關閉</button>
       <button onclick="_mdsOpenEdit(${id})" class="builder-btn-primary text-sm px-4 py-2">編輯程式碼</button>`
    );
    if (!document.getElementById('drawer').classList.contains('drawer-open')) {
      document.getElementById('drawer-overlay')?.classList.remove('hidden');
      document.getElementById('drawer')?.classList.add('drawer-open');
    }
  } catch (e) {
    _mdsToast(`執行失敗: ${e.message}`, 'error');
  } finally {
    _mdsRunning = false;
  }
}



// ══════════════════════════════════════════════════════════════════════════════
// 🗡️  Arsenal — 私有武器庫 (Agent Tool Chest)
// ══════════════════════════════════════════════════════════════════════════════
// ── Tool Catalog (工具目錄) ─────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════════════

const _BUILTIN_TOOLS = [
  { name: 'analyze_data', icon: '📊', description: '結構化分析模板引擎 — 呼叫預建模板（linear_regression / spc_chart / boxplot / stats_summary / correlation）對 MCP 資料進行統計分析與視覺化，輸出圖表 + 結果表格，可直接固化為 MCP。', params: 'template, mcp_id, params{}' },
  { name: 'execute_jit',  icon: '🐍', description: '即時 Python 沙盒 — Agent 自行撰寫 Python 程式碼，在安全的受限環境中對資料執行一次性計算，適合 analyze_data 模板無法覆蓋的客製化分析。', params: 'python_code, mcp_id, run_params{}' },
  { name: 'search_catalog', icon: '🔍', description: '工具目錄搜尋 — 以語義關鍵字搜尋可用 Skills 或 MCPs，返回最相關的候選清單，Agent 決策時優先呼叫。', params: 'query, type(skill|mcp)' },
  { name: 'execute_agent_tool', icon: '⚡', description: '私有武器庫執行 — 從用戶私有武器庫中選取已儲存的 Python 工具腳本並在沙盒中執行，適合重複使用的自訂分析邏輯。', params: 'tool_id, data[]' },
];

async function _toolCatalogLoad() {
  const body = document.getElementById('tool-catalog-body');
  if (!body) return;
  body.innerHTML = '<div class="flex items-center justify-center py-20 text-slate-400 text-sm">載入中…</div>';

  try {
    const [manifestR, templatesR, arsenalR, allSkillsR, mcpDefsR, genericR] = await Promise.all([
      _api('GET', '/agent/tools_manifest'),
      _api('GET', '/agent/analyze-data/templates'),
      _api('GET', '/agent-tools'),
      _api('GET', '/skill-definitions'),
      _api('GET', '/mcp-definitions?type=custom'),
      _api('GET', '/generic-tools/catalog'),        // 25 processing + 25 visualization
    ]);

    const allSkills    = Array.isArray(allSkillsR) ? allSkillsR : (allSkillsR?.items || manifestR?.tools || []);
    const metaTools    = manifestR?.meta_tools   || [];
    const privateTools = arsenalR?.items         || [];
    const templates    = templatesR?.templates   || {};
    const customMcps   = Array.isArray(mcpDefsR) ? mcpDefsR : (mcpDefsR?.items || []);
    const genericTools = genericR?.tools         || [];

    body.innerHTML = '';

    // ── Section helper ─────────────────────────────────────────────────────
    function _section(icon, title, color, cards) {
      const sec = document.createElement('div');
      sec.innerHTML = `
        <div class="flex items-center gap-2 mb-3">
          <span class="text-lg">${icon}</span>
          <h2 class="text-sm font-bold text-slate-700">${title}</h2>
          <span class="text-xs px-2 py-0.5 rounded-full font-semibold ${color}">${cards.length}</span>
        </div>
        <div class="grid grid-cols-1 xl:grid-cols-2 2xl:grid-cols-3 gap-3" id="tc-section-${title.replace(/\s/g,'')}"></div>
      `;
      body.appendChild(sec);
      const grid = sec.querySelector('[id^="tc-section-"]');
      cards.forEach(c => grid.appendChild(c));
    }

    // ── Card builder ───────────────────────────────────────────────────────
    function _card(opts) {
      const el = document.createElement('div');
      el.className = 'bg-white rounded-xl border border-slate-200 p-4 flex flex-col gap-2 shadow-sm hover:shadow-md transition-shadow';
      el.innerHTML = `
        <div class="flex items-start justify-between gap-2">
          <div class="flex items-center gap-2 min-w-0">
            <span class="text-base flex-shrink-0">${opts.icon || '🔧'}</span>
            <span class="font-semibold text-slate-800 text-sm truncate">${_esc(opts.name)}</span>
          </div>
          ${opts.badge ? `<span class="flex-shrink-0 text-[10px] px-2 py-0.5 rounded-full font-semibold ${opts.badgeClass || 'bg-slate-100 text-slate-500'}">${opts.badge}</span>` : ''}
        </div>
        <p class="text-xs text-slate-500 leading-relaxed">${_esc(opts.description || '（無說明）')}</p>
        ${opts.params ? `<div class="text-[10px] font-mono bg-slate-50 border border-slate-100 rounded-lg px-3 py-2 text-slate-500">${_esc(opts.params)}</div>` : ''}
        ${opts.endpoint ? `<div class="text-[10px] font-mono bg-slate-900 text-green-300 rounded-lg px-3 py-1.5">${_esc(opts.endpoint)}</div>` : ''}
      `;
      return el;
    }

    // 1. 系統內建工具
    _section('🤖', '系統內建工具', 'bg-blue-100 text-blue-700',
      _BUILTIN_TOOLS.map(t => _card({ icon: t.icon, name: t.name, description: t.description, params: `params: ${t.params}`, badge: 'Built-in', badgeClass: 'bg-blue-100 text-blue-600' }))
    );

    // 2. 分析模板 (analyze_data sub-tools)
    const tmplCards = Object.entries(templates).map(([key, meta]) =>
      _card({
        icon: '📈',
        name: key,
        description: meta.description || '',
        params: `必填: ${(meta.required_params||[]).join(', ') || '—'}　選填: ${Object.keys(meta.optional_params||{}).join(', ') || '—'}`,
        badge: 'Template',
        badgeClass: 'bg-violet-100 text-violet-600',
      })
    );
    _section('📊', '分析模板 (analyze_data)', 'bg-violet-100 text-violet-700', tmplCards);

    // 3. 診斷技能 (Skills) — all skills including private
    const skillCards = allSkills.map(s => {
      const isPublic = s.visibility === 'public';
      return _card({
        icon: '🎯',
        name: s.name,
        description: s.description || '',
        endpoint: `POST /api/v1/execute/skill/${s.id || s.skill_id}`,
        badge: isPublic ? '🌐 public' : '🔒 private',
        badgeClass: isPublic ? 'bg-emerald-100 text-emerald-600' : 'bg-slate-100 text-slate-500',
      });
    });
    _section('🎯', `診斷技能 (Skills)`, 'bg-emerald-100 text-emerald-700',
      skillCards.length ? skillCards : [_card({ icon: '💤', name: '尚無 Skill', description: '請在 Skill Builder 建立診斷技能。' })]);

    // 3.7 Generic Tools (25 processing + 25 visualization)
    const processingTools = genericTools.filter(t => t.category === 'processing');
    const vizTools        = genericTools.filter(t => t.category === 'visualization');

    function _genericCard(t) {
      const paramsStr = Object.entries(t.params || {}).map(([k,v]) => `${k}: ${v}`).join('  |  ');
      return _card({
        icon: t.category === 'processing' ? '⚙️' : '📉',
        name: t.name,
        description: t.description || '',
        params: paramsStr || null,
        badge: t.category === 'processing' ? 'Processing' : 'Visualization',
        badgeClass: t.category === 'processing' ? 'bg-cyan-100 text-cyan-700' : 'bg-pink-100 text-pink-700',
      });
    }

    if (processingTools.length)
      _section('⚙️', `資料處理工具 (Generic Processing × ${processingTools.length})`, 'bg-cyan-100 text-cyan-700',
        processingTools.map(_genericCard));
    if (vizTools.length)
      _section('📉', `視覺化工具 (Generic Visualization × ${vizTools.length})`, 'bg-pink-100 text-pink-700',
        vizTools.map(_genericCard));

    // ── Code card with collapsible Python block ──────────────────────────────
    let _codeCardIdx = 0;
    function _codeCard(opts) {
      const idx = _codeCardIdx++;
      const el = document.createElement('div');
      el.className = 'bg-white rounded-xl border border-slate-200 shadow-sm hover:shadow-md transition-shadow overflow-hidden';
      el.innerHTML = `
        <div class="p-4 flex flex-col gap-2">
          <div class="flex items-start justify-between gap-2">
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-base flex-shrink-0">${opts.icon || '🐍'}</span>
              <span class="font-semibold text-slate-800 text-sm truncate">${_esc(opts.name)}</span>
            </div>
            <span class="flex-shrink-0 text-[10px] px-2 py-0.5 rounded-full font-semibold ${opts.badgeClass || 'bg-slate-100 text-slate-500'}">${opts.badge || ''}</span>
          </div>
          ${opts.description ? `<p class="text-xs text-slate-500 leading-relaxed">${_esc(opts.description)}</p>` : ''}
          <button onclick="
            var b=document.getElementById('tc-code-${idx}');
            var a=document.getElementById('tc-arrow-${idx}');
            b.classList.toggle('hidden');
            a.textContent=b.classList.contains('hidden')?'▶ 展開腳本':'▼ 收合腳本';
          " class="self-start text-[10px] font-semibold text-indigo-500 hover:text-indigo-700 transition-colors">
            <span id="tc-arrow-${idx}">▶ 展開腳本</span>
          </button>
        </div>
        <div id="tc-code-${idx}" class="hidden border-t border-slate-100">
          <pre class="bg-slate-900 text-green-300 text-[10px] font-mono p-4 overflow-x-auto overflow-y-auto max-h-72 leading-relaxed whitespace-pre">${_esc(opts.code || '（無腳本）')}</pre>
        </div>
      `;
      return el;
    }

    // 3.5 MCP Python 腳本庫
    const mcpScriptCards = customMcps
      .filter(m => m.processing_script)
      .map(m => _codeCard({
        icon: '📦',
        name: m.name,
        description: m.description || m.processing_intent || '',
        code: m.processing_script,
        badge: 'MCP Script',
        badgeClass: 'bg-indigo-100 text-indigo-600',
      }));
    if (mcpScriptCards.length) {
      _section('🐍', 'MCP Python 腳本庫（我們幫 Agent 準備的）', 'bg-indigo-100 text-indigo-700', mcpScriptCards);
    }

    // 4. Meta Tools
    if (metaTools.length) {
      const metaCards = metaTools.map(m =>
        _card({
          icon: '🔧',
          name: m.tool_name,
          description: m.description || '',
          params: `workflow: ${(m.workflow||'').slice(0, 80)}…`,
          badge: 'Meta',
          badgeClass: 'bg-amber-100 text-amber-600',
        })
      );
      _section('🔧', 'Meta Tools', 'bg-amber-100 text-amber-700', metaCards);
    }

    // 5. 私有武器庫 (Agent 自己寫的 / 固化的)
    const privateCards = privateTools.map(t =>
      _codeCard({
        icon: '⚡',
        name: `${t.name}  （使用 ${t.usage_count || 0} 次）`,
        description: t.description || '',
        code: t.code || '（無腳本）',
        badge: 'Agent 寫的',
        badgeClass: 'bg-orange-100 text-orange-600',
      })
    );
    _section('💾', '私有武器庫（Agent 自己寫的）', 'bg-orange-100 text-orange-700',
      privateCards.length ? privateCards : [_card({ icon: '💤', name: '武器庫目前為空', description: '從 Shadow Analyst 儲存分析腳本，或固化分析模板，工具會自動出現在這裡。' })]
    );

  } catch (e) {
    body.innerHTML = `<div class="text-center py-20 text-red-400 text-sm">載入失敗：${_esc(e.message)}</div>`;
  }
}

// ══════════════════════════════════════════════════════════════════════════════

async function _arsenalLoad() {
  const grid    = document.getElementById('arsenal-grid');
  const empty   = document.getElementById('arsenal-empty');
  const loading = document.getElementById('arsenal-loading');
  const badge   = document.getElementById('arsenal-count-badge');
  if (!grid) return;

  grid.innerHTML = '';
  empty?.classList.add('hidden');
  loading?.classList.remove('hidden');

  try {
    const r = await _api('GET', '/agent-tools');
    const items = r?.items || r?.data?.items || [];
    loading?.classList.add('hidden');

    if (badge) {
      badge.textContent = `${items.length} 件武器`;
      badge.classList.toggle('hidden', items.length === 0);
    }

    if (items.length === 0) {
      empty?.classList.remove('hidden');
      return;
    }

    items.forEach(tool => grid.appendChild(_arsenalBuildCard(tool)));
  } catch (e) {
    loading?.classList.add('hidden');
    empty?.classList.remove('hidden');
  }
}

function _arsenalBuildCard(tool) {
  const usageColor = tool.usage_count > 0
    ? 'bg-violet-100 text-violet-700'
    : 'bg-slate-100 text-slate-500';
  const usageLabel = tool.usage_count > 0
    ? `⚔️ 已出戰 ${tool.usage_count} 次`
    : '⚔️ 尚未出戰';
  const date = tool.created_at
    ? new Date(tool.created_at).toLocaleDateString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit' })
    : '';
  const cardId = `arsenal-card-${tool.id}`;
  const codeId = `arsenal-code-${tool.id}`;

  const card = document.createElement('div');
  card.id = cardId;
  card.className = [
    'group relative bg-white rounded-2xl border border-slate-200',
    'shadow-sm hover:shadow-md hover:border-violet-300',
    'transition-all duration-200 overflow-hidden flex flex-col',
  ].join(' ');

  card.innerHTML = `
    <!-- Accent bar -->
    <div class="h-1 w-full bg-gradient-to-r from-violet-500 via-purple-400 to-fuchsia-400"></div>

    <div class="p-5 flex flex-col gap-3 flex-1">
      <!-- Title row -->
      <div class="flex items-start justify-between gap-2">
        <div class="flex items-center gap-2.5 min-w-0">
          <div class="w-9 h-9 rounded-xl bg-violet-50 flex items-center justify-center flex-shrink-0">
            <svg class="w-4.5 h-4.5 text-violet-500" style="width:18px;height:18px"
                 viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="16 18 22 12 16 6"/>
              <polyline points="8 6 2 12 8 18"/>
            </svg>
          </div>
          <div class="min-w-0">
            <p class="text-sm font-semibold text-slate-800 truncate" title="${_escHtml(tool.name)}">${_escHtml(tool.name)}</p>
            <p class="text-[11px] text-slate-400 mt-0.5">${date}</p>
          </div>
        </div>
        <!-- Usage badge -->
        <span class="flex-shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-full ${usageColor} whitespace-nowrap">
          ${usageLabel}
        </span>
      </div>

      <!-- Description -->
      ${tool.description ? `
      <p class="text-xs text-slate-500 leading-relaxed line-clamp-2">${_escHtml(tool.description)}</p>
      ` : ''}

      <!-- Code toggle -->
      <button onclick="_arsenalToggleCode(${tool.id})"
              class="flex items-center gap-1.5 text-[11px] text-violet-600 hover:text-violet-800
                     font-medium transition-colors self-start">
        <svg id="arsenal-chevron-${tool.id}" class="w-3.5 h-3.5 transition-transform" viewBox="0 0 24 24"
             fill="none" stroke="currentColor" stroke-width="2.5"
             stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
        查看程式碼
      </button>

      <!-- Code block (hidden by default) -->
      <div id="${codeId}" class="hidden">
        <pre class="mt-1 bg-slate-900 text-green-300 text-[10px] font-mono rounded-xl p-4
                    overflow-x-auto leading-relaxed max-h-56 overflow-y-auto whitespace-pre-wrap
                    break-words">${_escHtml(tool.code || '（程式碼需重新載入）')}</pre>
      </div>
    </div>

    <!-- Footer actions -->
    <div class="px-5 py-3 bg-slate-50 border-t border-slate-100 flex items-center justify-between">
      <span class="text-[10px] text-slate-400">ID #${tool.id}</span>
      <button onclick="_arsenalDelete(${tool.id}, '${_escHtml(tool.name).replace(/'/g, "\\'")}')"
              class="flex items-center gap-1 text-[11px] text-red-400 hover:text-red-600
                     hover:bg-red-50 px-2 py-1 rounded-lg transition-colors font-medium">
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="3 6 5 6 21 6"/>
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
          <path d="M10 11v6"/><path d="M14 11v6"/>
          <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
        </svg>
        解除武裝
      </button>
    </div>
  `;

  // Fetch full code (list endpoint trims it; get single item for full code)
  if (!tool.code) {
    _api('GET', `/agent-tools/${tool.id}`).then(r => {
      const pre = card.querySelector(`#${codeId} pre`);
      if (pre && r?.data?.code) pre.textContent = r.data.code;
    }).catch(() => {});
  }

  return card;
}

function _arsenalToggleCode(id) {
  const block   = document.getElementById(`arsenal-code-${id}`);
  const chevron = document.getElementById(`arsenal-chevron-${id}`);
  if (!block) return;
  const open = block.classList.toggle('hidden');
  // open=true means now hidden (just toggled to hidden), open=false means now visible
  if (chevron) chevron.style.transform = block.classList.contains('hidden') ? '' : 'rotate(180deg)';

  // Lazy-load full code on first expand
  if (!block.classList.contains('hidden')) {
    const pre = block.querySelector('pre');
    if (pre && pre.textContent.includes('（程式碼需重新載入）')) {
      _api('GET', `/agent-tools/${id}`).then(r => {
        if (r?.data?.code) pre.textContent = r.data.code;
      }).catch(() => {});
    }
  }
}

async function _arsenalDelete(id, name) {
  if (!confirm(`確定要從武器庫移除「${name}」嗎？此動作無法復原。`)) return;
  try {
    await _api('DELETE', `/agent-tools/${id}`);
    document.getElementById(`arsenal-card-${id}`)?.remove();
    // Recount
    const remaining = document.querySelectorAll('[id^="arsenal-card-"]').length;
    const badge = document.getElementById('arsenal-count-badge');
    if (badge) badge.textContent = `${remaining} 件武器`;
    if (remaining === 0) {
      badge?.classList.add('hidden');
      document.getElementById('arsenal-empty')?.classList.remove('hidden');
    }
  } catch (e) {
    alert('刪除失敗，請稍後再試。');
  }
}

function _escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}


// ══════════════════════════════════════════════════════════════════
// Builder Detail Inspector
// ══════════════════════════════════════════════════════════════════

let _bdiMode = 'mcp';   // 'mcp' | 'skill'
let _bdiActiveTab = 'meta';

function _openBuilderDetail(mode) {
  _bdiMode = mode;
  const panel = document.getElementById('builder-detail-inspector');
  if (!panel) return;
  panel.classList.remove('hidden');
  const title = document.getElementById('bdi-title');
  if (title) title.textContent = mode === 'skill'
    ? '🔍 Skill Builder Detail Inspector'
    : '🔍 MCP Builder Detail Inspector';
  _bdiShowTab('meta');
}

function _closeBuilderDetail() {
  document.getElementById('builder-detail-inspector')?.classList.add('hidden');
}

function _bdiShowTab(tab) {
  _bdiActiveTab = tab;
  ['meta', 'json', 'script', 'diag'].forEach(t => {
    const btn = document.getElementById(`bdi-tab-btn-${t}`);
    if (btn) btn.className = t === tab
      ? 'flex-shrink-0 px-4 py-2.5 text-xs font-semibold border-b-2 border-emerald-500 text-emerald-300 transition-colors'
      : 'flex-shrink-0 px-4 py-2.5 text-xs font-semibold border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition-colors';
  });
  _renderBdiContent(tab);
}

function _renderBdiContent(tab) {
  const content = document.getElementById('bdi-content');
  if (!content) return;

  const result = _bdiMode === 'skill' ? _skLastDiagnosisResult : _mceLastTryRunResult;

  if (tab === 'meta') {
    if (!result) { content.innerHTML = '<p class="text-slate-500 text-xs">尚無執行結果</p>'; return; }
    const rows = _bdiMode === 'mcp' ? [
      ['✅ 成功', result.success ? 'Yes' : 'No'],
      ['🧠 LLM 耗時', result.llm_elapsed_s ? `${result.llm_elapsed_s}s` : '—'],
      ['⚙ 沙盒耗時', result.sandbox_elapsed_s ? `${result.sandbox_elapsed_s}s` : '—'],
      ['📥 輸入筆數', result.input_records || '—'],
      ['📤 輸出筆數', result.output_records || '—'],
      ['📊 Charts', (result.output_data?.ui_render?.charts || []).length],
    ] : [
      ['📋 Status', result.status || '—'],
      ['🔬 Diagnosis', result.diagnosis_message || '—'],
      ['⏱ LLM 耗時', result.llm_elapsed_s ? `${result.llm_elapsed_s}s` : '—'],
      ['🔴 Problem Object', JSON.stringify(result.problem_object || {})],
      ['⏰ Timestamp', result.timestamp || '—'],
    ];
    content.innerHTML = `<table class="w-full text-[11px]">
      ${rows.map(([k,v]) => `<tr class="border-b border-slate-800"><td class="py-2 pr-4 text-slate-400 font-semibold whitespace-nowrap">${_esc(k)}</td><td class="py-2 text-slate-200">${_esc(String(v))}</td></tr>`).join('')}
    </table>`;
  } else if (tab === 'json') {
    const obj = _bdiMode === 'mcp' ? (_mceLastTryRunResult?.output_data || null) : _skLastDiagnosisResult;
    content.innerHTML = obj
      ? `<pre class="text-[11px] text-green-300 whitespace-pre-wrap leading-relaxed">${_esc(JSON.stringify(obj, null, 2))}</pre>`
      : '<p class="text-slate-500 text-xs">尚無 JSON 資料</p>';
  } else if (tab === 'script') {
    const script = _bdiMode === 'mcp'
      ? (_mceLastTryRunResult?.script || _mceCurrentMcp?.processing_script || null)
      : (_skLastDiagnosisResult?.generated_code || null);
    content.innerHTML = script
      ? `<pre class="text-[11px] text-blue-200 whitespace-pre-wrap leading-relaxed">${_esc(script)}</pre>`
      : '<p class="text-slate-500 text-xs">尚無腳本</p>';
  } else if (tab === 'diag') {
    if (_bdiMode === 'skill') {
      const d = _skLastDiagnosisResult;
      if (!d) { content.innerHTML = '<p class="text-slate-500 text-xs">尚無診斷結果</p>'; return; }
      const color = d.status === 'ABNORMAL' ? 'text-red-400' : 'text-emerald-400';
      content.innerHTML = `<div class="space-y-3">
        <div class="text-base font-bold ${color}">${_esc(d.status || '—')}</div>
        <div class="text-slate-300 text-xs">${_esc(d.diagnosis_message || '—')}</div>
        <div class="text-[10px] text-slate-500 font-semibold uppercase">Problem Object</div>
        <pre class="text-[11px] text-amber-300 whitespace-pre-wrap">${_esc(JSON.stringify(d.problem_object || {}, null, 2))}</pre>
      </div>`;
    } else {
      const schema = _mceLastTryRunResult?.output_schema;
      if (!schema) { content.innerHTML = '<p class="text-slate-500 text-xs">尚無輸出 Schema</p>'; return; }
      const fields = schema.fields || [];
      content.innerHTML = `<table class="w-full text-[11px]">
        <tr class="text-slate-400 border-b border-slate-700"><th class="text-left py-1 pr-3">欄位</th><th class="text-left py-1 pr-3">型別</th><th class="text-left py-1">說明</th></tr>
        ${fields.map(f => `<tr class="border-b border-slate-800"><td class="py-1.5 pr-3 text-emerald-300">${_esc(f.name||'')}</td><td class="py-1.5 pr-3 text-blue-300">${_esc(f.type||'')}</td><td class="py-1.5 text-slate-300">${_esc(f.description||'')}</td></tr>`).join('')}
      </table>`;
    }
  }
}

// ══════════════════════════════════════════════════════════════════
// MCP Feedback Submit
// ══════════════════════════════════════════════════════════════════

async function _mceSubmitFeedback(forceRegen = false) {
  const feedback = document.getElementById('mce-feedback-text')?.value?.trim();
  if (!feedback) { alert('請填寫回饋說明'); return; }
  const mcpId = parseInt(document.getElementById('mce-edit-id')?.value) || null;
  if (!mcpId) { alert('請先儲存 MCP 再提交回饋'); return; }
  if (!_mceLastRawData) { alert('請先執行 Try Run 取得資料'); return; }

  // Disable both buttons
  const btnReflect = document.getElementById('mce-feedback-btn-reflect');
  const btnRegen   = document.getElementById('mce-feedback-btn-regen');
  const label = forceRegen ? '⏳ LLM 重新生成腳本...' : '⏳ AI 反思修正中...';
  if (btnReflect) { btnReflect.disabled = true; }
  if (btnRegen)   { btnRegen.disabled = true; btnRegen.textContent = label; }
  if (!forceRegen && btnReflect) btnReflect.textContent = label;

  // Switch to Logs tab and clear old logs before writing fresh ones
  _mceSwitchRightTab('logs');
  document.getElementById('mce-exec-log-lines').innerHTML = '';
  document.getElementById('mce-exec-log')?.classList.remove('hidden');
  document.getElementById('mce-console-placeholder')?.classList.add('hidden');
  const dot = document.getElementById('mce-console-status-dot');
  if (dot) dot.classList.remove('hidden');
  _mceLogLine('💬', `用戶回饋：${feedback}`, 'text-amber-600');
  _mceLogLine(forceRegen ? '✨' : '🔄', forceRegen ? 'LLM 重新生成腳本（Force Regen）…' : 'AI 反思修正腳本…');

  // Build previous_result_summary
  const prev = _mceLastTryRunResult;
  const prevCharts = prev?.output_data?.ui_render?.charts || [];
  const prevRows = prev?.output_data?.dataset?.length || 0;
  const prevSummary = prev
    ? `charts=${prevCharts.length}, dataset_rows=${prevRows}, success=${prev.success}`
    : '';

  try {
    const result = await _api('POST', `/mcp-definitions/${mcpId}/run-with-feedback`, {
      input_params: _mceLastRawData,
      user_feedback: feedback,
      previous_result_summary: prevSummary,
      force_regen: forceRegen,
    });

    // Show reflection in logs
    if (result.reflection) {
      _mceLogLine('💡', `AI 反思：${result.reflection}`, 'text-amber-600');
    }

    // Show reflection banner in report
    const banner = document.getElementById('mce-reflection-banner');
    const reflText = document.getElementById('mce-reflection-text');
    if (banner && reflText) {
      reflText.textContent = result.reflection || '(無反思內容)';
      banner.classList.remove('hidden');
    }

    if (result.rerun_success && result.output_data) {
      _mceLogLine('✓', `重跑成功 — charts=${(result.output_data?.ui_render?.charts||[]).length}, rows=${(result.output_data?.dataset||[]).length}`, 'text-emerald-600');
      _mceLastTryRunResult = { ...prev, output_data: result.output_data, script: result.revised_script || prev?.script };

      // Re-render charts
      const uiRender = result.output_data.ui_render || {};
      const newCharts = uiRender.charts || [];
      const dataset   = Array.isArray(result.output_data.dataset) ? result.output_data.dataset : [];
      const chartEl   = document.getElementById('mce-mcp-tab-charting');
      const sumEl     = document.getElementById('mce-mcp-tab-summary');
      const rawTabEl  = document.getElementById('mce-mcp-tab-raw');
      if (chartEl) {
        if (newCharts.length) {
          chartEl.innerHTML = '';
          newCharts.forEach(chartJson => {
            const wrapper = document.createElement('div');
            wrapper.style.cssText = 'height:380px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;margin-bottom:8px;';
            chartEl.appendChild(wrapper);
            try {
              const figData = typeof chartJson === 'string' ? JSON.parse(chartJson) : chartJson;
              const fl = figData.layout || {};
              const m = Object.assign({l:50,r:20,t:40,b:40}, fl.margin||{});
              if (fl.title && m.t < 55) m.t = 55;
              Plotly.newPlot(wrapper, figData.data||[], {...fl, paper_bgcolor:'#f8fafc', plot_bgcolor:'#ffffff', font:{color:'#334155',size:11}, margin:m}, {responsive:true});
            } catch(e) { wrapper.innerHTML = `<p class="text-xs text-red-500 p-3">渲染失敗：${_esc(e.message)}</p>`; }
          });
        } else {
          chartEl.innerHTML = `<div class="flex items-center justify-center h-24 text-slate-400 text-sm">無圖表資料</div>`;
        }
      }
      if (sumEl) _nbRenderDataGrid(sumEl, dataset, '無摘要資料');
      if (rawTabEl) _nbRenderDataGrid(rawTabEl, result.output_data._raw_dataset || [], '無原始資料');

      // Update data/format review on left panel
      const rawEl = document.getElementById('mce-data-review');
      if (rawEl) _nbRenderDataGrid(rawEl, result.output_data._raw_dataset || dataset, '無原始資料');

      // Switch to report after a moment
      setTimeout(() => _mceSwitchRightTab('report'), 500);
      setTimeout(() => _mceSwitchMcpTab('charting'), 550);

    } else {
      const errMsg = result.error || '未知錯誤';
      _mceLogLine('✗', `重跑失敗：${errMsg}`, 'text-red-600');
      if (reflText) reflText.textContent += `\n\n⚠️ 重跑失敗：${errMsg}`;
    }

    // Clear textarea
    const textEl = document.getElementById('mce-feedback-text');
    if (textEl) textEl.value = '';

  } catch(e) {
    _mceLogLine('✗', `回饋提交失敗：${e.message}`, 'text-red-600');
  } finally {
    if (dot) dot.classList.add('hidden');
    if (btnReflect) { btnReflect.disabled = false; btnReflect.textContent = '🔄 修正腳本 + 反思'; }
    if (btnRegen)   { btnRegen.disabled = false;   btnRegen.textContent = '✨ 重新生成腳本'; }
  }
}

// ══════════════════════════════════════════════════════════════════
// Skill Feedback Submit
// ══════════════════════════════════════════════════════════════════

async function _skSubmitFeedback() {
  const feedback = document.getElementById('sk-feedback-text')?.value?.trim();
  if (!feedback) { alert('請填寫回饋說明'); return; }
  const skillId = parseInt(document.getElementById('sk-edit-id')?.value) || null;
  if (!skillId) { alert('請先儲存 Skill 再提交回饋'); return; }
  if (!_skLastMcpSampleOutputs) { alert('請先執行 Try Run 取得資料'); return; }

  const btn = document.querySelector('#sk-feedback-section button');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ AI 反思中...'; }

  const prev = _skLastDiagnosisResult;
  const prevSummary = prev
    ? `status=${prev.status}, diagnosis_message="${(prev.diagnosis_message||'').slice(0,80)}"`
    : '';

  try {
    const result = await _api('POST', `/skill-definitions/${skillId}/diagnose-with-feedback`, {
      mcp_sample_outputs:       _skLastMcpSampleOutputs,
      user_feedback:            feedback,
      previous_result_summary:  prevSummary,
    });

    // Show reflection banner
    const banner = document.getElementById('sk-reflection-banner');
    const reflText = document.getElementById('sk-reflection-text');
    if (banner && reflText) {
      reflText.textContent = result.reflection || '(無反思內容)';
      banner.classList.remove('hidden');
    }

    // If re-run succeeded, update diagnosis card
    if (result.rerun_success) {
      _skLastDiagnosisResult = {
        status:            result.status || '',
        diagnosis_message: result.diagnosis_message || '',
        problem_object:    result.problem_object || {},
        timestamp:         new Date().toISOString(),
      };
      _skRenderDiagnosis({
        ...result,
        skillName:    document.getElementById('sk-edit-name')?.value?.trim() || 'Skill',
        expertAction: document.getElementById('sk-edit-action')?.value?.trim() || '',
      });

      // Update diagnostic_prompt textarea if revised
      if (result.revised_prompt) {
        const promptEl = document.getElementById('sk-edit-prompt');
        if (promptEl) promptEl.value = result.revised_prompt;
      }
    } else if (!result.rerun_success && result.error) {
      if (banner) document.getElementById('sk-reflection-text').textContent +=
        `\n\n⚠️ 重跑失敗：${result.error}`;
    }

    const textEl = document.getElementById('sk-feedback-text');
    if (textEl) textEl.value = '';

  } catch(e) {
    alert(`回饋提交失敗：${e.message}`);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🔄 重跑診斷 + AI 反思'; }
  }
}
