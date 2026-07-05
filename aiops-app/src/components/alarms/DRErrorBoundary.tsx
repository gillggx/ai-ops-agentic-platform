"use client";

import React from "react";
import { useTranslations } from "next-intl";

type Props = {
  label: string;
  logId?: number | string | null;
  children: React.ReactNode;
};

type InnerProps = Props & {
  crashTitle: string;
  crashBody: string;
};

type State = { error: Error | null };

/** Class component owns the error-boundary lifecycle (hooks can't); the
 *  exported functional wrapper below injects the translated strings. */
class DRErrorBoundaryInner extends React.Component<InnerProps, State> {
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
            ⚠ {this.props.crashTitle}
          </div>
          <div style={{ fontSize: 11, color: "#78716c" }}>
            {this.props.crashBody}
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

export function DRErrorBoundary({ label, logId, children }: Props) {
  const t = useTranslations("alarms");
  const ref = logId != null ? t("boundary.logRef", { id: logId }) : "";
  return (
    <DRErrorBoundaryInner
      label={label}
      logId={logId}
      crashTitle={t("boundary.crashTitle", { label })}
      crashBody={t("boundary.crashBody", { ref })}
    >
      {children}
    </DRErrorBoundaryInner>
  );
}
