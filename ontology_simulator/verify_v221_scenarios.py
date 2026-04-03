#!/usr/bin/env python3
"""
verify_v221_scenarios.py — v2.2.1 Backend API Verification Script

依序執行三項驗證：
  1. Lot-Centric Trace        → GET /api/v2/ontology/trajectory/{lot_id}
  2. Object-Centric Explorer  → GET /api/v2/ontology/indices/APC?limit=3
                                + 取回其中一筆 JSON 實體（payload inline）
  3. Scenario Browser 組裝    → Scenario 1 (SPC OOC) 預計打出的 URL，試打確認 HTTP 200

使用方式：
  python verify_v221_scenarios.py [--base-url http://127.0.0.1:8001]
"""
import argparse
import json
import sys
import urllib.request
import urllib.parse
import urllib.error

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_BASE = "http://127.0.0.1:8001"

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_json(url: str) -> tuple[int, dict | list | None]:
    """Return (status_code, parsed_body).  Body is None on parse error."""
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            body = json.loads(raw)
        except Exception:
            body = {"raw": raw}
        return e.code, body
    except Exception as exc:
        print(f"    [network error] {exc}")
        return 0, None


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def check(label: str, condition: bool, detail: str = "") -> bool:
    icon = PASS if condition else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  {icon}  {label}{suffix}")
    return condition


# ── Test 1: Lot-Centric Trace ─────────────────────────────────────────────────

def test_trajectory(base: str) -> bool:
    section("TEST 1 — Lot-Centric Trace  (trajectory/{lot_id})")
    lot_id = "LOT-0001"
    url = f"{base}/api/v2/ontology/trajectory/{lot_id}"
    print(f"  GET {url}")

    code, body = get_json(url)
    ok_status = check("HTTP 200", code == 200, f"got {code}")
    if not ok_status or body is None:
        return False

    ok_lot   = check("lot_id in response",   body.get("lot_id") == lot_id)
    ok_steps = check("steps is list",        isinstance(body.get("steps"), list))
    steps    = body.get("steps", [])
    ok_nonempty = check("steps not empty",   len(steps) > 0, f"got {len(steps)} steps")

    if steps:
        first = steps[0]
        ok_fields = check(
            "step record has required fields",
            all(k in first for k in ("step", "event_time", "tool_id")),
            str(list(first.keys())),
        )
        print(f"\n  📋 First 3 steps for {lot_id}:")
        for s in steps[:3]:
            print(f"     • {s['step']:12s}  tool={s['tool_id']}  "
                  f"spc={s.get('spc_status','—'):7s}  t={s['event_time'][:19]}")
        print(f"  … total {body['total_steps']} steps recorded")
    else:
        ok_fields = False

    return all([ok_status, ok_lot, ok_steps, ok_nonempty, ok_fields])


# ── Test 2: Object-Centric Explorer ──────────────────────────────────────────

def test_object_indices(base: str) -> bool:
    section("TEST 2 — Object-Centric Explorer  (indices/APC?limit=3)")
    url = f"{base}/api/v2/ontology/indices/APC?limit=3"
    print(f"  GET {url}")

    code, body = get_json(url)
    ok_status = check("HTTP 200", code == 200, f"got {code}")
    if not ok_status or body is None:
        return False

    records = body.get("records", [])
    ok_type    = check("object_type == APC",   body.get("object_type") == "APC")
    ok_records = check("records is list",      isinstance(records, list))
    ok_count   = check("got 3 records",        len(records) == 3, f"got {len(records)}")

    if not records:
        return False

    first = records[0]
    ok_index_id = check("index_id present",   bool(first.get("index_id")))
    ok_payload  = check("payload present",    isinstance(first.get("payload"), dict))
    ok_params   = check("payload has parameters",
                        "parameters" in first.get("payload", {}))

    print(f"\n  📋 Latest 3 APC index records:")
    for r in records:
        param_count = len(r.get("payload", {}).get("parameters", {}))
        print(f"     • {r.get('object_id','?'):10s}  lot={r.get('lot_id','?'):10s}  "
              f"step={r.get('step','?'):10s}  params={param_count}")

    # Spot-check: inline payload is the real JSON entity
    if first.get("payload", {}).get("parameters"):
        p = first["payload"]["parameters"]
        sample = list(p.items())[:2]
        print(f"\n  🔬 Inline payload spot-check (first record, first 2 params):")
        for k, v in sample:
            print(f"     {k}: {v}")

    return all([ok_status, ok_type, ok_records, ok_count,
                ok_index_id, ok_payload, ok_params])


# ── Test 3: Scenario Browser URL Assembly ─────────────────────────────────────

def test_scenario_browser(base: str, trajectory_body: dict | None = None) -> bool:
    section("TEST 3 — Scenario Browser  (Scenario 1: SPC OOC 根因分析)")

    # Pick an OOC event if we can (use lot_id=LOT-0001 as default probe)
    lot_id = "LOT-0001"
    step   = None

    # Try to find an OOC step from trajectory data
    if trajectory_body:
        for s in trajectory_body.get("steps", []):
            if s.get("spc_status") == "OOC":
                step = s["step"]
                break

    # Fallback: ask the /context endpoint to find any OOC event
    if not step:
        probe_url = f"{base}/api/v2/ontology/context?lot_id={lot_id}&step=STEP_001&ooc_only=false"
        _, probe = get_json(probe_url)
        if probe and probe.get("root"):
            step = probe["root"].get("step", "STEP_001")
        else:
            step = "STEP_001"

    # Build the Scenario 1 URL
    params = urllib.parse.urlencode({"lot_id": lot_id, "step": step, "ooc_only": "false"})
    scenario_url = f"{base}/api/v2/ontology/context?{params}"

    print(f"  Scenario 1 URL:\n  {scenario_url}\n")
    check("URL contains lot_id",  f"lot_id={lot_id}" in scenario_url)
    check("URL contains step",    f"step={step}"     in scenario_url)

    print(f"  Firing request…")
    code, body = get_json(scenario_url)
    ok_200  = check("HTTP 200",            code == 200, f"got {code}")
    ok_root = check("root node present",   bool(body and body.get("root")))
    ok_tool = check("tool node present",   bool(body and body.get("tool")))

    if body and body.get("root"):
        root = body["root"]
        nodes_present = sum(1 for k in ("tool", "recipe", "apc", "dc", "spc")
                           if body.get(k) and not body[k].get("orphan"))
        print(f"\n  🕸  Context graph for {lot_id} / {step}:")
        print(f"     spc_status : {root.get('spc_status','—')}")
        print(f"     tool_id    : {root.get('tool_id','—')}")
        print(f"     recipe_id  : {root.get('recipe_id','—')}")
        print(f"     apc_id     : {root.get('apc_id','—')}")
        print(f"     nodes present (non-orphan): {nodes_present}/5")

    return all([ok_200, ok_root, ok_tool])


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="v2.2.1 API verification script")
    parser.add_argument("--base-url", default=DEFAULT_BASE,
                        help=f"OntologySimulator base URL (default: {DEFAULT_BASE})")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"\n{'═' * 60}")
    print(f"  verify_v221_scenarios.py")
    print(f"  Target: {base}")
    print(f"{'═' * 60}")

    # Quick connectivity check
    code, _ = get_json(f"{base}/api/v1/status")
    if code != 200:
        print(f"\n  ⚠️  Cannot reach {base}/api/v1/status (got {code}).")
        print("  Ensure OntologySimulator is running first.\n")
        sys.exit(1)

    results: list[bool] = []

    # Run Test 1 and capture body for Test 3
    r1 = test_trajectory(base)
    results.append(r1)

    # Fetch trajectory body again for Test 3 (lot OOC step discovery)
    _, traj_body = get_json(f"{base}/api/v2/ontology/trajectory/LOT-0001")

    results.append(test_object_indices(base))
    results.append(test_scenario_browser(base, traj_body))

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = sum(results)
    total  = len(results)
    print(f"\n{'═' * 60}")
    print(f"  RESULT: {passed}/{total} tests passed")
    if passed == total:
        print(f"  ✅  All v2.2.1 scenarios verified — ready for Next.js UI build")
    else:
        print(f"  ❌  Some tests failed — fix backend before building UI")
    print(f"{'═' * 60}\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
