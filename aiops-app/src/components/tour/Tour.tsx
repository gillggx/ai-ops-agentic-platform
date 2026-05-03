"use client";

/**
 * Tour — spotlight onboarding overlay (ported from the AIOps Charting
 * design tour.jsx). Uses an SVG mask to cut a hole around the target
 * element and shows a bubble at the configured placement.
 *
 * Renders into a portal at document.body so it's never clipped by an
 * ancestor's overflow:hidden.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { TourStep } from "./types";

const BUBBLE_W = 320;
const BUBBLE_H_GUESS = 180; // initial guess for placement clamping; actual content height varies
const PAD = 14;

interface Props {
  steps: TourStep[];
  startStep?: number;
  onClose: () => void;
}

function getRect(step: TourStep) {
  if (step.selectorRect) return step.selectorRect();
  if (!step.target) return null;
  const el = document.querySelector(step.target);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { left: r.left, top: r.top, width: r.width, height: r.height };
}

function bubblePos(rect: { left: number; top: number; width: number; height: number } | null,
                   placement: TourStep["placement"]) {
  const W = window.innerWidth;
  const H = window.innerHeight;
  const bw = BUBBLE_W;
  const bh = BUBBLE_H_GUESS;
  if (!rect || placement === "center") {
    return { left: (W - bw) / 2, top: (H - bh) / 2, arrow: null as null };
  }
  let left: number;
  let top: number;
  let arrow: "left" | "right" | "top" | "bottom" | null;
  if (placement === "right") {
    left = rect.left + rect.width + PAD;
    top = rect.top + 8;
    arrow = "left";
  } else if (placement === "left") {
    left = rect.left - bw - PAD;
    top = rect.top + 8;
    arrow = "right";
  } else if (placement === "top") {
    left = rect.left + rect.width / 2 - bw / 2;
    top = rect.top - bh - PAD;
    arrow = "bottom";
  } else {
    // bottom
    left = rect.left + rect.width / 2 - bw / 2;
    top = rect.top + rect.height + PAD;
    arrow = "top";
  }
  // clamp inside viewport
  left = Math.max(8, Math.min(W - bw - 8, left));
  top = Math.max(8, Math.min(H - bh - 8, top));
  return { left, top, arrow };
}

export default function Tour({ steps, startStep = 0, onClose }: Props) {
  const [step, setStep] = useState(startStep);
  const [, force] = useState(0);
  // Mount flag — portal needs document. Server-side render → null.
  const [mounted, setMounted] = useState(false);
  const portalEl = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setMounted(true);
    portalEl.current = document.createElement("div");
    portalEl.current.className = "tour-portal-root";
    document.body.appendChild(portalEl.current);
    return () => {
      if (portalEl.current && portalEl.current.parentNode) {
        portalEl.current.parentNode.removeChild(portalEl.current);
      }
    };
  }, []);

  useEffect(() => {
    const onResize = () => force((x) => x + 1);
    const onKey = (e: KeyboardEvent) => {
      // Don't trap typing in an input — but tour uses no inputs, so OK.
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === "Enter") {
        setStep((s) => Math.min(steps.length - 1, s + 1));
      } else if (e.key === "ArrowLeft") {
        setStep((s) => Math.max(0, s - 1));
      }
    };
    window.addEventListener("resize", onResize);
    window.addEventListener("keydown", onKey);
    // Re-render after layout settles so getBoundingClientRect is accurate.
    const t = window.setTimeout(() => force((x) => x + 1), 50);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(t);
    };
  }, [step, steps.length, onClose]);

  if (!mounted || !portalEl.current) return null;

  const s = steps[step];
  if (!s) return null;
  const rect = getRect(s);
  const bp = bubblePos(rect, s.placement);
  const padPx = 6;

  return createPortal(
    <>
      <div className="tour-mask">
        <svg>
          <defs>
            <mask id="tourCut">
              <rect x="0" y="0" width="100%" height="100%" fill="#fff" />
              {rect && (
                <rect
                  x={rect.left - padPx}
                  y={rect.top - padPx}
                  width={rect.width + padPx * 2}
                  height={rect.height + padPx * 2}
                  rx="6"
                  fill="#000"
                />
              )}
            </mask>
          </defs>
          <rect
            x="0"
            y="0"
            width="100%"
            height="100%"
            fill="rgba(20,20,17,0.55)"
            mask="url(#tourCut)"
          />
          {rect && (
            <rect
              x={rect.left - padPx}
              y={rect.top - padPx}
              width={rect.width + padPx * 2}
              height={rect.height + padPx * 2}
              rx="6"
              fill="none"
              stroke="#2563EB"
              strokeWidth="2"
            />
          )}
        </svg>
      </div>
      <div className="tour-bubble" style={{ left: bp.left, top: bp.top }}>
        {bp.arrow && <div className={"tb-arrow " + bp.arrow} />}
        <div className="tb-step">Step {step + 1} / {steps.length}</div>
        <div className="tb-title">{s.title}</div>
        <div className="tb-body">{s.body}</div>
        <div className="tb-foot">
          <div className="tb-progress">
            {steps.map((_, i) => (
              <div key={i} className={"tb-dot " + (i === step ? "on" : "")} />
            ))}
          </div>
          <button className="skip" onClick={onClose}>Skip</button>
          {step > 0 && (
            <button onClick={() => setStep((s) => s - 1)}>← Back</button>
          )}
          {step < steps.length - 1 ? (
            <button className="primary" onClick={() => setStep((s) => s + 1)}>Next →</button>
          ) : (
            <button className="primary" onClick={onClose}>Done ✓</button>
          )}
        </div>
      </div>
    </>,
    portalEl.current,
  );
}
