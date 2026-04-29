"use client";

/**
 * useAgentStream — subscribe to the Agent Builder's SSE stream and feed each
 * event into BuilderContext so the canvas updates in real time.
 *
 * Usage pattern:
 *   const { start, cancel, status, chat, errors, summary } = useAgentStream();
 *   start("build me a filter on OOC events");
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useBuilder } from "./BuilderContext";
import {
  cancelAgentSession,
  createAgentSession,
  agentStreamUrl,
  type AgentStreamEvent,
  type AgentStreamEventChat,
  type AgentStreamEventDone,
  type AgentStreamEventError,
  type AgentStreamEventOperation,
  type AgentStreamEventSuggestionCard,
  type SuggestionAction,
} from "@/lib/pipeline-builder/agent-api";
import type { PipelineJSON, BlockSpec } from "@/lib/pipeline-builder/types";

export interface AgentChatEntry {
  role: "agent" | "system";
  content: string;
  highlight_nodes?: string[];
  kind: "chat" | "op" | "error" | "suggestion";
  op?: string;
  ts: number;
  /** PR-E3b: for kind="suggestion" — proposed actions for Apply/Dismiss UI. */
  suggestion?: {
    summary: string;
    rationale?: string | null;
    actions: SuggestionAction[];
    applied: boolean;
    dismissed: boolean;
  };
}

export type AgentStatus = "idle" | "connecting" | "running" | "finished" | "failed" | "cancelled";

interface UseAgentStreamOpts {
  /** Catalog used to resolve block spec when applying add_node ops to canvas. */
  blockCatalog: BlockSpec[];
}

export function useAgentStream(opts: UseAgentStreamOpts) {
  const { actions } = useBuilder();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<AgentStatus>("idle");
  const [chat, setChat] = useState<AgentChatEntry[]>([]);
  const [finalPipeline, setFinalPipeline] = useState<PipelineJSON | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const closeEventSource = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  useEffect(() => () => closeEventSource(), [closeEventSource]);

  const resetState = useCallback(() => {
    setChat([]);
    setFinalPipeline(null);
    setSummary(null);
    setSessionId(null);
    setStatus("idle");
  }, []);

  const appendChat = useCallback((entry: AgentChatEntry) => {
    setChat((prev) => [...prev, entry]);
  }, []);

  const applyEvent = useCallback(
    (evt: AgentStreamEvent) => {
      switch (evt.type) {
        case "chat": {
          const e = evt as AgentStreamEventChat;
          appendChat({
            role: "agent",
            kind: "chat",
            content: e.data.content,
            highlight_nodes: e.data.highlight_nodes ?? [],
            ts: e.data.ts,
          });
          return;
        }
        case "error": {
          const e = evt as AgentStreamEventError;
          appendChat({
            role: "system",
            kind: "error",
            content: `${e.data.op}: ${e.data.message}${e.data.hint ? ` — ${e.data.hint}` : ""}`,
            op: e.data.op,
            ts: e.data.ts,
          });
          return;
        }
        case "operation": {
          const e = evt as AgentStreamEventOperation;
          appendChat({
            role: "system",
            kind: "op",
            content: describeOp(e),
            op: e.data.op,
            ts: e.data.ts,
          });
          applyOperationToCanvas(e, actions, opts.blockCatalog);
          return;
        }
        case "done": {
          const e = evt as AgentStreamEventDone;
          setFinalPipeline(e.data.pipeline_json);
          setSummary(e.data.summary ?? null);
          setStatus(e.data.status === "finished" ? "finished" : e.data.status);
          closeEventSource();
          return;
        }
        case "suggestion_card": {
          const e = evt as AgentStreamEventSuggestionCard;
          appendChat({
            role: "agent",
            kind: "suggestion",
            content: e.data.summary,
            ts: e.data.ts,
            suggestion: {
              summary: e.data.summary,
              rationale: e.data.rationale,
              actions: e.data.actions ?? [],
              applied: false,
              dismissed: false,
            },
          });
          return;
        }
      }
    },
    [actions, opts.blockCatalog, appendChat, closeEventSource]
  );

  const start = useCallback(
    async (prompt: string, base_pipeline_id?: number) => {
      resetState();
      setStatus("connecting");
      try {
        const { session_id } = await createAgentSession({ prompt, base_pipeline_id });
        setSessionId(session_id);
        setStatus("running");

        const es = new EventSource(agentStreamUrl(session_id));
        esRef.current = es;

        // Generic onmessage handler — events without explicit "event:" land here.
        es.onmessage = (msg) => {
          try {
            const data = JSON.parse(msg.data);
            applyEvent({ type: "chat", data } as AgentStreamEvent);
          } catch {
            /* ignore */
          }
        };

        // Named event listeners
        for (const name of ["chat", "operation", "error", "done", "suggestion_card"] as const) {
          es.addEventListener(name, ((e: MessageEvent) => {
            try {
              const data = JSON.parse(e.data);
              applyEvent({ type: name, data } as AgentStreamEvent);
            } catch (err) {
              console.error("Failed to parse SSE event", name, err);
            }
          }) as EventListener);
        }

        es.onerror = (err) => {
          console.error("EventSource error", err);
          // If we've already received a done event, don't mark as failed
          if (status === "finished" || status === "cancelled") return;
          setStatus((prev) => (prev === "running" || prev === "connecting" ? "failed" : prev));
          closeEventSource();
        };
      } catch (e) {
        console.error("start agent failed", e);
        setStatus("failed");
        appendChat({
          role: "system",
          kind: "error",
          content: `Failed to start agent: ${(e as Error).message}`,
          ts: Date.now() / 1000,
        });
      }
    },
    // note: `status` intentionally NOT a dep to keep `start` stable (read via closure in onerror)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [resetState, applyEvent, appendChat, closeEventSource]
  );

  const cancel = useCallback(async () => {
    if (!sessionId) return;
    try {
      await cancelAgentSession(sessionId);
    } catch (e) {
      console.error("cancel failed", e);
    }
  }, [sessionId]);

  /** PR-E3b: apply a suggestion's actions to the canvas + mark entry as applied. */
  const applySuggestion = useCallback(
    (entryIndex: number) => {
      setChat((prev) => {
        const item = prev[entryIndex];
        if (!item?.suggestion || item.suggestion.applied || item.suggestion.dismissed) return prev;
        for (const act of item.suggestion.actions) {
          try {
            applySuggestionAction(act, actions, opts.blockCatalog);
          } catch (e) {
            console.error("apply suggestion action failed", act, e);
          }
        }
        const next = [...prev];
        next[entryIndex] = {
          ...item,
          suggestion: { ...item.suggestion, applied: true },
        };
        return next;
      });
    },
    [actions, opts.blockCatalog],
  );

  const dismissSuggestion = useCallback((entryIndex: number) => {
    setChat((prev) => {
      const item = prev[entryIndex];
      if (!item?.suggestion || item.suggestion.dismissed || item.suggestion.applied) return prev;
      const next = [...prev];
      next[entryIndex] = {
        ...item,
        suggestion: { ...item.suggestion, dismissed: true },
      };
      return next;
    });
  }, []);

  return {
    sessionId,
    status,
    chat,
    finalPipeline,
    summary,
    start,
    cancel,
    applySuggestion,
    dismissSuggestion,
    reset: resetState,
  };
}

/** PR-E3b: apply one suggestion action to the canvas. */
function applySuggestionAction(
  act: SuggestionAction,
  actions: ReturnType<typeof useBuilder>["actions"],
  blockCatalog: BlockSpec[],
): void {
  const { tool, args } = act;
  switch (tool) {
    case "add_node": {
      const a = args as {
        block_name?: string;
        block_version?: string;
        position?: { x: number; y: number };
        params?: Record<string, unknown>;
      };
      const spec =
        blockCatalog.find(
          (b) => b.name === a.block_name && b.version === (a.block_version ?? "1.0.0"),
        ) ?? blockCatalog.find((b) => b.name === a.block_name);
      if (!spec) return;
      actions.addNode(spec, a.position ?? { x: 120, y: 120 });
      return;
    }
    case "connect": {
      const a = args as { from_node: string; from_port: string; to_node: string; to_port: string };
      actions.connect({
        id: "",
        from: { node: a.from_node, port: a.from_port },
        to: { node: a.to_node, port: a.to_port },
      });
      return;
    }
    case "set_param": {
      const a = args as { node_id: string; key: string; value: unknown };
      actions.setParam(a.node_id, a.key, a.value);
      return;
    }
    case "rename_node": {
      const a = args as { node_id: string; label: string };
      actions.renameNode(a.node_id, a.label);
      return;
    }
    case "remove_node": {
      const a = args as { node_id: string };
      actions.removeNode(a.node_id);
      return;
    }
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function describeOp(e: AgentStreamEventOperation): string {
  const { op, args, result } = e.data;
  switch (op) {
    case "add_node":
      return `added ${(args as { block_name?: string })?.block_name ?? "node"} → ${(result as { node_id?: string })?.node_id ?? "?"}`;
    case "connect": {
      const a = args as { from_node?: string; from_port?: string; to_node?: string; to_port?: string };
      return `connected ${a.from_node}.${a.from_port} → ${a.to_node}.${a.to_port}`;
    }
    case "set_param": {
      const a = args as { node_id?: string; key?: string; value?: unknown };
      return `set ${a.node_id}.${a.key} = ${JSON.stringify(a.value)}`;
    }
    case "remove_node":
      return `removed ${(args as { node_id?: string })?.node_id}`;
    case "disconnect":
      return `disconnected ${(args as { edge_id?: string })?.edge_id}`;
    case "preview":
      return `previewed ${(args as { node_id?: string })?.node_id} — ${(result as { rows?: number })?.rows ?? "?"} rows`;
    case "validate": {
      const r = result as { valid?: boolean; errors?: unknown[] };
      return r.valid ? "validated: ✓ pipeline OK" : `validated: ${r.errors?.length ?? 0} errors`;
    }
    case "list_blocks":
      return `listed ${(result as { count?: number })?.count ?? 0} blocks`;
    case "finish":
      return `finished — ${(result as { summary?: string })?.summary ?? ""}`;
    default:
      return `${op}(...)`;
  }
}

/** Apply a single operation event to the BuilderContext so canvas reflects Agent's work in real time.
 *
 *  Phase E3: also exported as `applyGlassOpToCanvas` (small adapter) so
 *  BuilderLayout can wire AIAgentPanel.onGlassOp directly into the same
 *  BuilderContext mutation path that AgentBuilderPanel uses internally,
 *  keeping a single source of truth for "what Glass Box ops do to the canvas".
 */
function applyOperationToCanvas(
  e: AgentStreamEventOperation,
  actions: ReturnType<typeof useBuilder>["actions"],
  blockCatalog: BlockSpec[]
): void {
  const { op, args, result } = e.data;
  try {
    switch (op) {
      case "add_node": {
        const a = args as {
          block_name?: string;
          block_version?: string;
          position?: { x: number; y: number };
          params?: Record<string, unknown>;
        };
        const res = result as { node_id?: string; position?: { x: number; y: number } };
        const spec = blockCatalog.find(
          (b) => b.name === a.block_name && b.version === (a.block_version ?? "1.0.0")
        ) ?? blockCatalog.find((b) => b.name === a.block_name);
        if (!spec || !res.node_id) return;
        // Backend minted the node_id + applied smart-offset — use them verbatim so
        // FE/BE IDs stay in sync for downstream set_param / connect calls.
        const pos = res.position ?? a.position ?? { x: 40, y: 80 };
        actions.addNodeAgent(spec, pos, a.params ?? {}, res.node_id);
        return;
      }
      case "remove_node": {
        const a = args as { node_id?: string };
        if (a.node_id) actions.removeNode(a.node_id);
        return;
      }
      case "connect": {
        const a = args as { from_node: string; from_port: string; to_node: string; to_port: string };
        const res = result as { edge_id?: string };
        actions.connectAgent({
          id: res.edge_id ?? "",
          from: { node: a.from_node, port: a.from_port },
          to: { node: a.to_node, port: a.to_port },
        });
        return;
      }
      case "disconnect": {
        const a = args as { edge_id?: string };
        if (a.edge_id) actions.disconnect(a.edge_id);
        return;
      }
      case "set_param": {
        const a = args as { node_id: string; key: string; value: unknown };
        actions.setParam(a.node_id, a.key, a.value);
        return;
      }
      case "move_node": {
        const a = args as { node_id: string; position: { x: number; y: number } };
        actions.moveNode(a.node_id, a.position);
        return;
      }
      case "rename_node": {
        const a = args as { node_id: string; label: string };
        actions.renameNode(a.node_id, a.label);
        return;
      }
      case "list_blocks":
      case "preview":
      case "validate":
      case "get_state":
      case "finish":
      case "explain":
        return; // informational, no canvas mutation
    }
  } catch (err) {
    console.error("applyOperationToCanvas failed", op, err);
  }
}

/**
 * Phase E3 adapter — flat (op, args, result) → AgentStreamEventOperation
 * shape expected by applyOperationToCanvas. Lets BuilderLayout wire
 * AIAgentPanel.onGlassOp without copy-pasting the switch logic.
 */
export function applyGlassOpToCanvas(
  ev: { op: string; args: Record<string, unknown>; result: Record<string, unknown> },
  actions: ReturnType<typeof useBuilder>["actions"],
  blockCatalog: BlockSpec[]
): void {
  applyOperationToCanvas(
    {
      type: "operation",
      data: ev,
    } as AgentStreamEventOperation,
    actions,
    blockCatalog,
  );
}
