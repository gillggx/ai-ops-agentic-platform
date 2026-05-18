"""Prompt assets (markdown) loaded by graph nodes at startup."""
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent

_glossary_cache: str | None = None


def load_spc_apc_glossary() -> str:
    """Return SPC/APC domain glossary (cached after first load)."""
    global _glossary_cache
    if _glossary_cache is None:
        _glossary_cache = (_PROMPTS_DIR / "spc_apc_glossary.md").read_text()
    return _glossary_cache
