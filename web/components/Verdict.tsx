"use client";

import { useState } from "react";
import { GapComposition, type GapSegment } from "@/components/GapComposition";
import {
  Dot,
  Eyebrow,
  type Severity,
  severityOf,
  ShareBar,
  TONE,
  toneAlpha,
} from "@/components/ui";
import type { Verdict as VerdictData, VerdictLine } from "@/lib/api";

/**
 * The default screen: three figures, a bar, four lines and a verdict. Deliberately
 * NOT a dashboard.
 *
 * Hyperswitch and Cointab build for a finance operator who lives in the tool. This is
 * for a merchant who opens it for two minutes on Monday. The depth exists (one click
 * down) which is what proves the simplicity is a choice rather than a limitation.
 *
 * Hierarchy is weight before size: Expected and Received are set at 300 so the Gap's
 * 700 reads as the answer rather than merely the biggest number.
 */
export function Verdict({ data }: { data: VerdictData }) {
  const benign = data.lines.filter((l) => !l.actionable);
  const actionable = data.lines.filter((l) => l.actionable);
  const gapPaise = data.gap.paise;

  const segments: GapSegment[] = [
    ...data.lines.map((line) => ({
      id: line.classification,
      label: line.label,
      amount: line.amount.display,
      paise: line.amount.paise,
      severity: severityOf(line),
    })),
    {
      id: "__unexplained",
      label: "Unexplained",
      amount: data.unexplained.display,
      paise: data.unexplained.paise,
      severity: "neutral" as const,
    },
  ];

  return (
    <>
      {/* The three numbers that frame everything else. Gap is the hero — it is the
          question the whole page exists to answer. */}
      <section className="mb-7 grid grid-cols-2 items-end gap-5 sm:grid-cols-[1fr_1fr_1.3fr]">
        <Figure label="Expected" value={data.expected.display} delay={0.05} />
        <Figure label="Received" value={data.received.display} delay={0.12} />
        <Figure
          label="Gap"
          value={data.gap.display}
          share={shareOfExpected(data)}
          loud
          delay={0.19}
        />
      </section>

      <GapComposition segments={segments} />

      {/* Benign first — the eye should land on "mostly fine" — then what needs a
          decision, which is washed in its severity so scanning slows down there. */}
      <section aria-label="What explains the gap">
        {[...benign, ...actionable].map((line, i) => (
          <Line key={line.classification} line={line} gapPaise={gapPaise} index={i} />
        ))}

        <div className="flex items-center justify-between gap-4 p-4">
          <div>
            <div className="text-[14.5px] italic text-[var(--color-ink-soft)]">
              Unexplained
            </div>
            <div className="mt-1 text-[12.5px] text-[var(--color-ink-faint)]">
              nothing in the data accounts for this
            </div>
          </div>
          <div className="money text-[15.5px] text-[var(--color-ink-soft)]">
            {data.unexplained.display}
          </div>
        </div>

        {/*
          These lines sum to the gap exactly, and the engine asserts it on every run.
          Showing the total is not decoration — it is the claim, and it was wrong once.
        */}
        <div className="mt-1.5 flex items-center justify-between gap-4 border-t border-[var(--color-line-strong)] px-4 pt-[18px]">
          <span className="text-[13.5px] font-semibold text-[var(--color-ink-soft)]">
            Total accounted — sums to the gap exactly
          </span>
          <span className="money text-base font-bold">{data.gap.display}</span>
        </div>
      </section>

      {/* The verdict. One thing, not a list — if everything is urgent, nothing is. */}
      <section
        className="mt-11 flex items-start gap-4 rounded-r-xl border-l-4 bg-[var(--color-raised)] px-6 py-[22px]"
        style={{ borderLeftColor: "var(--color-action)" }}
      >
        <span
          aria-hidden
          className="mt-0.5 flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full text-sm font-extrabold"
          style={{
            background: toneAlpha("action", 0.16),
            color: "var(--color-action)",
          }}
        >
          !
        </span>
        <p className="text-base leading-relaxed font-semibold text-pretty">
          {data.headline}
        </p>
      </section>

      <Provenance data={data} />
    </>
  );
}

/** Gap as a share of expected — the number that says whether 16,040 is a lot. */
function shareOfExpected(data: VerdictData): string | null {
  if (data.expected.paise <= 0) return null;
  const pct = (data.gap.paise / data.expected.paise) * 100;
  return `${pct < 0.01 ? "<0.01" : pct.toFixed(2)}% of expected`;
}

function Figure({
  label,
  value,
  share,
  loud,
  delay,
}: {
  label: string;
  value: string;
  share?: string | null;
  loud?: boolean;
  delay: number;
}) {
  return (
    <div style={{ animation: `fadeUp 0.5s cubic-bezier(0.2,0.7,0.2,1) ${delay}s both` }}>
      <Eyebrow className="mb-2.5">{label}</Eyebrow>
      <div className={loud ? "figure-loud" : "figure-quiet"}>{value}</div>
      {share && (
        <div
          className="mt-2.5 inline-flex items-center rounded-full px-2.5 py-1 text-[11.5px] font-bold"
          style={{
            background: toneAlpha("action", 0.12),
            color: "var(--color-action)",
          }}
        >
          {share}
        </div>
      )}
    </div>
  );
}

/**
 * One explanation of the gap. Collapsed it is a scannable row; expanded it gives the
 * engine's own explanation. Severity is encoded three ways at once — wash, dot, and
 * bar width — so urgency survives both a quick scan and a colourblind reader.
 */
function Line({
  line,
  gapPaise,
  index,
}: {
  line: VerdictLine;
  gapPaise: number;
  index: number;
}) {
  const [open, setOpen] = useState(false);
  const severity: Severity = severityOf(line);
  const flagged = line.actionable;
  const share = gapPaise > 0 ? line.amount.paise / gapPaise : 0;

  return (
    <div
      className="mb-1.5 overflow-hidden rounded-xl border transition-[background-color,border-color] duration-200"
      style={{
        background: flagged ? toneAlpha(severity, 0.07) : "transparent",
        borderColor: flagged ? toneAlpha(severity, 0.28) : "transparent",
        animation: `fadeUp 0.45s cubic-bezier(0.2,0.7,0.2,1) ${0.36 + index * 0.05}s both`,
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-4 p-4 text-left"
      >
        <span className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden
            className="inline-block h-1.5 w-1.5 shrink-0 border-r-2 border-b-2 border-[var(--color-ink-faint)] transition-transform duration-200"
            style={{ transform: open ? "rotate(225deg)" : "rotate(-45deg)" }}
          />
          <span className="flex min-w-0 flex-col gap-1.5">
            <span
              className={`flex items-center gap-2.5 text-[14.5px] leading-snug ${
                flagged ? "font-bold" : "font-normal"
              }`}
            >
              <Dot severity={flagged ? severity : "neutral"} />
              {line.label}
            </span>
            <span className="text-[12.5px] text-[var(--color-ink-faint)]">
              {line.count} {line.count === 1 ? "order" : "orders"} ·{" "}
              {Math.round(share * 100)}% of gap
            </span>
          </span>
        </span>

        <span className="flex shrink-0 items-center gap-3.5">
          <ShareBar
            fraction={share}
            severity={flagged ? severity : "neutral"}
            delay={0.5 + index * 0.06}
            className="w-[74px]"
          />
          <span
            className={`money min-w-[74px] text-right text-[15.5px] ${
              flagged ? "font-bold" : ""
            }`}
            style={{ color: flagged ? TONE[severity] : "var(--color-ink)" }}
          >
            {line.amount.display}
          </span>
        </span>
      </button>

      {open && (
        <div className="fade pt-0 pr-4 pb-5 pl-[42px]">
          <p className="max-w-[52ch] text-[13.5px] leading-relaxed text-pretty text-[var(--color-ink-soft)]">
            {line.explanation}
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * The receipt. Every order reached the engine, and the run was fast — both are claims
 * this line has to be able to back, so it reports the engine's own counters.
 */
function Provenance({ data }: { data: VerdictData }) {
  const { pass1 } = data.match;
  const { rows_processed, elapsed_seconds } = data.performance;

  return (
    <p className="tnum mt-14 text-center text-[12.5px] text-[var(--color-ink-dim)]">
      {pass1.matched.toLocaleString("en-IN")} / {pass1.total.toLocaleString("en-IN")}{" "}
      orders reached Razorpay · {rows_processed.toLocaleString("en-IN")} rows processed
      in {Math.round(elapsed_seconds * 1000)}ms
    </p>
  );
}
