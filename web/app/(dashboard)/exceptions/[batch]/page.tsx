"use client";

/**
 * Exceptions — every order the engine could not close on its own, flattened
 * out of `api.actions(batch).groups[].items[]` (both the "chase" groups and
 * the offsetting ones; see the doc comment on `Actions.chase_total` in
 * `lib/api.ts` for why those are not the same number).
 *
 * The mockup's table also has Ledger/Settled/Diff/Age/Status columns and a
 * bulk-action bar (Mark resolved / Assign to payouts / Mark as noise). None
 * of that exists on `ActionItem` or in the backend — there is no persisted
 * resolution workflow and no per-item ledger/settled pair, only a single
 * signed amount. Rather than invent numbers or wire buttons to nothing, this
 * screen drops those columns and that bar entirely and keeps only what's
 * real: order, cause, amount, and the two links that actually do something
 * (CSV export, Copilot).
 */

import Link from "next/link";
import { use, useEffect, useMemo, useState } from "react";
import { DashCard } from "@/components/dash/primitives";
import { actionSeverity, labelForClassification } from "@/components/dash/action-labels";
import { useCurrentBatch } from "@/lib/current-batch";
import { api, ApiError, type Actions } from "@/lib/api";

type Row = {
  key: string;
  orderId: string;
  customer: string | null;
  classification: string;
  cause: string;
  detail: string;
  amountDisplay: string;
  paise: number;
  offset: boolean;
};

/** How many distinct classifications get their own filter pill before the
 *  rest fold into "All" — the mockup shows four; this picks the four with
 *  the most orders behind them rather than hardcoding names a given batch
 *  might not have. */
const MAX_CLASS_FILTERS = 4;

export default function ExceptionsPage({
  params,
}: {
  params: Promise<{ batch: string }>;
}) {
  const { batch } = use(params);
  const { setBatch } = useCurrentBatch();
  const [data, setData] = useState<Actions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

  useEffect(() => {
    setBatch(batch);
  }, [batch, setBatch]);

  useEffect(() => {
    setData(null);
    setError(null);
    setFilter("all");
    api
      .actions(batch)
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load exceptions."));
  }, [batch]);

  const { rows, skippedCount } = useMemo(() => {
    if (!data) return { rows: [] as Row[], skippedCount: 0 };
    const out: Row[] = [];
    let skipped = 0;
    for (const g of data.groups) {
      const offset = g.total.paise < 0;
      for (const it of g.items) {
        if (!it.order_id) {
          // Some findings — an unrecorded refund with no matching ledger
          // row, say — have no order id at all. Nothing to link to, so
          // they don't belong in a queue whose whole point is "click to
          // open the order."
          skipped += 1;
          continue;
        }
        out.push({
          key: `${g.classification}-${it.order_id}-${it.payment_id ?? out.length}`,
          orderId: it.order_id,
          customer: it.email ?? it.customer_id ?? it.contact,
          classification: g.classification,
          cause: labelForClassification(g.classification),
          detail: it.reason ?? it.detail ?? g.next_step,
          amountDisplay: it.amount.display,
          paise: it.amount.paise,
          offset,
        });
      }
    }
    out.sort((a, b) => Math.abs(b.paise) - Math.abs(a.paise));
    return { rows: out, skippedCount: skipped };
  }, [data]);

  const filters = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of rows) counts.set(r.classification, (counts.get(r.classification) ?? 0) + 1);
    const top = [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, MAX_CLASS_FILTERS)
      .map(([classification, count]) => ({
        key: classification,
        label: labelForClassification(classification),
        count,
      }));
    return [{ key: "all", label: "All", count: rows.length }, ...top];
  }, [rows]);

  const filtered = filter === "all" ? rows : rows.filter((r) => r.classification === filter);

  if (error) {
    return (
      <div style={{ maxWidth: 640 }}>
        <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 32, fontWeight: 400, margin: "0 0 10px" }}>
          Can&apos;t load exceptions
        </h1>
        <p style={{ color: "var(--dash-ink-soft)", fontSize: 14 }}>{error}</p>
      </div>
    );
  }

  if (!data) {
    return <div style={{ color: "var(--dash-ink-faint)", fontSize: 13 }}>Loading exceptions…</div>;
  }

  return (
    <div style={{ maxWidth: 1180, animation: "fadeUp .45s cubic-bezier(.2,.7,.2,1) both" }}>
      <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.012em", margin: "0 0 8px" }}>
        Exception queue
      </h1>
      <p style={{ fontSize: 14, color: "var(--dash-ink-soft)", margin: "0 0 28px" }}>
        {rows.length === 0
          ? "Nothing needs a decision — every order this cycle closed on its own."
          : `The ${rows.length} order${rows.length === 1 ? "" : "s"} the engine could not close on its own — sorted by size.`}
        {skippedCount > 0 && (
          <span style={{ color: "var(--dash-ink-faint)" }}>
            {" "}
            ({skippedCount} more {skippedCount === 1 ? "finding has" : "findings have"} no order id and
            aren&apos;t listed here.)
          </span>
        )}
      </p>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap", marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {filters.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              style={{
                borderRadius: 999,
                padding: "8px 14px",
                fontSize: 12.5,
                fontWeight: 600,
                cursor: "pointer",
                background: filter === f.key ? "var(--dash-ink)" : "var(--dash-raised)",
                color: filter === f.key ? "var(--dash-ground)" : "var(--dash-ink-soft)",
                border: filter === f.key ? "none" : "1px solid var(--dash-line-strong)",
              }}
            >
              {f.label} <span style={{ opacity: 0.6, fontFamily: "var(--dash-font-mono)" }}>{f.count}</span>
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <a
            href={api.actionsCsvUrl(batch)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 7,
              border: "1px solid var(--dash-line-strong)",
              borderRadius: 9,
              padding: "8px 13px",
              fontSize: 12.5,
              color: "var(--dash-ink-soft)",
              cursor: "pointer",
            }}
          >
            Export queue
          </a>
          <Link
            href={`/copilot/${encodeURIComponent(batch)}`}
            style={{
              background: "var(--dash-benign-soft)",
              color: "oklch(0.30 0.06 148)",
              borderRadius: 9,
              padding: "8px 15px",
              fontSize: 12.5,
              fontWeight: 700,
            }}
          >
            Ask Copilot to triage
          </Link>
        </div>
      </div>

      <DashCard style={{ overflow: "hidden" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1.3fr 2fr 0.9fr",
            gap: 16,
            padding: "13px 20px",
            borderBottom: "1px solid var(--dash-line)",
            fontSize: 10.5,
            fontWeight: 700,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--dash-ink-faint)",
          }}
        >
          <div>Order</div>
          <div>Why it broke</div>
          <div style={{ textAlign: "right" }}>Amount</div>
        </div>

        {filtered.length === 0 && rows.length > 0 && (
          <div style={{ padding: 20, fontSize: 13, color: "var(--dash-ink-faint)", fontStyle: "italic" }}>
            No exceptions match this filter.
          </div>
        )}
        {rows.length === 0 && (
          <div style={{ padding: 20, fontSize: 13, color: "var(--dash-ink-faint)", fontStyle: "italic" }}>
            Nothing needs chasing this cycle.
          </div>
        )}

        {filtered.map((r) => {
          const severity = actionSeverity(r.classification);
          const tone = r.offset
            ? "var(--dash-ink-soft)"
            : severity === "urgent"
              ? "var(--dash-urgent)"
              : "var(--dash-action)";
          return (
            <Link
              key={r.key}
              href={`/orders/${encodeURIComponent(batch)}/${encodeURIComponent(r.orderId)}`}
              className="dash-row"
              style={{
                display: "grid",
                gridTemplateColumns: "1.3fr 2fr 0.9fr",
                gap: 16,
                padding: "14px 20px",
                borderBottom: "1px solid var(--dash-line-soft)",
                alignItems: "center",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 12.5, fontWeight: 700 }}>{r.orderId}</div>
                {r.customer && (
                  <div style={{ fontSize: 11.5, color: "var(--dash-ink-faint)", marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {r.customer}
                  </div>
                )}
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.cause}</div>
                <div style={{ fontSize: 11.5, color: "var(--dash-ink-faint)", marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {r.detail}
                </div>
              </div>
              <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 13, fontWeight: 700, fontVariantNumeric: "tabular-nums", textAlign: "right", color: tone }}>
                {r.amountDisplay}
              </div>
            </Link>
          );
        })}
      </DashCard>

      {rows.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14, fontSize: 12.5, color: "var(--dash-ink-faint)" }}>
          <span>
            Showing {filtered.length} of {rows.length} exceptions
          </span>
          <span style={{ fontFamily: "var(--dash-font-mono)" }}>
            {data.total.display} net · {data.chase_total.display} worth chasing
          </span>
        </div>
      )}
    </div>
  );
}
