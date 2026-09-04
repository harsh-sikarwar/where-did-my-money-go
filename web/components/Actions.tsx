"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Button,
  DownloadIcon,
  Eyebrow,
  type Severity,
  TONE,
  toneAlpha,
} from "@/components/ui";
import { api, ApiError, type ActionGroup, type Actions as ActionsData } from "@/lib/api";

/**
 * Who to chase, for how much, and why.
 *
 * The verdict ends with "one thing needs you this week" and until now could not name
 * them. This is the difference between an insight and a tool — and the README argues
 * against dashboards precisely because a merchant should be handed the work rather
 * than a chart of it. ADR-048.
 *
 * Priority is money, not the order the engine happened to emit groups in: sorted by
 * total impact descending, with the single largest group open, badged TOP, and given
 * the one repeating animation in the product. Everything else collapses to a summary
 * row. A merchant with 29 items across 6 reasons should read "which one first" in the
 * first two seconds.
 *
 * The CSV is not a nicety. The work leaving the screen is the point: a merchant sorts
 * it, forwards it, or hands it to whoever does the chasing.
 */
/** How many rows one group unrolls inline before deferring to the CSV. */
const ROW_LIMIT = 12;

export function Actions({ batch }: { batch: string }) {
  const [data, setData] = useState<ActionsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    setData(null);
    setError(null);
    setExpanded(new Set());
    api
      .actions(batch)
      .then((d) => {
        setData(d);
        const top = [...d.groups].sort(
          (a, b) => Math.abs(b.total.paise) - Math.abs(a.total.paise),
        )[0];
        if (top) setExpanded(new Set([top.classification]));
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Could not load the list."),
      );
  }, [batch]);

  // Sorted by SIZE, not signed value. A negative component (a refund Razorpay paid
  // out anyway) is not the smallest thing on the list — it is an ₹18,988 discrepancy
  // that happens to point the other way, and signed sorting buried it at the bottom
  // under items a hundredth its size.
  const sorted = useMemo(
    () =>
      data
        ? [...data.groups].sort(
            (a, b) => Math.abs(b.total.paise) - Math.abs(a.total.paise),
          )
        : [],
    [data],
  );

  if (error) {
    return <p className="mb-14 text-sm font-medium text-[var(--color-urgent)]">{error}</p>;
  }
  if (!data) return null;

  if (data.groups.length === 0) {
    return (
      <section className="mt-14">
        <Eyebrow className="mb-5">What needs you</Eyebrow>
        <p className="text-body text-[var(--color-ink-soft)]">
          Nothing needs chasing this cycle — every rupee of the gap is explained.
        </p>
      </section>
    );
  }

  const maxPaise = Math.abs(sorted[0]?.total.paise ?? 1) || 1;

  // The chase figure counts only groups that ADD to the gap. Summing every group (what
  // `data.total` does) nets an ₹18,988 refund offset against real recoverable money and
  // reports a smaller number than the verdict's actionable total for the same batch.
  // Both figures come from the engine (`chase_total`, `chase_count`) rather than being
  // summed here — ADR-001 keeps every money value, and its formatting, upstream.
  const offsetCount = sorted.filter((g) => g.total.paise < 0).length;

  return (
    <section className="mt-14">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-4">
        <Eyebrow>What needs you</Eyebrow>
        <a
          href={api.actionsCsvUrl(batch)}
          className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[var(--color-ink-soft)] transition-colors hover:text-[var(--color-ink)]"
        >
          <DownloadIcon size={13} /> Download as CSV
        </a>
      </div>

      {/* What the list adds up to, said once, before the rows. The engine's own
          `total` is the signed sum across every group — including the offsets, which
          are not money to chase — so stating the chase figure separately is the only
          way this line and the cards below can agree. */}
      <p className="mb-5 text-[13px] leading-relaxed text-[var(--color-ink-soft)]">
        <span className="money font-bold text-[var(--color-ink)]">
          {data.chase_total.display}
        </span>{" "}
        across {data.chase_count}{" "}
        {data.chase_count === 1 ? "order" : "orders"} to chase
        {offsetCount > 0 && (
          <span className="text-[var(--color-ink-faint)]">
            {" "}
            · {offsetCount} {offsetCount === 1 ? "line" : "lines"} below offset the gap
            rather than adding to it
          </span>
        )}
      </p>

      {sorted.map((group, i) => (
        <Group
          key={group.classification}
          group={group}
          top={i === 0}
          maxPaise={maxPaise}
          open={expanded.has(group.classification)}
          onToggle={() =>
            setExpanded((prev) => {
              const next = new Set(prev);
              if (next.has(group.classification)) next.delete(group.classification);
              else next.add(group.classification);
              return next;
            })
          }
        />
      ))}
    </section>
  );
}

function Group({
  group,
  top,
  maxPaise,
  open,
  onToggle,
}: {
  group: ActionGroup;
  top: boolean;
  maxPaise: number;
  open: boolean;
  onToggle: () => void;
}) {
  // A component can be negative: money that arrived which the books did not expect.
  // It is a real discrepancy worth reconciling, but it is not money to CHASE, so it
  // never wears the urgent tone or the ringing TOP badge even when it is the largest
  // single line — "recover this" and "explain this" are different instructions.
  const offset = group.total.paise < 0;
  const severity: Severity = offset ? "neutral" : top ? "urgent" : "action";
  const tone = offset ? "var(--color-ink-soft)" : TONE[severity];
  // Widths are drawn from magnitude; a negative width renders nothing at all.
  const width = Math.min(Math.abs(group.total.paise) / maxPaise, 1) * 100;
  // A ledger uploaded without its settlement file classifies every order MISSING, so
  // one group can hold every row in the batch — 200 table rows unrolled inside an
  // accordion nobody asked to open that far. The engine sorts items largest-first, so
  // the head of the list is the part worth acting on; the CSV remains the full record.
  const shown = group.items.slice(0, ROW_LIMIT);

  return (
    <div
      className="mb-3 overflow-hidden rounded-2xl border transition-[border-color,background-color] duration-200"
      style={{
        borderColor: offset ? "var(--color-line)" : toneAlpha(severity, 0.28),
        background: offset ? "transparent" : toneAlpha(severity, 0.05),
      }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-4 p-5 text-left"
      >
        <span className="flex min-w-0 items-center gap-3">
          {top && !offset && (
            <span
              className="shrink-0 rounded-[5px] px-[7px] py-[3px] text-[10.5px] font-extrabold tracking-[0.06em] text-[var(--color-ground)]"
              style={{ background: tone, animation: "ring 2.6s ease-out infinite" }}
            >
              TOP
            </span>
          )}
          <span className="flex min-w-0 flex-col gap-[7px]">
            <span className="text-[15px] leading-snug font-bold">
              {labelFor(group)}
            </span>
            <span className="flex flex-wrap items-center gap-2.5">
              <span
                className="rounded-full px-2.5 py-[3px] text-[11.5px] font-bold whitespace-nowrap"
                style={{
                  background: offset
                    ? "oklch(1 0 0 / 0.08)"
                    : toneAlpha(severity, 0.14),
                  color: tone,
                }}
              >
                {group.count} {group.count === 1 ? "order" : "orders"}
              </span>
              <span className="text-[13px] text-[var(--color-ink-faint)]">
                {group.next_step}
              </span>
            </span>
          </span>
        </span>

        <span
          className="money shrink-0 text-base font-bold"
          style={{ color: tone }}
        >
          {group.total.display}
        </span>
      </button>

      {/* A full-bleed bar at the card's foot: this group's weight against the largest
          one, readable without opening anything. */}
      <div className="h-[3px] bg-[oklch(1_0_0/0.05)]">
        <div
          className="h-full origin-left"
          style={{
            width: `${width}%`,
            background: tone,
            animation: "growX 0.8s cubic-bezier(0.2,0.7,0.2,1) 0.2s both",
          }}
        />
      </div>

      {open && (
        <div className="fade border-t border-[var(--color-line)] px-5 pt-2 pb-3">
          <table className="w-full border-collapse">
            <caption className="sr-only">
              {labelFor(group)} — {group.count} orders totalling {group.total.display}
            </caption>
            <tbody>
              {shown.map((item, i) => (
                <tr
                  key={`${item.order_id ?? "row"}-${i}`}
                  className="border-b border-[oklch(1_0_0/0.06)] transition-colors hover:bg-[oklch(1_0_0/0.03)]"
                >
                  <td className="money w-[90px] py-2.5 text-[12.5px] font-bold">
                    {item.amount.display}
                  </td>
                  <td className="money py-2.5 pr-3 text-[12.5px] text-[var(--color-ink-soft)]">
                    {item.email ?? item.customer_id ?? "—"}
                  </td>
                  <td
                    className="money py-2.5 pr-3 text-[12.5px]"
                    style={{ color: "var(--color-accent)" }}
                  >
                    {item.reason ?? group.classification}
                  </td>
                  <td className="money py-2.5 text-right text-[12.5px] text-[var(--color-ink-faint)]">
                    {item.order_id ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {group.count > shown.length && (
            <p className="tnum pt-3 text-[12.5px] text-[var(--color-ink-faint)]">
              Showing the {shown.length} largest of {group.count} — the CSV has all of
              them.
            </p>
          )}

          <div className="flex gap-2.5 pt-4 pb-1.5">
            <Button
              size="sm"
              style={{ background: tone, color: "var(--color-ground)" }}
              className="font-bold"
            >
              {ctaFor(group)}
            </Button>
            <Button size="sm" variant="secondary">
              Mark reviewed
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * The engine sends a classification; make it a phrase a merchant would say.
 *
 * The fallback (de-underscore, capitalise) produced "Halted subscription" and
 * "Unrecorded refund" — the schema's names, not the merchant's. The verdict screen
 * already says "subscriptions died silently" for the same rows, and two names for one
 * thing on one page reads as two different findings.
 */
const LABELS: Record<string, string> = {
  HALTED_SUBSCRIPTION: "Subscriptions that died silently",
  PAYMENT_FAILED: "Payments that failed",
  ON_HOLD: "Held by Razorpay — not on its way",
  DISPUTED: "Disputed by the customer — you have a deadline",
  REFUND: "Refunds you recorded that Razorpay paid out anyway",
  UNRECORDED_REFUND: "Refunds Razorpay paid out that you never recorded",
  MISSING: "No record at Razorpay at all",
  UNEXPECTED_SETTLEMENT: "Settled, but not in your ledger",
  NEEDS_REVIEW: "More than one explanation fits",
  DUPLICATE: "The same order twice in your ledger",
  UNEXPLAINED: "We could not account for this",
};

function labelFor(group: ActionGroup): string {
  return (
    LABELS[group.classification] ??
    group.classification.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
  );
}

/**
 * The button is a commitment, not a restatement. `next_step` is a full instruction
 * ("Email these customers a new payment link. Razorpay stopped attempting charges and
 * will not restart on its own.") and is already printed above the fold of the card —
 * setting it again as a button label gave a two-sentence paragraph a rounded
 * background and made the control impossible to scan.
 */
const CTA: Record<string, string> = {
  HALTED_SUBSCRIPTION: "Send payment links",
  PAYMENT_FAILED: "Retry these payments",
  ON_HOLD: "Open Razorpay dashboard",
  DISPUTED: "Submit evidence",
  REFUND: "Check refund records",
  UNRECORDED_REFUND: "Correct the books",
};

function ctaFor(group: ActionGroup): string {
  return CTA[group.classification] ?? "Start on these";
}
