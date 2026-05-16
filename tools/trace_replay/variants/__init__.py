"""Built-in trace_replay variants. Each module exports a callable matching
the Variant signature. The registry below maps CLI names to callables.

To add a variant:
  1. Create a new module here.
  2. Export a callable (LLMInput) -> LLMInput. Pure function — do not
     mutate the input; return a new LLMInput.
  3. Register in `VARIANT_REGISTRY` at the bottom of this file.

For parameterized variants, build a factory inside the module and register
its default invocation. CLI users wanting params can write a custom file
and pass --variants-module.
"""
from __future__ import annotations

from .identity import identity
from .catalog_brief import enrich_catalog_brief
from .phase_goal import rewrite_phase_goal_generic
from .prepend import prepend_oneblock_solutions
from .spc_status_enum import clarify_spc_status_enum
from .remove_spc_summary import remove_spc_summary_expand_spc_charts


VARIANT_REGISTRY = {
    "identity": identity,
    "enrich_catalog_brief": enrich_catalog_brief,
    "rewrite_phase_goal_generic": rewrite_phase_goal_generic,
    "prepend_oneblock_solutions": prepend_oneblock_solutions,
    "clarify_spc_status_enum": clarify_spc_status_enum,
    "remove_spc_summary_expand_spc_charts": remove_spc_summary_expand_spc_charts,
}


__all__ = ["VARIANT_REGISTRY"]
