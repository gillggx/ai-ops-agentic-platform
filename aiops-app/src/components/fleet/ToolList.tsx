"use client";

import { useState } from "react";
import { HourStrip, Pill, StatusDot, TrendArrow } from "./primitives";
import type { FleetEquipment } from "./types";

type Filter = "all" | "crit" | "warn";

export function ToolList({ tools, onOpenTool }: {
  tools: FleetEquipment[];
  onOpenTool: (id: string) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");

  const visible = tools.filter(t => {
    if (filter === "crit") return t.health === "crit";
    if (filter === "warn") return t.health === "warn";
    return true;
  });

  const critCount = tools.filter(t => t.health === "crit").length;
  const warnCount = tools.filter(t => t.health === "warn").length;

  return (
    <div className="surface tool-list">
      <div className="tool-list__header">
        <div>
          <div className="h2">需介入機台 (依嚴重度排序)</div>
          <div className="micro" style={{ color: "var(--c-ink-3)", marginTop: 2 }}>
            依嚴重度排序：需介入 → 需關注 → 健康
          </div>
        </div>
        <div className="tool-list__filters">
          <button
            className={"btn " + (filter === "all" ? "btn-primary" : "btn-ghost")}
            onClick={() => setFilter("all")}
          >
            全部 ({tools.length})
          </button>
          <button
            className={"btn " + (filter === "crit" ? "btn-primary" : "btn-ghost")}
            onClick={() => setFilter("crit")}
            style={filter !== "crit" ? { color: "var(--c-crit)" } : {}}
          >
            需介入 ({critCount})
          </button>
          <button
            className={"btn " + (filter === "warn" ? "btn-primary" : "btn-ghost")}
            onClick={() => setFilter("warn")}
            style={filter !== "warn" ? { color: "var(--c-warn)" } : {}}
          >
            關注 ({warnCount})
          </button>
        </div>
      </div>

      <div className="tool-list__cols">
        <div className="label">#</div>
        <div className="label">設備</div>
        <div className="label">狀態</div>
        <div className="label">OOC Rate</div>
        <div className="label">24h OOC %</div>
        <div className="label">事件 / 趨勢</div>
        <div></div>
      </div>

      {visible.map((t, i) => {
        return (
          <div
            key={t.id}
            className={"tool-list__row" + (t.health === "crit" ? " tool-list__row--crit" : "")}
            onClick={() => onOpenTool(t.id)}
            role="button"
            tabIndex={0}
          >
            <div className="tool-list__rank">{String(i + 1).padStart(2, "0")}</div>
            <div style={{ minWidth: 0 }}>
              <div className="tool-list__id-line">
                <StatusDot status={t.health} />
                <span className="tool-list__id">{t.id}</span>
              </div>
              {t.note && <div className="tool-list__note">{t.note}</div>}
            </div>
            <div>
              <Pill kind={t.health === "healthy" ? "ok" : t.health}>
                {t.health === "crit" ? "需介入" : t.health === "warn" ? "關注" : "健康"}
              </Pill>
            </div>
            <div>
              <div
                className={
                  "tool-list__ooc-pct mono " +
                  (t.health === "crit" ? "tool-list__ooc-pct--crit" : t.health === "warn" ? "tool-list__ooc-pct--warn" : "")
                }
              >
                {t.ooc.toFixed(1)}%
              </div>
              <div className="tool-list__ooc-sub">{t.ooc_count} OOC</div>
            </div>
            <div>
              <HourStrip values={t.hourly} />
              <div className="tool-list__hour-axis">-24h ··············· 現在</div>
            </div>
            <div>
              <div className="micro mono" style={{ color: "var(--c-ink-2)" }}>
                {t.lots24h} LOTs · {t.fdc} FDC · {t.alarms} alarm
              </div>
              <div style={{ marginTop: 2 }}><TrendArrow dir={t.trend} /></div>
            </div>
            <div style={{ textAlign: "right" }}>
              <button className="btn btn-ghost" style={{ height: 24, padding: "0 8px" }}>檢視 →</button>
            </div>
          </div>
        );
      })}

      {visible.length === 0 && (
        <div className="fleet-overview__empty">沒有符合條件的機台</div>
      )}
    </div>
  );
}
