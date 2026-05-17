// Main App + variations

const { useState, useEffect } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "light",
  "density": "comfortable",
  "listMode": "cluster",
  "saturation": 1.0,
  "agentPosition": "side",
  "showFloorMap": true,
  "sparkStyle": "bars"
}/*EDITMODE-END*/;

function App({ variant }) {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [selectedId, setSelectedId] = useState('c1');
  const [filter, setFilter] = useState('all');
  const [agentVisible, setAgentVisible] = useState(true);
  const [view, setView] = useState('detail'); // 'detail' | 'pipeline'

  const { CLUSTERS } = window.MOCK;
  const clusters = filter === 'all'
    ? CLUSTERS
    : filter === 'open'
    ? CLUSTERS.filter(c => c.openCount > 0)
    : CLUSTERS.filter(c => c.severity === filter);

  const selected = CLUSTERS.find(c => c.id === selectedId) || CLUSTERS[0];
  const v = variant || 'A';

  // Apply tweaks
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', tweaks.theme);
    document.documentElement.setAttribute('data-density', tweaks.density);
    document.documentElement.style.setProperty('--sat', tweaks.saturation);
    window.__sparkStyle = tweaks.sparkStyle;
  }, [tweaks.theme, tweaks.density, tweaks.saturation, tweaks.sparkStyle]);

  const totalHigh = CLUSTERS.filter(c => c.severity === 'high').reduce((s, c) => s + c.count, 0);
  const totalMed = CLUSTERS.filter(c => c.severity === 'med').reduce((s, c) => s + c.count, 0);
  const totalAll = CLUSTERS.reduce((s, c) => s + c.count, 0);

  const agentPos = v === 'A' ? tweaks.agentPosition : v === 'B' ? 'bottom' : 'side';
  const listMode = v === 'C' ? 'triage' : tweaks.listMode;

  return (
    <div className="app" data-agent-pos={agentVisible ? agentPos : 'hidden'} data-list-pos={v === 'B' ? 'shown' : 'shown'}>
      {/* TOPBAR */}
      <div className="topbar">
        <div className="brand"><span className="brand-dot"></span>AIOps · Alarm Center</div>
        <div className="topbar-pulse">
          <span className="pulse-dot"></span>
          <span className="pulse-stat"><strong>{totalHigh}</strong> high</span>
          <span className="pulse-divider"></span>
          <span className="pulse-stat"><strong>{totalMed}</strong> med</span>
          <span className="pulse-divider"></span>
  <span className="pulse-stat" style={{ color: 'var(--text-3)', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0 }}>共 <strong>{totalAll}</strong> 告警 → <strong>{CLUSTERS.length}</strong> 事件</span>
          <span className="topbar-pulse-ai">
            <Icon name="sparkles" size={11} /> AI 戰況：建議優先處理 EQP-03 + EQP-07
          </span>
        </div>
        <div className="topbar-actions">
          <button className="btn icon"><Icon name="refresh" size={12} /></button>
          <button className="btn icon"><Icon name="settings" size={12} /></button>
        </div>
      </div>

      {/* RAIL */}
      <div className="rail">
        <button className="rail-btn"><Icon name="play" size={16} /></button>
        <button className="rail-btn active"><Icon name="bell" size={16} /><span className="rail-badge">{CLUSTERS.length}</span></button>
        <button className="rail-btn"><Icon name="chart" size={16} /></button>
        <button className="rail-btn"><Icon name="map" size={16} /></button>
        <button className="rail-btn"><Icon name="layers" size={16} /></button>
        <button className="rail-btn"><Icon name="server" size={16} /></button>
        <button className="rail-btn"><Icon name="users" size={16} /></button>
        <div style={{ flex: 1 }}></div>
        <button className="rail-btn"><Icon name="settings" size={16} /></button>
      </div>

      {/* LIST */}
      <div className="list">
        <div className="list-header">
          <div className="list-title-row">
            <div className="list-title">告警 · 群集視圖</div>
            <div className="list-title-meta">{clusters.length} / {CLUSTERS.length}</div>
          </div>
          <div className="list-modes">
            {['cluster', 'timeline', 'flat'].map(m => (
              <button
                key={m}
                className={`list-mode-btn ${listMode === m ? 'active' : ''}`}
                onClick={() => setTweak('listMode', m)}
              >
                {m === 'cluster' ? '群集' : m === 'timeline' ? '時間軸' : '清單'}
              </button>
            ))}
          </div>
        </div>

        <div className="list-filters">
          {[
            { id: 'all', label: '全部', count: CLUSTERS.length, color: null },
            { id: 'high', label: 'High', count: CLUSTERS.filter(c => c.severity === 'high').length, color: 'var(--high)' },
            { id: 'med', label: 'Med', count: CLUSTERS.filter(c => c.severity === 'med').length, color: 'var(--med)' },
            { id: 'low', label: 'Low', count: CLUSTERS.filter(c => c.severity === 'low').length, color: 'var(--low)' },
            { id: 'open', label: 'Open', count: CLUSTERS.filter(c => c.openCount > 0).length, color: null },
          ].map(f => (
            <button key={f.id} className={`chip ${filter === f.id ? 'active' : ''}`} onClick={() => setFilter(f.id)}>
              {f.color && <span className="chip-dot" style={{ background: f.color }}></span>}
              {f.label} <span className="count">{f.count}</span>
            </button>
          ))}
        </div>

        <div className="list-body">
          {listMode === 'cluster' && clusters.map(c => (
            <ClusterCard key={c.id} cluster={c} selected={c.id === selectedId} onClick={() => setSelectedId(c.id)} />
          ))}
          {listMode === 'timeline' && (
            <TimelineList clusters={clusters} selectedId={selectedId} onSelect={setSelectedId} />
          )}
          {listMode === 'flat' && (
            <FlatList clusters={clusters} selectedId={selectedId} onSelect={setSelectedId} />
          )}
          {listMode === 'triage' && <TriageBoard clusters={clusters} selectedId={selectedId} onSelect={setSelectedId} />}
        </div>
      </div>

      {/* MAIN */}
      <div className="main">
        <div className="main-inner">
          {v === 'B' && (
            <>
              <div className="overview">
                <KPI label="High alarms" value={totalHigh} trend="+8 vs 昨日" trendDir="up"
                  sparkData={[3, 5, 8, 12, 18, 22, 28, 32, 35, totalHigh]} sparkColor="var(--high)" />
                <KPI label="MTTR (median)" value="42m" trend="-6m" trendDir="down"
                  sparkData={[55, 52, 48, 50, 47, 46, 44, 43, 42, 42]} sparkColor="var(--ok)" />
                <KPI label="Tool 健康度" value="87%" trend="持平" trendDir="flat"
                  sparkData={[88, 87, 89, 88, 87, 88, 87, 87, 87, 87]} sparkColor="var(--text-3)" />
                <KPI label="On-shift" value="3 / 5" trend="2 待派工" trendDir="flat" />
              </div>
              <div className="floormap-card">
                <div className="section-head">
                  <div>
                    <div className="section-title">Fab Floor · 30 機台 · 3 bays</div>
                    <div className="section-sub">點擊機台檢視該機台所有告警 · 紅 = 高嚴重度，黃 = 中等，藍 = 低</div>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn"><Icon name="filter" size={11} /> 篩選</button>
                    <button className="btn"><Icon name="grid" size={11} /> Grid</button>
                  </div>
                </div>
                <FloorMap selectedTool={selected?.tool} onSelect={(toolId) => {
                  const c = CLUSTERS.find(x => x.tool === toolId);
                  if (c) setSelectedId(c.id);
                }} />
              </div>
            </>
          )}

          {v === 'A' && tweaks.showFloorMap && (
            <div className="overview" style={{ marginBottom: 12 }}>
              <KPI label="High" value={totalHigh} trend="+8 vs 昨" trendDir="up" sparkData={[3,5,8,12,18,22,28,32,35,totalHigh]} sparkColor="var(--high)" />
              <KPI label="Med" value={totalMed} trend="-2" trendDir="down" sparkData={[12,11,10,11,10,9,9,9,9,totalMed]} sparkColor="var(--med)" />
              <KPI label="MTTR" value="42m" trend="-6m" trendDir="down" sparkData={[55,52,48,50,47,46,44,43,42,42]} sparkColor="var(--ok)" />
              <KPI label="健康度" value="87%" trend="持平" trendDir="flat" sparkData={[88,87,89,88,87,88,87,87,87,87]} sparkColor="var(--text-3)" />
            </div>
          )}

          <DetailPanel cluster={selected} onOpenPipeline={() => setView('pipeline')} view={view} onBack={() => setView('detail')} />
        </div>
      </div>

      {/* AGENT */}
      {agentVisible && <AgentPanel cluster={selected} onClose={() => setAgentVisible(false)} position={agentPos} onOpenPipeline={() => setView('pipeline')} />}

      {/* TWEAKS PANEL */}
      <TweaksPanel title="Tweaks">
        <TweakSection title="主題">
          <TweakRadio label="深淺色" value={tweaks.theme} onChange={v => setTweak('theme', v)}
            options={[{ value: 'light', label: '淺' }, { value: 'dark', label: '深' }]} />
        </TweakSection>
        <TweakSection title="資訊密度">
          <TweakRadio label="密度" value={tweaks.density} onChange={v => setTweak('density', v)}
            options={[{ value: 'compact', label: 'Compact' }, { value: 'comfortable', label: 'Comfort' }]} />
        </TweakSection>
        <TweakSection title="左側列表">
          <TweakRadio label="模式" value={tweaks.listMode} onChange={v => setTweak('listMode', v)}
            options={[{ value: 'cluster', label: '群集' }, { value: 'timeline', label: '時間軸' }, { value: 'flat', label: '清單' }]} />
        </TweakSection>
        <TweakSection title="顏色強度">
          <TweakSlider label="飽和度" value={tweaks.saturation} onChange={v => setTweak('saturation', v)} min={0.3} max={1.4} step={0.05} />
        </TweakSection>
        <TweakSection title="AI Agent 位置">
          <TweakRadio label="位置" value={tweaks.agentPosition} onChange={v => setTweak('agentPosition', v)}
            options={[{ value: 'side', label: '側邊' }, { value: 'bottom', label: '底部' }, { value: 'floating', label: '浮動' }]} />
        </TweakSection>
        <TweakSection title="Sparkline 樣式">
          <TweakRadio label="樣式" value={tweaks.sparkStyle} onChange={v => setTweak('sparkStyle', v)}
            options={[{ value: 'bars', label: '長條' }, { value: 'line', label: '折線' }, { value: 'dots', label: '點狀' }]} />
        </TweakSection>
        <TweakSection title="頂部 KPI">
          <TweakToggle label="顯示 KPI 卡" value={tweaks.showFloorMap} onChange={v => setTweak('showFloorMap', v)} />
        </TweakSection>
      </TweaksPanel>
    </div>
  );
}

// Variation C: Triage board
function TriageBoard({ clusters, selectedId, onSelect }) {
  const lanes = [
    { id: 'new', label: 'New', items: clusters.filter(c => !c.assignee) },
    { id: 'invest', label: 'Investigating', items: clusters.filter(c => c.assignee && c.assignee !== 'auto' && c.openCount > 0) },
    { id: 'resolved', label: 'Resolved', items: clusters.filter(c => c.openCount === 0 || c.assignee === 'auto') },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {lanes.map(lane => (
        <div key={lane.id}>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', padding: '4px 8px', display: 'flex', justifyContent: 'space-between' }}>
            <span>{lane.label}</span>
            <span className="mono">{lane.items.length}</span>
          </div>
          {lane.items.map(c => (
            <ClusterCard key={c.id} cluster={c} selected={c.id === selectedId} onClick={() => onSelect(c.id)} />
          ))}
          {lane.items.length === 0 && (
            <div style={{ padding: 8, fontSize: 11, color: 'var(--text-4)', textAlign: 'center', fontStyle: 'italic' }}>無</div>
          )}
        </div>
      ))}
    </div>
  );
}

window.App = App;
