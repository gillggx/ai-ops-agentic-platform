"use client";

import React from "react";

type Props = { children: React.ReactNode };
type State = { error: Error | null };

export class CanvasErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[CanvasErrorBoundary] DagCanvas crashed:", error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div style={{
          height: "100%", display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center",
          background: "#fffbeb", padding: 32, gap: 12,
        }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#92400e" }}>
            ⚠ Canvas 渲染失敗
          </div>
          <div style={{ fontSize: 12, color: "#78716c", maxWidth: 480, textAlign: "center" }}>
            Pipeline 結構異常導致 React Flow 無法繪製。常見原因：node 缺少必填參數、
            edge 指向不存在的 node、或 incremental edit 留下 orphan node。
          </div>
          <div style={{
            fontSize: 10, color: "#a8a29e", fontFamily: "ui-monospace, monospace",
            maxWidth: 600, wordBreak: "break-word", textAlign: "center",
          }}>
            {this.state.error.message}
          </div>
          <button
            type="button"
            onClick={this.reset}
            style={{
              marginTop: 8, padding: "6px 14px", fontSize: 12,
              background: "#f59e0b", color: "white", border: "none",
              borderRadius: 4, cursor: "pointer",
            }}
          >
            重試渲染
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
