"use client";
import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { MachineState } from "@/lib/types";

function getApiUrl() {
  if (typeof window === "undefined") return "http://localhost:8001/api/v1";
  const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  return isLocal ? `http://${window.location.hostname}:8001/api/v1` : `${window.location.origin}/simulator-api/api/v1`;
}

// ── Sensor name & unit mappings ───────────────────────────────
const DC_GROUPS = [
  {
    label: "Vacuum",
    sensors: [
      { key: "sensor_01", name: "Chamber_Press",  unit: "mTorr" },
      { key: "sensor_02", name: "Foreline_Press", unit: "mTorr" },
      { key: "sensor_03", name: "He_Cool_Press",  unit: "Torr"  },
      { key: "sensor_04", name: "Sensor_04",      unit: ""      },
      { key: "sensor_05", name: "Sensor_05",      unit: ""      },
      { key: "sensor_06", name: "Sensor_06",      unit: ""      },
      { key: "sensor_07", name: "Sensor_07",      unit: ""      },
      { key: "sensor_08", name: "Sensor_08",      unit: ""      },
      { key: "sensor_09", name: "Sensor_09",      unit: ""      },
      { key: "sensor_10", name: "Sensor_10",      unit: ""      },
    ],
  },
  {
    label: "Thermal",
    sensors: [
      { key: "sensor_11", name: "ESC_Zone1_Temp",  unit: "°C" },
      { key: "sensor_12", name: "ESC_Zone2_Temp",  unit: "°C" },
      { key: "sensor_13", name: "Upper_Electrode", unit: "°C" },
      { key: "sensor_14", name: "Sensor_14",       unit: ""   },
      { key: "sensor_15", name: "Sensor_15",       unit: ""   },
      { key: "sensor_16", name: "Sensor_16",       unit: ""   },
      { key: "sensor_17", name: "Sensor_17",       unit: ""   },
      { key: "sensor_18", name: "Sensor_18",       unit: ""   },
      { key: "sensor_19", name: "Sensor_19",       unit: ""   },
      { key: "sensor_20", name: "Sensor_20",       unit: ""   },
    ],
  },
  {
    label: "RF Power",
    sensors: [
      { key: "sensor_21", name: "Source_Power_HF", unit: "W" },
      { key: "sensor_22", name: "Bias_Power_LF",   unit: "W" },
      { key: "sensor_23", name: "Vpp_Voltage",     unit: "V" },
      { key: "sensor_24", name: "Sensor_24",       unit: ""  },
      { key: "sensor_25", name: "Sensor_25",       unit: ""  },
      { key: "sensor_26", name: "Sensor_26",       unit: ""  },
      { key: "sensor_27", name: "Sensor_27",       unit: ""  },
      { key: "sensor_28", name: "Sensor_28",       unit: ""  },
      { key: "sensor_29", name: "Sensor_29",       unit: ""  },
      { key: "sensor_30", name: "Sensor_30",       unit: ""  },
    ],
  },
];

// ── Accordion section ─────────────────────────────────────────
function SensorSection({
  label, sensors, params,
}: {
  label: string;
  sensors: { key: string; name: string; unit: string }[];
  params: Record<string, number>;
}) {
  const [open, setOpen] = useState(label === "Vacuum");

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden mb-2">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2 bg-slate-50
                   hover:bg-slate-100 text-left transition-colors"
      >
        <span className="text-[11px] font-semibold text-slate-500 tracking-wider uppercase">
          {label}
        </span>
        {open
          ? <ChevronDown   size={13} className="text-slate-400" />
          : <ChevronRight  size={13} className="text-slate-400" />}
      </button>
      {open && (
        <div className="divide-y divide-slate-100">
          {sensors.map(({ key, name, unit }) => (
            <div key={key} className="flex justify-between items-center px-3 py-1.5 text-[12px]">
              <span className="text-slate-500 font-mono">{name}</span>
              <span className="font-mono text-slate-800 value-cell">
                {((params[key] ?? 0) as number).toFixed(4)}
                {unit && <span className="text-slate-400 text-[10px] ml-1">{unit}</span>}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── DC Telemetry Inspector (right column) ─────────────────────
export default function DCInspector({ machine }: { machine: MachineState | null }) {
  const [dcData,  setDcData]  = useState<Record<string, unknown> | null>(null);
  const [spcData, setSpcData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const lotId = machine?.lotId ?? null;

  useEffect(() => {
    if (!lotId) { setDcData(null); setSpcData(null); return; }
    setLoading(true);
    Promise.all([
      fetch(`${getApiUrl()}/analytics/history?targetID=${lotId}&objectName=DC&limit=1`).then(r => r.json()),
      fetch(`${getApiUrl()}/analytics/history?targetID=${lotId}&objectName=SPC&limit=1`).then(r => r.json()),
    ])
      .then(([dcRows, spcRows]: [unknown[], unknown[]]) => {
        setDcData((dcRows as Record<string, unknown>[])[dcRows.length - 1] ?? null);
        setSpcData((spcRows as Record<string, unknown>[])[spcRows.length - 1] ?? null);
      })
      .catch(() => { setDcData(null); setSpcData(null); })
      .finally(() => setLoading(false));
  }, [lotId]);

  if (!machine) {
    return (
      <div className="h-full flex items-center justify-center p-4">
        <p className="text-slate-400 text-sm text-center">No machine selected</p>
      </div>
    );
  }

  if (!lotId) {
    return (
      <div className="h-full flex items-center justify-center p-4">
        <p className="text-slate-400 text-sm text-center">Machine is idle</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center gap-2 text-slate-400">
        <Loader2 size={14} className="animate-spin" />
        <span className="text-sm">Loading…</span>
      </div>
    );
  }

  const spcStatus = String(spcData?.spc_status ?? "PASS");
  const isWarning = spcStatus === "OOC";
  const spcCharts = (spcData?.charts ?? {}) as Record<string, { value: number; ucl: number; lcl: number }>;
  const dcParams  = (dcData?.parameters ?? {}) as Record<string, number>;

  return (
    <div className="h-full flex flex-col overflow-hidden">

      {/* SPC status banner */}
      <div className={`px-4 py-2.5 border-b flex items-center gap-2 shrink-0 ${
        isWarning ? "bg-amber-50 border-amber-200" : "bg-emerald-50 border-emerald-200"
      }`}>
        <span className={`w-2 h-2 rounded-full ${isWarning ? "bg-amber-500" : "bg-emerald-500"}`} />
        <span className={`text-[12px] font-semibold ${isWarning ? "text-amber-700" : "text-emerald-700"}`}>
          {isWarning ? "SPC WARNING" : "IN CONTROL"}
        </span>
        {isWarning && (
          <span className="ml-auto text-[10px] text-amber-600 font-medium">
            {Object.entries(spcCharts).filter(([, c]) => c.value > c.ucl || c.value < c.lcl).length} chart(s) OOC
          </span>
        )}
      </div>

      {/* SPC chart detail rows (warning only) */}
      {isWarning && Object.entries(spcCharts).length > 0 && (
        <div className="px-4 py-2 border-b border-amber-100 space-y-1 shrink-0">
          {Object.entries(spcCharts).map(([name, c]) => {
            const ooc = c.value > c.ucl || c.value < c.lcl;
            return (
              <div key={name} className={`flex justify-between text-[11px] ${ooc ? "text-amber-700" : "text-slate-500"}`}>
                <span className="font-mono">{name.replace("_chart","").toUpperCase()}</span>
                <span className="font-mono">
                  {c.value.toFixed(4)}
                  <span className="text-slate-400"> / {c.ucl.toFixed(4)}</span>
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* DC sensor accordion */}
      <div className="flex-1 overflow-y-auto p-3">
        <p className="text-[10px] text-slate-400 font-semibold tracking-widest uppercase mb-2">
          DC Telemetry · {lotId}
        </p>
        {DC_GROUPS.map(group => (
          <SensorSection
            key={group.label}
            label={group.label}
            sensors={group.sensors}
            params={dcParams}
          />
        ))}
      </div>
    </div>
  );
}
