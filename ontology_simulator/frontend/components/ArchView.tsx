"use client";
/**
 * ArchView — MES Ontology System Architecture Diagram
 * Shows the layered architecture: Equipment → WIP → Subsystems → Ontology Store
 * Live stats fetched from the backend.
 */
import { useEffect, useState } from "react";

function getApiBase() {
  if (typeof window === "undefined") return "http://localhost:8001";
  const local = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  return local ? `http://${window.location.hostname}:8001` : `${window.location.origin}/simulator-api`;
}

interface Stats {
  tools_busy: number;
  tools_total: number;
  lots_processing: number;
  lots_total: number;
  spc_ooc: number;
  orphans: number;
  snapshots: Record<string, number>; // {APC: N, DC: N, SPC: N, RECIPE: N}
}

async function fetchStats(): Promise<Stats> {
  const base = getApiBase();
  const [status, spcOoc, orphans] = await Promise.all([
    fetch(`${base}/api/v1/status`).then(r => r.json()).catch(() => null),
    fetch(`${base}/api/v2/ontology/indices/SPC?status=OOC&limit=1`).then(r => r.json()).catch(() => null),
    fetch(`${base}/api/v2/ontology/orphans?limit=5`).then(r => r.json()).catch(() => null),
  ]);

  const counts: Record<string, number> = {};
  for (const type of ["APC", "DC", "SPC", "RECIPE"]) {
    const res = await fetch(`${base}/api/v2/ontology/indices/${type}?limit=1`)
      .then(r => r.json()).catch(() => null);
    counts[type] = res?.count ?? 0;
  }

  return {
    tools_busy:      status?.tools_busy   ?? 0,
    tools_total:     status?.tools_total  ?? 10,
    lots_processing: status?.lots_processing ?? 0,
    lots_total:      status?.lots_total   ?? 20,
    spc_ooc:         spcOoc?.count        ?? 0,
    orphans:         orphans?.total_orphans ?? 0,
    snapshots:       counts,
  };
}

// ── SVG Architecture Diagram ───────────────────────────────────────────────────

const W = 820, H = 540;

// Layer Y positions
const LAYERS = {
  EQ:   { y: 60,  h: 90, label: "EQUIPMENT LAYER",   sub: "10 Physical Tools",    color: "#475569", fill: "#1e293b" },
  WIP:  { y: 200, h: 90, label: "WIP LAYER",          sub: "Lot Queue (MongoDB)",  color: "#3b82f6", fill: "#1e3a8a22" },
  SUB:  { y: 340, h: 90, label: "SUBSYSTEM LAYER",    sub: "Object Registry",      color: "#8b5cf6", fill: "#1e1b4b22" },
  STORE:{ y: 480, h: 44, label: "ONTOLOGY STORE",     sub: "object_snapshots",     color: "#0891b2", fill: "#0c4a6e22" },
};

const EQ_NODES = ["ETCH-LAM", "PHO-ASML", "CVD-AMAT", "IMP-VARIAN"];
const SUB_NODES = [
  { key: "RECIPE", color: "#22c55e", x: 180 },
  { key: "APC",    color: "#38bdf8", x: 340 },
  { key: "DC",     color: "#818cf8", x: 500 },
  { key: "SPC",    color: "#f59e0b", x: 660 },
];

function Arrow({ x1, y1, x2, y2, color = "#334155", label }: {
  x1: number; y1: number; x2: number; y2: number; color?: string; label?: string;
}) {
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  return (
    <g>
      <defs>
        <marker id={`arr-${color.replace("#","")}`} markerWidth="6" markerHeight="6"
          refX="5" refY="3" orient="auto">
          <path d="M0,0 L0,6 L6,3 Z" fill={color} />
        </marker>
      </defs>
      <line x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={color} strokeWidth="1.5" strokeDasharray="5 3"
        markerEnd={`url(#arr-${color.replace("#","")})`} />
      {label && (
        <text x={mx + 4} y={my - 4} fill={color} fontSize={9}
          fontFamily="Inter,system-ui" fontWeight={600} letterSpacing="0.05em">
          {label}
        </text>
      )}
    </g>
  );
}

function LayerBox({ layer, children }: {
  layer: typeof LAYERS[keyof typeof LAYERS];
  children?: React.ReactNode;
}) {
  return (
    <g>
      <rect x={30} y={layer.y} width={W - 60} height={layer.h} rx={8}
        fill={layer.fill} stroke={layer.color} strokeWidth={1.5} />
      <text x={50} y={layer.y + 16} fill={layer.color}
        fontSize={9} fontWeight={700} fontFamily="Inter,system-ui" letterSpacing="0.12em">
        {layer.label}
      </text>
      <text x={50} y={layer.y + 29} fill="#475569"
        fontSize={8} fontFamily="Inter,system-ui">
        {layer.sub}
      </text>
      {children}
    </g>
  );
}

function StatBadge({ value, label, color, alert }: {
  value: number | string; label: string; color: string; alert?: boolean;
}) {
  return (
    <div className="flex flex-col items-center px-4 py-2 rounded-lg border"
      style={{ borderColor: alert && Number(value) > 0 ? "#ef4444" : color,
               background: alert && Number(value) > 0 ? "#450a0a55" : "#1e293b" }}>
      <span className="font-mono font-bold text-xl" style={{ color: alert && Number(value) > 0 ? "#ef4444" : color }}>
        {value}
      </span>
      <span className="text-[10px] text-slate-500 font-semibold tracking-widest uppercase mt-0.5">
        {label}
      </span>
    </div>
  );
}

export default function ArchView({ machineCount }: { machineCount?: number }) {
  const [stats, setStats]     = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchStats()
      .then(setStats)
      .finally(() => setLoading(false));

    const t = setInterval(() => fetchStats().then(setStats), 15000);
    return () => clearInterval(t);
  }, []);

  const busyCount = machineCount ?? stats?.tools_busy ?? 0;

  return (
    <div className="h-full overflow-y-auto bg-[#0b1120] flex flex-col"
      style={{ backgroundImage: "radial-gradient(#1e293b 1px, transparent 1px)", backgroundSize: "24px 24px" }}>

      {/* Header */}
      <div className="shrink-0 px-6 pt-4 pb-2 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-slate-200 tracking-wide">
            MES Ontology — System Architecture
          </h2>
          <p className="text-[10px] text-slate-500 mt-0.5">
            4-layer stack · Event-driven snapshots · Object-API registry
          </p>
        </div>
        {loading && (
          <span className="text-[10px] font-mono text-slate-600 animate-pulse">refreshing…</span>
        )}
      </div>

      {/* Live stat pills */}
      <div className="shrink-0 flex gap-3 px-6 pb-4 flex-wrap">
        <StatBadge value={busyCount}                       label="Tools Active"  color="#475569" />
        <StatBadge value={stats?.lots_processing ?? "—"}  label="Lots Running"  color="#3b82f6" />
        <StatBadge value={stats?.snapshots.RECIPE ?? "—"} label="Recipes"       color="#22c55e" />
        <StatBadge value={stats?.snapshots.APC    ?? "—"} label="APC Snaps"     color="#38bdf8" />
        <StatBadge value={stats?.snapshots.DC     ?? "—"} label="DC Snaps"      color="#818cf8" />
        <StatBadge value={stats?.snapshots.SPC    ?? "—"} label="SPC Snaps"     color="#f59e0b" />
        <StatBadge value={stats?.spc_ooc ?? "—"}          label="OOC Events"    color="#ef4444" alert />
        <StatBadge value={stats?.orphans ?? "—"}          label="Orphan Links"  color="#f97316" alert />
      </div>

      {/* Architecture SVG */}
      <div className="flex-1 px-6 pb-6 min-h-0">
        <div className="w-full h-full bg-[#0d1626] rounded-xl border border-slate-800 overflow-hidden">
          <svg viewBox={`0 0 ${W} ${H + 60}`} className="w-full h-full" style={{ overflow: "visible" }}>
            <defs>
              <style>{`
                @keyframes flowPulse { 0%,100%{opacity:0.4} 50%{opacity:1} }
                .flow-arrow { animation: flowPulse 2.5s ease-in-out infinite; }
              `}</style>
            </defs>

            {/* ── EQUIPMENT LAYER ── */}
            <LayerBox layer={LAYERS.EQ}>
              {EQ_NODES.map((name, i) => {
                const nx = 160 + i * 160;
                return (
                  <g key={name}>
                    <rect x={nx - 55} y={LAYERS.EQ.y + 38} width={110} height={36}
                      rx={6} fill="#1e293b" stroke="#475569" strokeWidth={1.5} />
                    <text x={nx} y={LAYERS.EQ.y + 53} textAnchor="middle" fill="#94a3b8"
                      fontSize={8} fontWeight={700} fontFamily="Inter,system-ui" letterSpacing="0.1em">
                      {name}
                    </text>
                    <text x={nx} y={LAYERS.EQ.y + 65} textAnchor="middle" fill="#475569"
                      fontSize={7} fontFamily="'JetBrains Mono',monospace">
                      ×{i < 2 ? "2" : i === 2 ? "2" : "2"}
                    </text>
                  </g>
                );
              })}
              {/* WebSocket badge */}
              <rect x={W - 160} y={LAYERS.EQ.y + 38} width={110} height={36} rx={6}
                fill="#0f172a" stroke="#1d4ed8" strokeWidth={1.5} />
              <text x={W - 105} y={LAYERS.EQ.y + 53} textAnchor="middle" fill="#60a5fa"
                fontSize={8} fontWeight={700} fontFamily="Inter,system-ui" letterSpacing="0.1em">
                WebSocket
              </text>
              <text x={W - 105} y={LAYERS.EQ.y + 65} textAnchor="middle" fill="#3b82f6"
                fontSize={7} fontFamily="Inter,system-ui">
                Live events
              </text>
            </LayerBox>

            {/* ── Arrows: EQ → WIP ── */}
            <Arrow x1={W/2} y1={LAYERS.EQ.y + LAYERS.EQ.h} x2={W/2} y2={LAYERS.WIP.y}
              color="#3b82f6" label="TOOL_EVENT" />

            {/* ── WIP LAYER ── */}
            <LayerBox layer={LAYERS.WIP}>
              {/* Lot dots */}
              {Array.from({ length: 10 }, (_, i) => (
                <g key={i}>
                  <circle cx={140 + i * 58} cy={LAYERS.WIP.y + 56} r={20}
                    fill="#1e3a8a33" stroke="#3b82f6" strokeWidth={1.5} />
                  <text x={140 + i * 58} y={LAYERS.WIP.y + 52} textAnchor="middle" fill="#60a5fa"
                    fontSize={7} fontWeight={700} fontFamily="Inter,system-ui">
                    WIP
                  </text>
                  <text x={140 + i * 58} y={LAYERS.WIP.y + 63} textAnchor="middle" fill="#93c5fd"
                    fontSize={6} fontFamily="'JetBrains Mono',monospace">
                    LOT
                  </text>
                </g>
              ))}
              {/* "×20" label */}
              <text x={W - 70} y={LAYERS.WIP.y + 58} textAnchor="middle" fill="#1d4ed8"
                fontSize={18} fontWeight={800} fontFamily="Inter,system-ui">
                ×20
              </text>
            </LayerBox>

            {/* ── Arrows: WIP → Subsystems ── */}
            {SUB_NODES.map(n => (
              <Arrow key={n.key}
                x1={W / 2} y1={LAYERS.WIP.y + LAYERS.WIP.h}
                x2={n.x}   y2={LAYERS.SUB.y}
                color={n.color} />
            ))}

            {/* ── SUBSYSTEM LAYER ── */}
            <LayerBox layer={LAYERS.SUB}>
              {SUB_NODES.map(n => (
                <g key={n.key}>
                  <rect x={n.x - 62} y={LAYERS.SUB.y + 32} width={124} height={48}
                    rx={8} fill="#1e293b" stroke={n.color} strokeWidth={1.5} />
                  <text x={n.x} y={LAYERS.SUB.y + 50} textAnchor="middle" fill={n.color}
                    fontSize={9} fontWeight={700} fontFamily="Inter,system-ui" letterSpacing="0.12em">
                    {n.key}
                  </text>
                  <text x={n.x} y={LAYERS.SUB.y + 64} textAnchor="middle" fill="#64748b"
                    fontSize={8} fontFamily="'JetBrains Mono',monospace">
                    {stats?.snapshots[n.key] != null
                      ? `${stats.snapshots[n.key].toLocaleString()} snapshots`
                      : "…"}
                  </text>
                </g>
              ))}
              {/* Object-API Registry label */}
              <rect x={W - 200} y={LAYERS.SUB.y + 32} width={170} height={48} rx={8}
                fill="#0f172a" stroke="#6366f1" strokeWidth={1.5} strokeDasharray="4 2" />
              <text x={W - 115} y={LAYERS.SUB.y + 50} textAnchor="middle" fill="#818cf8"
                fontSize={8} fontWeight={700} fontFamily="Inter,system-ui" letterSpacing="0.1em">
                Object-API Registry
              </text>
              <text x={W - 115} y={LAYERS.SUB.y + 64} textAnchor="middle" fill="#4f46e5"
                fontSize={7} fontFamily="Inter,system-ui">
                /api/v2/ontology/…
              </text>
            </LayerBox>

            {/* ── Arrows: SUB → STORE ── */}
            <Arrow x1={W/2} y1={LAYERS.SUB.y + LAYERS.SUB.h} x2={W/2} y2={LAYERS.STORE.y}
              color="#0891b2" label="snapshot write" />

            {/* ── ONTOLOGY STORE ── */}
            <LayerBox layer={LAYERS.STORE}>
              {["events", "object_snapshots", "lots", "tools", "apc_state", "recipe_data"].map((coll, i) => (
                <g key={coll}>
                  <rect x={80 + i * 118} y={LAYERS.STORE.y + 12} width={108} height={22}
                    rx={4} fill="#0c4a6e33" stroke="#0891b2" strokeWidth={1} />
                  <text x={80 + i * 118 + 54} y={LAYERS.STORE.y + 26} textAnchor="middle"
                    fill="#67e8f9" fontSize={8} fontFamily="'JetBrains Mono',monospace" fontWeight={600}>
                    {coll}
                  </text>
                </g>
              ))}
            </LayerBox>

            {/* ── Context & Fanout API labels ── */}
            <rect x={30} y={LAYERS.STORE.y + LAYERS.STORE.h + 12} width={370} height={30}
              rx={6} fill="#0f172a" stroke="#334155" strokeWidth={1} />
            <text x={215} y={LAYERS.STORE.y + LAYERS.STORE.h + 22} textAnchor="middle"
              fill="#94a3b8" fontSize={8} fontFamily="Inter,system-ui" fontWeight={600}>
              Query Layer
            </text>
            <text x={215} y={LAYERS.STORE.y + LAYERS.STORE.h + 34} textAnchor="middle"
              fill="#475569" fontSize={7} fontFamily="'JetBrains Mono',monospace">
              /context · /fanout · /trajectory · /indices · /orphans
            </text>

            <rect x={420} y={LAYERS.STORE.y + LAYERS.STORE.h + 12} width={370} height={30}
              rx={6} fill="#0f172a" stroke="#334155" strokeWidth={1} />
            <text x={605} y={LAYERS.STORE.y + LAYERS.STORE.h + 22} textAnchor="middle"
              fill="#94a3b8" fontSize={8} fontFamily="Inter,system-ui" fontWeight={600}>
              Simulation Engine
            </text>
            <text x={605} y={LAYERS.STORE.y + LAYERS.STORE.h + 34} textAnchor="middle"
              fill="#475569" fontSize={7} fontFamily="'JetBrains Mono',monospace">
              MES Simulator · Station Agent · SPC Service · APC Model
            </text>
          </svg>
        </div>
      </div>
    </div>
  );
}
