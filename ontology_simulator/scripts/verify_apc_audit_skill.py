#!/usr/bin/env python3
"""
verify_apc_audit_skill.py — Sprint v2.3a Demo / Local Troubleshooting Script
=============================================================================

Purpose
-------
Validates the Pillar 4 endpoint (GET /api/v2/ontology/history/APC/{apc_id})
and simulates the AIOps APC_Model_Audit skill logic end-to-end.

Positioning
-----------
  Local Troubleshooting / Demo Script (per team spec 2026-02-27).
  NOT mounted in CI; run manually by architect or devops to confirm
  DB join logic is correct before a release.

Usage
-----
  # With the OntologySimulator running on port 8001:
  python verify_apc_audit_skill.py

  # Against a custom host:
  python verify_apc_audit_skill.py --host https://aiops.example.com

  # Use embedded mock data (no live server needed):
  python verify_apc_audit_skill.py --mock

Agent Simulation
----------------
The script mirrors what the APC_Model_Audit AIOps skill would do:

  1. Call GET /api/v2/ontology/history/APC/APC-0042
  2. Extract (etch_time_offset, spc_status) from each history record
  3. Scan for the oscillation pattern:
       - 3 consecutive OOC events
       - etch_time_offset variance > OSCILLATION_THRESHOLD
  4. If pattern found → print Agent decision and exit with code 1
     (non-zero exit signals CI/operator that action is required)
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from statistics import variance

# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_HOST      = "http://127.0.0.1:8001"
APC_ID            = "APC-0042"
ENDPOINT_TEMPLATE = "{host}/api/v2/ontology/history/APC/{apc_id}"
OSCILLATION_THRESHOLD = 0.5   # offset variance threshold to flag oscillation
CONSECUTIVE_OOC_MIN   = 3     # min consecutive OOC events to trigger warning

# ── Mock data (fallback when --mock or server unreachable) ────────────────────
#
# Represents a realistic oscillating APC-0042 scenario:
#   • records 0-1  : stable compensation, IN_CTRL
#   • records 2-4  : large offset swings + 3× consecutive OOC ← trigger
#   • records 5-9  : mixed, mostly IN_CTRL

_MOCK_HISTORY = [
    # (etch_time_offset, spc_status)         ← newest first
    {"etch_time_offset":  0.12, "spc_status": "IN_CTRL"},
    {"etch_time_offset":  0.09, "spc_status": "IN_CTRL"},
    {"etch_time_offset":  1.87, "spc_status": "OOC"},      # ← oscillation starts
    {"etch_time_offset": -1.63, "spc_status": "OOC"},
    {"etch_time_offset":  2.11, "spc_status": "OOC"},      # ← 3 consecutive OOC
    {"etch_time_offset":  0.31, "spc_status": "IN_CTRL"},
    {"etch_time_offset":  0.18, "spc_status": "IN_CTRL"},
    {"etch_time_offset": -0.07, "spc_status": "OOC"},
    {"etch_time_offset":  0.44, "spc_status": "IN_CTRL"},
    {"etch_time_offset":  0.22, "spc_status": "IN_CTRL"},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_history(host: str, apc_id: str) -> list[dict]:
    """Call Pillar 4 and return the history list."""
    url = ENDPOINT_TEMPLATE.format(host=host, apc_id=apc_id)
    print(f"[Agent] 呼叫 Pillar 4 API: GET {url}")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] HTTP {e.code}: {e.reason}")
        sys.exit(2)
    except urllib.error.URLError as e:
        print(f"[ERROR] 無法連線至 {host}: {e.reason}")
        print("       → 請確認 OntologySimulator 已啟動，或加上 --mock 使用內嵌測試資料")
        sys.exit(2)

    total   = body.get("total_records", 0)
    history = body.get("history", [])
    print(f"[Agent] 取得 {total} 筆 {apc_id} 歷史紀錄 (joined with spc_status)\n")
    return history


def _extract_pairs(history: list[dict]) -> list[tuple[float, str]]:
    """Extract (etch_time_offset, spc_status) pairs from history records."""
    pairs = []
    for rec in history:
        params = rec.get("parameters") or {}
        offset = params.get("etch_time_offset") or rec.get("etch_time_offset")
        status = rec.get("spc_status") or "UNKNOWN"
        if offset is not None:
            pairs.append((float(offset), status))
    return pairs


def _audit(pairs: list[tuple[float, str]]) -> bool:
    """
    Simulate APC_Model_Audit skill logic.

    Returns True if oscillation divergence is detected.

    Algorithm
    ---------
    Scan a sliding window of CONSECUTIVE_OOC_MIN records. If any window
    contains only OOC events AND the offset variance within that window
    exceeds OSCILLATION_THRESHOLD, flag it.
    """
    n = len(pairs)
    if n < CONSECUTIVE_OOC_MIN:
        print(f"[Agent] 資料量不足（{n} 筆 < {CONSECUTIVE_OOC_MIN}），無法進行震盪分析")
        return False

    print(f"{'Index':>6}  {'Offset':>12}  {'SPC Status':>12}")
    print("─" * 36)
    for i, (offset, status) in enumerate(pairs):
        flag = " ◀ OOC" if status == "OOC" else ""
        print(f"{i:>6}  {offset:>+12.4f}  {status:>12}{flag}")
    print()

    triggered = False
    for i in range(n - CONSECUTIVE_OOC_MIN + 1):
        window      = pairs[i : i + CONSECUTIVE_OOC_MIN]
        statuses    = [s for _, s in window]
        offsets     = [o for o, _ in window]
        all_ooc     = all(s == "OOC" for s in statuses)
        offset_var  = variance(offsets) if len(offsets) > 1 else 0.0

        if all_ooc and offset_var > OSCILLATION_THRESHOLD:
            print(f"[Agent] ⚠  窗口 [{i}:{i+CONSECUTIVE_OOC_MIN}] 觸發條件:")
            print(f"         連續 OOC 次數 = {CONSECUTIVE_OOC_MIN}")
            print(f"         offset 變異數  = {offset_var:.4f} > 閾值 {OSCILLATION_THRESHOLD}")
            triggered = True
            break

    return triggered


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="APC_Model_Audit skill verifier")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"OntologySimulator base URL (default: {DEFAULT_HOST})")
    parser.add_argument("--apc",  default=APC_ID,
                        help=f"APC object ID to audit (default: {APC_ID})")
    parser.add_argument("--mock", action="store_true",
                        help="Use embedded mock data instead of calling the API")
    args = parser.parse_args()

    print("=" * 60)
    print("  AIOps Skill: APC_Model_Audit — Sprint v2.3a Verifier")
    print(f"  Target  : {args.apc}")
    print(f"  Mode    : {'MOCK' if args.mock else 'LIVE  → ' + args.host}")
    print(f"  Time    : {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print()

    # ── Step 1: Fetch data ─────────────────────────────────────────────────
    if args.mock:
        print(f"[Agent] 使用內嵌 Mock 資料 ({len(_MOCK_HISTORY)} 筆)\n")
        history = _MOCK_HISTORY
    else:
        history = _fetch_history(args.host, args.apc)

    # ── Step 2: Extract (offset, spc_status) pairs ────────────────────────
    pairs = _extract_pairs(history)
    if not pairs:
        print("[Agent] 無法從回傳資料中找到 etch_time_offset 欄位。")
        print("       → 請確認 APC Snapshot parameters 已包含 etch_time_offset 鍵。")
        sys.exit(2)

    print(f"[Agent] 已提取 {len(pairs)} 筆 (etch_time_offset, spc_status) 配對\n")

    # ── Step 3: Run oscillation audit ─────────────────────────────────────
    print("[Agent] 執行震盪發散分析...")
    print()
    oscillating = _audit(pairs)

    # ── Step 4: Agent Decision ─────────────────────────────────────────────
    print()
    if oscillating:
        # This exact line is required by the spec (master_prod_spec_v2.3.md)
        print("[Agent 決策] 警告：APC-0042 模型發生震盪發散，建議立即停止補償。")
        print()
        print("  建議行動：")
        print("    1. 立即 Freeze APC-0042 補償輸出")
        print("    2. 通知 APC 工程師檢視 R2R 模型收斂條件")
        print("    3. 手動設定 Bias=0 並監控後續 3 批次 SPC 結果")
        sys.exit(1)   # non-zero: signals operator/CI that action is needed
    else:
        print("[Agent 決策] APC-0042 模型運作正常，未偵測到震盪發散。")
        print()
        ooc_count = sum(1 for _, s in pairs if s == "OOC")
        ooc_rate  = ooc_count / len(pairs) * 100
        print(f"  統計摘要：共 {len(pairs)} 筆，OOC 率 = {ooc_rate:.1f}%")
        sys.exit(0)


if __name__ == "__main__":
    main()
