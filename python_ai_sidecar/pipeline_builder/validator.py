"""Pipeline Validator — 7 rules (SPEC §4.2).

Each rule produces a list of ValidationError dicts:
  { rule, message, node_id?, edge_id? }

Rules:
  C1 Schema 合法性
  C2 Block 存在性
  C3 Block Status 合規
  C4 Port 型別相容
  C5 DAG 無循環
  C6 參數 schema 驗證
  C7 起訖合理（至少 1 source + 1 output）
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Any, Iterable, Optional

from pydantic import ValidationError as PydanticValidationError

from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON


class PipelineValidator:
    """Validate a Pipeline JSON against a pre-loaded block catalog.

    Block catalog format (passed to __init__):
        {
          (block_name, block_version): {
              "category": str,
              "status": str,                 # draft | pi_run | production | deprecated
              "input_schema": [port_spec],
              "output_schema": [port_spec],
              "param_schema": dict,
              "name": str,
              "version": str,
          }
        }
    """

    def __init__(
        self,
        block_catalog: dict[tuple[str, str], dict[str, Any]],
        *,
        enforce_pipeline_status: Optional[str] = None,
        enforce_kind: Optional[str] = None,
    ) -> None:
        """
        Args:
            block_catalog: Map (name, version) → block spec dict.
            enforce_pipeline_status: If set (e.g. "production"), C3 rule requires
                all blocks to have at least the same status level.
            enforce_kind: PR-B. If set, runs C11/C12 kind-specific structural checks:
                "auto_patrol" → must end with ≥1 block_alert; no chart-only pipeline
                "diagnostic" → must have ≥1 block_chart and zero block_alert
        """
        self.catalog = block_catalog
        self.enforce_pipeline_status = enforce_pipeline_status
        self.enforce_kind = enforce_kind

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def validate(self, pipeline_json: Any) -> list[dict[str, Any]]:
        """Run all 7 rules. Returns list of errors (empty = valid)."""
        errors: list[dict[str, Any]] = []

        # C1: parse into Pydantic model
        try:
            pipeline = self._parse(pipeline_json)
        except PydanticValidationError as e:
            return [
                {
                    "rule": "C1_SCHEMA",
                    "message": f"Pipeline JSON schema invalid: {e.errors()[0]['msg']}",
                }
            ]
        except Exception as e:
            return [{"rule": "C1_SCHEMA", "message": f"Cannot parse pipeline: {e}"}]

        # C2, C3, C6 per-node checks
        for node in pipeline.nodes:
            errors.extend(self._check_node_block(node))
            errors.extend(self._check_param_schema(node))

        # C4 edge checks (port type compatibility)
        errors.extend(self._check_port_compat(pipeline))

        # C5 DAG cycle
        errors.extend(self._check_cycles(pipeline))

        # C7 start/end presence
        errors.extend(self._check_endpoints(pipeline))

        # C9 chart sequence sanity (duplicate warning)
        # NOTE: C8 (single-alert) was removed in Phase β — monitoring multiple SPC
        # chart types cleanly needs one alert per chart. Multi-alert strategy is
        # now a design choice for Agent/PE, not a hard constraint.
        errors.extend(self._check_chart_sequence(pipeline))

        # C10 undeclared input refs (Phase 4-B0)
        errors.extend(self._check_input_refs(pipeline))

        # PR-B: C11/C12 kind-specific structural checks (gate for validating → locked)
        if self.enforce_kind:
            errors.extend(self._check_kind_constraints(pipeline))

        return errors

    # ---------------------------------------------------------------
    # Rule implementations
    # ---------------------------------------------------------------

    def _parse(self, pipeline_json: Any) -> PipelineJSON:
        if isinstance(pipeline_json, PipelineJSON):
            return pipeline_json
        if isinstance(pipeline_json, str):
            pipeline_json = json.loads(pipeline_json)
        return PipelineJSON.model_validate(pipeline_json)

    def _catalog_key(self, node) -> tuple[str, str]:
        return (node.block_id, node.block_version)

    def _check_node_block(self, node) -> Iterable[dict[str, Any]]:
        key = self._catalog_key(node)
        spec = self.catalog.get(key)
        if spec is None:
            yield {
                "rule": "C2_BLOCK_EXISTS",
                "message": f"Block '{node.block_id}@{node.block_version}' not found in catalog",
                "node_id": node.id,
            }
            return

        # C3 — status check
        if self.enforce_pipeline_status == "production" and spec["status"] != "production":
            yield {
                "rule": "C3_BLOCK_STATUS",
                "message": f"Block '{node.block_id}' status={spec['status']}, "
                           f"must be 'production' for production pipeline",
                "node_id": node.id,
            }

    def _check_param_schema(self, node) -> Iterable[dict[str, Any]]:
        key = self._catalog_key(node)
        spec = self.catalog.get(key)
        if spec is None:
            return  # already reported by C2
        schema = spec.get("param_schema") or {}
        required = schema.get("required") or []
        props = schema.get("properties") or {}

        for key_name in required:
            if key_name not in (node.params or {}):
                yield {
                    "rule": "C6_PARAM_SCHEMA",
                    "message": f"Missing required parameter '{key_name}' for node {node.id}",
                    "node_id": node.id,
                }

        # Shallow type hint validation (no full JSON Schema to keep deps minimal).
        # A `"$input_ref"` value is resolved at runtime — skip type/enum checks here;
        # C10 already enforces the ref is declared.
        for key_name, value in (node.params or {}).items():
            prop = props.get(key_name)
            if not prop:
                continue
            if isinstance(value, str) and value.startswith("$"):
                continue
            expected = prop.get("type")
            if expected and not _type_matches(expected, value):
                yield {
                    "rule": "C6_PARAM_SCHEMA",
                    "message": f"Parameter '{key_name}' expected type '{expected}', got {type(value).__name__}",
                    "node_id": node.id,
                }
            enum = prop.get("enum")
            if enum is not None and value not in enum:
                yield {
                    "rule": "C6_PARAM_SCHEMA",
                    "message": f"Parameter '{key_name}' value '{value}' not in allowed enum {enum}",
                    "node_id": node.id,
                }

    def _check_port_compat(self, pipeline: PipelineJSON) -> Iterable[dict[str, Any]]:
        # Build node id → spec map
        node_specs: dict[str, dict[str, Any]] = {}
        for node in pipeline.nodes:
            spec = self.catalog.get(self._catalog_key(node))
            if spec:
                node_specs[node.id] = spec

        node_ids = {n.id for n in pipeline.nodes}

        for edge in pipeline.edges:
            if edge.from_.node not in node_ids:
                yield {
                    "rule": "C1_SCHEMA",
                    "message": f"Edge {edge.id} references unknown from-node '{edge.from_.node}'",
                    "edge_id": edge.id,
                }
                continue
            if edge.to.node not in node_ids:
                yield {
                    "rule": "C1_SCHEMA",
                    "message": f"Edge {edge.id} references unknown to-node '{edge.to.node}'",
                    "edge_id": edge.id,
                }
                continue

            from_spec = node_specs.get(edge.from_.node)
            to_spec = node_specs.get(edge.to.node)
            if not from_spec or not to_spec:
                continue

            from_port = _find_port(from_spec.get("output_schema") or [], edge.from_.port)
            to_port = _find_port(to_spec.get("input_schema") or [], edge.to.port)
            if from_port is None:
                yield {
                    "rule": "C4_PORT_COMPAT",
                    "message": f"Output port '{edge.from_.port}' not declared on node {edge.from_.node}",
                    "edge_id": edge.id,
                }
                continue
            if to_port is None:
                yield {
                    "rule": "C4_PORT_COMPAT",
                    "message": f"Input port '{edge.to.port}' not declared on node {edge.to.node}",
                    "edge_id": edge.id,
                }
                continue
            from_type = from_port.get("type")
            to_type = to_port.get("type")
            if from_type and to_type and from_type != to_type:
                yield {
                    "rule": "C4_PORT_COMPAT",
                    "message": f"Type mismatch: '{from_type}' → '{to_type}' on edge {edge.id}",
                    "edge_id": edge.id,
                }

    def _check_cycles(self, pipeline: PipelineJSON) -> Iterable[dict[str, Any]]:
        graph: dict[str, list[str]] = defaultdict(list)
        in_deg: dict[str, int] = defaultdict(int)
        for node in pipeline.nodes:
            in_deg.setdefault(node.id, 0)
        for edge in pipeline.edges:
            graph[edge.from_.node].append(edge.to.node)
            in_deg[edge.to.node] += 1

        queue = deque([n for n, d in in_deg.items() if d == 0])
        visited = 0
        while queue:
            n = queue.popleft()
            visited += 1
            for nxt in graph[n]:
                in_deg[nxt] -= 1
                if in_deg[nxt] == 0:
                    queue.append(nxt)
        if visited != len(pipeline.nodes):
            yield {
                "rule": "C5_CYCLE",
                "message": "Pipeline contains a cycle (DAG violated)",
            }

    def _check_chart_sequence(self, pipeline: PipelineJSON) -> Iterable[dict[str, Any]]:
        """Warn when two chart blocks share the same sequence number."""
        seqs: dict[int, list[str]] = defaultdict(list)
        for n in pipeline.nodes:
            if n.block_id != "block_chart":
                continue
            s = (n.params or {}).get("sequence")
            if isinstance(s, int):
                seqs[s].append(n.id)
        for seq, ids in seqs.items():
            if len(ids) > 1:
                yield {
                    "rule": "C9_CHART_SEQUENCE",
                    "message": f"Multiple chart nodes share sequence={seq}: {ids}",
                }

    def _check_input_refs(self, pipeline: PipelineJSON) -> Iterable[dict[str, Any]]:
        """C10: every `"$foo"` param value must reference a declared pipeline input."""
        declared = {inp.name for inp in (pipeline.inputs or [])}
        for node in pipeline.nodes:
            for key, val in (node.params or {}).items():
                if isinstance(val, str) and val.startswith("$"):
                    ref = val[1:]
                    if ref not in declared:
                        yield {
                            "rule": "C10_UNDECLARED_INPUT_REF",
                            "message": (
                                f"Node '{node.id}' param '{key}' references ${ref}, "
                                f"but pipeline.inputs has no '{ref}' declared."
                            ),
                            "node_id": node.id,
                        }

    def _check_endpoints(self, pipeline: PipelineJSON) -> Iterable[dict[str, Any]]:
        sources: set[str] = set()
        outputs: set[str] = set()
        for node in pipeline.nodes:
            spec = self.catalog.get(self._catalog_key(node))
            if not spec:
                continue
            if spec.get("category") == "source":
                sources.add(node.id)
            elif spec.get("category") == "output":
                outputs.add(node.id)
        if not sources:
            yield {"rule": "C7_ENDPOINTS", "message": "Pipeline must contain at least one source block"}
        if not outputs:
            yield {"rule": "C7_ENDPOINTS", "message": "Pipeline must contain at least one output block"}

    def _check_kind_constraints(self, pipeline: PipelineJSON) -> Iterable[dict[str, Any]]:
        """Phase 5-UX-7 C11/C12/C13 — structural constraints tied to pipeline_kind.

        Three kinds:
          - auto_patrol: cron-scheduled patrol → must emit block_alert; no inputs
          - auto_check : alarm-driven diagnosis → must have inputs_schema (pulls
                          from alarm payload by name); block_alert OR block_chart OK
          - skill      : on-demand via agent → must have block_chart; block_alert forbidden
        """
        has_alert = any(n.block_id == "block_alert" for n in pipeline.nodes)
        has_chart = any(n.block_id == "block_chart" for n in pipeline.nodes)
        declared_inputs = pipeline.inputs or []

        if self.enforce_kind == "auto_patrol":
            if not has_alert:
                yield {
                    "rule": "C11_AUTO_PATROL_NEEDS_ALERT",
                    "message": (
                        "Auto-Patrol pipelines must end in at least one block_alert "
                        "(Alert is how the patrol signals a finding)."
                    ),
                }
        elif self.enforce_kind == "auto_check":
            if not has_alert and not has_chart:
                yield {
                    "rule": "C13_AUTO_CHECK_NEEDS_OUTPUT",
                    "message": (
                        "Auto-Check pipelines must include at least one block_alert "
                        "or block_chart (the engineer needs to see the check result)."
                    ),
                }
            if not declared_inputs:
                yield {
                    "rule": "C13_AUTO_CHECK_NEEDS_INPUTS",
                    "message": (
                        "Auto-Check pipelines must declare inputs — the alarm payload is "
                        "passed in by name (e.g. tool_id, lot_id). Declare at least one "
                        "input your MCP blocks reference via $name."
                    ),
                }
        elif self.enforce_kind == "skill":
            if not has_chart:
                yield {
                    "rule": "C12_SKILL_NEEDS_CHART",
                    "message": (
                        "Skill pipelines must include at least one block_chart "
                        "(chart/table is the visual handoff to the engineer)."
                    ),
                }
            if has_alert:
                yield {
                    "rule": "C12_SKILL_NEEDS_CHART",
                    "message": (
                        "Skill pipelines must NOT contain block_alert — use "
                        "pipeline_kind=auto_patrol or auto_check if you want alerting."
                    ),
                }
        elif self.enforce_kind == "diagnostic":
            # Legacy read-only — treat as skill
            if not has_chart:
                yield {
                    "rule": "C12_DIAGNOSTIC_NEEDS_CHART",
                    "message": "Legacy diagnostic kind: treat as skill — must include block_chart.",
                }


# ---------------------------------------------------------------
# helpers
# ---------------------------------------------------------------

def _find_port(port_list: list[dict[str, Any]], name: str) -> Optional[dict[str, Any]]:
    for p in port_list:
        if p.get("port") == name:
            return p
    return None


def _type_matches(expected: Any, value: Any) -> bool:
    """Supports JSON Schema `type: str | list[str]` (e.g. `["string", "array"]`)."""
    mapping = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "array": (list, tuple),
        "object": (dict,),
    }
    if isinstance(expected, list):
        return any(_type_matches(t, value) for t in expected)
    accepted = mapping.get(expected)
    if not accepted:
        return True  # unknown type hint → don't block
    if expected == "integer" and isinstance(value, bool):
        return False
    return isinstance(value, accepted)
