/**
 * Western Electric Company (WECO) rules — full R1–R8 ruleset for SPC charts.
 *
 * Standard reference: AT&T's Statistical Quality Control Handbook (1956).
 * The Reference design (`charts-p2.js`) only implements R1/R2/R3/R5; we
 * extend to all 8.
 *
 * Each rule operates on:
 *   arr   — the value series in chronological order
 *   mu    — center line (process mean)
 *   sigma — process standard deviation (used to define σ-zones)
 *   idx   — index of the current point being evaluated
 *
 * `wecoCheck` returns the ID of the first violated rule (or null). If you
 * need ALL violations for a single point, call `wecoCheckAll`.
 *
 * "Same side" rules ignore points exactly on CL (which would be ambiguous);
 * matches the conservative interpretation used by JMP / Minitab.
 */

export type WecoRuleId =
  | 'R1'
  | 'R2'
  | 'R3'
  | 'R4'
  | 'R5'
  | 'R6'
  | 'R7'
  | 'R8';

export interface WecoViolation {
  rule: WecoRuleId;
  reason: string;
}

export const ALL_WECO_RULES: WecoRuleId[] = ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8'];

const R1_LABEL = 'R1: 1 pt outside 3σ';
const R2_LABEL = 'R2: 9 pts same side of CL';
const R3_LABEL = 'R3: 6 pts trending';
const R4_LABEL = 'R4: 14 pts alternating up/down';
const R5_LABEL = 'R5: 2 of 3 > 2σ same side';
const R6_LABEL = 'R6: 4 of 5 > 1σ same side';
const R7_LABEL = 'R7: 15 pts within ±1σ (process too tight)';
const R8_LABEL = 'R8: 8 pts outside ±1σ both sides';

function isAbove(v: number, mu: number): boolean {
  return v > mu;
}

function isBelow(v: number, mu: number): boolean {
  return v < mu;
}

function r1(v: number, mu: number, sigma: number): WecoViolation | null {
  if (sigma <= 0) return null;
  if (Math.abs(v - mu) > 3 * sigma) return { rule: 'R1', reason: R1_LABEL };
  return null;
}

function r2(arr: ArrayLike<number>, mu: number, idx: number): WecoViolation | null {
  if (idx < 8) return null;
  let above = true;
  let below = true;
  for (let k = idx - 8; k <= idx; k++) {
    const v = arr[k];
    if (!isAbove(v, mu)) above = false;
    if (!isBelow(v, mu)) below = false;
  }
  if (above) return { rule: 'R2', reason: `${R2_LABEL} (above)` };
  if (below) return { rule: 'R2', reason: `${R2_LABEL} (below)` };
  return null;
}

function r3(arr: ArrayLike<number>, idx: number): WecoViolation | null {
  if (idx < 5) return null;
  let up = true;
  let down = true;
  for (let k = idx - 5; k < idx; k++) {
    const a = arr[k];
    const b = arr[k + 1];
    if (!(b > a)) up = false;
    if (!(b < a)) down = false;
  }
  if (up) return { rule: 'R3', reason: `${R3_LABEL} (up)` };
  if (down) return { rule: 'R3', reason: `${R3_LABEL} (down)` };
  return null;
}

function r4(arr: ArrayLike<number>, idx: number): WecoViolation | null {
  if (idx < 13) return null;
  for (let k = idx - 13; k < idx; k++) {
    const sign1 = arr[k + 1] - arr[k];
    const sign2 = arr[k + 2] - arr[k + 1];
    if (sign1 === 0 || sign2 === 0) return null;
    if (Math.sign(sign1) === Math.sign(sign2)) return null;
  }
  return { rule: 'R4', reason: R4_LABEL };
}

function r5(arr: ArrayLike<number>, mu: number, sigma: number, idx: number): WecoViolation | null {
  if (idx < 2 || sigma <= 0) return null;
  // Current point must itself be > 2σ on the same side as 1 of the prior 2.
  const v = arr[idx];
  if (v - mu > 2 * sigma) {
    let cnt = 0;
    for (let k = idx - 2; k <= idx; k++) {
      if (arr[k] - mu > 2 * sigma) cnt += 1;
    }
    if (cnt >= 2) return { rule: 'R5', reason: `${R5_LABEL} (above)` };
  }
  if (mu - v > 2 * sigma) {
    let cnt = 0;
    for (let k = idx - 2; k <= idx; k++) {
      if (mu - arr[k] > 2 * sigma) cnt += 1;
    }
    if (cnt >= 2) return { rule: 'R5', reason: `${R5_LABEL} (below)` };
  }
  return null;
}

function r6(arr: ArrayLike<number>, mu: number, sigma: number, idx: number): WecoViolation | null {
  if (idx < 4 || sigma <= 0) return null;
  // 4 of 5 consecutive points > 1σ on same side (current point must be one of them).
  const v = arr[idx];
  if (v - mu > sigma) {
    let cnt = 0;
    for (let k = idx - 4; k <= idx; k++) {
      if (arr[k] - mu > sigma) cnt += 1;
    }
    if (cnt >= 4) return { rule: 'R6', reason: `${R6_LABEL} (above)` };
  }
  if (mu - v > sigma) {
    let cnt = 0;
    for (let k = idx - 4; k <= idx; k++) {
      if (mu - arr[k] > sigma) cnt += 1;
    }
    if (cnt >= 4) return { rule: 'R6', reason: `${R6_LABEL} (below)` };
  }
  return null;
}

function r7(arr: ArrayLike<number>, mu: number, sigma: number, idx: number): WecoViolation | null {
  if (idx < 14 || sigma <= 0) return null;
  // 15 points in a row within ±1σ (process too tight).
  for (let k = idx - 14; k <= idx; k++) {
    if (Math.abs(arr[k] - mu) > sigma) return null;
  }
  return { rule: 'R7', reason: R7_LABEL };
}

function r8(arr: ArrayLike<number>, mu: number, sigma: number, idx: number): WecoViolation | null {
  if (idx < 7 || sigma <= 0) return null;
  // 8 points in a row outside ±1σ (zones A or B), either side.
  for (let k = idx - 7; k <= idx; k++) {
    if (Math.abs(arr[k] - mu) <= sigma) return null;
  }
  return { rule: 'R8', reason: R8_LABEL };
}

/** Run enabled rules in order; return the first violation, or null. */
export function wecoCheck(
  arr: ArrayLike<number>,
  mu: number,
  sigma: number,
  idx: number,
  enabled: ReadonlyArray<WecoRuleId> = ALL_WECO_RULES,
): WecoViolation | null {
  if (idx < 0 || idx >= arr.length) return null;
  const v = arr[idx];
  if (!Number.isFinite(v)) return null;
  const set = new Set<WecoRuleId>(enabled);
  if (set.has('R1')) {
    const out = r1(v, mu, sigma);
    if (out) return out;
  }
  if (set.has('R2')) {
    const out = r2(arr, mu, idx);
    if (out) return out;
  }
  if (set.has('R3')) {
    const out = r3(arr, idx);
    if (out) return out;
  }
  if (set.has('R4')) {
    const out = r4(arr, idx);
    if (out) return out;
  }
  if (set.has('R5')) {
    const out = r5(arr, mu, sigma, idx);
    if (out) return out;
  }
  if (set.has('R6')) {
    const out = r6(arr, mu, sigma, idx);
    if (out) return out;
  }
  if (set.has('R7')) {
    const out = r7(arr, mu, sigma, idx);
    if (out) return out;
  }
  if (set.has('R8')) {
    const out = r8(arr, mu, sigma, idx);
    if (out) return out;
  }
  return null;
}

/** Run enabled rules and return ALL violations for a single point. */
export function wecoCheckAll(
  arr: ArrayLike<number>,
  mu: number,
  sigma: number,
  idx: number,
  enabled: ReadonlyArray<WecoRuleId> = ALL_WECO_RULES,
): WecoViolation[] {
  if (idx < 0 || idx >= arr.length) return [];
  const v = arr[idx];
  if (!Number.isFinite(v)) return [];
  const set = new Set<WecoRuleId>(enabled);
  const out: WecoViolation[] = [];
  if (set.has('R1')) { const x = r1(v, mu, sigma); if (x) out.push(x); }
  if (set.has('R2')) { const x = r2(arr, mu, idx); if (x) out.push(x); }
  if (set.has('R3')) { const x = r3(arr, idx); if (x) out.push(x); }
  if (set.has('R4')) { const x = r4(arr, idx); if (x) out.push(x); }
  if (set.has('R5')) { const x = r5(arr, mu, sigma, idx); if (x) out.push(x); }
  if (set.has('R6')) { const x = r6(arr, mu, sigma, idx); if (x) out.push(x); }
  if (set.has('R7')) { const x = r7(arr, mu, sigma, idx); if (x) out.push(x); }
  if (set.has('R8')) { const x = r8(arr, mu, sigma, idx); if (x) out.push(x); }
  return out;
}
