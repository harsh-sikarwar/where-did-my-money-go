"use client";

import { useMemo } from "react";
import { shortDay } from "@/components/GapByDay";
import type { Timeline } from "@/lib/api";

/**
 * Expected and received, accumulated across the cycle.
 *
 * Cumulative rather than daily on purpose: day-by-day, both lines are spiky and the
 * reader has to integrate them by eye to see the answer. Accumulated, the vertical
 * distance between the lines at any point IS the gap so far, and the distance at the
 * right edge is the gap printed at the top of the page. The chart makes one claim and
 * you can check it with a ruler.
 *
 * `received` is derived per day as `expected - gap`, never summed from the bank side,
 * so the lines cannot drift apart from the figures above them.
 *
 * The y-axis starts at zero and stays there. On a healthy cycle the gap is a few
 * percent, so the two lines very nearly coincide — which is the true shape of a
 * healthy cycle, and zooming the axis until the band looked dramatic would be drawing
 * a different claim than the data supports. The distance is annotated at the right
 * edge instead, so the reader gets the quantity without the chart overstating it.
 *
 * Colour: these are the categorical chart series, not the status tones. `globals.css`
 * routes the series hues around amber, green and red precisely so a line on a chart
 * can never be misread as a severity — the band between the lines is the gap, and most
 * of a healthy gap is ordinary fees.
 */

const W = 760;
const H = 170;
const PAD_X = 10;
/** The plot stops here; the strip to its right carries the gap annotation. */
const PLOT_W = 660;
const TOP = 16;
const BOTTOM = 150;

function money(paise: number): string {
  // Indian grouping, whole rupees — this is an axis label, not a ledger entry.
  return "₹" + Math.round(paise / 100).toLocaleString("en-IN");
}

export function ExpectedVsReceived({ data }: { data: Timeline }) {
  const model = useMemo(() => {
    let expected = 0;
    let received = 0;
    const points = data.days.map((day) => {
      expected += day.expected.paise;
      received += day.received.paise;
      return { day: day.day, expected, received };
    });

    const max = Math.max(expected, received, 1);
    const n = points.length;
    const x = (i: number) => PAD_X + (n <= 1 ? 0 : (i / (n - 1)) * (PLOT_W - PAD_X * 2));
    const y = (v: number) => BOTTOM - (v / max) * (BOTTOM - TOP);

    return {
      points,
      totalExpected: expected,
      totalReceived: received,
      expectedPath: points.map((p, i) => `${x(i)},${y(p.expected)}`).join(" "),
      receivedPath: points.map((p, i) => `${x(i)},${y(p.received)}`).join(" "),
      // The band between the lines: down the received line, back along expected.
      band:
        points.map((p, i) => `${x(i)},${y(p.expected)}`).join(" ") +
        " " +
        points
          .map((p, i) => `${x(n - 1 - i)},${y(points[n - 1 - i].received)}`)
          .join(" "),
      endX: x(n - 1),
      endY: y(received),
      endYExpected: y(expected),
    };
  }, [data]);

  if (data.days.length < 2) return null;

  return (
    <section className="mb-9">
      <div className="mb-3.5 flex items-baseline justify-between gap-4">
        <h3 className="text-label text-[var(--color-ink-faint)]">
          Expected vs. received
        </h3>
        <div className="flex gap-4 text-[11.5px] text-[var(--color-ink-soft)]">
          <span className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block h-0.5 w-3.5"
              style={{ background: "var(--color-series-1)" }}
            />
            Expected
          </span>
          <span className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block h-0.5 w-3.5"
              style={{ background: "var(--color-series-2)" }}
            />
            Received
          </span>
        </div>
      </div>

      <div className="rounded-xl border border-[var(--color-line)] bg-[var(--color-well)] px-4 pt-[18px] pb-3">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="block h-[170px] w-full overflow-visible"
          role="img"
          aria-label={`Cumulative expected ${money(model.totalExpected)} against received ${money(model.totalReceived)} across ${data.days.length} days.`}
        >
          {[30, 75, 120].map((gy) => (
            <line
              key={gy}
              x1="0"
              y1={gy}
              x2={PLOT_W}
              y2={gy}
              stroke="var(--color-line)"
              strokeWidth="1"
            />
          ))}

          <polygon
            points={model.band}
            fill="color-mix(in oklch, var(--color-series-2) 14%, transparent)"
            style={{ animation: "fadeIn 0.8s ease 0.5s both" }}
          />

          <polyline
            points={model.expectedPath}
            fill="none"
            stroke="var(--color-series-1)"
            strokeWidth="2"
            strokeLinejoin="round"
            strokeDasharray="1600"
            style={{ animation: "drawLine 1.3s cubic-bezier(0.3,0.8,0.3,1) both" }}
          />
          <polyline
            points={model.receivedPath}
            fill="none"
            stroke="var(--color-series-2)"
            strokeWidth="2.5"
            strokeLinejoin="round"
            strokeDasharray="1600"
            style={{ animation: "drawLine 1.3s cubic-bezier(0.3,0.8,0.3,1) 0.15s both" }}
          />
          <circle
            cx={model.endX}
            cy={model.endY}
            r="4.5"
            fill="var(--color-series-2)"
            style={{ animation: "fadeIn 0.4s ease 1.2s both" }}
          />

          {/* The band at the right edge is the gap. At a few percent it is only a few
              pixels tall, so it is named rather than left to the eye to measure. */}
          <g style={{ animation: "fadeIn 0.4s ease 1.4s both" }}>
            <line
              x1={model.endX + 14}
              y1={model.endYExpected}
              x2={model.endX + 14}
              y2={model.endY}
              stroke="var(--color-ink-faint)"
              strokeWidth="1"
            />
            <line
              x1={model.endX + 10}
              y1={model.endYExpected}
              x2={model.endX + 18}
              y2={model.endYExpected}
              stroke="var(--color-ink-faint)"
              strokeWidth="1"
            />
            <line
              x1={model.endX + 10}
              y1={model.endY}
              x2={model.endX + 18}
              y2={model.endY}
              stroke="var(--color-ink-faint)"
              strokeWidth="1"
            />
            <text
              x={model.endX + 22}
              y={(model.endY + model.endYExpected) / 2 + 4}
              fill="var(--color-ink-soft)"
              fontSize="12"
              fontFamily="var(--font-mono)"
            >
              {data.gap.display}
            </text>
          </g>
        </svg>

        <div className="money mt-2 flex justify-between text-[11px] text-[var(--color-ink-dim)]">
          <span>{shortDay(data.days[0].day)}</span>
          <span>
            {money(model.totalExpected)} expected · {money(model.totalReceived)} received
          </span>
          <span>{shortDay(data.days[data.days.length - 1].day)}</span>
        </div>
      </div>
    </section>
  );
}
