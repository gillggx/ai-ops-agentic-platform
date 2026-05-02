/**
 * SPC control-limit constants.
 *
 * Subgroup-size-dependent factors used to compute control limits from
 * subgroup means + ranges. Source: AIAG SPC manual, Table II.
 *
 *   A2 — multiplier for R̄ → 3σ limits on X̄ chart
 *   D3 — lower-control-limit factor for R chart (= 0 when n ≤ 6)
 *   D4 — upper-control-limit factor for R chart
 *   d2 — unbiasing constant; σ ≈ R̄ / d2
 *
 * Defined for n = 2..10 (the practically useful range). Outside that range
 * we fall back to n=5 values, which is the SEMI manufacturing default.
 */

export interface SpcConstants {
  A2: number;
  D3: number;
  D4: number;
  d2: number;
}

const TABLE: Record<number, SpcConstants> = {
  2: { A2: 1.880, D3: 0, D4: 3.267, d2: 1.128 },
  3: { A2: 1.023, D3: 0, D4: 2.575, d2: 1.693 },
  4: { A2: 0.729, D3: 0, D4: 2.282, d2: 2.059 },
  5: { A2: 0.577, D3: 0, D4: 2.114, d2: 2.326 },
  6: { A2: 0.483, D3: 0, D4: 2.004, d2: 2.534 },
  7: { A2: 0.419, D3: 0.076, D4: 1.924, d2: 2.704 },
  8: { A2: 0.373, D3: 0.136, D4: 1.864, d2: 2.847 },
  9: { A2: 0.337, D3: 0.184, D4: 1.816, d2: 2.970 },
  10: { A2: 0.308, D3: 0.223, D4: 1.777, d2: 3.078 },
};

const FALLBACK_N = 5;

export function spcConstants(n: number): SpcConstants {
  if (n in TABLE) return TABLE[n];
  return TABLE[FALLBACK_N];
}

/** Convenience: σ ≈ R̄ / d2(n). */
export function rangeSigma(rBar: number, n: number): number {
  return rBar / spcConstants(n).d2;
}

/** Bias-corrected σ for I-MR charts (n=2 effective). */
export const IMR_D2 = TABLE[2].d2; // 1.128

/** Bias-corrected D4 for I-MR (n=2 effective). */
export const IMR_D4 = TABLE[2].D4; // 3.267
