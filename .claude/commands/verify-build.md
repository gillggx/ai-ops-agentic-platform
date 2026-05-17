---
description: Run a builder test case and report plan / stuck phase / round history
argument-hint: [--mode chat|builder|test] "<user message>" [--json-out PATH]
allowed-tools: Bash
---

Run the verify-build skill with the user's arguments. The runner lives at
`.claude/skills/verify-build/run.py` and SSH's into EC2 prod to execute
the chosen mode against the live sidecar.

**Defaults**
- If `--mode` not given, use `chat`.
- The positional argument is treated as the chat/builder message.
- If `--json-out` is given, also write structured JSON for further analysis.

**Steps**
1. Parse `$ARGUMENTS` to decide mode + message + flags.
2. Invoke:
   ```bash
   python3 .claude/skills/verify-build/run.py [parsed-args]
   ```
3. Show the 3-section report to the user (plan / stuck phase / round-by-round).
4. If a phase is stuck, surface the verifier verdicts + suggest the most
   likely root cause (covers mismatch, row threshold, etc.) — do not
   silently dump raw trace.

**Reference**: `.claude/skills/verify-build/SKILL.md` for full mode docs.

Arguments: $ARGUMENTS
