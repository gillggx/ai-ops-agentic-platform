"""V49 (2026-05-19) — auto-generate block_docs from seed.py catalog.

For each block in the sidecar catalog:
  1. Read existing description + executor code + param_schema + examples
  2. Pass to LLM with the block_step_check reference doc as few-shot
  3. LLM emits YAML frontmatter + Markdown body following the template
  4. Upsert into block_docs DB via Java /api/v1/block-docs PUT
     (or directly POST with internal token via /internal — see flags)

Usage:
    python tools/generate_block_docs.py \
        --java-base http://localhost:8002 \
        --internal-token "$AIOPS_INTERNAL_TOKEN" \
        [--block_id block_step_check]   # single block only
        [--force]                       # overwrite non-auto_generated rows

Reference doc (few-shot): tools/block_doc_examples/block_step_check.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("generate_block_docs")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

REFERENCE_DOC_PATH = Path(__file__).parent / "block_doc_examples" / "block_step_check.md"


SYSTEM_PROMPT = """你是 pipeline block documentation generator。產出 single Markdown 文件,
follow Claude SKILL.md 慣例: YAML frontmatter (name + description) + body sections.

Body sections (固定順序, 缺一不可):
  # <block_id>           ← title
  1-2 段 overview 講做什麼

  ## When to invoke
  - bullet: 何時用 (use cases, business intent)
  不適用情境:
  - bullet: 該用另一個 block 的 case

  ## Inputs
  ### port: <name>
  - type, required, 期望狀態, 必要欄位, 不接受
  upstream sample (```json ... ```)

  ## Outputs
  ### port: <name>
  - type, shape (rows/columns), 產出欄位 + type + 描述, 下游 hint
  output sample (```json ... ```)

  ## Parameters
  | name | type | required | default | enum | 用途 |
  常見錯誤 bullets

  ## Examples
  1-2 完整 pipeline chain (```...```) + 意圖 + 注意事項

規則:
- frontmatter description 是 ≤150 chars 1-line headline (給 catalog brief 用)
- 不寫 case-specific rule (per CLAUDE.md rule 0); 只寫 principle/pattern
- 不用 emoji (per feedback_no_emoji.md)
- 全篇 1500-2500 chars 為宜
"""


def _build_user_prompt(block: dict, reference_doc: str) -> str:
    """Compose the LLM user prompt with source material."""
    name = block.get("name") or "(unknown)"
    desc_raw = (block.get("description") or "").strip()
    category = block.get("category") or ""
    status = block.get("status") or ""
    param_schema = block.get("param_schema") or {}
    input_schema = block.get("input_schema") or []
    output_schema = block.get("output_schema") or []
    examples = block.get("examples") or []
    produces = block.get("produces") or {}

    return f"""參考範例 (block_step_check):
```markdown
{reference_doc}
```

現在請為以下 block 產出同樣格式的 Markdown 文件:

== Source material ==
block_id: {name}
category: {category}
status: {status}

== Existing description (要重組到新格式內) ==
{desc_raw[:3000]}

== input_schema ==
{json.dumps(input_schema, ensure_ascii=False, indent=2)}

== output_schema ==
{json.dumps(output_schema, ensure_ascii=False, indent=2)}

== param_schema ==
{json.dumps(param_schema, ensure_ascii=False, indent=2)[:2000]}

== examples (from seed) ==
{json.dumps(examples, ensure_ascii=False, indent=2)[:2000]}

== produces ==
{json.dumps(produces, ensure_ascii=False, indent=2)[:600]}

請輸出 **single Markdown file content** (YAML frontmatter + body), 不要加額外
解釋, 不要 markdown fence 包整個檔。
"""


async def _list_blocks_from_seed() -> list[dict]:
    """Import seed catalog directly (script runs on sidecar host)."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from python_ai_sidecar.pipeline_builder.seed import BLOCK_DEFINITIONS
    return [dict(b) for b in BLOCK_DEFINITIONS]


async def _generate_doc(block: dict, reference_doc: str) -> str:
    """Call LLM to generate Markdown doc for one block."""
    from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
    client = get_llm_client()
    resp = await client.create(
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(block, reference_doc)}],
        max_tokens=3000,
    )
    return (resp.text or "").strip()


async def _upsert_doc(java_base: str, internal_token: str, block_id: str,
                      block_version: str, markdown: str, dry_run: bool) -> bool:
    """PUT block doc via internal endpoint variant.

    Internal write-path doesn't exist yet — this script POSTs to a temp
    raw SQL endpoint OR uses sidecar's own DB session. For now we go via
    the admin /api/v1 PUT path with bypass header (or print on dry-run).
    """
    if dry_run:
        logger.info("dry-run: would upsert %s/%s (%d chars)",
                    block_id, block_version, len(markdown))
        return True
    url = f"{java_base.rstrip('/')}/internal/block-docs/{block_id}/{block_version}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(
            url,
            json={"markdown": markdown, "auto_generated": True},
            headers={"X-Internal-Token": internal_token},
        )
    if resp.status_code in (200, 201):
        return True
    logger.warning("upsert %s/%s failed: %d %s",
                   block_id, block_version, resp.status_code, resp.text[:200])
    return False


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--java-base", default="http://localhost:8002")
    parser.add_argument("--internal-token", default="")
    parser.add_argument("--block_id", help="single block only (omit = all)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite even if existing doc is admin-edited")
    parser.add_argument("--dry-run", action="store_true",
                        help="generate but don't upsert; print first 400 chars")
    args = parser.parse_args()

    if not REFERENCE_DOC_PATH.exists():
        logger.error("reference doc not found: %s", REFERENCE_DOC_PATH)
        return 1
    reference_doc = REFERENCE_DOC_PATH.read_text()

    blocks = await _list_blocks_from_seed()
    if args.block_id:
        blocks = [b for b in blocks if b.get("name") == args.block_id]
        if not blocks:
            logger.error("block_id not found: %s", args.block_id)
            return 1

    logger.info("generating docs for %d blocks (dry_run=%s)", len(blocks), args.dry_run)
    ok = fail = 0
    for block in blocks:
        block_id = block.get("name")
        block_version = block.get("version") or "1.0.0"
        try:
            markdown = await _generate_doc(block, reference_doc)
            if not markdown.startswith("---"):
                logger.warning("%s: doc didn't start with frontmatter, prepending",
                               block_id)
                markdown = (
                    f"---\nname: {block_id}\n"
                    f"description: (auto-generated, needs review)\n---\n"
                ) + markdown
            if args.dry_run:
                print(f"\n===== {block_id} =====")
                print(markdown[:400])
                print(f"... ({len(markdown)} chars total)")
                ok += 1
                continue
            success = await _upsert_doc(args.java_base, args.internal_token,
                                        block_id, block_version, markdown,
                                        args.dry_run)
            if success:
                ok += 1
                logger.info("[ok] %s (%d chars)", block_id, len(markdown))
            else:
                fail += 1
        except Exception as ex:  # noqa: BLE001
            logger.exception("%s: generation failed: %s", block_id, ex)
            fail += 1

    logger.info("done: %d ok / %d fail", ok, fail)
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
