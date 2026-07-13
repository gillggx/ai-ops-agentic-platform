/**
 * result_render entry (2026-07-13) — headless bundle 的瀏覽器端入口。
 * esbuild 打包成 bundle.js（IIFE），由 render.mjs 以 file:// 頁面載入。
 * window.__renderResult(payload) → 在 #root 畫 chart（真實 SVG 引擎）或 table。
 */
import { renderChartHeadless } from "../../aiops-app/src/components/pipeline-builder/charts/headless";

interface RenderPayload {
  kind: "chart" | "table";
  spec?: Record<string, unknown>;                 // chart_spec（__dsl）
  columns?: string[];                             // table 用
  rows?: Array<Record<string, unknown>>;          // table 用（≤50 列）
  title?: string;
}

function esc(s: unknown): string {
  return String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));
}

(window as unknown as Record<string, unknown>).__renderResult = (payload: RenderPayload): string => {
  const root = document.getElementById("root")!;
  root.innerHTML = "";
  if (payload.kind === "chart" && payload.spec) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", "900");
    svg.setAttribute("height", "440");
    svg.style.background = "#ffffff";
    root.appendChild(svg);
    const ok = renderChartHeadless(svg as SVGSVGElement, payload.spec as never);
    return ok ? "ok" : `unknown chart type: ${String((payload.spec as { type?: string }).type)}`;
  }
  if (payload.kind === "table") {
    const cols = payload.columns ?? [];
    const rows = (payload.rows ?? []).slice(0, 50);
    const thead = `<tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>`;
    const tbody = rows.map((r) =>
      `<tr>${cols.map((c) => `<td>${esc(r[c])}</td>`).join("")}</tr>`).join("");
    root.innerHTML =
      `<div style="font:13px 'Noto Sans TC',sans-serif;padding:12px;background:#fff">` +
      (payload.title ? `<div style="font-weight:700;margin-bottom:8px">${esc(payload.title)}</div>` : "") +
      `<table style="border-collapse:collapse">` +
      `<style>th,td{border:1px solid #d5d9e2;padding:4px 10px;font-size:12px;text-align:left}th{background:#f1f5f9}</style>` +
      `${thead}${tbody}</table>` +
      (payload.rows && payload.rows.length > 50 ? `<div style="color:#8b90a7;margin-top:6px">…共 ${payload.rows.length} 列（截前 50）</div>` : "") +
      `</div>`;
    return "ok";
  }
  return "bad payload";
};
