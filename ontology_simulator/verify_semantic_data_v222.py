#!/usr/bin/env python3
"""
verify_semantic_data_v222.py
============================
Validates that v2.2.2 semantic data requirements are met.

Spec requirement:
  "Assert: 若發現任何 key 包含 param_ 字串，腳本必須拋出 AssertionError 測試失敗"

Tests:
  1. APC indices — zero param_N keys, must include spec-required names
  2. DC indices  — zero sensor_N keys, must include spec-required names
  3. RECIPE indices — zero param_N keys, must include spec-required names
"""

import sys
import urllib.request
import json

BASE = "http://localhost:8001"

PASS = "✓ PASS"
FAIL = "✗ FAIL"


def fetch(path: str) -> dict:
    url = BASE + path
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())


def check_no_generic_keys(params: dict, prefix: str, label: str) -> None:
    bad = [k for k in params if k.startswith(prefix)]
    assert not bad, (
        f"{label}: forbidden generic key(s) found — {bad[:5]}. "
        f"All parameter keys must use real semiconductor domain names."
    )


# ─────────────────────────────────────────────────────────────────
# Test 1: APC — no param_N, must contain spec-required names
# ─────────────────────────────────────────────────────────────────
print("\n[TEST 1] APC indices — semantic parameter names")
try:
    data = fetch("/api/v2/ontology/indices/APC?limit=1")
    assert data["count"] >= 1, "No APC records returned"
    params = data["records"][0]["payload"]["parameters"]
    check_no_generic_keys(params, "param_", "APC")

    required_apc = {"etch_time_offset", "rf_power_bias", "gas_flow_comp", "model_r2_score"}
    missing = required_apc - set(params.keys())
    assert not missing, f"APC missing required spec keys: {missing}"

    print(f"  {PASS}  keys (first 5): {list(params.keys())[:5]}")
    print(f"  {PASS}  required keys present: {sorted(required_apc)}")
except AssertionError as e:
    print(f"  {FAIL}  {e}")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────
# Test 2: DC — no sensor_N, must contain spec-required names
# ─────────────────────────────────────────────────────────────────
print("\n[TEST 2] DC indices — semantic sensor names")
try:
    data = fetch("/api/v2/ontology/indices/DC?limit=1")
    assert data["count"] >= 1, "No DC records returned"
    params = data["records"][0]["payload"]["parameters"]
    check_no_generic_keys(params, "sensor_", "DC")

    required_dc = {"chamber_pressure", "helium_coolant_press", "esc_zone1_temp",
                   "rf_forward_power", "reflected_power"}
    missing = required_dc - set(params.keys())
    assert not missing, f"DC missing required spec keys: {missing}"

    print(f"  {PASS}  keys (first 5): {list(params.keys())[:5]}")
    print(f"  {PASS}  required keys present: {sorted(required_dc)}")
except AssertionError as e:
    print(f"  {FAIL}  {e}")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────
# Test 3: RECIPE — no param_N, must contain spec-required names
# ─────────────────────────────────────────────────────────────────
print("\n[TEST 3] RECIPE indices — semantic parameter names")
try:
    data = fetch("/api/v2/ontology/indices/RECIPE?limit=1")
    assert data["count"] >= 1, "No RECIPE records returned"
    params = data["records"][0]["payload"]["parameters"]
    check_no_generic_keys(params, "param_", "RECIPE")

    required_recipe = {"target_thickness_nm", "etch_rate_nm_per_s", "etch_time_s",
                       "cf4_setpoint_sccm"}
    missing = required_recipe - set(params.keys())
    assert not missing, f"RECIPE missing required spec keys: {missing}"

    print(f"  {PASS}  keys (first 5): {list(params.keys())[:5]}")
    print(f"  {PASS}  required keys present: {sorted(required_recipe)}")
except AssertionError as e:
    print(f"  {FAIL}  {e}")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────
print("\n" + "="*50)
print("ALL 3 TESTS PASSED — v2.2.2 semantic data verified")
print("="*50 + "\n")
