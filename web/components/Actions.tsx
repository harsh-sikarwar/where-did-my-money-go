"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type Actions as ActionsData } from "@/lib/api";

/**
 * Who to chase, for how much, and why.
 *
 * The verdict ends with "One thing needs you this week: those 6 customers" and until
 * now could not name them. This is the difference between an insight and a tool — and
 * the README argues against dashboards precisely because a merchant should be handed
 * the work rather than a chart of it. ADR-048.
 *
 * The CSV is not a nicety. The work leaving the screen is the point: a merchant sorts
 * it, forwards it, or hands it to whoever does the chasing.
 */
export function Actions({ batch }: { batch: string }) {
  const [data, setData] = useState<ActionsData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api
      .actions(batch)
      .then(setData)
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Could not load the list."),
      );
  }, [batch]);

  if (error) {
    return <p className="mb-14 text-sm text-[var(--color-attention)]">{error}</p>;
  }
  if (!data) return null;

  if (data.groups.length === 0) {
    return (
      <section className="mb-14">
        <h2 className="text-sm font-medium">Nothing needs you.</h2>
        <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
          Everything reconciles.
        </p>
      </section>
    );
  }

  return (
    <section className="mb-14">
      <div className="mb-6 flex items-baseline justify-between border-b border-[var(--color-line)] pb-2">
        <h2 className="text-sm font-medium">What needs you</h2>
        <a
          href={api.actionsCsvUrl(batch)}
          download
          className="text-xs text-[var(--color-ink-faint)] underline underline-offset-4"
        >
          download as CSV
        </a>
      </div>

      <p className="mb-8 text-sm text-[var(--color-ink-faint)]">
        {data.count} {data.count === 1 ? "item" : "items"} · {data.total.display}
      </p>

      <div className="space-y-10">
        {data.groups.map((group) => (
          <div key={group.classification}>
            <div className="mb-1 flex items-baseline gap-3">
              <span className="tnum text-sm">{group.total.display}</span>
              <span className="text-sm text-[var(--color-ink-soft)]">
                {group.count} {group.count === 1 ? "order" : "orders"}
              </span>
            </div>

            {/* The instruction, not the category name. */}
            <p className="mb-4 text-sm text-[var(--color-ink-soft)]">
              {group.next_step}
            </p>

            <div className="space-y-px">
              {group.items.map((item, i) => (
                <div
                  key={`${item.order_id ?? item.payment_id ?? "row"}-${i}`}
                  className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-[var(--color-line)] py-2"
                >
                  <span className="tnum w-24 shrink-0 text-right text-sm">
                    {item.amount.display}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm">
                    {/* Whoever to contact: a real email if the export had one, the
                        customer id otherwise. */}
                    {item.email ?? item.contact ?? item.customer_id ?? "—"}
                  </span>
                  {item.reason && (
                    <span className="font-mono text-xs text-[var(--color-ink-faint)]">
                      {item.reason}
                    </span>
                  )}
                  <span className="w-full font-mono text-xs text-[var(--color-ink-faint)] sm:w-auto">
                    {item.order_id ?? item.payment_id ?? ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
