#!/usr/bin/env python3
"""Reset PROMPT_MCP_GENERATE and PROMPT_MCP_TRY_RUN in system_parameters.

These keys may contain stale LLM prompts that use fig.to_json() or fig.to_html().
Deleting them forces the service to fall back to the updated hardcoded defaults
in mcp_builder_service.py (which mandate json.dumps(fig.to_dict())).

Usage:
    cd fastapi_backend_service
    python scripts/reset_mcp_prompts.py            # uses dev.db in current dir
    python scripts/reset_mcp_prompts.py dev.db     # explicit path
"""
import sqlite3
import sys

KEYS = ("PROMPT_MCP_GENERATE", "PROMPT_MCP_TRY_RUN")
DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "dev.db"

with sqlite3.connect(DB_PATH) as conn:
    for key in KEYS:
        cur = conn.execute(
            "SELECT key, substr(value, 1, 100) FROM system_parameters WHERE key = ?", (key,)
        )
        row = cur.fetchone()
        if row:
            print(f"Deleting stale entry: {row[0]}\n  preview: {row[1]}...\n")
            conn.execute("DELETE FROM system_parameters WHERE key = ?", (key,))
        else:
            print(f"  {key}: not in DB — hardcoded defaults already active.")
    conn.commit()

print("\nDone. mcp_builder_service.py hardcoded defaults (json.dumps(fig.to_dict())) are now active.")
