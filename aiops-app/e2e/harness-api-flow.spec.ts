/**
 * 2026-05-13 — API-only harness (no GUI).
 *
 * Why this exists:
 * The GUI version (harness-flow.spec.ts) has had a string of races between
 * SSE event ordering, React Flow canvas state, and the Save button click —
 * each fix exposed another race. The agent's *real* output is just a JSON
 * (pipeline_json in the SSE "done" event). The GUI's role is only to render
 * + persist that JSON. By calling the APIs directly we skip the
 * GUI-reconstruction step entirely and test what actually matters:
 *
 *   1. /api/v1/agent/build → SSE → pluck pipeline_json from done event
 *   2. /api/v1/agent/build/confirm if confirm_gate paused us
 *   3. /api/v1/pipelines POST → save → get pipeline_id
 *   4. /api/v1/skill-documents/{slug}/bind-pipeline
 *   5. /api/skill-documents/{slug}/run with trigger_payload → verdict
 *
 * Pure pass/fail signal: did the agent's JSON, when executed by the same
 * Java-side path production uses, produce a numeric verdict?
 */
import { test, expect } from "@playwright/test";

const BASE = process.env.PW_BASE ?? "https://aiops-gill.com";
const USER = process.env.PW_USER ?? "admin";
const PASS = process.env.PW_PASS ?? "admin";
const SLUG = process.env.HARNESS_SLUG ?? "harness-spc-ooc";
const INSTRUCTION = process.env.INSTRUCTION ??
  "檢查機台最後一次OOC 時，是否有多張SPC 也OOC (>2)，並且顯示該SPC charts";

const TRIGGER_PAYLOAD = {
  equipment_id: "EQP-01",
  lot_id: "LOT-0001",
  step_id: "STEP_005",
  chamber_id: "CH-1",
  spc_chart: "xbar_chart",
  severity: "high",
};

type SseEvent = { event: string; data: Record<string, unknown> };

async function loginJava(): Promise<string> {
  const res = await fetch(`${BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASS }),
  });
  if (!res.ok) throw new Error(`auth/login failed: ${res.status}`);
  const j = await res.json();
  return j?.data?.access_token ?? "";
}

async function resetHarness(token: string) {
  const cc = {
    description: INSTRUCTION,
    ai_summary: "",
    pipeline_id: null,
    must_pass: true,
    trigger_payload: TRIGGER_PAYLOAD,
  };
  const res = await fetch(`${BASE}/api/v1/skill-documents/${SLUG}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ confirm_check: JSON.stringify(cc) }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`reset harness failed: ${res.status} ${body.slice(0, 200)}`);
  }
}

/**
 * Stream SSE response chunk-by-chunk, calling onEvent for each event.
 * Returns when stream ends naturally (or onEvent returns "stop").
 */
async function consumeSse(
  res: Response,
  onEvent: (ev: SseEvent) => "continue" | "stop",
): Promise<SseEvent[]> {
  if (!res.body) throw new Error("SSE response has no body");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const collected: SseEvent[] = [];
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let evt = "message";
      const dataLines: string[] = [];
      for (const ln of frame.split("\n")) {
        if (ln.startsWith("event:")) evt = ln.slice(6).trim();
        else if (ln.startsWith("data:")) dataLines.push(ln.slice(5).trim());
      }
      if (!dataLines.length) continue;
      let data: Record<string, unknown>;
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch {
        continue;
      }
      const ev = { event: evt, data };
      collected.push(ev);
      if (onEvent(ev) === "stop") {
        try { await reader.cancel(); } catch { /* noop */ }
        return collected;
      }
    }
  }
  return collected;
}

/**
 * Drive the build to completion. Handles v15 clarify_required (auto-picks
 * default answers) and confirm_pending (auto-confirms). Returns the final
 * pipeline_json from done event.
 */
async function runBuild(token: string): Promise<{
  pipelineJson: Record<string, unknown>;
  events: SseEvent[];
}> {
  const all: SseEvent[] = [];
  let nextResponse: Response | null = await fetch(`${BASE}/api/v1/agent/build`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      Accept: "text/event-stream",
    },
    body: JSON.stringify({
      instruction: INSTRUCTION,
      skillStepMode: true,
      triggerPayload: TRIGGER_PAYLOAD,
    }),
  });
  expect(nextResponse.ok, `/agent/build failed: ${nextResponse.status}`).toBeTruthy();

  let sessionId: string | null = null;
  let pauseKind: "clarify_required" | "confirm_pending" | null = null;
  let pausePayload: Record<string, unknown> | null = null;

  // Loop: each iteration consumes one SSE stream until it pauses (clarify
  // or confirm) or finishes (done). On pause we POST the appropriate
  // resume endpoint and consume the next stream. Bounded to 10 iterations
  // to avoid infinite loops on a buggy backend.
  for (let iter = 0; iter < 10 && nextResponse; iter++) {
    pauseKind = null;
    pausePayload = null;
    const events = await consumeSse(nextResponse, (ev) => {
      all.push(ev);
      if (ev.event === "clarify_required") {
        pauseKind = "clarify_required";
        pausePayload = ev.data;
        sessionId = String(ev.data.session_id ?? sessionId ?? "");
        return "stop";
      }
      if (ev.event === "confirm_pending") {
        pauseKind = "confirm_pending";
        pausePayload = ev.data;
        sessionId = String(ev.data.session_id ?? sessionId ?? "");
        return "stop";
      }
      if (ev.event === "done") {
        return "stop";
      }
      return "continue";
    });

    // Find done in this batch
    const doneInBatch = events.find((e) => e.event === "done");
    if (doneInBatch) {
      const status = String(doneInBatch.data.status);
      if (status !== "finished") {
        throw new Error(`build done but status=${status}, summary=${doneInBatch.data.summary}`);
      }
      const pj = (doneInBatch.data.pipeline_json ?? null) as Record<string, unknown> | null;
      if (!pj || typeof pj !== "object") throw new Error("done event missing pipeline_json");
      return { pipelineJson: pj, events: all };
    }

    if (!pauseKind || !sessionId) {
      throw new Error(`stream ended without done/pause (iter=${iter})`);
    }

    // Resume based on pause kind
    if (pauseKind === "clarify_required") {
      const payload = pausePayload as { clarifications?: Array<{
        id: string; default?: string; options?: Array<{ value: string }>;
      }> } | null;
      const questions = payload?.clarifications ?? [];
      const answers: Record<string, string> = {};
      for (const q of questions) {
        const pick = q.default ?? q.options?.[0]?.value ?? "yes";
        answers[q.id] = pick;
      }
      console.log(`  [clarify] auto-answer ${Object.entries(answers).map(([k,v]) => `${k}=${v}`).join(", ")}`);
      nextResponse = await fetch(`${BASE}/api/v1/agent/build/clarify-respond`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          Accept: "text/event-stream",
        },
        body: JSON.stringify({ sessionId, answers }),
      });
      expect(nextResponse.ok, `clarify-respond failed: ${nextResponse.status}`).toBeTruthy();
    } else if (pauseKind === "confirm_pending") {
      console.log(`  [confirm] auto-confirm sessionId=${sessionId}`);
      nextResponse = await fetch(`${BASE}/api/v1/agent/build/confirm`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          Accept: "text/event-stream",
        },
        body: JSON.stringify({ sessionId, confirmed: true }),
      });
      expect(nextResponse.ok, `confirm failed: ${nextResponse.status}`).toBeTruthy();
    }
  }
  throw new Error("build never reached done event after 10 iterations");
}

async function savePipeline(token: string, pipelineJson: Record<string, unknown>): Promise<number> {
  // Java's POST /api/v1/pipelines takes pipeline_json as a STRING (Jackson
  // doesn't auto-stringify nested), and uses snake_case wire format.
  const body = {
    name: `harness-api-${Date.now()}`,
    description: "harness-api-flow test",
    pipeline_kind: "skill",
    pipeline_json: JSON.stringify(pipelineJson),
  };
  const res = await fetch(`${BASE}/api/v1/pipelines`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  expect(res.ok, `POST /pipelines failed: ${res.status} ${await res.text().catch(() => "")}`).toBeTruthy();
  const j = await res.json();
  const pid = Number(j?.data?.id);
  expect(pid).toBeGreaterThan(0);
  return pid;
}

async function bindToSkill(token: string, pid: number): Promise<void> {
  const res = await fetch(
    `${BASE}/api/v1/skill-documents/${SLUG}/bind-pipeline`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ pipeline_id: pid, slot: "confirm" }),
    },
  );
  expect(res.ok, `bind-pipeline failed: ${res.status} ${await res.text().catch(() => "")}`).toBeTruthy();
}

async function runSkill(token: string): Promise<SseEvent> {
  const res = await fetch(`${BASE}/api/skill-documents/${SLUG}/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ trigger_payload: TRIGGER_PAYLOAD, is_test: true }),
  });
  expect(res.ok, `/skill-documents/.../run failed: ${res.status}`).toBeTruthy();
  const events = await consumeSse(res, (ev) =>
    ev.event === "confirm_done" ? "stop" : "continue",
  );
  const verdict = events.find((e) => e.event === "confirm_done");
  if (!verdict) throw new Error("run never emitted confirm_done");
  return verdict;
}

test.describe("Harness — API-only flow (no GUI)", () => {
  test.setTimeout(360_000);
  test.skip(
    !process.env.ANTHROPIC_LIVE,
    "Set ANTHROPIC_LIVE=1 to spend tokens against the harness",
  );

  test("build → save → bind → run, agent JSON measured directly", async () => {
    const token = await loginJava();
    expect(token).toBeTruthy();

    // 1. reset harness skill so each test starts from "stale" state
    await resetHarness(token);
    console.log("[1/5] harness reset");

    // 2. drive /agent/build to completion, get the pipeline_json
    const { pipelineJson } = await runBuild(token);
    const nodeCount = Array.isArray((pipelineJson as { nodes?: unknown[] }).nodes)
      ? (pipelineJson as { nodes: unknown[] }).nodes.length : 0;
    const edgeCount = Array.isArray((pipelineJson as { edges?: unknown[] }).edges)
      ? (pipelineJson as { edges: unknown[] }).edges.length : 0;
    console.log(`[2/5] build done → ${nodeCount} nodes, ${edgeCount} edges`);
    expect(nodeCount).toBeGreaterThan(0);

    // 3. save the pipeline as agent produced it (no GUI reconstruction)
    const pid = await savePipeline(token, pipelineJson);
    console.log(`[3/5] saved pipeline #${pid}`);

    // 4. bind to harness skill's confirm slot
    await bindToSkill(token, pid);
    console.log(`[4/5] bound to skill ${SLUG}`);

    // 5. run skill with trigger_payload, parse verdict
    const verdict = await runSkill(token);
    const v = verdict.data as { status?: unknown; value?: unknown; note?: unknown };
    console.log(`[5/5] verdict: status=${v.status} value=${v.value} note=${String(v.note ?? "").slice(0, 80)}`);

    // ── Assertions ────────────────────────────────────────────────
    // Signal 1: verdict value is numeric, not "error" (means the pipeline
    // actually ran end-to-end; "error" means it failed mid-execution).
    expect(v.value, `verdict.value should be numeric/bool, got: ${v.value}`).not.toBe("error");
    expect(v.value).not.toBeNull();
    if (typeof v.note === "string") {
      expect(v.note).not.toContain("not numeric");
      expect(v.note).not.toContain("pipeline failed");
    }
  });
});
