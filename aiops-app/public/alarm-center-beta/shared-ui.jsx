// shared-ui.jsx — shared <TopBar> used in all three modes

const SharedIc = {
  brand: (p={}) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M12 2L13.4 7.6 19 9 13.4 10.4 12 16 10.6 10.4 5 9 10.6 7.6z"/></svg>,
  pause: (p={}) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>,
  bell: (p={}) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>,
  cog: (p={}) => <svg width={p.size||14} height={p.size||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
};

function TopBar({ active }) {
  return (
    <div className="topbar">
      <div className="brand">
        <span className="brand-mark"></span>
        <span>Alarm Autopilot</span>
      </div>

      <div className="tabs">
        <a className={active === 'copilot' ? 'active' : ''} href="Alarm Autopilot.html">Copilot</a>
        <a className={active === 'machines' ? 'active' : ''} href="Machine Center.html">Machines</a>
        <a className={active === 'alarms' ? 'active' : ''} href="Alarm Center v2.html">Alarms</a>
      </div>

      <span className="auto-pill">
        <span className="auto-pill-dot"></span>
        <span className="lbl">Autopilot</span>
        <strong>ON</strong>
      </span>
    </div>
  );
}

window.TopBar = TopBar;
