// machines.jsx — Machine Center: every tool gets a card showing "Copilot did" + "Needs you"

const { useState, useMemo, useEffect } = React;

// === Icons ===
const Svg = (p, c) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={p.sw||2} strokeLinecap="round" strokeLinejoin="round">{c}</svg>;
const Ic = {
  check: (p={}) => Svg(p, <polyline points="20 6 9 17 4 12"/>),
  alert: (p={}) => Svg(p, <><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></>),
  zap: (p={}) => Svg(p, <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor"/>),
  send: (p={}) => Svg(p, <><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2" fill="currentColor"/></>),
  pause: (p={}) => Svg(p, <><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></>),
  search: (p={}) => Svg(p, <><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></>),
  more: (p={}) => Svg(p, <><circle cx="12" cy="12" r="1.5" fill="currentColor"/><circle cx="19" cy="12" r="1.5" fill="currentColor"/><circle cx="5" cy="12" r="1.5" fill="currentColor"/></>),
  ext: (p={}) => Svg(p, <><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></>),
  bell: (p={}) => Svg(p, <><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></>),
  bot: (p={}) => Svg(p, <><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/></>),
  cog: (p={}) => Svg(p, <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></>),
  brand: (p={}) => Svg(p, <><path d="M12 2L13.4 7.6 19 9 13.4 10.4 12 16 10.6 10.4 5 9 10.6 7.6z" fill="currentColor"/></>),
  filter: (p={}) => Svg(p, <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>)
};

// === Topbar (use shared) — see shared-ui.jsx for <TopBar />

// === Filters ===
function Filters({ filter, setFilter, sort, setSort, density, setDensity, counts }) {
  return (
    <div className="filters">
      <div className="filter-group">
        <button className={`filter-btn takeover ${filter==='needs' ? 'active' : ''}`} onClick={() => setFilter('needs')}>
          Needs you <span className="filter-num">{counts.needs}</span>
        </button>
        <button className={`filter-btn ${filter==='auto' ? 'active' : ''}`} onClick={() => setFilter('auto')}>
          Copilot 處理中 <span className="filter-num">{counts.auto}</span>
        </button>
        <button className={`filter-btn ${filter==='all' ? 'active' : ''}`} onClick={() => setFilter('all')}>
          全部 <span className="filter-num">{counts.all}</span>
        </button>
      </div>

      <div className="filter-group">
        <button className={`filter-btn ${sort==='priority' ? 'active' : ''}`} onClick={() => setSort('priority')}>優先序</button>
        <button className={`filter-btn ${sort==='recent' ? 'active' : ''}`} onClick={() => setSort('recent')}>最近動作</button>
        <button className={`filter-btn ${sort==='id' ? 'active' : ''}`} onClick={() => setSort('id')}>機台號</button>
      </div>

      <div className="search">
        <Ic.search size={13} />
        <input placeholder="找機台、lot、recipe…" />
        <span className="kbd-mini">⌘K</span>
      </div>

      <div className="filter-group">
        {['compact', 'normal', 'wide'].map(d => (
          <button key={d} className={`filter-btn ${density===d ? 'active' : ''}`} onClick={() => setDensity(d)}>
            {d === 'compact' ? '密' : d === 'wide' ? '寬' : '中'}
          </button>
        ))}
      </div>
    </div>
  );
}

// === Hero strip ===
function Hero({ needsCount }) {
  return (
    <div className="hero">
      <div className="hero-inner">
        {needsCount > 0 ? (
          <div className="hero-needs">
            <div className="hero-needs-icon"><Ic.alert size={22} sw={2.5}/></div>
            <div>
              <div className="hero-needs-tag">需要你接手 · {needsCount} 台機台</div>
              <div className="hero-needs-title">EQP-04 等你選 recovery 策略</div>
              <div className="hero-needs-sub">
                Copilot 信心 62% (門檻 75%) · STEP_007+009 雙偏移是新 pattern · 已準備 3 個選項
              </div>
            </div>
            <div className="hero-needs-cta">
              <button className="btn">稍後</button>
              <button className="btn takeover">前往決定 →</button>
            </div>
          </div>
        ) : (
          <div className="hero-needs clean">
            <div className="hero-needs-icon"><Ic.check size={22} sw={2.5}/></div>
            <div>
              <div className="hero-needs-tag">一切順利</div>
              <div className="hero-needs-title">Copilot 在自動駕駛，無需你介入</div>
              <div className="hero-needs-sub">過去 1 小時自動處理 14 件，0 件需要你決定。</div>
            </div>
          </div>
        )}

        <div className="hero-stats">
          <div className="hero-stat">
            <div className="hero-stat-label">Auto-handled</div>
            <div className="hero-stat-value auto-c">341</div>
            <div className="hero-stat-sub">98% of 348</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat-label">Needs you</div>
            <div className="hero-stat-value takeover-c">1</div>
            <div className="hero-stat-sub">EQP-04</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat-label">Time saved</div>
            <div className="hero-stat-value">2h 22m</div>
            <div className="hero-stat-sub">vs manual</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat-label">Trust</div>
            <div className="hero-stat-value auto-c">96%</div>
            <div className="hero-stat-sub">7d · 0 撤銷</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// === Mini chart inside card ===
function MiniChart({ data, ucl, lcl, mid, status }) {
  if (!data) return <div style={{height: 48, color: 'var(--text-4)', fontSize: 10, display: 'grid', placeItems: 'center', fontFamily: 'var(--font-mono)'}}>— no data —</div>;
  const w = 320, h = 48;
  const padX = 4, padY = 4;
  const max = Math.max(ucl + 0.3, ...data);
  const min = Math.min(lcl - 0.3, ...data);
  const xs = (i) => padX + (i / (data.length - 1)) * (w - padX * 2);
  const ys = (v) => padY + (1 - (v - min) / (max - min)) * (h - padY * 2);
  const linePts = data.map((v, i) => `${xs(i)},${ys(v)}`).join(' ');
  const areaPts = `${xs(0)},${h - padY} ${linePts} ${xs(data.length - 1)},${h - padY}`;
  const lineCls = status === 'takeover' || status === 'warn' ? 'takeover' : '';
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <rect x={padX} y={ys(ucl)} width={w - padX*2} height={Math.max(0, ys(lcl) - ys(ucl))} fill="oklch(96% 0.005 60)" />
      <line x1={padX} y1={ys(ucl)} x2={w - padX} y2={ys(ucl)} stroke="oklch(85% 0.10 25)" strokeDasharray="2,3" strokeWidth="1" />
      <line x1={padX} y1={ys(lcl)} x2={w - padX} y2={ys(lcl)} stroke="oklch(85% 0.10 25)" strokeDasharray="2,3" strokeWidth="1" />
      <polygon points={areaPts} fill={status === 'takeover' || status === 'warn' ? 'oklch(56% 0.20 25)' : 'oklch(62% 0.13 155)'} opacity="0.12" />
      <polyline points={linePts} fill="none" stroke={status === 'takeover' || status === 'warn' ? 'var(--takeover)' : 'var(--auto)'} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

// === Machine Card ===
function MachineCard({ m }) {
  const showFull = m.status === 'takeover' || m.status === 'warn' || m.status === 'assist';
  const doneCount = m.done?.length || 0;

  const pillLabel = {
    auto: 'Auto',
    warn: 'Watching',
    assist: 'Assist needed',
    takeover: 'Takeover',
    idle: 'Idle'
  }[m.status];

  return (
    <div className={`mc ${m.status}`}>
      <div className="mc-head">
        <div>
          <div className="mc-id-row">
            <span className="mc-id">{m.id}</span>
          </div>
        </div>
        <span className={`mc-status-pill ${m.status}`}>
          <span className="dot"></span>{pillLabel}
        </span>
        <div className="mc-summary" dangerouslySetInnerHTML={{__html: m.summary}} />
        <div className="mc-meta-row">
          <span>Uptime <strong>{m.meta.uptime}</strong></span>
          <span>Lots <strong>{m.meta.lots}</strong></span>
          <span>Last incident <strong>{m.meta.lastIncident}</strong></span>
        </div>
      </div>

      <div className="mc-chart">
        <MiniChart data={m.spark} ucl={m.ucl} lcl={m.lcl} mid={m.mid} status={m.status} />
        <div className="mc-chart-meta">
          <span>{m.spark ? `${m.spark.length}-pt SPC` : 'idle'}</span>
          <span>UCL {m.ucl}</span>
        </div>
      </div>

      <div className="mc-body">
        <div className="mc-section">
          <div className="mc-section-head">
            <span className="mc-section-title done">
              <Ic.check size={11} sw={3} /> Copilot 已處理 <span className="num">{doneCount}</span>
            </span>
            <button className="mc-section-link">查看全部 →</button>
          </div>
          {m.done.slice(0, showFull ? 3 : 4).map((d, i) => (
            <div key={i} className="done-item">
              <div className="done-icon"><Ic.check size={10} sw={3}/></div>
              <div className="done-text" dangerouslySetInnerHTML={{__html: d.text}} />
              <div className="done-meta">{d.meta}</div>
            </div>
          ))}
        </div>

        <div className="mc-section">
          <div className="mc-section-head">
            <span className={`mc-section-title ${m.needs ? 'needs' : ''}`}>
              {m.needs
                ? <><Ic.alert size={11} sw={2.5}/> 需要你 <span className="num">1</span></>
                : <>需要你 <span className="num">0</span></>
              }
            </span>
            {m.needs && m.confidence != null && (
              <span style={{fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--font-mono)'}}>
                conf {m.confidence}%
              </span>
            )}
          </div>

          {!m.needs && (
            <span className="needs-empty">
              <Ic.check size={11} sw={2.5} style={{color: 'var(--auto)'}}/> 不需要動作 · Copilot 全自動
            </span>
          )}

          {m.needs && (
            <div className={`needs-card ${m.needs.kind}`}>
              <div className="needs-card-title">{m.needs.title}</div>
              <div className="needs-card-sub" dangerouslySetInnerHTML={{__html: m.needs.sub}} />
              {m.confidence != null && m.needs.kind !== 'assist' && (
                <div className="needs-conf">
                  <span>Confidence {m.confidence}% / 75%</span>
                  <div className="needs-conf-bar">
                    <div className="needs-conf-bar-fill" style={{width: `${m.confidence}%`}}></div>
                  </div>
                </div>
              )}
              <div className="needs-options">
                {m.needs.options.map(o => (
                  <button key={o.key} className={`needs-opt ${o.recommended ? 'recommended' : ''}`}>
                    <div className={`needs-opt-key ${m.needs.kind === 'warn' ? 'warn' : m.needs.kind === 'assist' ? 'assist' : ''}`}>{o.key}</div>
                    <div>
                      <div className="needs-opt-text">{o.text}</div>
                      <div className="needs-opt-sub">{o.sub}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="mc-foot">
        <div className="mc-foot-stat">
          <strong>{m.confidence != null ? `${m.confidence}%` : '—'}</strong> Copilot confidence
        </div>
        <div className="mc-foot-actions">
          <button className="mc-foot-btn"><Ic.zap size={10}/> Ask</button>
          <button className="mc-foot-btn"><Ic.ext size={10}/> Open</button>
          <button className="mc-foot-btn"><Ic.more size={11}/></button>
        </div>
      </div>
    </div>
  );
}

// === App ===
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "saturation": 1.0,
  "density": "normal"
}/*EDITMODE-END*/;

function App() {
  const [tweaks, setTweak] = (window.useTweaks ? window.useTweaks(TWEAK_DEFAULTS) : [TWEAK_DEFAULTS, () => {}]);

  const viewMode = window.VIEW_MODE || 'machines';
  // Defaults per view mode
  const defaults = {
    copilot: { filter: 'auto', sort: 'recent' },
    machines: { filter: 'all', sort: 'priority' },
    alarms: { filter: 'needs', sort: 'priority' }
  }[viewMode] || { filter: 'all', sort: 'priority' };

  const [filter, setFilter] = useState(defaults.filter);
  const [sort, setSort] = useState(defaults.sort);
  const [density, setDensity] = useState(tweaks.density || 'normal');

  useEffect(() => {
    document.documentElement.style.setProperty('--sat', tweaks.saturation);
  }, [tweaks.saturation]);

  const all = window.MACHINES;
  const counts = {
    all: all.length,
    needs: all.filter(m => m.needs).length,
    auto: all.filter(m => !m.needs).length
  };

  const priorityRank = { takeover: 0, warn: 1, assist: 2, auto: 3, idle: 4 };
  const filtered = useMemo(() => {
    let xs = all.filter(m =>
      filter === 'all' || (filter === 'needs' && m.needs) || (filter === 'auto' && !m.needs)
    );
    if (sort === 'priority') xs = [...xs].sort((a, b) => priorityRank[a.status] - priorityRank[b.status]);
    if (sort === 'recent') xs = [...xs].sort((a, b) => (b.started || '').localeCompare(a.started || ''));
    if (sort === 'id') xs = [...xs].sort((a, b) => a.id.localeCompare(b.id));
    return xs;
  }, [filter, sort, all]);

  return (
    <>
      <div className="shell">
        <window.TopBar active={viewMode} />
        <Hero needsCount={counts.needs} />
        <Filters
          filter={filter} setFilter={setFilter}
          sort={sort} setSort={setSort}
          density={density} setDensity={setDensity}
          counts={counts}
        />
        <div className={`grid ${density}`}>
          {filtered.map(m => <MachineCard key={m.id} m={m} />)}
        </div>
      </div>
      {window.TweaksPanel && (
        <window.TweaksPanel title="Tweaks">
          <window.TweakSection title="Visuals">
            <window.TweakSlider label="Saturation" value={tweaks.saturation} min={0.4} max={1.4} step={0.05}
              onChange={v => setTweak('saturation', v)} />
            <window.TweakRadio label="Density" value={density} onChange={v => { setDensity(v); setTweak('density', v); }}
              options={[{value:'compact',label:'密'},{value:'normal',label:'中'},{value:'wide',label:'寬'}]} />
          </window.TweakSection>
        </window.TweaksPanel>
      )}
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
