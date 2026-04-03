#!/usr/bin/env python3
"""
scripts/migrate_memories_to_mem0.py
────────────────────────────────────
將 SQLite agent_memories 表格的現有記錄批量遷移至 Mem0。

使用方式：
    cd fastapi_backend_service
    MEM0_API_KEY=your_key python scripts/migrate_memories_to_mem0.py

    # 指定資料庫路徑 (預設 ./dev.db)
    DATABASE_PATH=./prod.db MEM0_API_KEY=your_key python scripts/migrate_memories_to_mem0.py

    # Dry-run 模式 (不實際寫入 Mem0，只顯示會遷移的記錄)
    DRY_RUN=1 python scripts/migrate_memories_to_mem0.py
"""

import asyncio
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DATABASE_PATH = os.environ.get("DATABASE_PATH", "./dev.db")
MEM0_API_KEY  = os.environ.get("MEM0_API_KEY", "")
DRY_RUN       = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
BATCH_SIZE    = int(os.environ.get("BATCH_SIZE", "50"))
MEM0_USER_ID  = "aiops_migrated"   # Mem0 user_id tag for all migrated memories

# ── Types ─────────────────────────────────────────────────────────────────────

@dataclass
class LocalMemory:
    id: int
    session_id: Optional[str]
    memory_type: str       # trap | diagnosis | preference | schema_lesson | general
    content: str
    tags: Optional[str]    # comma-separated
    source: Optional[str]
    created_at: str


# ── Fetch from SQLite ─────────────────────────────────────────────────────────

def fetch_memories(db_path: str) -> list[LocalMemory]:
    if not os.path.exists(db_path):
        log.error(f"資料庫不存在: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Skip trap / diagnosis — those stay local (conflict-checked logic)
        rows = conn.execute("""
            SELECT id, session_id, memory_type, content, tags, source, created_at
            FROM agent_memories
            WHERE memory_type NOT IN ('trap', 'diagnosis')
            ORDER BY created_at ASC
        """).fetchall()
        return [LocalMemory(**dict(r)) for r in rows]
    except sqlite3.OperationalError as e:
        log.error(f"無法讀取 agent_memories 表格: {e}")
        sys.exit(1)
    finally:
        conn.close()


def count_skipped(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM agent_memories WHERE memory_type IN ('trap', 'diagnosis')"
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0
    finally:
        conn.close()


# ── Build Mem0 payload ────────────────────────────────────────────────────────

def build_mem0_messages(mem: LocalMemory) -> list[dict]:
    """
    Mem0 add() 接受 messages list (OpenAI 格式)。
    我們把 content 包成 user message，讓 Mem0 自動萃取。
    """
    tag_note = f"\n[tags: {mem.tags}]" if mem.tags else ""
    source_note = f"\n[source: {mem.source}]" if mem.source else ""
    text = f"[memory_type: {mem.memory_type}] {mem.content}{tag_note}{source_note}"
    return [{"role": "user", "content": text}]


def build_mem0_metadata(mem: LocalMemory) -> dict:
    return {
        "migrated_from": "sqlite_agent_memories",
        "original_id": mem.id,
        "memory_type": mem.memory_type,
        "session_id": mem.session_id or "",
        "created_at": mem.created_at,
    }


# ── Migrate ───────────────────────────────────────────────────────────────────

async def migrate(memories: list[LocalMemory]) -> None:
    if not MEM0_API_KEY:
        log.error("MEM0_API_KEY 未設定，無法寫入 Mem0。")
        log.error("使用 export MEM0_API_KEY=your_key 設定後重試。")
        sys.exit(1)

    try:
        from mem0 import AsyncMemoryClient
    except ImportError:
        log.error("找不到 mem0ai 套件。請先執行: pip install mem0ai>=0.1.29")
        sys.exit(1)

    client = AsyncMemoryClient(api_key=MEM0_API_KEY)

    success = 0
    failed  = 0

    for i, mem in enumerate(memories, 1):
        log.info(f"[{i}/{len(memories)}] id={mem.id} type={mem.memory_type} | {mem.content[:60]}...")

        if DRY_RUN:
            success += 1
            continue

        try:
            await asyncio.wait_for(
                client.add(
                    messages=build_mem0_messages(mem),
                    user_id=MEM0_USER_ID,
                    metadata=build_mem0_metadata(mem),
                ),
                timeout=10.0,
            )
            success += 1
        except asyncio.TimeoutError:
            log.warning(f"  ⏱ 超時跳過 id={mem.id}")
            failed += 1
        except Exception as e:
            log.warning(f"  ❌ 失敗 id={mem.id}: {e}")
            failed += 1

        # 批次間短暫休息，避免 rate-limit
        if i % BATCH_SIZE == 0:
            log.info(f"  已完成 {i} 筆，休息 2 秒...")
            await asyncio.sleep(2)

    return success, failed


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    log.info("=" * 60)
    log.info("Mem0 Migration Script")
    log.info(f"  資料庫: {DATABASE_PATH}")
    log.info(f"  Dry-run: {DRY_RUN}")
    log.info(f"  批次大小: {BATCH_SIZE}")
    log.info("=" * 60)

    memories = fetch_memories(DATABASE_PATH)
    skipped  = count_skipped(DATABASE_PATH)

    log.info(f"找到 {len(memories)} 筆待遷移記錄 (跳過 {skipped} 筆 trap/diagnosis)")

    if not memories:
        log.info("無需遷移，結束。")
        return

    if DRY_RUN:
        log.info("[DRY-RUN] 以下記錄將被遷移（但不實際執行）：")
        for mem in memories[:20]:
            log.info(f"  id={mem.id:>4}  type={mem.memory_type:<20}  {mem.content[:50]}")
        if len(memories) > 20:
            log.info(f"  ... 還有 {len(memories) - 20} 筆")
        log.info("[DRY-RUN] 完成預覽。移除 DRY_RUN=1 後重新執行以實際遷移。")
        return

    success, failed = await migrate(memories)

    log.info("=" * 60)
    log.info(f"遷移完成: ✅ {success} 筆成功 | ❌ {failed} 筆失敗")
    if failed > 0:
        log.warning("部分記錄遷移失敗，可重新執行腳本（已成功的記錄會在 Mem0 中重複，影響不大）。")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
