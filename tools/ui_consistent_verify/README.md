# UI-consistent SSE Verify Harness

> Reproduces EXACTLY what the React UI sees when calling chat / builder
> endpoints. Use this — never read raw sidecar logs — to ack whether a
> fix actually fixes the user-facing experience.
>
> Lesson: 2026-05-17 v30.17a I ack'd "PASS" by inspecting raw
> `stream_graph_build` events. Those events were silently dropped by
> `wrap_build_event_for_chat` before reaching chat UI. User reported
> "still stuck". Don't trust raw logs again.

## Files

- `chat_verify.py` — mirrors `aiops-app/src/components/chat/ChatPanel.tsx`
  case statement (20 event types). Run via `POST /internal/agent/chat`.
- `builder_verify.py` — mirrors
  `aiops-app/src/components/pipeline-builder/AgentBuilderPanelV30.tsx`
  case statement (15 v30 event types). Run via `POST /internal/agent/build`.

## Invariant

When you add/rename a `case "..."` branch in the .tsx file, also update
the matching constant in the .py file. The Python constants carry
`# keep in sync with X.tsx:LINE` comments.

## Usage

```bash
# On EC2 — uses real sidecar
ssh -i ~/Desktop/ai-ops-key.pem ubuntu@43.213.71.239
set -a && source /opt/aiops/python_ai_sidecar/.env && set +a
export SVC_TOKEN=$SERVICE_TOKEN SIDECAR_BASE=http://localhost:8050

# Verify chat path (with [intent_confirmed:] to force build path)
python3 /opt/aiops/tools/ui_consistent_verify/chat_verify.py \
  "[intent_confirmed:auto-test-1] 檢查機台EQP-01 最後一次OOC 時，是否有多張SPC 也OOC"

# Verify builder path
python3 /opt/aiops/tools/ui_consistent_verify/builder_verify.py \
  "檢查機台EQP-01 最後一次OOC 時，是否有多張SPC 也OOC" \
  --skill-step-mode
```

## Output

Each event prints with one of 3 prefixes:
- `[UI]   ev=foo` — UI handles this event, will render something
- `[DROP] ev=bar` — Event arrived but UI's switch has no case for it
- `[META] ...` — Test harness metadata (run start, timing, etc.)

At end: summary count of UI / DROP events. If a fix should have shown
build progress to user but DROP count is high → the fix didn't reach UI.
