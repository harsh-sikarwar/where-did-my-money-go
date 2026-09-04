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
 *
 * NEGATIVE COMPONENTS. Some components are genuinely negative — a refund the merchant
 * recorded but Razorpay paid out anyway means the bank got MORE than the books
 * expected, and that line offsets the gap rather than adding to it. A stacked bar
 * cannot draw a negative width, so these are shown as a legend entry beneath the
 * track instead of being dropped. Dropping them (the original behaviour) was a
 * correctness bug, not a layout simplification: the remaining segments were then
 * weighted against a total larger than the gap, so every percentage the bar implied
 * was overstated, and money the merchant is owed an explanation for vanished from the
 * one picture that claims to show what the gap is made of.
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
  const offsets = segments.filter((s) => s.paise < 0);
  if (live.length === 0 && offsets.length === 0) return null;

  // The denominator for the share a segment is announced as. It is the sum of the
  // POSITIVE parts, which is what the bar actually draws — so the percentages a
  // screen reader hears match the widths a sighted reader sees.
  const drawn = live.reduce((sum, s) => sum + s.paise, 0);

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
            {/* "of the bar", not "of the gap" — the denominator here is the sum of the
                POSITIVE parts, which is what the track actually draws. The rows below
                announce share of NET gap, and the two legitimately differ whenever an
                offset line is present. Naming the denominator in the text is what keeps
                a screen-reader user from hearing two different percentages for one line
                and concluding one of them is wrong. F9. */}
            <span className="sr-only">
              , {Math.round((s.paise / drawn) * 100)} percent of the bar
            </span>
          </li>
        ))}
      </ul>

      {/* Offsets sit below the track with an explicit minus glyph, because a bar
          cannot draw them and silence about money is the one thing this screen
          may never do. */}
      {offsets.length > 0 && (
        <ul className="mt-2.5 flex flex-wrap gap-x-5 gap-y-2">
          {offsets.map((s) => (
            <li
              key={s.id}
              className="flex items-center gap-2 text-xs text-[var(--color-ink-faint)]"
            >
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-[2px] border border-dashed border-[var(--color-ink-faint)]"
              />
              {s.label}
              <span className="money text-[var(--color-ink-soft)]">{s.amount}</span>
              <span className="text-[var(--color-ink-faint)]">
                offsets the gap
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
