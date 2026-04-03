#!/usr/bin/env python3
"""
verify_data_services.py — v2.2 Data Services Verification Script

Usage:
    python verify_data_services.py [--base-url http://localhost:8001]

Tests:
    1. GET /api/v2/ontology/context  — Graph Context Service (Use Case 1)
       Finds the most recent OOC event (or any event if none OOC), then expands
       all related entities: Tool, Recipe, APC, DC, SPC into a nested JSON.

    2. GET /api/v2/ontology/fanout/{event_id}
       Given the event_id from step 1, traces all subsystem registrations
       and reports any orphan (broken-link) entries.

    3. GET /api/v2/ontology/orphans
       Scans recent events for broken snapshot references.

    4. GET /api/v1/audit  (sanity check — existing endpoint)
       Verifies Object-Index Ratio is healthy.
"""
import argparse
import json
import sys
import urllib.request
import urllib.error
from typing import Any

BASE_URL = "http://localhost:8001"

# ── ANSI colours ──────────────────────────────────────────────────────────────
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg: str)   -> None: print(f"  {GREEN}✅  {msg}{RESET}")
def fail(msg: str) -> None: print(f"  {RED}❌  {msg}{RESET}")
def warn(msg: str) -> None: print(f"  {YELLOW}⚠️   {msg}{RESET}")
def info(msg: str) -> None: print(f"  {CYAN}ℹ️   {msg}{RESET}")
def hdr(msg: str)  -> None: print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}\n{BOLD}  {msg}{RESET}\n{'─'*60}")


def get(path: str) -> Any:
    url = BASE_URL + path
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code} from {path}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach {url}: {e.reason}") from e


def pp(obj: Any, max_keys: int = 6) -> None:
    """Pretty-print a dict, truncating large parameter blocks."""
    if isinstance(obj, dict):
        trimmed = {}
        for k, v in list(obj.items())[:max_keys]:
            if isinstance(v, dict) and len(v) > 5:
                trimmed[k] = {kk: vv for kk, vv in list(v.items())[:5]}
                trimmed[k]["..."] = f"({len(v)} total keys)"
            else:
                trimmed[k] = v
        if len(obj) > max_keys:
            trimmed["..."] = f"({len(obj)} total keys)"
        print(json.dumps(trimmed, indent=4, default=str))
    else:
        print(json.dumps(obj, indent=4, default=str))


# ── Test 1: Graph Context Service (Use Case 1) ────────────────────────────────

def test_graph_context() -> dict:
    hdr("TEST 1 — Graph Context Service (Use Case 1: SPC OOC Context Expansion)")

    # Try OOC first; fall back to any event
    events = get("/api/v1/events?limit=200")
    ooc_event = next((e for e in events if e.get("spc_status") == "OOC"), None)
    any_event = events[0] if events else None

    target = ooc_event or any_event
    if not target:
        fail("No events found — is the simulator running?")
        sys.exit(1)

    lot_id = target["lotID"]
    step   = target["step"]
    tag    = "OOC" if ooc_event else "any (no OOC found yet)"
    info(f"Using event: lot_id={lot_id}  step={step}  [{tag}]")

    ctx = get(f"/api/v2/ontology/context?lot_id={lot_id}&step={step}")

    root = ctx.get("root", {})
    ok(f"Root node — lot={root.get('lot_id')}  step={root.get('step')}  "
       f"spc_status={root.get('spc_status')}  event_id={root.get('event_id')}")

    for node_name in ("tool", "recipe", "apc", "dc", "spc"):
        node = ctx.get(node_name)
        if node is None:
            warn(f"{node_name.upper()} node is None")
        elif node.get("orphan"):
            fail(f"{node_name.upper()} node is an ORPHAN — snapshot missing!")
        else:
            ok(f"{node_name.upper()} node present")

    print()
    print("  Full nested context JSON (trimmed):")
    pp(ctx)

    return root   # return root so subsequent tests can use event_id


# ── Test 2: Fanout Trace ──────────────────────────────────────────────────────

def test_fanout(event_id: str) -> None:
    hdr(f"TEST 2 — Fanout Trace  (event_id={event_id})")

    fanout = get(f"/api/v2/ontology/fanout/{event_id}")

    info(f"Event: lot={fanout.get('lotID')}  tool={fanout.get('toolID')}  "
         f"step={fanout.get('step')}  type={fanout.get('eventType')}")

    subsystems = fanout.get("subsystems", {})
    if not subsystems:
        fail("No subsystems returned — check event schema")
        return

    all_healthy = True
    for name, data in subsystems.items():
        snap_ok   = data.get("snapshot_exists", False)
        master_ok = data.get("master_exists")   # None = N/A (DC/SPC)
        orphan    = data.get("orphan", False)

        master_str = ""
        if master_ok is not None:
            master_str = f"  master={'✓' if master_ok else '✗'}"

        if orphan:
            fail(f"{name:8s} — ORPHAN (snapshot missing){master_str}")
            all_healthy = False
        else:
            ok(f"{name:8s} — snapshot={'✓' if snap_ok else '?'}{master_str}  "
               f"id={data.get('snapshot_id', 'N/A')[:16]}...")

    if all_healthy:
        ok("All 4 subsystems have intact snapshot links — no orphans detected")

    print()
    print("  Full fanout JSON (trimmed):")
    pp(fanout)


# ── Test 3: Orphan Scanner ────────────────────────────────────────────────────

def test_orphans() -> None:
    hdr("TEST 3 — Orphan Scanner (broken-link detection)")

    result = get("/api/v2/ontology/orphans?limit=20")
    total  = result.get("total_orphans", 0)
    orphans = result.get("orphans", [])

    if total == 0:
        ok("No orphans found — all snapshot links are intact ✨")
    else:
        warn(f"{total} orphan event(s) detected:")
        for o in orphans[:5]:
            broken = ", ".join(b["subsystem"] for b in o["broken_links"])
            print(f"    event={o['event_id'][:16]}...  lot={o['lotID']}  "
                  f"step={o['step']}  broken=[{broken}]")
        if total > 5:
            print(f"    ... and {total - 5} more")


# ── Test 4: Audit Sanity Check ────────────────────────────────────────────────

def test_audit() -> None:
    hdr("TEST 4 — Audit Sanity Check (Object-Index Ratio)")

    audit = get("/api/v1/audit")
    subs  = audit.get("subsystems", {})
    fanout = audit.get("event_fanout", {})
    master = audit.get("master_data", {})

    info(f"Events: TOOL={fanout.get('TOOL_EVENT', 0):,}  "
         f"LOT={fanout.get('LOT_EVENT', 0):,}")
    info(f"Master data: lots={master.get('lots', 0)}  tools={master.get('tools', 0)}  "
         f"recipes={master.get('recipe_versions', 0)}  apc_models={master.get('apc_models', 0)}")

    print()
    print(f"  {'Subsystem':<10} {'Indices':>10} {'Objects':>10} {'Ratio':>10}  Health")
    print(f"  {'─'*10} {'─'*10} {'─'*10} {'─'*10}  {'─'*10}")

    for name, data in subs.items():
        idx  = data.get("index_entries", 0)
        objs = data.get("distinct_objects", 0)
        ratio = data.get("compression_ratio")
        ratio_str = f"{ratio:.1f}:1" if ratio else "N/A"
        health = "✅  healthy" if objs > 0 else "⚠️   no data"
        print(f"  {name:<10} {idx:>10,} {objs:>10,} {ratio_str:>10}  {health}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    global BASE_URL
    parser = argparse.ArgumentParser(description="Verify v2.2 Data Services")
    parser.add_argument("--base-url", default=BASE_URL, help="Ontology Simulator base URL")
    args = parser.parse_args()
    BASE_URL = args.base_url.rstrip("/")

    print(f"\n{BOLD}{'='*60}")
    print(f"  Agentic OS v2.2 — Data Services Verification")
    print(f"  Target: {BASE_URL}")
    print(f"{'='*60}{RESET}")

    try:
        root = test_graph_context()
        test_fanout(root["event_id"])
        test_orphans()
        test_audit()
    except RuntimeError as e:
        print(f"\n{RED}{BOLD}FATAL: {e}{RESET}")
        sys.exit(1)

    print(f"\n{BOLD}{GREEN}{'='*60}")
    print("  Verification complete.")
    print(f"{'='*60}{RESET}\n")


if __name__ == "__main__":
    main()
