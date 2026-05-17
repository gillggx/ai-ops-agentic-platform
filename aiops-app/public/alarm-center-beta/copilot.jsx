// copilot.jsx — Copilot chat-stream view (uses shared topbar)
const { useState, useEffect, useRef } = React;

const CIc = {
  brand: (p={}) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L13.4 7.6 19 9 13.4 10.4 12 16 10.6 10.4 5 9 10.6 7.6z"/></svg>,
  check: (p={}) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>,
  alert: (p={}) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>,
  user: (p={}) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>,
  send: (p={}) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2" fill="currentColor"/></svg>,
  undo: (p={}) => <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-15-6.7L3 13"/></svg>,
  eye: (p={}) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>,
  zap: (p={}) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor"/></svg>
};

function AutoCard({ card }) {
  return (
    <div className="auto-card">
      <div className="auto-card-icon"><CIc.check size={14} /></div>
      <div>
        <div className="auto-card-title">{card.title}</div>
        <div className="auto-card-sub">{card.sub}</div>
      </div>
      <div className="auto-card-meta">
        <span>{card.meta}</span>
        <button className="undo"><CIc.undo /> Undo</button>
      </div>
    </div>
  );
}

function TakeoverCard({ msg }) {
  return (
    <div className="takeover-card">
      <div className="takeover-card-head">
        <span className="takeover-tag"><CIc.alert size={11} /> Takeover required</span>
        <span className="takeover-conf">Confidence <strong>{msg.conf}%</strong> · threshold 75%</span>
      </div>
      <div className="takeover-title">{msg.headline}</div>
      <div className="takeover-body" dangerouslySetInnerHTML={{ __html: msg.body }} />
      <div className="takeover-opts">
        {msg.options.map(o => (
          <button key={o.key} className={`takeover-opt ${o.recommended ? 'recommended' : ''}`}>
            <div className="takeover-opt-key">
              Option {o.key}
              {o.recommended && <span className="takeover-opt-rec-tag">Recommended</span>}
            </div>
            <div className="takeover-opt-title">{o.title}</div>
            <div className="takeover-opt-sub">{o.sub}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

function Message({ m }) {
  if (m.type === 'time-divider') {
    return <div className="tm-divider"><span>{m.label}</span></div>;
  }
  if (m.type === 'user') {
    return (
      <div className="msg user">
        <div>
          <div className="msg-head"><span className="ts">{m.time}</span><span className="nm">You</span></div>
          <div className="msg-text">{m.text}</div>
        </div>
        <div className="msg-av"><CIc.user size={14} /></div>
      </div>
    );
  }
  if (m.type === 'takeover') {
    return (
      <div className="msg">
        <div className="msg-av takeover"><CIc.alert size={15} /></div>
        <div className="msg-body">
          <div className="msg-head">
            <span className="nm">Copilot</span>
            <span className="ts">{m.time}</span>
          </div>
          <TakeoverCard msg={m} />
        </div>
      </div>
    );
  }
  return (
    <div className="msg">
      <div className="msg-av"><CIc.brand size={15} /></div>
      <div className="msg-body">
        <div className="msg-head">
          <span className="nm">Copilot</span>
          <span className="ts">{m.time}</span>
        </div>
        <div className="msg-text" dangerouslySetInnerHTML={{ __html: m.text }} />
        {m.autoCard && <AutoCard card={m.autoCard} />}
        {m.dataBlock && <div className="data-block">{m.dataBlock}</div>}
        {m.followup && <div className="msg-text" style={{ marginTop: 8 }} dangerouslySetInnerHTML={{ __html: m.followup }} />}
        {m.chips && (
          <div className="chips">
            {m.chips.map((c, i) => (
              <button key={i} className={`chip-s ${c.kind === 'primary' ? 'primary' : ''}`}>{c.label}</button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Right() {
  // Build "watching now" from MACHINES
  const watching = window.MACHINES
    .filter(m => m.status !== 'auto' && m.status !== 'idle' || (m.confidence != null && m.confidence < 95 && m.confidence != null))
    .slice(0, 6)
    .map(m => ({
      id: m.id,
      label: m.summary.replace(/<[^>]+>/g, '').slice(0, 32),
      conf: m.confidence ?? 0,
      status: m.status,
      meta: m.needs ? m.needs.title.slice(0, 24) : '監看中',
      age: m.started || 'now'
    }));

  return (
    <div className="right">
      <h3>I'm watching now</h3>
      {watching.map(w => (
        <div key={w.id} className={`watch-card ${w.status === 'takeover' ? 'takeover' : w.status === 'warn' ? 'warn' : w.status === 'assist' ? 'assist' : ''}`}>
          <div>
            <div className="watch-tool">{w.id}</div>
            <div className="watch-meta">{w.meta} · {w.age}</div>
          </div>
          <div className={`watch-conf ${w.conf >= 85 ? 'high' : w.conf >= 70 ? 'med' : 'low'}`}>{w.conf}%</div>
          <div className="watch-progress">
            <div className={`watch-progress-fill ${w.status === 'takeover' ? 'takeover' : w.status === 'warn' ? 'warn' : w.status === 'assist' ? 'assist' : ''}`}
                 style={{ width: `${w.conf}%` }}></div>
          </div>
        </div>
      ))}

      <div className="divider-h"></div>

      <h3>Autonomy this shift</h3>
      <div className="trust">
        <div className="trust-row">
          <span className="trust-label">Trust score</span>
          <span className="trust-value">{window.SHIFT_STATS.trust}%</span>
        </div>
        <div className="trust-bar"><div className="trust-fill" style={{ width: `${window.SHIFT_STATS.trust}%` }}></div></div>
        <div className="trust-sub">過去 7 天 Copilot 決策中 <strong>0 件</strong>被你撤銷。</div>
      </div>

      <div className="shift-stats">
        <div className="shift-stat">
          <div className="shift-stat-label">Auto-fixed</div>
          <div className="shift-stat-value auto-c">14</div>
          <div className="shift-stat-sub">in 55m</div>
        </div>
        <div className="shift-stat">
          <div className="shift-stat-label">Suppressed</div>
          <div className="shift-stat-value">{window.SHIFT_STATS.suppressed}</div>
          <div className="shift-stat-sub">noise alarms</div>
        </div>
        <div className="shift-stat">
          <div className="shift-stat-label">Saved</div>
          <div className="shift-stat-value auto-c">{window.SHIFT_STATS.timeSaved}</div>
          <div className="shift-stat-sub">vs manual</div>
        </div>
        <div className="shift-stat">
          <div className="shift-stat-label">Cost avoided</div>
          <div className="shift-stat-value">{window.SHIFT_STATS.cost}</div>
          <div className="shift-stat-sub">est. lot save</div>
        </div>
      </div>
    </div>
  );
}

function CenterStream() {
  const streamRef = useRef(null);
  useEffect(() => {
    if (streamRef.current) streamRef.current.scrollTop = streamRef.current.scrollHeight;
  }, []);

  return (
    <div className="center">
      <div className="center-head">
        <div>
          <div className="center-head-title">
            <span className="av"><CIc.brand size={15} /></span>
            <span>Copilot</span>
          </div>
          <div className="center-head-sub">監看 30 台機台 · 本班次已自動處理 {window.SHIFT_STATS.autoHandled} 件 · {window.SHIFT_STATS.needsYou} 件需要你</div>
        </div>
        <div className="center-head-actions">
          <button className="icon-btn" title="Watch live"><CIc.eye /></button>
          <button className="icon-btn" title="Audit log"><CIc.zap /></button>
        </div>
      </div>

      <div className="stream" ref={streamRef}>
        <div className="stream-inner">
          {window.COPILOT_MESSAGES.map((m, i) => <Message key={i} m={m} />)}
        </div>
      </div>

      <div className="chat-input-wrap">
        <div className="chat-input">
          <div className="chat-input-row">
            <CIc.brand size={15} />
            <input placeholder="問 Copilot 或下指令⋯ 例如「show EQP-04 trend」「pause autopilot」" />
            <span className="kbd">⌘K</span>
            <button className="chat-input-send"><CIc.send size={13} /></button>
          </div>
          <div className="chat-input-hints">
            <button className="chat-input-hint">列出今天所有 takeover 決定</button>
            <button className="chat-input-hint">why did you suppress EQP-09?</button>
            <button className="chat-input-hint">show fab health</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// === App ===
const TWEAK_DEFAULTS_COPILOT = /*EDITMODE-BEGIN*/{
  "saturation": 1.0,
  "showRight": true
}/*EDITMODE-END*/;

function CopilotApp() {
  const [tweaks, setTweak] = (window.useTweaks ? window.useTweaks(TWEAK_DEFAULTS_COPILOT) : [TWEAK_DEFAULTS_COPILOT, () => {}]);

  useEffect(() => {
    document.documentElement.style.setProperty('--sat', tweaks.saturation);
  }, [tweaks.saturation]);

  const cols = tweaks.showRight ? 'minmax(0, 1fr) 340px' : 'minmax(0, 1fr)';

  return (
    <>
      <div className="shell-chat" style={{ gridTemplateColumns: cols }}>
        <window.TopBar active="copilot" />
        <CenterStream />
        {tweaks.showRight && <Right />}
      </div>
      {window.TweaksPanel && (
        <window.TweaksPanel title="Tweaks">
          <window.TweakSection title="Layout">
            <window.TweakToggle label="顯示右側面板" value={tweaks.showRight} onChange={v => setTweak('showRight', v)} />
          </window.TweakSection>
          <window.TweakSection title="Visuals">
            <window.TweakSlider label="Saturation" value={tweaks.saturation} min={0.4} max={1.4} step={0.05}
              onChange={v => setTweak('saturation', v)} />
          </window.TweakSection>
        </window.TweaksPanel>
      )}
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<CopilotApp />);
