"""Canonical flat-column aliases — single source of truth.

Consumers:
  - skill_migrator.py: normalises legacy skill column refs (e.g. "value" → "spc_xbar_chart_value")
    when migrating diagnose.py logic into pb-pipeline block params
  - (future) runtime param normaliser: could apply same aliases to block_chart/etc
    to make the system forgiving of nested paths / short names the LLM might emit

Previously lived inline in `skill_migrator._build_pipeline_for_skill`; extracted so
prompt_hint + migrator + future validation share the same mappings.
"""

from __future__ import annotations

from typing import Optional


# Common unqualified names that historically appear in skill code / user queries.
# Mapped to their canonical flat column names produced by block_process_history.
SPC_COL_ALIASES: dict[str, str] = {
    "value": "spc_xbar_chart_value",
    "ucl": "spc_xbar_chart_ucl",
    "lcl": "spc_xbar_chart_lcl",
    "is_ooc": "spc_xbar_chart_is_ooc",
    "predicted": "spc_xbar_chart_value",
    # Chart specs that reference specific nested fields without an object fetch
    "xbar_value": "spc_xbar_chart_value",
    "r_value": "spc_r_chart_value",
    "s_value": "spc_s_chart_value",
    "chamber_pressure": "dc_chamber_pressure",
    "foreline_pressure": "dc_foreline_pressure",
}

# object_name → flat column prefix. Emitted by process_history when a specific
# dimension is requested (object_name=APC → apc_ prefix on every APC parameter).
OBJ_PREFIX: dict[str, str] = {
    "APC": "apc_",
    "RECIPE": "recipe_",
    "DC": "dc_",
    "FDC": "fdc_",
}

# Columns always present on process_history output, regardless of object_name.
# These must never be prefixed by a dimension.
BASE_COLS: frozenset[str] = frozenset(
    {"eventTime", "lotID", "toolID", "step", "spc_status", "fdc_classification"}
)

# Known prefixes so we don't double-prefix already-flattened columns.
KNOWN_PREFIXES: tuple[str, ...] = ("apc_", "recipe_", "dc_", "fdc_", "spc_")


def canonicalise_column(
    col: Optional[str],
    *,
    object_name: Optional[str] = None,
) -> Optional[str]:
    """Return the canonical flat column name for a user/skill-supplied ref.

    Rules:
      1. None passes through (callers often pass optional refs)
      2. SPC_COL_ALIASES override first (e.g. "value" → "spc_xbar_chart_value")
      3. BASE_COLS pass through (never prefix eventTime/lotID/etc.)
      4. If the request targets a specific dimension (APC/RECIPE/DC/FDC) AND the
         column is not already prefixed, prefix it (param_name → apc_param_name)
      5. Otherwise pass through unchanged
    """
    if col is None:
        return None
    if col in SPC_COL_ALIASES:
        return SPC_COL_ALIASES[col]
    if col in BASE_COLS:
        return col
    prefix = OBJ_PREFIX.get(object_name or "")
    if prefix and not col.startswith(KNOWN_PREFIXES):
        return f"{prefix}{col}"
    return col
