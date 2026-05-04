"""Eager placeholder check on set_param / add_node.

The Glass Box agent loop accepts `$xxx` placeholders in node params, but only
those whose `xxx` is declared via declare_input(). This test pins the
left-shifted invariant so a regression — bad placeholder slipping through to
the canvas SSE stream — surfaces at PR time, not in production.

Background: a chat-mode build for "EQP-01 STEP_001 xbar 趨勢" once produced
`set_param(n1, "tool_id", "$EquipmentID")` even though no `EquipmentID` input
was declared, so Full Run on the resulting canvas exploded with
UNDECLARED_INPUT_REF. The check below blocks that drift at write time.
"""

from __future__ import annotations

import pytest

from python_ai_sidecar.agent_builder.session import AgentBuilderSession
from python_ai_sidecar.agent_builder.tools import BuilderToolset, ToolError
from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry
from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineInput


def _make_registry() -> BlockRegistry:
    """Stub registry with one block whose params include `tool_id` (string)."""
    reg = BlockRegistry()
    reg._catalog[("block_process_history", "1.0.0")] = {
        "name": "block_process_history",
        "version": "1.0.0",
        "category": "source",
        "status": "production",
        "input_schema": [],
        "output_schema": [{"port": "data", "type": "dataframe"}],
        "param_schema": {
            "type": "object",
            "properties": {
                "tool_id": {"type": "string"},
                "step": {"type": "string"},
                "object_name": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
    }
    return reg


def _make_toolset(*, with_input: bool = False) -> BuilderToolset:
    session = AgentBuilderSession.new(user_prompt="test")
    if with_input:
        session.pipeline_json.inputs.append(
            PipelineInput(name="tool_id", type="string", example="EQP-01")
        )
    return BuilderToolset(session, _make_registry())


@pytest.mark.asyncio
async def test_set_param_rejects_undeclared_placeholder():
    ts = _make_toolset(with_input=False)
    await ts.add_node(block_name="block_process_history")

    with pytest.raises(ToolError) as exc:
        await ts.set_param(node_id="n1", key="tool_id", value="$EquipmentID")

    assert exc.value.code == "UNDECLARED_INPUT_REF"
    assert "$EquipmentID" in exc.value.message
    assert exc.value.hint and "declare_input" in exc.value.hint


@pytest.mark.asyncio
async def test_set_param_accepts_declared_placeholder():
    ts = _make_toolset(with_input=True)
    await ts.add_node(block_name="block_process_history")

    result = await ts.set_param(node_id="n1", key="tool_id", value="$tool_id")
    assert result["params"]["tool_id"] == "$tool_id"


@pytest.mark.asyncio
async def test_set_param_accepts_literal_value():
    ts = _make_toolset(with_input=False)
    await ts.add_node(block_name="block_process_history")

    result = await ts.set_param(node_id="n1", key="tool_id", value="EQP-01")
    assert result["params"]["tool_id"] == "EQP-01"


@pytest.mark.asyncio
async def test_add_node_rejects_undeclared_placeholder_in_params():
    ts = _make_toolset(with_input=False)

    with pytest.raises(ToolError) as exc:
        await ts.add_node(
            block_name="block_process_history",
            params={"tool_id": "$EquipmentID", "step": "STEP_001"},
        )

    assert exc.value.code == "UNDECLARED_INPUT_REF"
    assert "$EquipmentID" in exc.value.message


@pytest.mark.asyncio
async def test_add_node_accepts_declared_placeholder_in_params():
    ts = _make_toolset(with_input=True)

    result = await ts.add_node(
        block_name="block_process_history",
        params={"tool_id": "$tool_id", "step": "STEP_001"},
    )
    assert result["node_id"] == "n1"
    assert ts.session.pipeline_json.nodes[0].params == {
        "tool_id": "$tool_id",
        "step": "STEP_001",
    }


@pytest.mark.asyncio
async def test_set_param_lists_currently_declared_inputs_in_error():
    """Error hint should name what IS declared so LLM can pick a valid ref."""
    ts = _make_toolset(with_input=True)
    ts.session.pipeline_json.inputs.append(
        PipelineInput(name="step", type="string", example="STEP_001")
    )
    await ts.add_node(block_name="block_process_history")

    with pytest.raises(ToolError) as exc:
        await ts.set_param(node_id="n1", key="tool_id", value="$EquipmentID")

    # both declared inputs surface in the message
    assert "$step" in exc.value.message
    assert "$tool_id" in exc.value.message
