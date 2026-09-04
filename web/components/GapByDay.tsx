"use client";

import { useMemo, useState } from "react";
import { Eyebrow, TONE } from "@/components/ui";
import type { Timeline, TimelineDay } from "@/lib/api";

/**
 * The gap, spread over the days it happened on.
 *
 * The composition bar says WHAT explains the gap. This says WHEN — the question a
 * merchant asks next, because one bad Tuesday and a steady leak of the same size are
 * different problems and the composition bar cannot tell them apart.
 *
 * Two decisions worth keeping:
 *
 * Colour is not magnitude. The mockup coloured tall bars amber; this product reserves
 * amber for money that needs a decision, so a bar is amber because the engine marked
 * that day's money actionable, never because the bar is tall. A tall grey bar is a busy
 * day, not a problem. `--color-neutral` carries the benign days precisely because it
 * says nothing.
 *
 * Days that NARROW the gap are drawn benign and downward-facing in meaning but not in
 * geometry: their height is absolute value, since a chart with two directions at this
 * size reads as noise. The readout names the sign.
 */

/** A bar shorter than this is invisible; a day with money in it must be visible. */
const MIN_BAR_PCT = 6;

function toneFor(day: TimelineDay, peakDay: string | null): string {
  if (day.amount.paise < 0) return TONE.benign;
  if (day.actionable.paise !== 0) {
    return day.day === peakDay ? TONE.urgent : TONE.action;
  }
  return TONE.neutral;
}

/** "21 Aug" — short, because forty of these share one axis. */
export function shortDay(iso: string): string {
  const [, m, d] = iso.split("-");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(d)} ${months[Number(m) - 1]}`;
}

function useBars(data: Timeline) {
  return useMemo(() => {
    const max = Math.max(...data.days.map((d) => Math.abs(d.amount.paise)), 1);
    const peakDay = data.peak?.day ?? null;
    return data.days.map((day) => ({
      day,
      // A day with no gap is drawn as a baseline tick, not a short bar. At this width
      // a 3% bar reads as a small amount of something rather than as none of it.
      empty: day.amount.paise === 0,
      heightPct: Math.max(MIN_BAR_PCT, (Math.abs(day.amount.paise) / max) * 100),
      tone: toneFor(day, peakDay),
    }));
  }, [data]);
}

export function GapByDay({ data }: { data: Timeline }) {
  const bars = useBars(data);
  const [hover, setHover] = useState<number | null>(null);

  if (data.days.length < 2) return null;

  const hovered = hover === null ? null : bars[hover].day;
  const readout = hovered
    ? `${shortDay(hovered.day)} · ${hovered.amount.display}${
        hovered.orders ? ` · ${hovered.orders} order${hovered.orders === 1 ? "" : "s"}` : ""
      }`
    : data.peak
      ? `worst day ${data.peak.amount.display} on ${shortDay(data.peak.day)}`
      : "no single day dominates";

  const readoutTone = hovered
    ? toneFor(hovered, data.peak?.day ?? null)
    : "var(--color-ink-soft)";

  const first = data.days[0].day;
  const last = data.days[data.days.length - 1].day;
  const middle = data.days[Math.floor(data.days.length / 2)].day;

  return (
    <section
      className="mb-11 rounded-2xl border border-[var(--color-line)] bg-[var(--color-well)] px-6 pt-[22px] pb-[18px]"
      style={{ animation: "fadeUp 0.5s cubic-bezier(0.2,0.7,0.2,1) 0.32s both" }}
    >
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <h2 className="text-label text-[var(--color-ink-faint)]">Gap by day</h2>
        <div
          className="money text-[13px] transition-colors"
          style={{ color: readoutTone }}
          aria-live="polite"
        >
          {readout}
        </div>
      </div>

      <div
        className="flex h-[110px] items-end gap-[3px] sm:gap-1.5"
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={
          data.peak
            ? `Gap by day, ${shortDay(first)} to ${shortDay(last)}. Worst day ${data.peak.amount.display} on ${shortDay(data.peak.day)}.`
            : `Gap by day, ${shortDay(first)} to ${shortDay(last)}.`
        }
      >
        {bars.map((bar, i) => (
          <div
            key={bar.day.day}
            onMouseEnter={() => setHover(i)}
            title={`${shortDay(bar.day.day)} — ${bar.day.amount.display}`}
            className="min-w-0 flex-1 rounded-[3px] transition-[opacity,filter] duration-150"
            style={{
              height: bar.empty ? "2px" : `${bar.heightPct}%`,
              background: bar.empty ? "var(--color-line-strong)" : bar.tone,
              opacity: hover === null || hover === i ? 1 : 0.45,
              filter: hover === i ? "brightness(1.25)" : undefined,
              animation: `growY 0.55s cubic-bezier(0.2,0.7,0.2,1) ${0.35 + i * 0.015}s both`,
              transformOrigin: "bottom",
            }}
          />
        ))}
      </div>

      <div className="money mt-2.5 flex justify-between text-[11px] text-[var(--color-ink-dim)]">
        <span>{shortDay(first)}</span>
        <span>{shortDay(middle)}</span>
        <span>{shortDay(last)}</span>
      </div>

      {/*
        Money the engine could not pin to a day. Stated rather than folded into a bar:
        a chart that silently absorbs what it cannot place is the same defect as a
        summary line that disagrees with its own drill-down.
      */}
      {data.undated.paise !== 0 && (
        <p className="mt-3 text-[12px] text-[var(--color-ink-faint)]">
          <span className="money">{data.undated.display}</span> of the gap has no
          capture date behind it and is not shown above.
        </p>
      )}
    </section>
  );
}

/**
 * The landing card's version: same data, no chrome, no interaction. It is a preview of
 * the analysis screen, so it must not invent a shape the real chart does not have.
 */
export function GapSparkline({ data }: { data: Timeline }) {
  const bars = useBars(data);
  if (data.days.length < 2) return null;

  const first = data.days[0].day;
  const last = data.days[data.days.length - 1].day;

  return (
    <div className="flex flex-col gap-2.5">
      <div
        className="flex h-[120px] items-end gap-[3px]"
        role="img"
        aria-label={`Daily gap from ${shortDay(first)} to ${shortDay(last)}.`}
      >
        {bars.map((bar, i) => (
          <div
            key={bar.day.day}
            title={`${shortDay(bar.day.day)} — ${bar.day.amount.display}`}
            className="min-w-0 flex-1 rounded-[3px]"
            style={{
              height: bar.empty ? "2px" : `${bar.heightPct}%`,
              background: bar.empty ? "var(--color-line-strong)" : bar.tone,
              animation: `growY 0.55s cubic-bezier(0.2,0.7,0.2,1) ${0.35 + i * 0.015}s both`,
              transformOrigin: "bottom",
            }}
          />
        ))}
      </div>
      <div className="money flex justify-between text-[11px] text-[var(--color-ink-dim)]">
        <span>{shortDay(first)}</span>
        <span>daily gap</span>
        <span>{shortDay(last)}</span>
      </div>
    </div>
  );
}
