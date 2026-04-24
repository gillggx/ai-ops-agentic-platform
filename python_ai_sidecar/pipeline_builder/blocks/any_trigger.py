"""block_any_trigger — OR 多個 logic node 的 triggered + 合併 evidence。

Use case: 監控 5 張 SPC chart，5 個 WECO node 各自 triggered；想要「任一觸發就
發一封聚合告警」，就把它們全部串進 block_any_trigger，再接一個 block_alert。

Input ports: `trigger_1..4` (bool, 必須至少接一個)，`evidence_1..4` (dataframe, optional)

Output (PR-A evidence semantics):
  triggered (bool)      — OR over all connected trigger_*
  evidence  (dataframe) — concat of all connected evidence_* (不論該 port 有沒有觸發，
                          讓 audit 可看全部評估紀錄)，加欄：
                           source_port   — 來源 port 名稱（trigger_1..4）
                           triggered_row — 若上游已提供則保留；否則用 trigger_port 的 bool 填
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


# Pipeline builder input ports need to be declared at block-spec level; we fix
# a max fan-in of 4 for simplicity (covers SPC 5-chart minus one; for more,
# cascade via a second any_trigger).
_MAX_FANIN = 4
_TRIGGER_PORTS = tuple(f"trigger_{i}" for i in range(1, _MAX_FANIN + 1))
_EVIDENCE_PORTS = tuple(f"evidence_{i}" for i in range(1, _MAX_FANIN + 1))


class AnyTriggerBlockExecutor(BlockExecutor):
    block_id = "block_any_trigger"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        # At least one trigger_* must be connected
        trigger_values: list[tuple[str, bool]] = []
        for port in _TRIGGER_PORTS:
            if port in inputs:
                v = inputs[port]
                if not isinstance(v, bool):
                    raise BlockExecutionError(
                        code="INVALID_INPUT",
                        message=f"'{port}' must be bool (got {type(v).__name__})",
                    )
                trigger_values.append((port, v))
        if not trigger_values:
            raise BlockExecutionError(
                code="MISSING_INPUT",
                message="At least one of trigger_1..trigger_4 must be connected",
            )

        triggered = any(v for _, v in trigger_values)

        # Concat evidence from every connected port (NOT only triggered ones) —
        # PR-A semantics: evidence is an audit trail of all evaluated rows.
        frames: list[pd.DataFrame] = []
        for t_port, t_val in trigger_values:
            idx = t_port.split("_")[1]
            ev_port = f"evidence_{idx}"
            ev = inputs.get(ev_port)
            if isinstance(ev, pd.DataFrame) and not ev.empty:
                ev_with_source = ev.copy()
                ev_with_source["source_port"] = t_port
                # If upstream didn't emit triggered_row (older block or non-logic
                # source), fall back to propagating the port-level boolean.
                if "triggered_row" not in ev_with_source.columns:
                    ev_with_source["triggered_row"] = bool(t_val)
                frames.append(ev_with_source)

        evidence = (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame()
        )
        return {"triggered": triggered, "evidence": evidence}
