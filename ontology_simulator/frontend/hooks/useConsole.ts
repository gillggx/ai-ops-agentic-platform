"use client";
import { useCallback, useRef, useState } from "react";

export type LogType = "SYSTEM" | "WS" | "API_REQ" | "API_RES" | "USER" | "TRACE" | "ERROR";

export interface LogEntry {
  id: number;
  ts: string;        // HH:MM:SS.mmm
  type: LogType;
  text: string;
}

const MAX_ENTRIES = 500;
let _seq = 0;

function nowTs(): string {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

export function useConsole() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const pausedRef = useRef(false);
  const bufferRef = useRef<LogEntry[]>([]);

  const addLog = useCallback((type: LogType, text: string) => {
    const entry: LogEntry = { id: _seq++, ts: nowTs(), type, text };
    if (pausedRef.current) {
      bufferRef.current.push(entry);
      return;
    }
    setLogs(prev => {
      const next = [...prev, entry];
      return next.length > MAX_ENTRIES ? next.slice(next.length - MAX_ENTRIES) : next;
    });
  }, []);

  const pause = useCallback(() => {
    pausedRef.current = true;
  }, []);

  const resume = useCallback(() => {
    pausedRef.current = false;
    const buffered = bufferRef.current.splice(0);
    if (buffered.length === 0) return;
    setLogs(prev => {
      const next = [...prev, ...buffered];
      return next.length > MAX_ENTRIES ? next.slice(next.length - MAX_ENTRIES) : next;
    });
  }, []);

  const clear = useCallback(() => {
    bufferRef.current = [];
    setLogs([]);
  }, []);

  return { logs, addLog, pause, resume, clear };
}
