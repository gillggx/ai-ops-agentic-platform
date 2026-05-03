"use client";

import { ViewKind, VIEW_LABEL } from "../lib/types";

interface Props { view: ViewKind; }

export default function ViewPlaceholder({ view }: Props) {
  return (
    <div style={{
      flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
      color: "#bbb", fontSize: 12, letterSpacing: "0.04em",
    }}>
      {VIEW_LABEL[view].toUpperCase()} VIEW · 即將上線
    </div>
  );
}
