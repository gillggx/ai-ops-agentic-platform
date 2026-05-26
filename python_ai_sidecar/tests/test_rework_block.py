"""block_rework_request — covers param validation, request shape, response
flattening, and error pathways. Network calls are mocked via
httpx.MockTransport (no extra deps).

Field-name mapping context: reworkInfo uses renamed keys vs MESInfo
(mainPD_ID = flowID etc). This block surfaces them as ``rwi_<key>``
columns so downstream pandas operations work cleanly.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import httpx
import pytest

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.rework_request import (
    ReworkRequestBlockExecutor,
)


_SIM_URL = "http://fake-sim:8012"

pytestmark = pytest.mark.asyncio


@pytest.fixture
def block(monkeypatch):
    monkeypatch.setenv("ONTOLOGY_SIM_URL", _SIM_URL)
    # Settings is cached as singleton — reset so our env var is honoured
    from python_ai_sidecar.pipeline_builder import _sidecar_deps
    _sidecar_deps._settings_singleton = None
    return ReworkRequestBlockExecutor()


@pytest.fixture
def context():
    return ExecutionContext(run_id=1)


def _sample_payload(n: int = 2):
    """Mimic the simulator's POST /api/v1/rework_request response."""
    return {
        "total": n,
        "rework_records": [
            {
                "reworkTime":  datetime(2026, 5, 26, 10, 0, i).isoformat() + "Z",
                "reworkCount": i + 1,
                "lotID":       "LOT-0123",
                "step":        f"STEP_{(i + 1) * 5:03d}",
                "reworkInfo": {
                    "mainPD_ID":   "FLOW-LOGIC-28-V2",
                    "PDID":        f"STG-PHOTO-STEP_{(i + 1) * 5:03d}",
                    "rwJobID":     f"PJ-20260526-abc{i}",
                    "slotMap":     list(range(1, 26)),
                    "prodCode":    "PROD-A100-V3",
                    "layerName":   f"M{i + 1}",
                    "techNode":    "28HPC+",
                    "rootPD":      "MPD-LOGIC-28-A",
                    "subPDCode":   f"SPD-STEP_{(i + 1) * 5:03d}-V1",
                    "routeName":   "RT-FAB14-LINE3",
                    "recipeFamily": "RG-PHOTO-M1",
                    "carrierID":   "FOUP-000123",
                    "slotCount":   25,
                    "lotKind":     "production",
                    "priorityClass": "HOT",
                    "customerCode": "CUST-X-VIETNAM",
                    "region":       "TW-HSINCHU",
                    "stepSeq":      (i + 1) * 5,
                    "toolRecipeRev": "R-003.1",
                    "holdStatus":    "RELEASED",
                },
            }
            for i in range(n)
        ],
    }


class _Recorder:
    """Captures request bodies so tests can assert on what the block sent."""

    def __init__(self, response_json, status: int = 200, raise_exc: Exception | None = None):
        self._response_json = response_json
        self._status = status
        self._raise = raise_exc
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._raise:
            raise self._raise
        return httpx.Response(self._status, json=self._response_json)


def _patched_client(recorder: _Recorder):
    """Return a patcher that swaps httpx.AsyncClient for one wired to the
    MockTransport. Use as: `with _patched_client(rec): ...`"""
    transport = httpx.MockTransport(recorder.handler)
    real_init = httpx.AsyncClient.__init__

    def _fake_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    return patch.object(httpx.AsyncClient, "__init__", _fake_init)


async def test_missing_lot_id_raises(block, context):
    with pytest.raises(BlockExecutionError) as exc:
        await block.execute(params={}, inputs={}, context=context)
    assert exc.value.code == "MISSING_PARAM"


async def test_lot_id_alias_lotID_accepted(block, context):
    rec = _Recorder(_sample_payload(0))
    with _patched_client(rec):
        result = await block.execute(
            params={"lotID": "LOT-0001"}, inputs={}, context=context,
        )
    assert result["data"].empty
    assert len(rec.requests) == 1


async def test_happy_path_flattens_rework_info(block, context):
    rec = _Recorder(_sample_payload(2))
    with _patched_client(rec):
        result = await block.execute(
            params={"lot_id": "LOT-0123"}, inputs={}, context=context,
        )

    # Request body shape
    body = json.loads(rec.requests[0].content)
    assert body == {"lotID": "LOT-0123"}

    # Flattening: rwi_* columns present, reworkInfo dict absent
    df = result["data"]
    assert len(df) == 2
    assert "reworkInfo" not in df.columns
    for expected in ("rwi_mainPD_ID", "rwi_PDID", "rwi_techNode", "rwi_holdStatus"):
        assert expected in df.columns, f"missing column {expected}"
    assert df.iloc[0]["rwi_mainPD_ID"] == "FLOW-LOGIC-28-V2"
    assert df.iloc[1]["step"] == "STEP_010"


async def test_optional_filters_threaded_to_request(block, context):
    rec = _Recorder(_sample_payload(0))
    with _patched_client(rec):
        await block.execute(
            params={"lot_id": "LOT-0123", "step": "STEP_010", "flow_id": "FLOW-X"},
            inputs={}, context=context,
        )
    body = json.loads(rec.requests[0].content)
    assert body == {"lotID": "LOT-0123", "step": "STEP_010", "flowID": "FLOW-X"}


async def test_empty_response_returns_empty_dataframe(block, context):
    rec = _Recorder({"total": 0, "rework_records": []})
    with _patched_client(rec):
        result = await block.execute(
            params={"lot_id": "LOT-9999"}, inputs={}, context=context,
        )
    assert result["data"].empty


async def test_upstream_500_raises_block_error(block, context):
    rec = _Recorder({"error": "boom"}, status=500)
    with _patched_client(rec):
        with pytest.raises(BlockExecutionError) as exc:
            await block.execute(
                params={"lot_id": "LOT-0123"}, inputs={}, context=context,
            )
    assert exc.value.code == "UPSTREAM_ERROR"
    assert "500" in exc.value.message


async def test_http_connect_error_raises_block_error(block, context):
    rec = _Recorder({}, raise_exc=httpx.ConnectError("no route to host"))
    with _patched_client(rec):
        with pytest.raises(BlockExecutionError) as exc:
            await block.execute(
                params={"lot_id": "LOT-0123"}, inputs={}, context=context,
            )
    assert exc.value.code == "HTTP_ERROR"
