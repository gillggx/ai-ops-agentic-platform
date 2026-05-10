"""Deterministic dimension detectors + LLM-enriched clarifications.

Plan-Mode-style multi-choice confirmation. When the chat orchestrator decides
to call confirm_pipeline_intent (because the prompt is ambiguous), this
module:

  1. Runs a battery of pure-Python detectors against (user_msg, declared_inputs,
     pipeline_snapshot). Each detector that fires returns a `Dimension` —
     a canonical id + canonical option values + a default. NO labels here.

  2. Calls the LLM once (cheap) to enrich the detected dimensions with
     user-facing question text + per-option label/hint, in the user's
     language. This is the ONLY LLM responsibility in this module — pure
     localization. Detection logic stays deterministic so unit-testing
     "did we detect scope conflict" doesn't depend on LLM behaviour.

  3. Provides `augment_goal_for_resolutions()` — a deterministic map from
     (dimension, chosen_option) → a sentence to splice into build_pipeline_live's
     goal text. So once the user picks scope=all_machines, the next
     build_pipeline_live call gets goal augmented with explicit guidance
     "**不要** filter $tool_id — 撈所有機台用於跨機台比較" without the LLM
     having to remember to do it.

The user (CLAUDE.md) preference: "LLM 只負責 generate label/hint" — detection
+ resolution stay deterministic.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)


# ── Data shape ─────────────────────────────────────────────────────────────


@dataclass
class Option:
    """Canonical option for a dimension. label/hint filled by LLM enrichment."""
    value: str
    label: str = ""        # Filled by LLM
    hint: str | None = None


@dataclass
class Dimension:
    """One detected ambiguity dimension."""
    dimension: str         # canonical id e.g. "scope" / "metric"
    question: str = ""     # Filled by LLM
    options: list[Option] = field(default_factory=list)
    default: str | None = None
    multi: bool = False    # single-select by default


# ── Detectors ──────────────────────────────────────────────────────────────
#
# Each detector takes (user_msg, declared_input_names, pipeline_snapshot)
# and returns a Dimension or None. Detectors are pure functions — no LLM,
# no I/O. Order matters: top-3 firing detectors become clarifications
# (more than 3 in one card is too noisy).


# Words that imply "across multiple machines / cross-machine comparison".
_MULTI_TOOL_TOKENS = (
    "各機台", "各 機台", "跨機台", "全廠", "所有機台", "全部機台",
    "every tool", "all tools", "across tools", "across machines",
)
# Words for "single tool" — when user says these, no scope ambiguity.
_SINGLE_TOOL_TOKENS = ("這台", "該機台", "指定機台", "single tool")


def _detect_scope_conflict(
    msg: str, declared: set[str], snap: dict[str, Any],
) -> Dimension | None:
    """User declared $tool_id (single-tool param) but message also mentions
    multi-tool concepts ("各機台" / "all tools"). Resolve before building."""
    if "tool_id" not in declared and "equipment_id" not in declared:
        return None
    if not any(tok in msg for tok in _MULTI_TOOL_TOKENS):
        return None
    if any(tok in msg for tok in _SINGLE_TOOL_TOKENS):
        # Explicit single-tool wording wins; no conflict.
        return None
    return Dimension(
        dimension="scope",
        options=[
            Option(value="single_via_param"),
            Option(value="all_machines"),
            Option(value="multi_via_list"),
        ],
        default="single_via_param",
    )


# Words for general anomaly/exception terms that don't pin a metric family.
_ANOMALY_TOKENS = ("OOC", "ooc", "異常", "exception", "anomaly", "out of control")
_APC_TOKENS = ("APC", "apc")
_SPC_TOKENS = ("SPC", "spc", "X̄", "xbar", "管制圖")
_FDC_TOKENS = ("FDC", "fdc")


def _detect_metric_type(
    msg: str, declared: set[str], snap: dict[str, Any],
) -> Dimension | None:
    """User mentions OOC/異常 without disambiguating the metric family.
    APC OOC vs SPC OOC vs FDC have totally different upstream blocks
    (apc_long_form vs spc_long_form vs raw process_history).
    """
    if not any(tok in msg for tok in _ANOMALY_TOKENS):
        return None
    has_apc = any(tok in msg for tok in _APC_TOKENS)
    has_spc = any(tok in msg for tok in _SPC_TOKENS)
    has_fdc = any(tok in msg for tok in _FDC_TOKENS)
    explicit_count = sum([has_apc, has_spc, has_fdc])
    if explicit_count == 1:
        return None  # Already explicit
    # Either zero or multiple metric families mentioned → ask
    return Dimension(
        dimension="metric",
        options=[
            Option(value="apc"),
            Option(value="spc"),
            Option(value="fdc"),
            Option(value="all"),
        ],
        default="spc" if has_spc else "apc" if has_apc else None,
    )


_BAR_TOKENS = ("bar chart", "長條圖", "bar 圖", "柱狀")


def _detect_bar_x_axis(
    msg: str, declared: set[str], snap: dict[str, Any],
) -> Dimension | None:
    """User wants bar chart but didn't pin the x-axis dimension.
    Common confusions: 各機台 vs 各 APC param vs 各 APC instance vs 各時間段.

    by_param vs by_apc_instance is THE distinction users always miss:
    - by_param   = bar per APC parameter (etch_time_offset, rf_power_bias…)
                   → degenerate for OOC count (every event has all params)
    - by_apc_instance = bar per APC model (APC-001, APC-009…)
                   → what user actually wants for "哪個 APC 觸發 OOC"
    """
    if not any(tok.lower() in msg.lower() for tok in _BAR_TOKENS):
        return None
    explicit_x = (
        any(tok in msg for tok in _MULTI_TOOL_TOKENS) or
        "各 param" in msg or "各參數" in msg or
        "每小時" in msg or "每天" in msg or "時間" in msg
    )
    if explicit_x:
        return None
    return Dimension(
        dimension="bar_x_axis",
        options=[
            Option(value="by_machine"),
            Option(value="by_apc_instance"),
            Option(value="by_param"),
            Option(value="by_time"),
        ],
        default=None,
    )


_TIME_TREND_TOKENS = ("trend", "走勢", "時序", "over time", "歷時")


def _detect_time_grain(
    msg: str, declared: set[str], snap: dict[str, Any],
) -> Dimension | None:
    """User wants a trend/time-series view but didn't pin the time bucket
    (raw events vs hourly vs daily aggregation)."""
    if not any(tok.lower() in msg.lower() for tok in _TIME_TREND_TOKENS):
        return None
    # If user already specified bucket
    if "每小時" in msg or "每天" in msg or "hourly" in msg.lower() or "daily" in msg.lower():
        return None
    return Dimension(
        dimension="time_grain",
        options=[
            Option(value="raw_events"),
            Option(value="hourly"),
            Option(value="daily"),
        ],
        default="raw_events",
    )


# Order matters — top 3 firing become clarifications.
_DETECTORS = (
    _detect_scope_conflict,   # high priority: causes silent wrong filter
    _detect_metric_type,      # high priority: wrong block family = pipeline broken
    _detect_bar_x_axis,       # mid priority: wrong x = chart misleading but works
    _detect_time_grain,       # low priority: usually fine with raw_events default
)
_MAX_CLARIFICATIONS = 3


def detect_dimensions(
    user_msg: str,
    declared_inputs: list[dict[str, Any]] | None,
    pipeline_snapshot: dict[str, Any] | None,
) -> list[Dimension]:
    """Run all detectors in order, return up to 3 fired dimensions."""
    declared_names: set[str] = set()
    for inp in declared_inputs or []:
        if isinstance(inp, dict):
            n = inp.get("name")
            if n:
                declared_names.add(str(n))
    snap = pipeline_snapshot or {}
    msg = user_msg or ""
    out: list[Dimension] = []
    for det in _DETECTORS:
        try:
            dim = det(msg, declared_names, snap)
        except Exception as e:  # noqa: BLE001
            logger.warning("dimension detector %s failed: %s", det.__name__, e)
            continue
        if dim is not None:
            out.append(dim)
            if len(out) >= _MAX_CLARIFICATIONS:
                break
    return out


# ── LLM enrichment ─────────────────────────────────────────────────────────


_ENRICH_SYSTEM = """You are localizing UI text for a Pipeline Builder confirmation card.

The system has detected ambiguity dimensions in the user's prompt. Your job is
to write the user-facing question + per-option label/hint in the user's language
(match the language the user typed in — Traditional Chinese if they typed 中文,
English if they typed English).

DO NOT change the dimension ids or option values — those are canonical and the
backend uses them deterministically. Only fill in `question`, `label`, `hint`.

Style rules:
- question: a short focused question. Reference the user's actual phrasing
  when possible (e.g. user said 「各機台」 → question references that).
- label: 5-15 chars. Concrete what-it-means, not abstract.
- hint: ≤25 chars. ONE-line consequence ("會做 X / 適合 Y") or trade-off.
- For Traditional Chinese: use 繁體, no markdown bullets.

Output JSON only (no fence). Schema:
{
  "dimensions": [
    {
      "dimension": "<unchanged id>",
      "question": "<user-facing question>",
      "options": [
        {"value": "<unchanged>", "label": "<short label>", "hint": "<short hint or null>"}
      ]
    }
  ]
}
"""


_DIMENSION_HINT = {
    "scope": (
        "Resolves: should the pipeline filter to one machine (via the declared "
        "$tool_id input) or aggregate across multiple machines?"
    ),
    "metric": (
        "Resolves: which metric family does the user want — APC parameters, "
        "SPC charts, FDC events, or combine all?"
    ),
    "bar_x_axis": (
        "Resolves: bar chart x-axis dimension — by machine / by parameter / "
        "by time bucket. Affects upstream groupby."
    ),
    "time_grain": (
        "Resolves: time-series granularity — raw events / hourly buckets / "
        "daily buckets."
    ),
}

_OPTION_HINT = {
    ("scope", "single_via_param"): "filter tool_id=$tool_id (skill runs per machine)",
    ("scope", "all_machines"): "no $tool_id filter (one pipeline scans all machines)",
    ("scope", "multi_via_list"): "declare a list input + iterate (rare)",
    ("metric", "apc"): "use block_apc_long_form upstream",
    ("metric", "spc"): "use block_spc_long_form upstream",
    ("metric", "fdc"): "filter event_type=FDC on raw process_history",
    ("metric", "all"): "process each family then union",
    ("bar_x_axis", "by_machine"): "x=toolID — needs cross-machine source",
    ("bar_x_axis", "by_apc_instance"): "x=apc_id (APC-001/APC-009/…) — direct from process_history, no long_form needed",
    ("bar_x_axis", "by_param"): "x=param_name (APC param sensors) or chart_name (SPC), needs long_form. ⚠ for OOC count this is degenerate (all bars same height — every event has all params)",
    ("bar_x_axis", "by_time"): "x=hour_bucket / day_bucket, needs time groupby",
    ("time_grain", "raw_events"): "one row per event",
    ("time_grain", "hourly"): "groupby hour",
    ("time_grain", "daily"): "groupby day",
}


async def enrich_dimensions(
    dims: list[Dimension], user_msg: str,
) -> list[Dimension]:
    """Single LLM call to fill question + label + hint on all dimensions.

    Falls back gracefully if LLM call fails — uses canonical option values
    as labels. Card is still functional, just less polished.
    """
    if not dims:
        return dims

    # Build a compact JSON payload for the LLM. Includes our internal
    # semantic hints so the LLM doesn't have to guess what each dimension/
    # option means.
    payload = {
        "user_prompt": user_msg,
        "dimensions": [
            {
                "dimension": d.dimension,
                "_meaning": _DIMENSION_HINT.get(d.dimension, ""),
                "options": [
                    {
                        "value": o.value,
                        "_meaning": _OPTION_HINT.get((d.dimension, o.value), ""),
                    }
                    for o in d.options
                ],
                "default": d.default,
            }
            for d in dims
        ],
    }

    client = get_llm_client()
    try:
        resp = await client.create(
            system=_ENRICH_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            max_tokens=800,
        )
        text = (resp.text or "").strip()
        # Strip markdown fence if any
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
        decision = json.loads(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("enrich_dimensions LLM failed (%s) — using canonical labels", e)
        return _fallback_labels(dims)

    enriched = decision.get("dimensions") or []
    by_id = {d.get("dimension"): d for d in enriched if isinstance(d, dict)}
    out: list[Dimension] = []
    for d in dims:
        e = by_id.get(d.dimension) or {}
        question = (e.get("question") or "").strip()
        e_opts = {o.get("value"): o for o in (e.get("options") or []) if isinstance(o, dict)}
        new_opts = []
        for o in d.options:
            eo = e_opts.get(o.value) or {}
            new_opts.append(Option(
                value=o.value,
                label=(eo.get("label") or o.value).strip(),
                hint=(eo.get("hint") or "").strip() or None,
            ))
        out.append(Dimension(
            dimension=d.dimension,
            question=question or _fallback_question(d.dimension),
            options=new_opts,
            default=d.default,
            multi=d.multi,
        ))
    return out


def _fallback_question(dim_id: str) -> str:
    return {
        "scope": "範圍要單台還是跨機台？",
        "metric": "看哪個 metric 家族？",
        "bar_x_axis": "Bar chart 的 x 軸用哪個維度？",
        "time_grain": "時間粒度要多細？",
    }.get(dim_id, f"請選擇 {dim_id}")


def _fallback_labels(dims: list[Dimension]) -> list[Dimension]:
    """LLM enrichment failed — use canonical values + question fallback so
    the card is still usable."""
    return [
        Dimension(
            dimension=d.dimension,
            question=_fallback_question(d.dimension),
            options=[Option(value=o.value, label=o.value, hint=None) for o in d.options],
            default=d.default,
            multi=d.multi,
        )
        for d in dims
    ]


# ── Resolution → goal augmentation ─────────────────────────────────────────


# (dimension, chosen_value) → sentence to splice into build_pipeline_live goal.
# Deterministic. LLM doesn't see this; computed at build_pipeline_live time.
_RESOLUTION_GOAL_HINTS: dict[tuple[str, str], str] = {
    ("scope", "single_via_param"):
        "（user 確認 scope=單台）保留 $tool_id filter — process_history params.tool_id=$tool_id",
    ("scope", "all_machines"):
        "（user 確認 scope=跨機台）**不要** filter $tool_id — process_history 不帶 tool_id 參數，撈全廠資料用於跨機台比較／聚合",
    ("scope", "multi_via_list"):
        "（user 確認 scope=多台 list）declare 一個 list-type input (e.g. $tool_ids: string[]) 並用 mcp_foreach iterate",

    ("metric", "apc"):
        "（user 確認 metric=APC）upstream 必用 block_apc_long_form 把 wide format 攤平成 long（含 param_name + value 欄位），再做 filter / groupby",
    ("metric", "spc"):
        "（user 確認 metric=SPC）upstream 必用 block_spc_long_form 把 wide 攤平（含 chart_name + value + is_ooc 欄位），再做 filter / groupby",
    ("metric", "fdc"):
        "（user 確認 metric=FDC）篩 process_history 的 event_type=FDC 或對應欄位",
    ("metric", "all"):
        "（user 確認 metric=ALL）分別 process APC（apc_long_form）+ SPC（spc_long_form），最後 union",

    ("bar_x_axis", "by_machine"):
        "（user 確認 x 軸=各機台）bar chart x=toolID — 注意 source process_history **不能** filter $tool_id 否則只剩一根 bar",
    ("bar_x_axis", "by_apc_instance"):
        "（user 確認 x 軸=各 APC instance）bar chart x=apc_id（值如 APC-001/APC-009）— "
        "**不需要 apc_long_form**，直接 process_history → filter spc_status=OOC → "
        "groupby_agg(group_by='apc_id', agg_column='lotID', agg_func='count') → bar_chart(x='apc_id')",
    ("bar_x_axis", "by_param"):
        "（user 確認 x 軸=各 APC sensor parameter）bar chart x=param_name (APC) 或 chart_name (SPC)，必先用 long_form block。"
        "⚠ 對「OOC count」這種統計，by_param 結果會是 degenerate（每 bar 高度相同）— 因為每個 event 都帶全部 ~20 個 APC params。"
        "如果 user 想看「哪個 APC 模型觸發 OOC」應該用 by_apc_instance。",
    ("bar_x_axis", "by_time"):
        "（user 確認 x 軸=時間）bar chart x=hour_bucket 或 day_bucket，需先用 groupby_agg by time bucket",

    ("time_grain", "raw_events"):
        "（user 確認 time grain=raw）保留 raw event timestamps，不做 time bucketing",
    ("time_grain", "hourly"):
        "（user 確認 time grain=每小時）用 block_compute / block_groupby_agg 把 eventTime 截到 hour bucket 後 groupby",
    ("time_grain", "daily"):
        "（user 確認 time grain=每天）用 block_compute / block_groupby_agg 把 eventTime 截到 day bucket 後 groupby",
}


def augment_goal_for_resolutions(
    base_goal: str, resolutions: dict[str, str],
) -> str:
    """Splice deterministic goal hints into the base goal text based on
    user's clarification picks. Resolutions: {dimension_id: chosen_value}."""
    if not resolutions:
        return base_goal
    hints: list[str] = []
    for dim, val in resolutions.items():
        hint = _RESOLUTION_GOAL_HINTS.get((dim, val))
        if hint:
            hints.append(f"  - {hint}")
    if not hints:
        return base_goal
    return base_goal + "\n\n# user 已透過 confirmation card 明確的選擇\n" + "\n".join(hints)


# ── Public façade ──────────────────────────────────────────────────────────


async def build_clarifications(
    user_msg: str,
    declared_inputs: list[dict[str, Any]] | None,
    pipeline_snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Called by tool_execute confirm_pipeline_intent handler.

    Returns the SSE-ready clarifications list (already enriched). Empty list
    means "no ambiguity dimensions found" — card renders without multi-choice.
    """
    dims = detect_dimensions(user_msg, declared_inputs, pipeline_snapshot)
    if not dims:
        return []
    enriched = await enrich_dimensions(dims, user_msg)
    return [
        {
            "dimension": d.dimension,
            "question": d.question,
            "options": [
                {"value": o.value, "label": o.label, "hint": o.hint}
                for o in d.options
            ],
            "default": d.default,
            "multi": d.multi,
        }
        for d in enriched
    ]


def parse_resolutions_from_prefix(user_msg: str) -> dict[str, str]:
    """Parse `[intent_confirmed:<id> dim1=A dim2=B] original prompt` →
    {dim1: A, dim2: B}. Returns empty dict if no prefix or no resolutions.
    Defensive: malformed pieces are skipped silently."""
    m = re.match(r"^\[intent_confirmed:[^\]]*\]", user_msg or "")
    if not m:
        return {}
    inner = m.group(0)[len("[intent_confirmed:"):-1]
    out: dict[str, str] = {}
    # Format: <card_id>[ space dim=value ...]
    parts = inner.split()
    for p in parts[1:]:  # skip card_id
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k and v:
            out[k] = v
    return out
