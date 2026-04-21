# Pipeline ↔ Skill Parity Diff (Phase 7c-1)

- **Date**: 2026-04-22
- **Scope**: 7 auto_patrol-kind pipelines (alarm-producing — critical path)
- **Verdict**: 🔴 **0 / 7 safe to activate**. 2 skeletons + 2 logic-inverted + 3 semantic narrower. Must not activate without fixing pipeline_json.

## Per-pair findings

### 1. `[auto_patrol] SPC chat's continue OOC check` — pipeline 1 vs skill 3
**Pipeline DAG**:
```
block_process_history(SPC,500) → rolling_window(spc_xbar_chart_is_ooc, w=5, sum) → threshold(upper=1) → alert
                             ├→ chart(xbar)
                             ├→ data_view(SPC Chart Data)
                             └→ data_view(異常批號)
```
**Skill logic (`steps_mapping`)**:
- Flatten 500 SPC events by **every chart_type** (not just xbar_chart)
- Last 5 unique process events → count OOC across all chart_types → trigger when ≥ 2

**Divergence**: Pipeline only looks at `spc_xbar_chart_is_ooc`. Skill counts **any** chart-type OOC. Pipeline under-reports — misses OOCs on range / r / s charts.

**Severity**: ⚠️ semantic narrower — fewer alarms than current prod
**Fix**: Add flatten block or use `block_filter(is_ooc == true)` before rolling_window on the is_ooc column across all chart types.

---

### 2. `[auto_patrol] Tool 5-in-3-out check` — pipeline 2 vs skill 4
**Pipeline**: rolling_sum on `spc_xbar_chart_is_ooc`, window=5, threshold `upper_bound=2` (trigger when sum > 2).
**Skill**: count `spc_status != 'PASS'` in last 5 processes, trigger when `> 2`.

**Divergence**: Same xbar-only issue. `spc_status` captures failures across **all** charts — pipeline only on xbar column.

**Severity**: ⚠️ semantic narrower
**Fix**: Use a column derived from `spc_status` (e.g., `spc_is_not_pass`) or flatten + aggregate.

---

### 3. `Same recipe check` — pipeline 4 vs skill 6
**Pipeline**: `filter(spc_status=='OOC') → count_rows(group_by=recipe_version) → count_rows → threshold(count > 1)`
**Skill**: compute `all_ooc_from_same_recipe` — trigger when OOCs come from **ONE** recipe version.

**Divergence**: 🔴 **INVERTED LOGIC**.
- Pipeline's outer `count_rows` (no group_by) counts **rows** (i.e., number of distinct recipe versions with OOC). Threshold `> 1` fires when **more than one** recipe version has OOC.
- Skill fires when **exactly one** recipe version owns all OOCs.

Pipeline fires on multi-recipe instability, Skill fires on single-recipe correlation. **Opposite intents**.

**Severity**: 🔴 critical — alarm content & meaning completely different.
**Fix**: Change pipeline threshold to `count == 1` OR restructure DAG to detect "ooc_recipe_count == 1 AND ooc_count > 0".

---

### 4. `Same APC check` — pipeline 5 vs skill 7
Same structure + same inversion as #3 but for `apc_mode` column.

**Severity**: 🔴 critical inverted
**Fix**: Same pattern as #3.

---

### 5. `[auto_patrol] 機台5 in 2 out check` — pipeline 6 vs skill 10
**Pipeline**: rolling_sum on `spc_xbar_chart_is_ooc`, window=5, threshold `upper_bound=1` (trigger when sum > 1 → ≥ 2 OOCs).
**Skill**: count `spc_status != 'PASS'` in last 5, trigger when `>= 2`.

**Divergence**: Same xbar-only issue as #1 and #2.

**Severity**: ⚠️ semantic narrower
**Fix**: same as #1.

---

### 6. `[auto_patrol] DC sensor drift check` — pipeline 16 vs skill 31
**Pipeline metadata**: `"migration_status": "skeleton"`
**Pipeline DAG**: only `block_process_history → block_data_view`. **No threshold, no alert block.** Will never trigger an alarm.

**Severity**: 🔴 skeleton — pipeline is a placeholder.
**Fix**: Migration from Skill was never finished. Needs full implementation of DC drift statistical detection.

---

### 7. `[auto_patrol] Recipe consistency check` — pipeline 17 vs skill 32
Same as #6 — `migration_status: skeleton`, no alert logic.

**Severity**: 🔴 skeleton
**Fix**: same — migration incomplete.

---

## Summary table

| # | Pipeline | Source Skill | Migration status | Parity | Severity |
|---|---|---|---|---|---|
| 1 | [auto_patrol] SPC chat's continue OOC check | 3 | full | ⚠️ xbar-only, misses other charts | medium |
| 2 | [auto_patrol] Tool 5-in-3-out check | 4 | full | ⚠️ xbar-only | medium |
| 3 | Same recipe check | 6 | full | 🔴 **INVERTED** | **critical** |
| 4 | Same APC check | 7 | full | 🔴 **INVERTED** | **critical** |
| 5 | [auto_patrol] 機台5 in 2 out check | 10 | full | ⚠️ xbar-only | medium |
| 6 | [auto_patrol] DC sensor drift check | 31 | **skeleton** | 🔴 never fires | **critical** |
| 7 | [auto_patrol] Recipe consistency check | 32 | **skeleton** | 🔴 never fires | **critical** |

## Gate 7c-1 verdict

🔴 **BLOCK**. Zero of 7 pipelines is safe to wire to `auto_patrols.pipeline_id`. If activated as-is:
- 4 critical-severity alarm streams disappear (2 inversions fire on opposite condition, 2 skeletons never fire)
- 3 medium-severity alarm streams under-report (xbar-only vs all-charts)

## Options for user

**A. Fix pipeline_json in-place**
For each of the 7 pipelines, edit pipeline_json to match the source Skill's logic semantics. Estimated effort: 1-2 days of domain-aware authoring + verification. Needs someone who understands the SPC / recipe / APC business rules, not just the JSON.

**B. Don't migrate — keep Skills as the engine**
Accept that the `[migrated]` draft pipelines were a prototype that didn't finish. Leave `auto_patrols.pipeline_id` NULL. Old Python Skill engine stays in charge of alarm generation indefinitely. Phase 8 (Java cutover) can still proceed — it's orthogonal to which engine generates alarms.

**C. Fix the 2 critical inversions only, leave the rest as-is**
Fix Same-recipe + Same-APC (the 2 inverted ones), leave the 2 skeletons as draft (still Skill-backed), leave the 3 xbar-only narrower ones as they are (accepting that alarm recall is slightly lower).

## Recommendation

**Option B or C**. Option A is real work (business semantics, not just refactoring). Phase 8 frontend cutover doesn't depend on this — Phase 8 can safely proceed on Option B or C.

If this were my production cluster, I'd go B: don't risk production alarm miss / invert for a prototype engine swap, do Phase 8 Java cutover first (which is contained API-parity work), then revisit pipeline migration later as a proper effort with the SPC-domain SME.

---

**Awaiting user decision.** Continue to Phase 8 directly?
