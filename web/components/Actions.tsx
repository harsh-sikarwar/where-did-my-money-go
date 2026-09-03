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
        const top = [...d.groups].sort((a, b) => b.total.paise - a.total.paise)[0];
        if (top) setExpanded(new Set([top.classification]));
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Could not load the list."),
      );
  }, [batch]);

  const sorted = useMemo(
    () => (data ? [...data.groups].sort((a, b) => b.total.paise - a.total.paise) : []),
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

  const maxPaise = sorted[0]?.total.paise ?? 1;

  return (
    <section className="mt-14">
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-4">
        <Eyebrow>What needs you</Eyebrow>
        <a
          href={api.actionsCsvUrl(batch)}
          className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[var(--color-ink-soft)] transition-colors hover:text-[var(--color-ink)]"
        >
          <DownloadIcon size={13} /> Download as CSV
        </a>
      </div>

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
  // The biggest group is the urgent one by definition — it is what the merchant does
  // first. Everything below it still needs a decision, but not before that one.
  const severity: Severity = top ? "urgent" : "action";
  const tone = TONE[severity];

  return (
    <div
      className="mb-3 overflow-hidden rounded-2xl border transition-[border-color,background-color] duration-200"
      style={{
        borderColor: toneAlpha(severity, 0.28),
        background: toneAlpha(severity, 0.05),
      }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-4 p-5 text-left"
      >
        <span className="flex min-w-0 items-center gap-3">
          {top && (
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
                style={{ background: toneAlpha(severity, 0.14), color: tone }}
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
            width: `${(group.total.paise / maxPaise) * 100}%`,
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
              {group.items.map((item, i) => (
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

          {group.count > group.items.length && (
            <p className="tnum pt-3 text-[12.5px] text-[var(--color-ink-faint)]">
              Showing {group.items.length} of {group.count} — the CSV has all of them.
            </p>
          )}

          <div className="flex gap-2.5 pt-4 pb-1.5">
            <Button
              size="sm"
              style={{ background: tone, color: "var(--color-ground)" }}
              className="font-bold"
            >
              {group.next_step}
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

/** The engine sends a classification; make it a sentence a merchant would say. */
function labelFor(group: ActionGroup): string {
  return group.classification
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase());
}
