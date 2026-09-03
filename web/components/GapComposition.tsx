"use client";

import { type Severity, Swatch, TONE } from "@/components/ui";

/**
 * The gap, as one bar.
 *
 * A merchant's first question is not "what are the categories" but "how much of this
 * is a problem". A stacked bar answers that pre-attentively: the amber and red run is
 * either most of the bar or a sliver of it, and that reads before a single number is
 * parsed. The legend underneath then names the parts, in the same order, left to
 * right — so the eye can walk from a segment to its label without hunting.
 *
 * Segments are flex-weighted by paise, so widths are exact rather than rounded
 * percentages that fail to fill the track.
 */
export type GapSegment = {
  id: string;
  label: string;
  amount: string;
  paise: number;
  severity: Severity;
};

export function GapComposition({ segments }: { segments: GapSegment[] }) {
  const live = segments.filter((s) => s.paise > 0);
  if (live.length === 0) return null;

  const total = live.reduce((sum, s) => sum + s.paise, 0);

  return (
    <section className="mb-10" aria-label="What the gap is made of">
      <div className="flex h-3 gap-[3px] overflow-hidden rounded-full">
        {live.map((s, i) => (
          <div
            key={s.id}
            title={`${s.label} — ${s.amount}`}
            className="origin-left"
            style={{
              flex: s.paise,
              background: TONE[s.severity],
              animation: `growX 0.7s cubic-bezier(0.2,0.7,0.2,1) ${0.28 + i * 0.07}s both`,
            }}
          />
        ))}
      </div>

      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
        {live.map((s) => (
          <li
            key={s.id}
            className="flex items-center gap-2 text-xs text-[var(--color-ink-soft)]"
          >
            <Swatch severity={s.severity} />
            {s.label}
            <span className="money text-[var(--color-ink)]">{s.amount}</span>
            <span className="sr-only">
              , {Math.round((s.paise / total) * 100)} percent of the gap
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
