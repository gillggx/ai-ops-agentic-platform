"""Chat-mode grader (W1). Grades a chat_driver run's per-case behaviour against
an expected-behaviour map.

IMPORTANT — WANT is PROVISIONAL. It encodes one reading of correct chat
behaviour: an operations *data* question should be ANSWERED (directly, or by
building+running a pipeline and reporting the result — either counts as
"answer" here), a *concept* question answered, and a *vague* prompt should
clarify. Whether chat should instead drop the user into the pipeline-build
confirm flow for data questions is a PRODUCT decision — confirm with the owner
before treating a WANT mismatch as a real failure (the SLASH-17 lesson: a
failing grade is a hypothesis, and a stale golden blames the agent for being
right). See tools/chat_eval/README.md.

Env: RESULTS_DIR (default /tmp), reads chat_eval_results.json (or
<label> via argv1 → chat_eval_<label>.json).
"""
import json
import os
import sys
from collections import Counter

RESULTS_DIR = os.environ.get("RESULTS_DIR", "/tmp")

# key -> expected terminal behaviour. Per the 2026-06-23 product decision:
# operations DATA questions SHOULD route to a build-confirm card (chat = pipeline
# entry, consistent with the builder); CONCEPT questions answer directly; VAGUE
# prompts clarify. For build_confirm cases the bar is higher than "a card showed"
# — after auto-confirm the pipeline must actually BUILD + RUN + return a result
# (the eval runs as PE via X-User-Roles so build_pipeline_live is allowed).
WANT = {
    "status-one":   "build_confirm",
    "status-fleet": "build_confirm",
    "ooc-rank":     "build_confirm",
    "ooc-count":    "build_confirm",
    "spc-trend":    "build_confirm",
    "compare":      "build_confirm",
    "knowledge":    "answer",
    "vague":        "clarify",
}


def main():
    lbl = sys.argv[1] if len(sys.argv) > 1 else None
    path = (f"{RESULTS_DIR}/chat_eval_{lbl}.json" if lbl
            else f"{RESULTS_DIR}/chat_eval_results.json")
    R = {r["key"]: r for r in json.load(open(path))}
    gc = Counter()
    print("%-14s %-7s %-13s %-13s %s" % ("case", "grade", "want", "got", "deliverable"))
    print("-" * 78)
    for key, want in WANT.items():
        r = R.get(key, {})
        got = r.get("behavior")
        # deliverable check (build_confirm only): confirmed → built nodes + ran
        nblocks = len(r.get("confirmed_blocks") or [])
        ran = r.get("confirmed_ran")
        deliv = (f"blocks={nblocks} ran={ran}" if r.get("confirmed") else "-")
        if got is None:
            grade, note = "MISS", "(not run)"
        elif got == "error":
            grade, note = "FAIL", "errored"
        elif got != want:
            grade, note = "WRONG", deliv
        elif want == "build_confirm":
            # behaviour right — now verify the confirmed build actually delivered.
            if ran and nblocks > 0:
                grade, note = "MATCH", deliv
            else:
                grade, note = "BUILD?", deliv + " (confirm OK but build incomplete)"
        else:
            grade, note = "MATCH", ""
        gc[grade] += 1
        print("%-14s %-7s %-13s %-13s %s" % (key, grade, want, got or "-", note))
    print("-" * 78)
    print("grades:", dict(gc))
    print("MATCH(build_confirm) = card shown AND auto-confirm built+ran a pipeline.")


if __name__ == "__main__":
    main()
