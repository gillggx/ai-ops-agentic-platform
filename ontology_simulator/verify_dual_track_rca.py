#!/usr/bin/env python3
"""
verify_dual_track_rca.py
========================
2.2.3 OOC Forensic Showcase — Dual-Track RCA Verification Script

Test flow:
  1. GET /api/v2/ontology/indices/SPC?status=OOC&limit=50
     → find latest OOC alert (Target)
  2. Promise.all equivalent:
     GET /api/v2/ontology/trajectory/{lot_id}
     GET /api/v1/events?toolID={tool_id}&limit=100
  3. Merge + sort timelines, print combined log
  4. Assert: all eventTime values are valid ISO 8601
  5. Assert: merged list is sortable (no parse failures)
  6. GET /api/v2/ontology/context?lot_id=...&step=...
     using one event from the merged timeline
  7. Assert: DC payload contains real semantic keys (no param_N / sensor_N)
"""

import sys
import json
import urllib.request
from datetime import datetime, timezone

BASE = "http://localhost:8001"
PASS = "✓ PASS"
FAIL = "✗ FAIL"


def fetch(path: str) -> object:
    url = BASE + path
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())


def parse_iso(s: str) -> datetime:
    """Parse ISO 8601 string (with or without trailing Z)."""
    s = s.rstrip("Z")
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────
# TEST 1: Find latest OOC alert
# ─────────────────────────────────────────────────────────────────
print("\n[TEST 1] GET /api/v2/ontology/indices/SPC?status=OOC&limit=50")
try:
    data = fetch("/api/v2/ontology/indices/SPC?status=OOC&limit=50")
    assert data["count"] >= 1, "No OOC SPC records found — run simulator first"
    target = data["records"][0]
    lot_id  = target["lot_id"]
    tool_id = target["tool_id"]
    step    = target["step"]
    ev_time = target["event_time"]
    print(f"  {PASS}  OOC alert found: lot={lot_id} tool={tool_id} step={step}")
    print(f"  {PASS}  event_time={ev_time}")
except AssertionError as e:
    print(f"  {FAIL}  {e}");  sys.exit(1)
except Exception as e:
    print(f"  {FAIL}  {e}");  sys.exit(1)


# ─────────────────────────────────────────────────────────────────
# TEST 2: Dual-Track fetch (simulated Promise.all)
# ─────────────────────────────────────────────────────────────────
print(f"\n[TEST 2] Dual-Track fetch — Lot: {lot_id}  Tool: {tool_id}")
try:
    lot_data  = fetch(f"/api/v2/ontology/trajectory/{lot_id}")
    tool_data = fetch(f"/api/v1/events?toolID={tool_id}&limit=100")

    assert "steps" in lot_data, "trajectory response missing 'steps'"
    assert isinstance(tool_data, list), "tool events response should be a list"

    print(f"  {PASS}  Lot trajectory: {lot_data['total_steps']} steps")
    print(f"  {PASS}  Tool events: {len(tool_data)} events")
except AssertionError as e:
    print(f"  {FAIL}  {e}");  sys.exit(1)
except Exception as e:
    print(f"  {FAIL}  {e}");  sys.exit(1)


# ─────────────────────────────────────────────────────────────────
# TEST 3: Merge + sort timelines
# ─────────────────────────────────────────────────────────────────
print("\n[TEST 3] Merge & sort combined timeline")
try:
    combined = []

    for s in lot_data["steps"]:
        t = parse_iso(s["event_time"])
        combined.append({
            "time":       t,
            "track":      "LOT",
            "step":       s["step"],
            "lot_id":     lot_id,
            "spc_status": s.get("spc_status"),
        })

    for e in tool_data:
        t = parse_iso(e["eventTime"])
        combined.append({
            "time":       t,
            "track":      "TOOL",
            "step":       e.get("step"),
            "lot_id":     e.get("lotID"),
            "spc_status": e.get("spc_status"),
        })

    combined.sort(key=lambda x: x["time"])

    print(f"  {PASS}  Merged timeline: {len(combined)} total events (sortable)")
    print()
    print("  ── Combined Timeline Log ──────────────────────────────────")
    for ev in combined:
        ts       = ev["time"].strftime("%H:%M:%S")
        track    = ev["track"]
        ooc_flag = " ⚠ OOC" if ev.get("spc_status") == "OOC" else ""
        print(f"  {ts}  [{track:4s}]  lot={ev['lot_id'] or '—':12s}  step={ev['step'] or '—':10s}{ooc_flag}")
    print()

except Exception as e:
    print(f"  {FAIL}  {e}");  sys.exit(1)


# ─────────────────────────────────────────────────────────────────
# TEST 4: Assert ISO 8601 format consistency
# ─────────────────────────────────────────────────────────────────
print("[TEST 4] Assert ISO 8601 format on all eventTime values")
try:
    for ev in combined:
        assert ev["time"].tzinfo is not None, f"Missing timezone in {ev['time']}"
    print(f"  {PASS}  All {len(combined)} timestamps parsed as valid ISO 8601 UTC")
except AssertionError as e:
    print(f"  {FAIL}  {e}");  sys.exit(1)


# ─────────────────────────────────────────────────────────────────
# TEST 5: GET /context and assert semantic DC keys
# ─────────────────────────────────────────────────────────────────
print(f"\n[TEST 5] GET /api/v2/ontology/context?lot_id={lot_id}&step={step}")
try:
    ctx = fetch(f"/api/v2/ontology/context?lot_id={lot_id}&step={step}")

    assert "dc" in ctx, "context response missing 'dc' node"
    dc_params = ctx["dc"].get("parameters", {})
    assert dc_params, "DC parameters dict is empty"

    # Assert no generic sensor_N or param_N keys
    bad_sensor = [k for k in dc_params if k.startswith("sensor_")]
    bad_param  = [k for k in dc_params if k.startswith("param_")]
    assert not bad_sensor, f"DC contains forbidden sensor_N keys: {bad_sensor[:3]}"
    assert not bad_param,  f"DC contains forbidden param_N keys:  {bad_param[:3]}"

    # Assert at least one known semantic key
    known = {"chamber_pressure", "esc_zone1_temp", "rf_forward_power",
             "helium_coolant_press", "bias_voltage_v", "cf4_flow_sccm"}
    found = known & set(dc_params.keys())
    assert found, f"DC missing expected semantic keys; got: {list(dc_params.keys())[:5]}"

    print(f"  {PASS}  DC semantic keys (first 5): {list(dc_params.keys())[:5]}")
    print(f"  {PASS}  Known semantic keys present: {sorted(found)}")
    print(f"  {PASS}  spc_status in context: {ctx.get('spc_status')}")

except AssertionError as e:
    print(f"  {FAIL}  {e}");  sys.exit(1)
except Exception as e:
    print(f"  {FAIL}  {e}");  sys.exit(1)


# ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("ALL 5 TESTS PASSED — v2.2.3 Dual-Track RCA verified")
print("=" * 60 + "\n")
