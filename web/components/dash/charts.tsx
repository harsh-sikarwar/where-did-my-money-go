"use client";

/**
 * Overview's gap-trend line chart. Reuses `shortDay` from the original
 * `GapByDay` component (`components/GapByDay.tsx`) rather than redefining
 * date formatting — same discipline as the rest of the dashboard rebuild:
 * port computation, rebuild visuals.
 */

import { useMemo } from "react";
import { shortDay } from "@/components/GapByDay";
import type { Timeline } from "@/lib/api";

const W = 700;
const H = 200;
const PAD_BOTTOM = 10;

function points(values: number[], max: number): string {
  if (values.length < 2) return "";
  const step = W / (values.length - 1);
  return values
    .map((v, i) => {
      const x = i * step;
      const y = H - PAD_BOTTOM - (Math.max(0, v) / max) * (H - PAD_BOTTOM - 10);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function GapTrendChart({ timeline }: { timeline: Timeline }) {
  const { expectedPts, gapPts, areaPts, max } = useMemo(() => {
    const expected = timeline.days.map((d) => d.expected.paise);
    const gap = timeline.days.map((d) => Math.abs(d.amount.paise));
    const max = Math.max(...expected, ...gap, 1);
    const expectedPts = points(expected, max);
    const gapPts = points(gap, max);
    const gapLine = timeline.days.map((d, i) => {
      const step = W / (timeline.days.length - 1);
      const y = H - PAD_BOTTOM - (Math.max(0, Math.abs(d.amount.paise)) / max) * (H - PAD_BOTTOM - 10);
      return `${(i * step).toFixed(1)},${y.toFixed(1)}`;
    });
    const areaPts = `0,${H} ${gapLine.join(" ")} ${W},${H}`;
    return { expectedPts, gapPts, areaPts, max };
  }, [timeline]);

  const first = timeline.days[0];
  const mid = timeline.days[Math.floor(timeline.days.length / 2)];
  const last = timeline.days[timeline.days.length - 1];

  if (max <= 0) return null;

  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: 212, display: "block", overflow: "visible" }}>
        <defs>
          <linearGradient id="dashGapFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--dash-action)" stopOpacity="0.3" />
            <stop offset="100%" stopColor="var(--dash-action)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[40, 90, 140, 190].map((y) => (
          <line key={y} x1={0} y1={y} x2={W} y2={y} stroke="oklch(0.5 0.045 72 / 0.11)" />
        ))}
        <polygon points={areaPts} fill="url(#dashGapFill)" style={{ animation: "fadeIn .9s ease .3s both" }} />
        <polyline
          points={expectedPts}
          fill="none"
          stroke="var(--dash-benign)"
          strokeWidth={1.7}
          strokeLinejoin="round"
          strokeDasharray={1600}
          style={{ animation: "drawLine 1.4s cubic-bezier(.3,.8,.3,1) both" }}
        />
        <polyline
          points={gapPts}
          fill="none"
          stroke="var(--dash-action)"
          strokeWidth={2.4}
          strokeLinejoin="round"
          strokeDasharray={1600}
          style={{ animation: "drawLine 1.4s cubic-bezier(.3,.8,.3,1) .15s both" }}
        />
      </svg>
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--dash-font-mono)", fontSize: 10.5, color: "var(--dash-neutral)", marginTop: 8 }}>
        <span>{shortDay(first.day)}</span>
        <span>{shortDay(mid.day)}</span>
        <span>{shortDay(last.day)}</span>
      </div>
    </>
  );
}
