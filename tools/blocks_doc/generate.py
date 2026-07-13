"""blocks 文件產生器（2026-07-13, user 要求）。

從 seed.py（block 文件的單一來源）產生 docs/BLOCKS.md — 人讀版積木手冊。
改了 seed 的 description/param_schema 後重跑本檔，文件永不過時：

    python3 tools/blocks_doc/generate.py

驗證配套：python_ai_sidecar/tests/test_blocks_core.py 逐案對照文件宣稱的
行為（例：block_streak 的 doc example 直接是一個測試案例）。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from python_ai_sidecar.pipeline_builder.seed import _blocks  # noqa: E402

CATEGORY_LABEL = {
    "source": "資料源 Source",
    "transform": "處理 Transform",
    "logic": "邏輯/統計 Logic & Stats",
    "output": "輸出 Output（圖表/表格/告警）",
}


def _ports(schema: list) -> str:
    return ", ".join(f"`{p.get('port')}` ({p.get('type')})" for p in (schema or [])) or "—"


def _params_table(ps: dict) -> str:
    props = (ps or {}).get("properties") or {}
    if not props:
        return "（無參數）\n"
    required = set((ps or {}).get("required") or [])
    lines = ["| 參數 | 型別 | 必填 | 說明 |", "|---|---|---|---|"]
    for name, prop in props.items():
        t = prop.get("type")
        if not t and isinstance(prop.get("oneOf"), list):
            t = " / ".join(str(o.get("type", "?")) for o in prop["oneOf"])
        enum = prop.get("enum")
        desc = str(prop.get("title") or "")
        if enum:
            desc = (desc + " " if desc else "") + f"可選：{', '.join(map(str, enum))}"
        lines.append(f"| `{name}` | {t or 'any'} | {'是' if name in required else ''} | {desc} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    blocks = sorted(_blocks(), key=lambda b: (b.get("category", ""), b["name"]))
    out: list[str] = [
        "# Pipeline Builder — 積木手冊",
        "",
        f"自動產生於 {date.today().isoformat()}，來源 `python_ai_sidecar/pipeline_builder/seed.py`"
        "（block 文件的單一來源 — GUI 表單、agent 目錄與本檔皆出自它）。",
        "**不要手改本檔** — 改 seed 後跑 `python3 tools/blocks_doc/generate.py` 重生。",
        "",
        f"共 {len(blocks)} 個積木。行為驗證：`python_ai_sidecar/tests/test_blocks_core.py`。",
        "",
        "## 目錄",
        "",
    ]
    by_cat: dict[str, list[dict]] = {}
    for b in blocks:
        by_cat.setdefault(b.get("category", "other"), []).append(b)
    for cat, items in by_cat.items():
        out.append(f"- **{CATEGORY_LABEL.get(cat, cat)}**：" +
                   "、".join(f"[`{b['name']}`](#{b['name'].replace('_', '-')})" for b in items))
    out.append("")

    for cat, items in by_cat.items():
        out.append(f"# {CATEGORY_LABEL.get(cat, cat)}")
        out.append("")
        for b in items:
            out.append(f"## {b['name']}")
            out.append("")
            out.append(f"- **狀態**：{b.get('status')}　**版本**：{b.get('version')}")
            out.append(f"- **輸入**：{_ports(b.get('input_schema'))}")
            out.append(f"- **輸出**：{_ports(b.get('output_schema'))}")
            out.append("")
            out.append("```")
            out.append(str(b.get("description", "")).strip())
            out.append("```")
            out.append("")
            out.append("**參數**")
            out.append("")
            out.append(_params_table(b.get("param_schema") or {}))
    target = REPO / "docs" / "BLOCKS.md"
    target.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size} bytes, {len(blocks)} blocks)")


if __name__ == "__main__":
    main()
