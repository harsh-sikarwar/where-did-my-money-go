"use client";

import { useState } from "react";
import { GapByDay } from "@/components/GapByDay";
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
import type {
  Timeline as TimelineData,
  Verdict as VerdictData,
  VerdictLine,
} from "@/lib/api";

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
export function Verdict({
  data,
  timeline = null,
}: {
  data: VerdictData;
  timeline?: TimelineData | null;
}) {
  const benign = data.lines.filter((l) => !l.actionable);
  const actionable = data.lines.filter((l) => l.actionable);
  const gapPaise = data.gap.paise;
  const unexplainedPaise = data.unexplained.paise;

  // The bar is the LINES, and only the lines. `unexplained` used to be appended as a
  // segment, which was harmless while it was the decomposition residual — structurally
  // always zero, so it drew nothing. It is now the correlation residual: money that is
  // already inside the lines above and could not be attributed to a cause. Adding it
  // here would draw the same rupees twice and the bar would no longer be the gap.
  const segments: GapSegment[] = data.lines.map((line) => ({
    id: line.classification,
    label: line.label,
    amount: line.amount.display,
    paise: line.amount.paise,
    severity: severityOf(line),
  }));

  // The settlement file is what a ledger is reconciled AGAINST. Without it every order
  // is unmatched by construction, so the page reports a 100% gap and "0 of N orders
  // reached Razorpay" — both true of the upload, neither true of the merchant's money.
  const cannotReconcile = data.missing_sources.includes("recon");

  return (
    <>
      {data.missing_note && (
        <section
          aria-label="What this run could not see"
          className="mb-7 rounded-xl border px-5 py-4"
          style={{
            borderColor: cannotReconcile
              ? toneAlpha("urgent", 0.35)
              : "var(--color-line)",
            background: cannotReconcile
              ? toneAlpha("urgent", 0.06)
              : "transparent",
          }}
        >
          <div className="text-[14.5px] font-bold">
            {cannotReconcile
              ? "This run had nothing to reconcile against"
              : `Reconciled without ${data.missing_sources.length} of the five files`}
          </div>
          <p className="mt-1.5 max-w-[62ch] text-[12.5px] leading-relaxed text-[var(--color-ink-soft)]">
            {data.missing_note}
          </p>
          <p className="mt-2 text-[12px] text-[var(--color-ink-faint)]">
            Missing: {data.missing_sources.join(", ")}
          </p>
        </section>
      )}

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

      {/* WHAT explains the gap is above; WHEN it happened is here. Between the two
          because a merchant reads the composition, then asks when — and the line
          items below answer neither question. */}
      {timeline && <GapByDay data={timeline} />}

      {data.late && <LatePayouts late={data.late} />}

      {/* Benign first — the eye should land on "mostly fine" — then what needs a
          decision, which is washed in its severity so scanning slows down there. */}
      <section aria-label="What explains the gap">
        {[...benign, ...actionable].map((line, i) => (
          <Line key={line.classification} line={line} gapPaise={gapPaise} index={i} />
        ))}

        {/* The honest residual: money that IS in the lines above but which no rule
            could attribute to a cause, after the payments and subscriptions files were
            brought in. It used to show the decomposition residual instead — a figure
            that cannot be non-zero, since the components are built to close the gap —
            so it read ₹0.00 on every run ever made while the correlation section
            further down this page named real money outstanding. F2. */}
        <div className="flex items-center justify-between gap-4 p-4">
          <div>
            <div
              className="text-[14.5px] italic"
              style={{
                color: unexplainedPaise
                  ? "var(--color-ink)"
                  : "var(--color-ink-soft)",
              }}
            >
              Still unexplained
            </div>
            <div className="mt-1 text-[12.5px] text-[var(--color-ink-faint)]">
              {unexplainedPaise
                ? `${data.unexplained_count} ${
                    data.unexplained_count === 1 ? "order" : "orders"
                  } no rule could account for — already counted above`
                : "every rupee above has a cause behind it"}
            </div>
          </div>
          <div
            className="money text-[15.5px]"
            style={{
              color: unexplainedPaise ? TONE.action : "var(--color-ink-soft)",
            }}
          >
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
        <div className="min-w-0">
          <p className="text-base leading-relaxed font-semibold text-pretty">
            {data.headline}
          </p>

          {/*
            The summary sits UNDER the headline, never replacing it. The headline is
            engine output and always correct; this paragraph is prose that may have been
            written by a model, and the ordering says which one to trust if they ever
            read differently. It carries no figures at all — the engine strips any the
            model emits — so nothing here can contradict the numbers above.
          */}
          {data.summary ? (
            <p className="mt-2.5 text-[14.5px] leading-relaxed text-[var(--color-ink-soft)] text-pretty">
              {data.summary}
            </p>
          ) : null}

          {/*
            Attribution, not a badge. A merchant deciding how much to trust a sentence
            deserves to know a model wrote it, and the same honesty that put "Not built"
            in the README applies to the thing that replaced it.
          */}
          {data.summary && data.summary_source === "model" ? (
            <p className="mt-2 text-[12px] font-medium tracking-wide text-[var(--color-ink-faint)]">
              Summary written by a language model. Every figure on this page is computed
              by the engine.
            </p>
          ) : null}
        </div>
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
              {/* Share of the NET gap — the honest denominator, since a refund line
                  legitimately goes negative and narrows it. The bar's legend uses the
                  positive-parts sum instead, because that is what the track draws; both
                  now name their denominator rather than both saying "%". F9. */}
              {Math.round(share * 100)}% of the gap
              {/* The row stays benign — the fee itself is the contracted cost of
                  taking payments and there is nothing to chase. But an actionable
                  overcharge hiding inside a collapsed benign row is the same defect
                  in a quieter form, so the row says it is in there. */}
              {line.note?.actionable && (
                <>
                  {" · "}
                  <span style={{ color: TONE.action }} className="font-bold">
                    {line.note.amount.display} above your rate
                  </span>
                </>
              )}
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

          {/* A figure about the line, not another line. The fee overcharge is a subset
              of the fee above it, so it is set inside the row rather than beside it —
              putting it in the waterfall would double-count money and imply the two
              amounts add up. It carries its own tone because it is the actionable half
              of an otherwise benign line: the fee is the cost of doing business, the
              overcharge is the part you can dispute. F3. */}
          {line.note && (
            <div
              className="mt-3.5 max-w-[52ch] rounded-xl border px-3.5 py-3"
              style={{
                borderColor: line.note.actionable
                  ? toneAlpha("action", 0.3)
                  : "var(--color-line)",
                background: line.note.actionable
                  ? toneAlpha("action", 0.06)
                  : "transparent",
              }}
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] leading-snug font-bold">
                  {line.note.count}{" "}
                  {line.note.count === 1 ? "order" : "orders"} {line.note.label}
                </span>
                <span
                  className="money shrink-0 text-[14px] font-bold"
                  style={{
                    color: line.note.actionable
                      ? TONE.action
                      : "var(--color-ink)",
                  }}
                >
                  {line.note.amount.display}
                </span>
              </div>
              <p className="mt-1.5 text-[12.5px] leading-relaxed text-[var(--color-ink-faint)]">
                {line.note.explanation}
              </p>
            </div>
          )}
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

/**
 * Payouts that arrived, later than the cycle promised.
 *
 * Beside the waterfall, deliberately never in it. This money HAS arrived, so it is
 * already inside `received` and contributes nothing to the gap — putting it in the
 * composition would double-count the exact rupees `gap.py` was written to stop
 * double-counting. That is why it had no line, and why 213 detected late payouts on a
 * 2,500-order run were never mentioned anywhere in the product. F4.
 *
 * Zero gap impact is not zero information: a merchant financing operations on money
 * that lands two days after it was promised has a working-capital problem, whether or
 * not it nets to zero by the end of the cycle. So it gets a panel that states the
 * count, the value delayed and how late, and says plainly that it is not part of the
 * gap — rather than a line implying it is.
 */
function LatePayouts({
  late,
}: {
  late: NonNullable<VerdictData["late"]>;
}) {
  return (
    <section
      aria-label="Payouts that arrived late"
      className="mb-9 rounded-xl border border-[var(--color-line)] px-5 py-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1.5">
        <span className="text-[14.5px] font-bold">
          {late.count} {late.count === 1 ? "payout" : "payouts"} arrived late
        </span>
        <span className="money text-[15.5px] font-bold">{late.value.display}</span>
      </div>
      <p className="mt-1.5 max-w-[56ch] text-[12.5px] leading-relaxed text-[var(--color-ink-faint)]">
        Typically {late.median_days_late}{" "}
        {late.median_days_late === 1 ? "working day" : "working days"} past the
        {late.cycle_days ? ` T+${late.cycle_days} ` : " "}cycle
        {late.max_days_late > late.median_days_late &&
          `, at worst ${late.max_days_late}`}
        . This money arrived, so it is not part of the gap above — but it was money you
        could not use when you expected to.
      </p>
    </section>
  );
}
