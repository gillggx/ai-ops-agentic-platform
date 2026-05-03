"use client";

import { useEffect, useState, useRef } from "react";
import { FocusRef, RunsResponse } from "./types";

interface Args {
  from?:  string;          // ISO; default = 28 days ago
  to?:    string;          // ISO; default = now
  focus?: FocusRef | null;
  limit?: number;          // default 500 (server cap)
}

interface State {
  data:    RunsResponse | null;
  loading: boolean;
  error:   string | null;
  reload:  () => void;
}

/**
 * Fetches /api/ontology/topology/runs. Single-flight per query key,
 * abortable on unmount or arg change. No external SWR dep — pure useEffect.
 */
export function useTopologyRuns({ from, to, focus, limit }: Args): State {
  const [data,    setData]    = useState<RunsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [tick,    setTick]    = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const qs = new URLSearchParams();
    if (from)        qs.set("from", from);
    if (to)          qs.set("to", to);
    if (focus?.kind) qs.set("focus_kind", focus.kind);
    if (focus?.id)   qs.set("focus_id", focus.id);
    if (limit)       qs.set("limit", String(limit));

    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    setLoading(true);
    setError(null);

    fetch(`/api/ontology/topology/runs?${qs}`, { signal: ac.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`runs ${r.status}`);
        return r.json();
      })
      .then((body: RunsResponse) => {
        if (!ac.signal.aborted) setData(body);
      })
      .catch((err) => {
        if (ac.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
        setData(null);
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false);
      });

    return () => ac.abort();
  }, [from, to, focus?.kind, focus?.id, limit, tick]);

  return { data, loading, error, reload: () => setTick((t) => t + 1) };
}
