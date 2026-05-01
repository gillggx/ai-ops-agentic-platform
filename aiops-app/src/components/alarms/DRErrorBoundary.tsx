"use client";

import React from "react";

type Props = {
  label: string;
  logId?: number | string | null;
  children: React.ReactNode;
};

type State = { error: Error | null };

export class DRErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`[DRErrorBoundary] ${this.props.label} (log=${this.props.logId ?? "?"}) crashed:`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          border: "1px solid #fcd34d", borderRadius: 6, marginBottom: 12,
          background: "#fffbeb", padding: "12px 16px",
        }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#92400e", marginBottom: 4 }}>
            ⚠ {this.props.label} 無法載入
          </div>
          <div style={{ fontSize: 11, color: "#78716c" }}>
            診斷結果格式異常{this.props.logId != null ? `（log #${this.props.logId}）` : ""}，已略過此筆以保護整頁。
          </div>
          <div style={{ fontSize: 10, color: "#a8a29e", marginTop: 4, fontFamily: "ui-monospace, monospace" }}>
            {this.state.error.message}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
