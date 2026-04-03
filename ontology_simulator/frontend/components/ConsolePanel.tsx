"use client";
import { useEffect, useRef } from "react";
import { LogEntry, LogType } from "@/hooks/useConsole";

const TYPE_STYLE: Record<LogType, string> = {
  SYSTEM:  "text-slate-400",
  WS:      "text-sky-400",
  API_REQ: "text-yellow-400",
  API_RES: "text-green-400",
  USER:    "text-slate-300",
  TRACE:   "text-purple-400",
  ERROR:   "text-red-400",
};

const TYPE_TAG: Record<LogType, string> = {
  SYSTEM:  "SYS",
  WS:      " WS",
  API_REQ: "REQ",
  API_RES: "RES",
  USER:    "USR",
  TRACE:   "TRC",
  ERROR:   "ERR",
};

export default function ConsolePanel({
  logs,
  onClear,
  isOpen,
  onToggle,
}: {
  logs: LogEntry[];
  onClear: () => void;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs, isOpen]);

  return (
    <div className="flex flex-col bg-[#0f172a] overflow-hidden border-t border-slate-700">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 h-8 bg-[#1e293b] border-b border-slate-700 shrink-0">
        <button
          onClick={onToggle}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity"
        >
          {/* Terminal icon */}
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none"
               stroke="#38bdf8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>
          </svg>
          <span className="text-[10px] font-mono font-bold text-slate-300 tracking-widest">
            SYSTEM TRACE CONSOLE
          </span>
          {/* log count badge when collapsed */}
          {!isOpen && logs.length > 0 && (
            <span className="text-[9px] font-mono bg-slate-700 text-slate-400 px-1.5 py-0.5 rounded">
              {logs.length}
            </span>
          )}
          {/* chevron */}
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="ml-1 text-slate-500">
            {isOpen
              ? <path d="M1 3l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              : <path d="M1 7l4-4 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            }
          </svg>
        </button>

        <div className="flex items-center gap-3">
          {(["WS","REQ","RES","TRC","ERR"] as const).map(tag => {
            const type = ({ WS:"WS", REQ:"API_REQ", RES:"API_RES", TRC:"TRACE", ERR:"ERROR" } as Record<string,LogType>)[tag];
            return (
              <span key={tag} className={`text-[10px] font-mono ${TYPE_STYLE[type]}`}>{tag}</span>
            );
          })}
          <button
            onClick={onClear}
            className="text-[10px] font-mono text-slate-500 hover:text-slate-300 transition-colors uppercase tracking-wider"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Log lines — hidden when collapsed */}
      {isOpen && (
        <div className="console-scroll h-28 overflow-y-auto px-3 py-2 font-mono text-[11px] leading-5 space-y-0.5">
          {logs.length === 0 && (
            <span className="text-slate-600">— waiting for events —</span>
          )}
          {logs.map(entry => (
            <div key={entry.id} className="flex gap-2 whitespace-nowrap overflow-hidden">
              <span className="text-slate-600 shrink-0">[{entry.ts}]</span>
              <span className={`shrink-0 font-bold ${TYPE_STYLE[entry.type]}`}>
                [{TYPE_TAG[entry.type]}]
              </span>
              <span className={`truncate ${TYPE_STYLE[entry.type]}`}>
                {entry.text}
              </span>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}
