"""Tests for the block_docs frontmatter parser used by list_blocks +
explain_block (POC skill-library, 2026-06-10).

Covers the four cases that flow through the catalog → detail path:
    - real markdown with frontmatter description + body
    - frontmatter without description: field
    - markdown without YAML frontmatter at all
    - empty / None input
"""
from __future__ import annotations

from python_ai_sidecar.agent_builder.tools import _parse_block_doc_markdown


def test_parses_frontmatter_with_description_and_body():
    md = """---
name: block_filter
description: Filter DataFrame rows by single condition. Pass-through transform — does not aggregate.
---

# block_filter

Body content here.

## When to invoke
"""
    desc, body = _parse_block_doc_markdown(md)
    assert desc == (
        "Filter DataFrame rows by single condition. Pass-through "
        "transform — does not aggregate."
    )
    assert body is not None
    assert body.startswith("# block_filter")
    assert "## When to invoke" in body


def test_collapses_multiline_description():
    md = """---
name: block_x
description: First sentence.
  Continuation indented per YAML.
  Third line.
---

body
"""
    desc, body = _parse_block_doc_markdown(md)
    assert desc is not None
    assert "\n" not in desc
    assert "First sentence" in desc
    assert "Third line" in desc
    assert body == "body\n"


def test_frontmatter_without_description_field():
    md = """---
name: block_x
category: chart
---

# block_x

Body.
"""
    desc, body = _parse_block_doc_markdown(md)
    assert desc is None
    assert body is not None
    assert body.startswith("# block_x")


def test_no_frontmatter_returns_whole_input_as_body():
    md = "# block_x\n\nNo frontmatter present.\n"
    desc, body = _parse_block_doc_markdown(md)
    assert desc is None
    assert body == md  # whole input becomes body


def test_empty_input():
    assert _parse_block_doc_markdown("") == (None, None)
    assert _parse_block_doc_markdown(None) == (None, None)


def test_handles_dashes_in_body():
    # body has its own --- separator (markdown horizontal rule) — must not
    # confuse the frontmatter close detection.
    md = """---
name: block_x
description: A block.
---

# block_x

Section A

---

Section B
"""
    desc, body = _parse_block_doc_markdown(md)
    assert desc == "A block."
    assert "Section A" in body
    assert "Section B" in body
