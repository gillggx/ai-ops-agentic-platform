"""block_rework_request — fetch rework records for a lot from OntologySimulator.

Wraps ``POST {ONTOLOGY_SIM_URL}/api/v1/rework_request`` (= system MCP
``rework_request``). Rework records are created automatically whenever a
photo station (step number multiple of 5) hits an OOC at the simulator,
so this block is the canonical way to inspect "what reworks did lot X
trigger?" downstream in a pipeline.

⚠ Field-name mapping (deliberate, documented here + in MCP description):

  MESInfo (process events)          → reworkInfo (rework_records)
  ─────────────────────────────────────────────────────────────────
  flowID                            → mainPD_ID
  stageID                           → PDID
  processJobID                      → rwJobID
  slotList                          → slotMap
  productID                         → prodCode
  photoLayerID                      → layerName
  technology                        → techNode
  mainPD                            → rootPD
  subPDID                           → subPDCode
  routeID                           → routeName
  recipeGroup                       → recipeFamily
  foupID                            → carrierID
  waferCount                        → slotCount
  lotType                           → lotKind
  lotPriority                       → priorityClass
  customer                          → customerCode
  mfgRegion                         → region
  processOrder                      → stepSeq
  eqpRecipeRevision                 → toolRecipeRev
  holdState                         → holdStatus

The renamed keys are flattened to top-level columns on the returned
DataFrame with a ``rwi_`` prefix so they never collide with eventTime /
step / lotID columns.
"""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings
from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_DEFAULT_TIMEOUT_S = 15.0


def _flatten_rework(rec: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested reworkInfo dict to flat ``rwi_<key>`` columns so
    downstream pandas operations are straightforward."""
    out: dict[str, Any] = {
        "reworkTime":  rec.get("reworkTime"),
        "reworkCount": rec.get("reworkCount"),
        "lotID":       rec.get("lotID"),
        "step":        rec.get("step"),
    }
    info = rec.get("reworkInfo") or {}
    if isinstance(info, dict):
        for k, v in info.items():
            out[f"rwi_{k}"] = v
    return out


class ReworkRequestBlockExecutor(BlockExecutor):
    block_id = "block_rework_request"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        lot_id = params.get("lot_id") or params.get("lotID")
        if not lot_id or not isinstance(lot_id, str):
            raise BlockExecutionError(
                code="MISSING_PARAM",
                message="lot_id is required",
                hint="Pass the LOT-NNNN identifier of the lot you want to inspect",
            )

        # Optional filters — only sent when provided.
        body: dict[str, Any] = {"lotID": lot_id}
        step = params.get("step")
        flow_id = params.get("flow_id") or params.get("flowID")
        if step:
            body["step"] = step
        if flow_id:
            body["flowID"] = flow_id

        settings = get_settings()
        base = getattr(settings, "ONTOLOGY_SIM_URL", "") or ""
        if not base:
            raise BlockExecutionError(
                code="MISSING_CONFIG",
                message="ONTOLOGY_SIM_URL not configured",
                hint="Set ONTOLOGY_SIM_URL in settings / env",
            )

        url = f"{base.rstrip('/')}/api/v1/rework_request"
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_S) as client:
                resp = await client.post(url, json=body)
        except httpx.HTTPError as e:
            raise BlockExecutionError(
                code="HTTP_ERROR",
                message=f"Simulator fetch failed: {e}",
                hint="Check ontology_simulator is reachable",
            ) from e

        if resp.status_code >= 400:
            raise BlockExecutionError(
                code="UPSTREAM_ERROR",
                message=f"Upstream returned HTTP {resp.status_code}",
                hint=resp.text[:200],
            )

        payload = resp.json()
        records = payload.get("rework_records", []) or []
        rows = [_flatten_rework(r) for r in records]
        return {"data": pd.DataFrame(rows)}
