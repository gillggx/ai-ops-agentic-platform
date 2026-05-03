/**
 * Derive the ontology graph from a list of runs.
 *
 * Each RUN contributes a 7-clique (lot ⨯ tool ⨯ step ⨯ recipe ⨯ apc ⨯ fdc ⨯ spc).
 * Co-occurrence count + alarm flag are accumulated per edge.
 */

import {
  Kind, KIND_ORDER,
  RunRecord, ObjNode, Link, FocusRef,
} from "./types";

interface DerivedOntology {
  objs:      Map<string, ObjNode>;       // id → node
  links:     Link[];
  neighbors: (id: string) => Set<string>;
  byKind:    Record<Kind, ObjNode[]>;    // sorted by alarms desc, then runs desc
}

/** Map a kind → which RunRecord field holds the id. */
const FIELD_OF: Record<Kind, keyof RunRecord> = {
  tool:   "toolID",
  lot:    "lotID",
  recipe: "recipeID",
  apc:    "apcID",
  step:   "step",
  fdc:    "fdcID",
  spc:    "spcID",
};

export function deriveOntology(runs: RunRecord[]): DerivedOntology {
  const objs    = new Map<string, ObjNode>();
  const linkMap = new Map<string, Link>();
  const adj     = new Map<string, Set<string>>();

  const touchObj = (id: string, kind: Kind, t: number, alarm: boolean) => {
    if (!id) return;
    let o = objs.get(id);
    if (!o) {
      o = { id, kind, name: id, runs: 0, alarms: 0, lastT: 0 };
      objs.set(id, o);
    }
    o.runs++;
    if (alarm) o.alarms++;
    if (t > o.lastT) o.lastT = t;
  };

  const touchLink = (a: string, b: string, t: number, alarm: boolean) => {
    if (!a || !b || a === b) return;
    const key = a < b ? `${a}|${b}` : `${b}|${a}`;
    let l = linkMap.get(key);
    if (!l) {
      l = { a: a < b ? a : b, b: a < b ? b : a, count: 0, lastT: 0, anyAlarm: false };
      linkMap.set(key, l);
    }
    l.count++;
    if (t > l.lastT)  l.lastT = t;
    if (alarm)        l.anyAlarm = true;

    if (!adj.has(a)) adj.set(a, new Set());
    if (!adj.has(b)) adj.set(b, new Set());
    adj.get(a)!.add(b);
    adj.get(b)!.add(a);
  };

  for (const r of runs) {
    const t     = Date.parse(r.eventTime);
    const alarm = r.status === "alarm";

    // Collect (kind, id) pairs present in this run
    const present: { kind: Kind; id: string }[] = [];
    for (const k of KIND_ORDER) {
      const id = r[FIELD_OF[k]] as string;
      if (id) present.push({ kind: k, id });
    }

    for (const p of present) touchObj(p.id, p.kind, t, alarm);
    for (let i = 0; i < present.length; i++) {
      for (let j = i + 1; j < present.length; j++) {
        touchLink(present[i].id, present[j].id, t, alarm);
      }
    }
  }

  // Bucket + sort per kind
  const byKind = {} as Record<Kind, ObjNode[]>;
  for (const k of KIND_ORDER) byKind[k] = [];
  for (const o of objs.values()) byKind[o.kind].push(o);
  for (const k of KIND_ORDER) {
    byKind[k].sort((a, b) => (b.alarms - a.alarms) || (b.runs - a.runs));
  }

  return {
    objs,
    links:     [...linkMap.values()],
    neighbors: (id) => adj.get(id) ?? new Set(),
    byKind,
  };
}

/** Filter runs to a time window (epoch ms). */
export function runsInWindow(runs: RunRecord[], t0: number, t1: number): RunRecord[] {
  return runs.filter((r) => {
    const t = Date.parse(r.eventTime);
    return t >= t0 && t <= t1;
  });
}

/** Filter runs that touch a specific focus (kind + id). */
export function runsTouching(runs: RunRecord[], focus: FocusRef | null): RunRecord[] {
  if (!focus) return runs;
  const f = FIELD_OF[focus.kind];
  return runs.filter((r) => r[f] === focus.id);
}

/** Bucket runs by hour for the timeline density histogram. */
export function bucketByHour(
  runs: RunRecord[],
  t0: number,
  t1: number,
  bucketMs: number,
): { t: number; ok: number; warn: number; alarm: number }[] {
  const buckets = new Map<number, { ok: number; warn: number; alarm: number }>();
  for (const r of runs) {
    const t  = Date.parse(r.eventTime);
    if (t < t0 || t > t1) continue;
    const b  = Math.floor((t - t0) / bucketMs) * bucketMs + t0;
    const cur = buckets.get(b) ?? { ok: 0, warn: 0, alarm: 0 };
    cur[r.status]++;
    buckets.set(b, cur);
  }
  return [...buckets.entries()]
    .map(([t, v]) => ({ t, ...v }))
    .sort((a, b) => a.t - b.t);
}
