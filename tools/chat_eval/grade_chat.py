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

# key -> expected terminal behaviour (PROVISIONAL — see module docstring).
WANT = {
    "status-one":   "answer",
    "status-fleet": "answer",
    "ooc-rank":     "answer",
    "ooc-count":    "answer",
    "spc-trend":    "answer",
    "compare":      "answer",
    "knowledge":    "answer",
    "vague":        "clarify",
}
# soft efficiency budget — flag, don't fail, when chat thrashes the tool catalog.
ITER_BUDGET = 4


def main():
    lbl = sys.argv[1] if len(sys.argv) > 1 else None
    path = (f"{RESULTS_DIR}/chat_eval_{lbl}.json" if lbl
            else f"{RESULTS_DIR}/chat_eval_results.json")
    R = {r["key"]: r for r in json.load(open(path))}
    gc = Counter()
    print("%-14s %-7s %-13s %-13s %-5s %s" % (
        "case", "grade", "want", "got", "iters", "note"))
    print("-" * 78)
    for key, want in WANT.items():
        r = R.get(key, {})
        got = r.get("behavior")
        iters = r.get("iterations", 0)
        if got is None:
            grade, note = "MISS", "(not run)"
        elif got == want:
            grade = "MATCH"
            note = "thrash?" if iters > ITER_BUDGET else ""
        elif got == "error":
            grade, note = "FAIL", "errored"
        else:
            grade, note = "WRONG", f"got {got}"
        gc[grade] += 1
        print("%-14s %-7s %-13s %-13s %-5s %s" % (
            key, grade, want, got or "-", iters, note))
    print("-" * 78)
    print("behavior grades:", dict(gc))
    print("note: WANT is provisional — confirm correct chat behaviour with the "
          "product owner before acting on WRONG (see README).")


if __name__ == "__main__":
    main()
