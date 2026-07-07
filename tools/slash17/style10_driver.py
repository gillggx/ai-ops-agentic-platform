"""STYLE-10 driver — does the agent translate natural-language STYLE asks into
the chart-style params (chart-style wave 1)?

Data side is deliberately trivial (EQP-01 STEP_001, 3-4 nodes); the only
variable is the style instruction. Grading is mechanical: assert the built
pipeline's chart-node params contain the expected keys — this tests whether
the agent READ the block docs, not whether the chart is pretty.

Run (on EC2):  SVC_TOKEN=... python3 tools/slash17/style10_driver.py
Subset:        STYLE_CASES=S1,S5 ... (comma keys)
"""
import json, os, sys, time
import requests

SIDECAR = os.environ.get("SIDECAR_BASE", "http://localhost:8050")
SVC = os.environ["SVC_TOKEN"]
HDR = {"X-Service-Token": SVC, "Content-Type": "application/json",
       "Accept": "text/event-stream"}

CHART_BLOCKS = {"block_line_chart", "block_xbar_r", "block_imr", "block_spc_panel"}


def _chart_nodes(pj):
    return [n for n in (pj.get("nodes") or [])
            if n.get("block_id") in CHART_BLOCKS]


def _first_chart_params(pj):
    ns = _chart_nodes(pj)
    return (ns[0].get("params") or {}) if ns else {}


def a_s1(pj):
    p = _first_chart_params(pj)
    zones = (p.get("style") or {}).get("spc_zones")
    has_limits = (p.get("ucl_column") and p.get("lcl_column")) \
        or any(n.get("block_id") in ("block_xbar_r", "block_spc_panel", "block_imr")
               for n in _chart_nodes(pj))
    # 管制圖 block (xbar_r/panel) 後端預設 zones on — agent 不設也算對；
    # line_chart 需 agent 給 limits（zones 隨之預設 on）或顯式開
    return bool(has_limits) and zones is not False, \
        f"limits={bool(has_limits)} zones={zones}"


def a_s2(pj):
    p = _first_chart_params(pj)
    tf = p.get("tooltip_fields") or []
    ok = "lotID" in tf and "recipe" in tf
    return ok, f"tooltip_fields={tf}"


def a_s3(pj):
    ns = [n for n in _chart_nodes(pj) if n.get("block_id") in ("block_xbar_r", "block_imr")]
    if not ns:
        return False, "no xbar_r/imr node"
    p = ns[0].get("params") or {}
    return p.get("weco_annotate") is True, f"weco_annotate={p.get('weco_annotate')}"


def a_s4(pj):
    p = _first_chart_params(pj)
    yl = (p.get("style") or {}).get("y_label") or ""
    return "xbar" in yl and "nm" in yl, f"y_label={yl!r}"


def a_s5(pj):
    p = _first_chart_params(pj)
    zones = (p.get("style") or {}).get("spc_zones")
    return zones is False, f"spc_zones={zones}"


def a_s9(pj):
    ns = [n for n in _chart_nodes(pj) if n.get("block_id") == "block_spc_panel"]
    if not ns:
        return False, "no spc_panel node"
    p = ns[0].get("params") or {}
    tf = p.get("tooltip_fields") or []
    zones = (p.get("style") or {}).get("spc_zones")
    return ("lotID" in tf) and zones is not False, f"tooltip={tf} zones={zones}"


def a_s10(pj):
    ok1, d1 = a_s1(pj)
    ok2, d2 = a_s2_lot_only(pj)
    ok3, d3 = a_s4(pj)
    return ok1 and ok2 and ok3, f"{d1} | {d2} | {d3}"


def a_s2_lot_only(pj):
    p = _first_chart_params(pj)
    tf = p.get("tooltip_fields") or []
    return "lotID" in tf, f"tooltip_fields={tf}"


CASES = [
    ("S1", "畫 EQP-01 STEP_001 最近 7 天的標準 SPC 管制圖", a_s1),
    ("S2", "畫 EQP-01 STEP_001 最近 7 天 xbar 趨勢圖，滑鼠提示要顯示 lotID 和 recipe", a_s2),
    ("S3", "EQP-01 STEP_001 最近 7 天的 X̄-R 管制圖，違規點要能看出違反哪條規則", a_s3),
    ("S4", "畫 EQP-01 STEP_001 最近 7 天 xbar 趨勢圖，y 軸標「xbar (nm)」", a_s4),
    ("S5", "畫 EQP-01 STEP_001 最近 7 天簡潔版 SPC 管制圖，不要畫 sigma 區帶", a_s5),
    ("S9", "EQP-01 三站 STEP_001 STEP_002 STEP_003 的 xbar 面板，每格含 sigma 區帶，提示顯示 lotID", a_s9),
    ("S10", "畫 EQP-01 STEP_001 最近 7 天標準 SPC 管制圖，提示顯示 lotID，y 軸標「xbar (nm)」", a_s10),
]
# S6(histogram lsl/usl) S7(bar show_values) S8(scatter trend_line) 屬 Wave 2 — 尚未實作


def sse(resp):
    buf = []
    for raw in resp.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        if raw == "":
            if buf:
                ev = next((l[6:].strip() for l in buf if l.startswith("event:")), None)
                data = next((l[5:].strip() for l in buf if l.startswith("data:")), None)
                if ev:
                    try:
                        yield ev, (json.loads(data) if data else {})
                    except Exception:
                        yield ev, {}
                buf = []
        else:
            buf.append(raw)


def drain(url, body, acc):
    sid = None
    r = requests.post(url, json=body, headers=HDR, stream=True, timeout=900)
    if r.status_code != 200:
        acc["http_error"] = f"{r.status_code}: {r.text[:200]}"
        return None
    for ev, d in sse(r):
        if ev == "goal_plan_confirm_required":
            sid = d.get("session_id")
        elif ev == "done":
            acc["status"] = d.get("status")
            acc["pipeline_json"] = d.get("pipeline_json") or {}
    return sid


def run_case(key, instruction, assert_fn):
    acc = {"key": key, "status": None, "pipeline_json": {}}
    body = {"instruction": instruction, "skill_step_mode": False, "v30_mode": True}
    t0 = time.time()
    try:
        sid = drain(f"{SIDECAR}/internal/agent/build", body, acc)
        if sid and acc.get("status") is None:
            drain(f"{SIDECAR}/internal/agent/build/plan-confirm",
                  {"sessionId": sid, "confirmed": True}, acc)
    except Exception as e:
        acc["exc"] = f"{type(e).__name__}: {str(e)[:150]}"
    acc["sec"] = round(time.time() - t0, 1)
    if acc.get("status") == "finished":
        ok, detail = assert_fn(acc["pipeline_json"])
        acc["ok"], acc["detail"] = ok, detail
    else:
        acc["ok"], acc["detail"] = False, f"build status={acc.get('status')} {acc.get('exc','')}{acc.get('http_error','')}"
    return acc


def main():
    want = {k.strip() for k in os.environ.get("STYLE_CASES", "").split(",") if k.strip()}
    cases = [(k, i, f) for (k, i, f) in CASES if not want or k in want]
    results = []
    for idx, (key, instruction, fn) in enumerate(cases, 1):
        r = run_case(key, instruction, fn)
        results.append(r)
        flag = "OK " if r["ok"] else "FAIL"
        print(f"[{idx}/{len(cases)}] {flag} {key:4s} {r['sec']:>6.1f}s  {r['detail']}", flush=True)
    npass = sum(1 for r in results if r["ok"])
    print(f"\n==== STYLE suite: {npass}/{len(cases)} ====", flush=True)
    out = os.environ.get("OUT_FILE", "/tmp/style10_results.json")
    for r in results:
        r.pop("pipeline_json", None)
    json.dump(results, open(out, "w"), ensure_ascii=False, indent=2)
    print(f"results -> {out}", flush=True)


if __name__ == "__main__":
    main()
