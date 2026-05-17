// Reusable UI components for the alarm center

const Sparkline = ({ data, color = 'currentColor', width = 60, height = 18 }) => {
  if (!data || !data.length) return null;
  const max = Math.max(...data, 1);
  const stepX = width / (data.length - 1 || 1);
  const points = data.map((v, i) => `${i * stepX},${height - (v / max) * height}`).join(' ');
  const area = `0,${height} ${points} ${width},${height}`;
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <polygon points={area} fill={color} opacity="0.12" />
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};

const SparkBars = ({ data, max, style }) => {
  const m = max || Math.max(...data, 1);
  const s = style || (window.__sparkStyle || 'bars');
  if (s === 'line') {
    const w = 60, h = 14;
    const stepX = w / (data.length - 1 || 1);
    const points = data.map((v, i) => `${i * stepX},${h - (v / m) * h}`).join(' ');
    return (
      <svg width={w} height={h} style={{ display: 'inline-block', verticalAlign: 'middle' }}>
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.85" />
      </svg>
    );
  }
  if (s === 'dots') {
    return (
      <span className="spark" style={{ alignItems: 'center' }}>
        {data.map((v, i) => (
          <span key={i} style={{ width: 3, height: 3, borderRadius: '50%', background: 'currentColor', opacity: 0.3 + 0.7 * (v / m), display: 'inline-block', margin: '0 0.5px' }} />
        ))}
      </span>
    );
  }
  return (
    <span className="spark">
      {data.map((v, i) => (
        <span key={i} style={{ height: `${Math.max(2, (v / m) * 14)}px` }} />
      ))}
    </span>
  );
};

const SeverityTag = ({ sev }) => (
  <span className="sev-tag">{sev.toUpperCase()}</span>
);

const Avatar = ({ name, size = 22 }) => {
  if (!name) {
    return (
      <span className="assignee-empty" style={{ width: size, height: size }}>
        <Icon name="plus" size={10} />
      </span>
    );
  }
  if (name === 'auto') {
    return (
      <span className="assignee" style={{ width: size, height: size, background: 'oklch(95% 0.02 155)', color: 'oklch(45% 0.13 155)' }} title="Auto-resolved">
        <Icon name="zap" size={10} />
      </span>
    );
  }
  return (
    <span className="assignee" style={{ width: size, height: size }}>{name}</span>
  );
};

const ClusterCard = ({ cluster, selected, onClick }) => {
  const { fmtAgo } = window.MOCK;
  return (
    <div className={`cluster sev-${cluster.severity} ${selected ? 'selected' : ''}`} onClick={onClick}>
      <div className="cluster-head">
        <div className="sev-bar"></div>
        <div className="cluster-main">
          <div className="cluster-top">
            <SeverityTag sev={cluster.severity} />
            <span className="cluster-tool">{cluster.tool}</span>
            <span className="cluster-area">· {cluster.area}</span>
            <span className="cluster-time">{fmtAgo(cluster.lastAt)}</span>
          </div>
          <div className="cluster-summary" dangerouslySetInnerHTML={{ __html: cluster.summary }} />
          <div className="cluster-meta">
            <span className="cluster-count">
              <span className="cluster-count-pill">×{cluster.count}</span>
              {cluster.openCount} open
              {cluster.ackCount > 0 && <span style={{ color: 'var(--text-4)' }}> · {cluster.ackCount} ack</span>}
            </span>
            <SparkBars data={cluster.spark} />
          </div>
        </div>
        <div className="cluster-side">
          <Avatar name={cluster.assignee} />
        </div>
      </div>
    </div>
  );
};

const TimelineList = ({ clusters, selectedId, onSelect }) => {
  const { fmtTime } = window.MOCK;
  // group by time bucket
  const groups = {};
  clusters.forEach(c => {
    const m = Math.floor((window.MOCK.NOW - c.lastAt) / 60000);
    const bucket = m < 15 ? 'Last 15 min' : m < 60 ? 'Last hour' : m < 180 ? '1–3 hours ago' : 'Earlier';
    (groups[bucket] = groups[bucket] || []).push(c);
  });
  return (
    <div className="timeline">
      {Object.entries(groups).map(([label, items]) => (
        <div key={label} className="tl-group">
          <div className="tl-label">{label}</div>
          {items.map(c => (
            <div
              key={c.id}
              className={`tl-item sev-${c.severity}`}
              onClick={() => onSelect(c.id)}
              style={selectedId === c.id ? { background: 'var(--accent-bg)' } : {}}
            >
              <div className="tl-time">{fmtTime(c.lastAt)} · {c.tool}</div>
              <div className="tl-title">{c.title}</div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
};

const FlatList = ({ clusters, selectedId, onSelect }) => {
  const { fmtAgo } = window.MOCK;
  // Expand each cluster into individual rows for "flat" mode (showing many)
  const rows = [];
  clusters.forEach(c => {
    const n = Math.min(c.count, 4);
    for (let i = 0; i < n; i++) {
      rows.push({
        id: `${c.id}-${i}`,
        clusterId: c.id,
        tool: c.tool,
        sev: c.severity,
        title: c.title,
        time: window.MOCK.minsAgo(((window.MOCK.NOW - c.firstAt) / 60000) * (1 - i / (n + 1))),
      });
    }
  });
  return (
    <>
      {rows.map(r => (
        <div
          key={r.id}
          className={`flat-row sev-${r.sev}`}
          onClick={() => onSelect(r.clusterId)}
          style={selectedId === r.clusterId ? { borderColor: 'var(--accent)' } : {}}
        >
          <div className="sev-bar"></div>
          <div className="flat-main">
            <div className="flat-title">
              <SeverityTag sev={r.sev} />{' '}
              <span className="mono" style={{ fontWeight: 600 }}>{r.tool}</span>{' '}
              <span style={{ color: 'var(--text-2)' }}>{r.title}</span>
            </div>
            <div className="flat-meta">{fmtAgo(r.time)} ago · OPEN</div>
          </div>
        </div>
      ))}
    </>
  );
};

const FloorMap = ({ selectedTool, onSelect }) => {
  const { FLOORMAP } = window.MOCK;
  const bays = ['A', 'B', 'C'];
  return (
    <div>
      {bays.map(bay => {
        const tools = FLOORMAP.filter(t => t.bay === bay);
        return (
          <div key={bay} style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 10, color: 'var(--text-3)', marginBottom: 4, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              BAY-{bay}
            </div>
            <div className="floormap" style={{ gridTemplateColumns: `repeat(${tools.length}, 1fr)` }}>
              {tools.map(t => (
                <div
                  key={t.id}
                  className={`tool-cell ${t.status} ${selectedTool === t.id ? 'selected' : ''}`}
                  onClick={() => onSelect && onSelect(t.id)}
                  title={`${t.id} · ${t.status} · util ${t.util}%`}
                >
                  <div className="tool-cell-id">{t.id.replace('EQP-', '')}</div>
                  <div className="tool-cell-bot">
                    <span style={{ color: 'var(--text-3)' }}>{t.util > 0 ? `${t.util}%` : 'idle'}</span>
                    {t.count && <strong style={{ fontFamily: 'var(--font-mono)' }}>×{t.count}</strong>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
      <div className="floor-legend">
        <span className="floor-legend-item"><span className="floor-legend-sw" style={{ background: 'var(--ok-bg)', border: '1px solid oklch(85% 0.05 155)' }}></span>OK</span>
        <span className="floor-legend-item"><span className="floor-legend-sw" style={{ background: 'var(--low-bg)', border: '1px solid var(--low-border)' }}></span>Low</span>
        <span className="floor-legend-item"><span className="floor-legend-sw" style={{ background: 'var(--med-bg)', border: '1px solid var(--med-border)' }}></span>Medium</span>
        <span className="floor-legend-item"><span className="floor-legend-sw" style={{ background: 'var(--high-bg)', border: '1px solid var(--high-border)' }}></span>High</span>
        <span className="floor-legend-item"><span className="floor-legend-sw" style={{ background: 'var(--bg-soft)', border: '1px solid var(--border)', opacity: 0.5 }}></span>Idle</span>
      </div>
    </div>
  );
};

const KPI = ({ label, value, trend, trendDir, sparkData, sparkColor }) => (
  <div className="kpi">
    <div className="kpi-label">{label}</div>
    <div className="kpi-value">{value}</div>
    {trend && (
      <div className={`kpi-trend trend-${trendDir}`}>
        <Icon name={trendDir === 'up' ? 'arrowUp' : trendDir === 'down' ? 'arrowDown' : 'arrowRight'} size={11} />
        {trend}
      </div>
    )}
    {sparkData && (
      <div className="kpi-spark">
        <Sparkline data={sparkData} color={sparkColor || 'var(--text-3)'} width={120} height={22} />
      </div>
    )}
  </div>
);

Object.assign(window, {
  Sparkline, SparkBars, SeverityTag, Avatar,
  ClusterCard, TimelineList, FlatList,
  FloorMap, KPI,
});
