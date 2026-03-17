/**
 * CJR — Compact JSON Renderer (vanilla JS port of @cjr/react)
 *
 * API:
 *   cjrHtml(data, options?)   → HTML string (for template literals)
 *   cjrRender(el, data, opts?) → mounts into an element (live expand/collapse)
 *
 * Options:
 *   theme:    'light' | 'dark'   default 'light'
 *   maxH:     CSS max-height      default '320px'
 *   maxRows:  number              table row limit, default 50
 *   initDepth: number             auto-expand depth, default 2
 *   view:     'auto'|'tree'|'table'  default 'auto'
 */

const CJR = (() => {
  // ── helpers ─────────────────────────────────────────────────────────────────
  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function isTableable(data) {
    return (
      Array.isArray(data) &&
      data.length > 0 &&
      typeof data[0] === 'object' &&
      data[0] !== null &&
      !Array.isArray(data[0])
    );
  }

  function metaLabel(data) {
    if (Array.isArray(data)) return `Array[${data.length}]`;
    if (data !== null && typeof data === 'object') {
      const keys = Object.keys(data).length;
      return `Object{${keys}}`;
    }
    return typeof data;
  }

  // ── Tree builder (returns DOM node) ─────────────────────────────────────────
  function buildTree(data, path, depth, initDepth) {
    const ul = document.createElement('ul');
    ul.className = 'cjr-tree';

    if (data === null || typeof data !== 'object') {
      const li = document.createElement('li');
      li.appendChild(buildLeaf(data));
      ul.appendChild(li);
      return ul;
    }

    const entries = Array.isArray(data)
      ? data.map((v, i) => [String(i), v])
      : Object.entries(data);

    for (const [key, val] of entries) {
      const li = document.createElement('li');
      const node = document.createElement('div');
      node.className = 'cjr-node';

      const isComplex = val !== null && typeof val === 'object';
      const childPath = `${path}.${key}`;

      if (isComplex) {
        const toggle = document.createElement('span');
        toggle.className = 'cjr-toggle';
        const childWrap = document.createElement('div');
        childWrap.className = 'cjr-children';

        const isOpen = depth < initDepth;
        toggle.textContent = isOpen ? '▾' : '▸';
        if (!isOpen) childWrap.classList.add('collapsed');

        // Lazy-render children on first expand
        let rendered = isOpen;
        if (isOpen) {
          childWrap.appendChild(buildTree(val, childPath, depth + 1, initDepth));
        }

        toggle.addEventListener('click', () => {
          const collapsed = childWrap.classList.toggle('collapsed');
          toggle.textContent = collapsed ? '▸' : '▾';
          if (!collapsed && !rendered) {
            childWrap.appendChild(buildTree(val, childPath, depth + 1, initDepth));
            rendered = true;
          }
        });

        const keySpan = document.createElement('span');
        keySpan.className = 'cjr-key';
        keySpan.textContent = Array.isArray(data) ? `[${key}]` : key;

        const colon = document.createElement('span');
        colon.className = 'cjr-colon';
        colon.textContent = ':';

        const bracket = document.createElement('span');
        bracket.className = 'cjr-bracket';
        bracket.textContent = Array.isArray(val)
          ? `[${val.length}]`
          : `{${Object.keys(val).length}}`;

        node.appendChild(toggle);
        node.appendChild(keySpan);
        node.appendChild(colon);
        node.appendChild(bracket);
        li.appendChild(node);
        li.appendChild(childWrap);
      } else {
        const indent = document.createElement('span');
        indent.style.minWidth = '12px';
        indent.style.display = 'inline-block';

        const keySpan = document.createElement('span');
        keySpan.className = 'cjr-key';
        keySpan.textContent = Array.isArray(data) ? `[${key}]` : key;

        const colon = document.createElement('span');
        colon.className = 'cjr-colon';
        colon.textContent = ':';

        node.appendChild(indent);
        node.appendChild(keySpan);
        node.appendChild(colon);
        node.appendChild(buildLeaf(val));
        li.appendChild(node);
      }

      ul.appendChild(li);
    }
    return ul;
  }

  function buildLeaf(val) {
    const span = document.createElement('span');
    if (val === null) {
      span.className = 'cjr-null';
      span.textContent = 'null';
    } else if (typeof val === 'string') {
      span.className = 'cjr-str';
      const display = val.length > 120 ? val.slice(0, 117) + '…' : val;
      span.textContent = `"${display}"`;
      if (val.length > 120) span.title = val;
    } else if (typeof val === 'number') {
      span.className = 'cjr-num';
      span.textContent = String(val);
    } else if (typeof val === 'boolean') {
      span.className = 'cjr-bool';
      span.textContent = String(val);
    } else {
      span.className = 'cjr-null';
      span.textContent = String(val);
    }
    return span;
  }

  // ── Card builder — each array item as a card ─────────────────────────────────
  function buildCards(data, maxRows) {
    const items = data.slice(0, maxRows);
    const wrap = document.createElement('div');
    wrap.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;padding:4px 0;';

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const card = document.createElement('div');
      card.style.cssText = 'border:1px solid var(--cjr-border);border-radius:8px;padding:8px 12px;min-width:180px;flex:1 1 200px;max-width:320px;background:var(--cjr-bg);';

      const header = document.createElement('div');
      header.style.cssText = 'font-size:10px;font-weight:700;color:var(--cjr-muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em;';
      header.textContent = `#${i}`;
      card.appendChild(header);

      if (item !== null && typeof item === 'object' && !Array.isArray(item)) {
        for (const [k, v] of Object.entries(item)) {
          const row = document.createElement('div');
          row.style.cssText = 'display:flex;gap:6px;margin:2px 0;align-items:baseline;';
          const kSpan = document.createElement('span');
          kSpan.className = 'cjr-key';
          kSpan.style.cssText = 'min-width:80px;flex-shrink:0;font-size:10.5px;';
          kSpan.textContent = k;
          const vSpan = document.createElement('span');
          vSpan.style.cssText = 'font-size:10.5px;word-break:break-all;';
          vSpan.appendChild(buildLeaf(typeof v === 'object' && v !== null ? null : v));
          if (typeof v === 'object' && v !== null) {
            vSpan.className = 'cjr-muted';
            vSpan.textContent = Array.isArray(v) ? `[${v.length}]` : `{${Object.keys(v).length}}`;
          }
          row.appendChild(kSpan);
          row.appendChild(vSpan);
          card.appendChild(row);
        }
      } else {
        card.appendChild(buildLeaf(item));
      }
      wrap.appendChild(card);
    }

    if (data.length > maxRows) {
      const more = document.createElement('div');
      more.className = 'cjr-tbl-more';
      more.textContent = `… 還有 ${data.length - maxRows} 筆`;
      wrap.appendChild(more);
    }
    return wrap;
  }

  // ── Table builder (returns DOM node) ────────────────────────────────────────
  function buildTable(data, maxRows) {
    const rows = data.slice(0, maxRows);
    const cols = [...new Set(rows.flatMap(r => Object.keys(r)))];

    const wrap = document.createElement('div');
    wrap.className = 'cjr-table-wrap';

    const tbl = document.createElement('table');
    tbl.className = 'cjr-tbl';

    // thead
    const thead = document.createElement('thead');
    const tr = document.createElement('tr');
    for (const col of cols) {
      const th = document.createElement('th');
      th.textContent = col;
      tr.appendChild(th);
    }
    thead.appendChild(tr);
    tbl.appendChild(thead);

    // tbody
    const tbody = document.createElement('tbody');
    for (const row of rows) {
      const tr = document.createElement('tr');
      for (const col of cols) {
        const td = document.createElement('td');
        const val = row[col];
        if (val === null || val === undefined) {
          td.className = 'cjr-td-null';
          td.textContent = '—';
        } else if (typeof val === 'object') {
          td.className = 'cjr-td-obj';
          td.textContent = JSON.stringify(val).slice(0, 40) + '…';
          td.title = JSON.stringify(val, null, 2);
        } else if (typeof val === 'number') {
          td.className = 'cjr-td-num';
          td.textContent = String(val);
        } else if (typeof val === 'boolean') {
          td.className = 'cjr-td-bool';
          td.textContent = String(val);
        } else {
          td.className = 'cjr-td-str';
          const s = String(val);
          td.textContent = s.length > 60 ? s.slice(0, 57) + '…' : s;
          if (s.length > 60) td.title = s;
        }
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);

    if (data.length > maxRows) {
      const more = document.createElement('div');
      more.className = 'cjr-tbl-more';
      more.textContent = `… 還有 ${data.length - maxRows} 筆資料`;
      wrap.appendChild(more);
    }

    return wrap;
  }

  // ── Record view — vertical key/value table for objects ──────────────────────
  function buildRecord(data) {
    const wrap = document.createElement('div');
    wrap.className = 'cjr-table-wrap';

    const tbl = document.createElement('table');
    tbl.className = 'cjr-tbl';

    const tbody = document.createElement('tbody');
    const entries = Array.isArray(data)
      ? data.map((v, i) => [String(i), v])
      : Object.entries(data);

    for (const [key, val] of entries) {
      const tr = document.createElement('tr');
      const th = document.createElement('th');
      th.textContent = key;
      th.style.width = '30%';
      tr.appendChild(th);

      const td = document.createElement('td');
      if (val === null || val === undefined) {
        td.className = 'cjr-td-null'; td.textContent = '—';
      } else if (typeof val === 'object') {
        td.className = 'cjr-td-obj';
        // Inline mini-tree for nested values
        const mini = document.createElement('div');
        mini.style.fontSize = '11px';
        buildTree(val, key, 0, 1).querySelectorAll ? mini.appendChild(buildTree(val, key, 0, 1)) : (mini.textContent = JSON.stringify(val).slice(0, 80));
        td.appendChild(mini);
      } else if (typeof val === 'number') {
        td.className = 'cjr-td-num'; td.textContent = String(val);
      } else if (typeof val === 'boolean') {
        td.className = 'cjr-td-bool'; td.textContent = String(val);
      } else {
        td.className = 'cjr-td-str'; td.textContent = String(val);
      }
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
    return wrap;
  }

  // ── Main mount function ──────────────────────────────────────────────────────
  function render(container, data, opts = {}) {
    const {
      theme    = 'light',
      maxH     = '320px',
      maxRows  = 50,
      initDepth = 2,
      view     = 'auto',
      toolbar  = true,   // set false for inline/cell embeds — no buttons, no meta
    } = opts;

    // Parse string data
    let parsed = data;
    if (typeof data === 'string') {
      try { parsed = JSON.parse(data); } catch { /* leave as string */ }
    }

    // Determine available views and default
    const isObj    = parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed);
    const isArr    = isTableable(parsed); // array-of-objects
    const isSingle = isArr && parsed.length === 1; // single-item array → also offer Record

    // Always: tree. Arrays get table+card. Objects get record. Single arrays also get record.
    const availViews = ['tree'];
    if (isArr)            { availViews.push('table'); availViews.push('card'); }
    if (isObj || isSingle) availViews.push('record');

    let defaultView = 'tree';
    if      (view === 'table'  && isArr)            defaultView = 'table';
    else if (view === 'card'   && isArr)            defaultView = 'card';
    else if (view === 'record' && (isObj||isSingle)) defaultView = 'record';
    else if (view === 'auto') {
      if (isSingle) defaultView = 'record';      // single row → vertical first
      else if (isArr) defaultView = 'table';
      else if (isObj) defaultView = 'record';
    }

    // Root wrapper
    const root = document.createElement('div');
    root.className = `cjr cjr-${theme}`;
    root.style.setProperty('--cjr-max-h', maxH);

    if (toolbar) {
      // Toolbar — only rendered for top-level viewers (toolbar: true, default)
      const tb = document.createElement('div');
      tb.className = 'cjr-toolbar';

      const viewBtns = {};
      if (availViews.length > 1) {
        const labels = { tree: '🌲 Tree', table: '⊞ Grid', card: '🃏 Card', record: '📄 Record' };
        for (const v of availViews) {
          const btn = document.createElement('button');
          btn.className = 'cjr-view-btn' + (v === defaultView ? ' active' : '');
          btn.textContent = labels[v];
          btn.addEventListener('click', () => {
            Object.values(viewBtns).forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderBody(v);
          });
          viewBtns[v] = btn;
          tb.appendChild(btn);
        }
      }

      const meta = document.createElement('span');
      meta.className = 'cjr-toolbar-meta';
      meta.textContent = metaLabel(parsed);
      tb.appendChild(meta);

      const copyBtn = document.createElement('button');
      copyBtn.className = 'cjr-copy-btn';
      copyBtn.textContent = '⎘ 複製';
      copyBtn.addEventListener('click', () => {
        navigator.clipboard?.writeText(JSON.stringify(parsed, null, 2)).then(() => {
          copyBtn.textContent = '✓ 已複製';
          setTimeout(() => { copyBtn.textContent = '⎘ 複製'; }, 1500);
        });
      });
      tb.appendChild(copyBtn);

      root.appendChild(tb);
    }

    // Body
    const body = document.createElement('div');
    body.className = 'cjr-body';
    root.appendChild(body);

    function renderBody(v) {
      body.innerHTML = '';
      if (v === 'table' && isArr) {
        body.appendChild(buildTable(parsed, maxRows));
      } else if (v === 'card' && isArr) {
        body.appendChild(buildCards(parsed, maxRows));
      } else if (v === 'record') {
        const recordData = isSingle ? parsed[0] : parsed;
        body.appendChild(buildRecord(recordData));
      } else {
        body.appendChild(buildTree(parsed, 'root', 0, initDepth));
      }
    }

    renderBody(defaultView);
    container.innerHTML = '';
    container.appendChild(root);
  }

  // ── html() convenience for template literals ─────────────────────────────────
  // Returns a placeholder <div> that gets hydrated via MutationObserver on insert
  let _uid = 0;
  function html(data, opts = {}) {
    const id = `cjr-ph-${++_uid}`;
    // Store pending renders
    CJR._pending = CJR._pending || {};
    CJR._pending[id] = { data, opts };
    // Return a lightweight placeholder; _hydrate() will mount it
    return `<div id="${id}" class="cjr-placeholder"></div>`;
  }

  // Call after inserting HTML with cjrHtml() placeholders
  function hydrate(root) {
    const pending = CJR._pending || {};
    const phs = (root || document).querySelectorAll('.cjr-placeholder[id^="cjr-ph-"]');
    for (const ph of phs) {
      const job = pending[ph.id];
      if (job) {
        render(ph, job.data, job.opts);
        delete pending[ph.id];
      }
    }
  }

  return { render, html, hydrate };
})();

// Global aliases
function cjrRender(el, data, opts) { CJR.render(el, data, opts); }
function cjrHtml(data, opts)       { return CJR.html(data, opts); }
function cjrHydrate(root)          { CJR.hydrate(root); }
