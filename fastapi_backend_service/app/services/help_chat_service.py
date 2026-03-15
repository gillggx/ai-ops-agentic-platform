"""Help Chat Service — LLM assistant for answering user usage questions.

Loads product spec and user manual as context, streams answers via the unified LLM client.
"""

import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from app.config import get_settings
from app.utils.llm_client import get_llm_client

logger = logging.getLogger(__name__)

# Module-level cache so docs are read once per process
_SYSTEM_PROMPT: Optional[str] = None


def _build_system_prompt() -> str:
    """Read docs and build the cached system prompt string."""
    docs_dir = Path(__file__).parents[3] / "docs"

    user_manual = ""
    spec = ""

    manual_path = docs_dir / "user_manual.md"
    if manual_path.exists():
        try:
            user_manual = manual_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Could not read user_manual.md: %s", e)

    spec_path = docs_dir / "Product_spec_V10" / "PRODUCT_SPEC_V10.md"
    if spec_path.exists():
        try:
            spec = spec_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Could not read PRODUCT_SPEC_V10.md: %s", e)

    return (
        "你是 Glass Box AI 診斷系統的使用輔助助理。\n"
        "請根據以下產品說明文件和使用者手冊，以繁體中文回答使用者的操作問題。\n"
        "回答請簡潔清晰，必要時可分點說明。\n"
        "如果文件中沒有相關資訊，請誠實告知，並建議使用者查閱文件或聯絡管理員。\n\n"
        "=== 使用者手冊 ===\n"
        f"{user_manual}\n\n"
        "=== 產品規格說明 ===\n"
        f"{spec}"
    )


def _get_system_prompt() -> str:
    """Return the cached system prompt, building it on first call."""
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _build_system_prompt()
    return _SYSTEM_PROMPT


class HelpChatService:
    """Streams answers to user usage questions based on product documentation."""

    def __init__(self) -> None:
        self._llm = get_llm_client()

    async def stream_chat(
        self,
        message: str,
        history: List[Dict[str, str]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield SSE-ready dicts: {type: "chat", message} ... {type: "done"}."""
        return self._stream_impl(message, history)

    async def _stream_impl(
        self,
        message: str,
        history: List[Dict[str, str]],
    ) -> AsyncIterator[Dict[str, Any]]:
        # Build messages: history + current user turn
        messages = []
        for h in history:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})

        system_prompt = _get_system_prompt()

        try:
            async for chunk_text in self._llm.stream(
                system=system_prompt,
                messages=messages,
                max_tokens=get_settings().LLM_MAX_TOKENS_CHAT,
            ):
                yield {"type": "chat", "message": chunk_text}

            yield {"type": "done"}

        except Exception as exc:
            logger.error("HelpChatService stream error: %s", exc)
            yield {"type": "error", "message": str(exc)}
            yield {"type": "done"}
