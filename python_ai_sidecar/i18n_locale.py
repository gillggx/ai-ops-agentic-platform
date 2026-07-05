"""i18n P4 (2026-07-05) — 對話跟隨 user 語系的 prompt 注入 helper。

原則：
- zh-TW（產品預設）**不注入**：現行 prompt 已產繁中，維持 byte-identical
  （SMOKE 基線與 prompt cache 不受影響）。
- 專有名詞（OOC/Cpk/SPC/block/pipeline、tool_id 值）不翻譯。
- ja 定調です・ます体。

`current_locale` contextvar 給不方便 thread state 的深層呼叫
（advisor synthesize 等）；有 state 的節點直接把 locale 傳給
locale_directive()。
"""
from __future__ import annotations

from contextvars import ContextVar

current_locale: ContextVar[str] = ContextVar("ui_locale", default="")

_LOCALE_LABELS = {
    "zh-CN": "Simplified Chinese (简体中文)",
    "en": "English",
    "ja": "Japanese (日本語)",
}


def locale_directive(locale: str | None = None) -> str:
    """System-prompt 附加段。zh-TW / 未知 locale 回空字串（不改 prompt）。"""
    loc = (locale if locale is not None else current_locale.get()) or ""
    label = _LOCALE_LABELS.get(loc.strip())
    if not label:
        return ""
    ja_style = " Use polite です・ます style." if loc.strip() == "ja" else ""
    return (
        f"\n\n# Response language\n"
        f"Reply to the user in {label}.{ja_style} Keep technical tokens "
        f"(OOC, Cpk, SPC, xbar, UCL/LCL, block/pipeline/phase names, "
        f"tool_id / lot_id values) in their original form.\n"
    )
