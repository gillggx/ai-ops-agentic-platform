"""SLASH-17 regression driver — run all 17 production slash commands through the
v30 builder e2e and capture per-command result. Runs ON EC2 (single session).

Captures: done.status, build_finalized.ok, node count, terminal block_id(s),
missing_output_reason (C2). Watches for regressions from C2/Fix1/Fix2.
"""
import json, os, sys, time
import requests

SIDECAR = os.environ.get("SIDECAR_BASE", "http://localhost:8050")
SVC = os.environ["SVC_TOKEN"]
HDR = {"X-Service-Token": SVC, "Content-Type": "application/json",
       "Accept": "text/event-stream"}
if os.environ.get("SLASH_FLAGS"):
    HDR["X-Feature-Flags"] = os.environ["SLASH_FLAGS"]
    print(f"[META] X-Feature-Flags: {os.environ["SLASH_FLAGS"]}", flush=True)

CMDS = [
    ("spc-trend", "幫我看 EQP-01 STEP_001 最近 100 筆 xbar 趨勢"),
    ("spc-ooc", "過去 24 小時哪些機台 SPC OOC 最多？列前 5 名"),
    ("spc-cpk", "比較 EQP-01 STEP_001 過去 7 天的 R、Cpk、Cpk_std 趨勢"),
    ("spc-multi-tool", "比較 EQP-01,EQP-02,EQP-03,EQP-04,EQP-05 在 STEP_001 的 xbar 趨勢，畫成一張彩色 line chart（color=toolID）"),
    ("spc-drift", "過去 7 天 EQP-01 STEP_001 的 spc_xbar_chart_value：(1) block_ewma_cusum (mode='cusum', k=0.5, h=4) 偵測 < 1σ 小幅 drift；(2) block_box_plot 比較各 lot 之間的分佈差異；(3) block_probability_plot 檢定是否符合常態（給 Cpk 計算打底）"),
    ("spc-xbar-r-pair", "EQP-01 STEP_001 最近 7 天的 X-bar 管制圖（含 WECO highlight）"),
    ("spc-multi-step", "EQP-01 過去 7 天三站 xbar 趨勢（用 1 個 block_spc_panel + step=['STEP_001','STEP_002','STEP_003'] + chart_name='xbar_chart' + event_filter='all'）"),
    ("spc-tool-box", "EQP-01 STEP_001 過去 7 天各 lot 的 xbar 分佈（用 block_box_plot，x=lotID, y=xbar value）"),
    ("spc-normality", "EQP-01 STEP_001 過去 7 天 xbar 常態性檢定 Q-Q plot"),
    ("spc-cusum", "EQP-01 STEP_001 過去 14 天 EWMA-CUSUM 漂移偵測（k=0.5, h=4）"),
    ("apc-drift", "EQP-01 APC etch_time_offset 最近 24 小時 趨勢 line chart + drift 判定（用 block_weco_rules）"),
    ("apc-trend", "EQP-01 過去 24 小時 APC etch_time_offset 趨勢 line chart"),
    ("apc-recipe-compare", "EQP-01 過去 14 天每個 recipe 的 APC etch_time_offset 分佈 box plot 對比"),
    ("patrol-status", "現在所有機台的狀態快照，標示異常的機台"),
    ("ooc-ranking", "EQP-01 EQP-02 EQP-03 過去 7 天 SPC 事件，用 block_groupby_agg 依 toolID 分組計數 OOC 事件，畫 bar chart 由多到少"),
    ("ooc-pareto", "EQP-01 過去 7 天 SPC OOC 事件，用 block_groupby_agg 依 chart_name 分組計數，畫 bar chart 由多到少"),
    ("step-yield", "EQP-01 過去 7 天各 STEP 的 OOC 事件數，依 step 分組計數，畫 bar chart"),
]


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
    """Drain one SSE stream into acc; return session_id if confirm gate fired."""
    sid = None
    r = requests.post(url, json=body, headers=HDR, stream=True, timeout=900)
    if r.status_code != 200:
        acc["http_error"] = f"{r.status_code}: {r.text[:200]}"
        return None
    for ev, d in sse(r):
        if ev == "goal_plan_confirm_required":
            sid = d.get("session_id")
        elif ev == "build_finalized":
            acc["ok"] = d.get("ok")
            acc["missing_output_reason"] = d.get("missing_output_reason")
        elif ev == "done":
            acc["status"] = d.get("status")
            pj = d.get("pipeline_json") or {}
            nodes = pj.get("nodes") or []
            acc["n_nodes"] = len(nodes)
            edges = pj.get("edges") or []
            # terminal = nodes with no outgoing edge
            outs = {(e.get("from") or {}).get("node") for e in edges}
            acc["terminals"] = [n.get("block_id") for n in nodes if n.get("id") not in outs]
            acc["blocks"] = [n.get("block_id") for n in nodes]
    return sid


def run_one(key, tpl):
    acc = {"key": key, "status": None, "ok": None, "n_nodes": 0,
           "terminals": [], "blocks": [], "missing_output_reason": None}
    body = {"instruction": tpl, "skill_step_mode": False, "v30_mode": True}
    t0 = time.time()
    try:
        sid = drain(f"{SIDECAR}/internal/agent/build", body, acc)
        if sid and acc.get("status") is None:
            drain(f"{SIDECAR}/internal/agent/build/plan-confirm",
                  {"sessionId": sid, "confirmed": True}, acc)
    except Exception as e:
        acc["exc"] = f"{type(e).__name__}: {str(e)[:160]}"
    acc["sec"] = round(time.time() - t0, 1)
    return acc


def main():
    results = []
    for i, (key, tpl) in enumerate(CMDS, 1):
        r = run_one(key, tpl)
        results.append(r)
        ok = r.get("ok")
        st = r.get("status")
        term = ",".join(r.get("terminals") or []) or "-"
        mor = r.get("missing_output_reason")
        flag = "OK " if (st == "finished" and ok is not False) else "FAIL"
        line = (f"[{i:2d}/17] {flag} {key:20s} status={st} ok={ok} "
                f"nodes={r.get('n_nodes')} term={term} {r.get('sec')}s")
        if mor:
            line += f"  MISSING_OUTPUT={mor[:80]}"
        if r.get("exc"):
            line += f"  EXC={r['exc']}"
        if r.get("http_error"):
            line += f"  HTTP={r['http_error']}"
        print(line, flush=True)
    # summary
    npass = sum(1 for r in results if r.get("status") == "finished" and r.get("ok") is not False)
    print(f"\n==== SLASH-17 summary: {npass}/17 finished+ok ====", flush=True)
    miss = [r["key"] for r in results if r.get("status") == "failed_missing_output"]
    if miss:
        print(f"  failed_missing_output (C2 fired): {miss}", flush=True)
    notok = [r["key"] for r in results if not (r.get("status") == "finished" and r.get("ok") is not False)]
    if notok:
        print(f"  NOT ok: {notok}", flush=True)
    out_file = os.environ.get("OUT_FILE", "/tmp/slash17_results_execON.json")
    json.dump(results, open(out_file, "w"), ensure_ascii=False, indent=2)
    print(f"  results -> {out_file}", flush=True)


if __name__ == "__main__":
    main()
