import json,glob,os,sys
# SLASH-17 grader. Compares a driver run's per-case blocks against hand-authored
# golden block-sets. Paths default to the EC2 /tmp convention but are env-tunable:
#   RESULTS_DIR (s17_<label>.json + .window)  TRACE_DIR (builder-traces)
# Goldens encode the corrected test cases (2026-06-22):
#   - spc-xbar-r-pair: "X-bar 管制圖" (NOT "X-bar/R 對偶" — the simulator's
#     pre-aggregated SPC data can't compute the R chart, so the dual ask was
#     unconstructible; see ALT/handoff). Golden = block_xbar_r.
#   - patrol-status: list_objects (fleet snapshot), not process_history.
#   - ooc-pareto: block_pareto OR sort+bar_chart (both correct) — see ALT.
RESULTS_DIR=os.environ.get("RESULTS_DIR","/tmp")
TRACE_DIR=os.environ.get("TRACE_DIR","/tmp/builder-traces")
# golden: key -> (instr_sig, required_blocks, ideal_nodes, allow_extra)
G=[
 ("spc-trend","最近 100 筆 xbar",{"process_history","unnest","filter","line_chart"},4,False),
 ("spc-ooc","哪些機台 SPC OOC",{"list_objects","mcp_foreach","unnest","filter","groupby_agg","sort","data_view"},7,False),
 ("spc-cpk","R、Cpk、Cpk_std",{"process_history","unnest","filter","line_chart"},4,False),
 ("spc-multi-tool","EQP-01,EQP-02,EQP-03",{"process_history","unnest","filter","line_chart"},4,False),
 ("spc-drift","block_ewma_cusum (mode",{"process_history","unnest","filter","ewma_cusum","box_plot","probability_plot"},6,False),
 ("spc-xbar-r-pair","X-bar 管制圖",{"process_history","unnest","filter","xbar_r"},4,True),
 ("spc-multi-step","三站 xbar",{"process_history","spc_panel"},2,False),
 ("spc-tool-box","各 lot 的 xbar 分佈",{"process_history","unnest","filter","box_plot"},4,False),
 ("spc-normality","常態性檢定 Q-Q",{"process_history","unnest","filter","probability_plot"},4,False),
 ("spc-cusum","EWMA-CUSUM 漂移偵測",{"process_history","unnest","filter","ewma_cusum"},4,False),
 ("apc-drift","etch_time_offset 最近 24 小時 趨勢 line chart + drift",{"process_history","line_chart","weco_rules"},4,True),
 ("apc-trend","過去 24 小時 APC etch_time_offset 趨勢 line chart",{"process_history","line_chart"},3,True),
 ("apc-recipe-compare","每個 recipe 的 APC",{"process_history","box_plot"},3,True),
 ("patrol-status","現在所有機台的狀態快照",{"list_objects","data_view"},3,True),
 ("ooc-ranking","依 toolID 分組計數",{"process_history","filter","groupby_agg","bar_chart"},4,True),
 ("ooc-pareto","依 chart_name 分組計數",{"process_history","unnest","filter","groupby_agg","pareto"},5,True),  # alt form in ALT[]
 ("step-yield","各 STEP 的 OOC 事件數，依 step",{"process_history","filter","groupby_agg","bar_chart"},5,False),
]
lbl=sys.argv[1] if len(sys.argv)>1 else "strict"
R={r["key"]:r for r in json.load(open("%s/s17_%s.json"%(RESULTS_DIR,lbl)))}
t0,t1=map(float,open("%s/s17_%s.window"%(RESULTS_DIR,lbl)).read().split())
def rounds(sig):
    best=0
    for f in glob.glob("%s/*.json"%TRACE_DIR):
        mt=os.path.getmtime(f)
        if mt<t0-2 or mt>t1+8: continue
        try: d=json.load(open(f))
        except: continue
        if sig not in json.dumps(d,ensure_ascii=False): continue
        cs=[]
        def w(o):
            if isinstance(o,dict):
                if "input_tokens" in o and "node" in o: cs.append(o)
                for v in o.values(): w(v)
            elif isinstance(o,list):
                for v in o: w(v)
        w(d); best=max(best,len(cs))
    return best
print("%-18s %-6s %-7s %-5s %-5s %s"%("case","grade","nodes","ideal","rnds","detail"))
print("-"*78)

# Alternative acceptable req-sets (a case can have >1 correct shape).
# 2026-06-25 (hardening #1): "由多到少" ranking is now in-block (bar_chart order=
# desc / pareto self-sorts), so a separate block_sort is no longer required.
ALT = {
 "ooc-pareto": [
  {"process_history","unnest","filter","groupby_agg","sort","bar_chart"},  # explicit sort + bar
  {"process_history","unnest","filter","groupby_agg","bar_chart"},          # bar(order=desc), no sort
 ],
}
from collections import Counter
gc=Counter()
for key,sig,req,ideal,allow in G:
    r=R.get(key,{})
    st=r.get("status")
    blocks=[b.replace("block_","") for b in (r.get("blocks") or [])]
    actual=set(blocks); n=len(blocks)
    if st!="finished": grade="FAIL"; detail=str(st)
    else:
        reqs=[req]+(ALT[key] if key in ALT else [])
        best=None
        for rq in reqs:
            miss=rq-actual; ext=actual-rq
            if not miss and (not ext or allow): best=("MATCH",""); break
            cand=("WRONG" if ext else "UNDER","miss:"+",".join(sorted(miss))) if miss else ("OVER","extra:"+",".join(sorted(ext)))
            if best is None or (cand[0]=="OVER"): best=cand
        grade,detail=best
    gc[grade]+=1
    print("%-18s %-6s %-7s %-5s %-5s %s"%(key,grade,n,ideal,rounds(sig),detail[:38]))
print("-"*78)
print("完成度:",dict(gc))
