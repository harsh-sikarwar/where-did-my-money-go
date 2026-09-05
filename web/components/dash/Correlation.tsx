"use client";

/**
 * The differentiator, in the dashboard's own idiom.
 *
 * A direct port of `components/Correlation.tsx` (Tailwind, `--color-*`) into the
 * `--dash-*` inline-style system of the rebuilt dashboard, where the original was
 * dropped and never re-landed — `api.correlation()` was defined and called by
 * nothing. The claim this screen makes is the project's whole argument: existing
 * tools are architecturally siloed, so an anomaly spanning reconciliation and
 * recovery has no owner and reaches the merchant as "unexplained". This is the
 * measurement of how much of that we remove, on the same batch, before and after.
 *
 * Three honesty constraints carried over verbatim from the original, because each
 * one exists to stop this component from overstating its own result:
 *
 *  1. Both bars are scaled to BEFORE. Scaling each to its own width would make
 *     every gain look total.
 *  2. The percentage rendered is `gain_ratio` from the engine, not a ratio derived
 *     here (ADR-001: no client-side money arithmetic). Bar widths are layout, not
 *     figures, and are the one place paise is touched.
 *  3. When nothing resolved, the copy says so. "Resolves most of it" printed above
 *     two identical bars is a sentence the picture contradicts.
 *  4. When reconciliation left no residual at all (`before` is zero — `qa-B`,
 *     `qa-split`, `up-hdr` all do this), there was never anything for correlation
 *     to resolve. A 0% gain and two empty bars would read as a failure of this
 *     stage rather than a clean run of the previous one, so the band collapses to
 *     one sentence instead.
 */

import { DashCard, SectionLabel } from "@/components/dash/primitives";
import type { Correlation as CorrelationData } from "@/lib/api";

/** Chart series, not status colours — "which classification resolved it" is a
 *  different question from "is this money a problem", and must not borrow the
 *  palette that answers the second one. */
const SERIES = [
  "var(--color-series-1)",
  "var(--color-series-2)",
  "var(--color-series-3)",
  "var(--color-series-4)",
  "var(--color-series-5)",
  "var(--color-series-6)",
];

export function CorrelationBand({
  data,
  compact = false,
}: {
  data: CorrelationData;
  compact?: boolean;
}) {
  const before = data.before.paise;
  const after = data.after.paise;
  const afterWidth =
    before > 0 ? Math.max((after / before) * 100, after > 0 ? 1.5 : 0) : 0;
  const resolvedNothing = data.resolved.paise === 0;
  const nothingToExplain = before === 0;
  const gainPct = (data.gain_ratio * 100).toFixed(1);

  if (nothingToExplain) {
    return (
      <DashCard
        style={{
          padding: "18px 22px",
          marginBottom: 16,
          animation: "fadeUp .5s cubic-bezier(.2,.7,.2,1) .18s both",
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 5 }}>
          What we could explain by looking wider
        </div>
        <div style={{ fontSize: 12.5, color: "var(--dash-ink-faint)", lineHeight: 1.55, maxWidth: 620 }}>
          Reconciliation left nothing unexplained on this batch, so there was nothing
          for correlation to resolve. This stage reads the payment and subscription
          records only for the residual the settlement file cannot account for.
        </div>
      </DashCard>
    );
  }

  return (
    <DashCard
      style={{
        padding: compact ? "20px 22px" : "24px 26px 22px",
        marginBottom: 16,
        animation: "fadeUp .5s cubic-bezier(.2,.7,.2,1) .18s both",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 16,
          marginBottom: 18,
        }}
      >
        <div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>
            What we could explain by looking wider
          </div>
          <div
            style={{
              fontSize: 12.5,
              color: "var(--dash-ink-faint)",
              marginTop: 4,
              maxWidth: 560,
              lineHeight: 1.5,
            }}
          >
            {resolvedNothing
              ? "Reconciliation alone leaves a residual. Cross-referencing it against payment failures and subscription status resolved none of it on this batch — either nothing joined, or the payments and subscriptions files were not supplied."
              : "Reconciliation alone leaves a residual. Cross-referencing it against payment failures and subscription status resolves most of it — same batch, before and after."}
          </div>
        </div>
        {!resolvedNothing && (
          <div style={{ textAlign: "right", flex: "none" }}>
            <div
              style={{
                fontFamily: "var(--dash-font-mono)",
                fontSize: 38,
                fontWeight: 500,
                letterSpacing: "-0.03em",
                lineHeight: 1,
                color: "var(--dash-benign)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {gainPct}%
            </div>
            <div
              style={{
                fontSize: 11.5,
                color: "var(--dash-ink-faint)",
                marginTop: 6,
              }}
            >
              of the unexplained gap, explained
            </div>
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <Bar
          label="before"
          value={data.before.display}
          widthPct={before > 0 ? 100 : 0}
          colour="var(--dash-action)"
        />
        <Bar
          label="after"
          value={data.after.display}
          widthPct={afterWidth}
          colour="var(--dash-benign)"
        />
      </div>

      <p
        style={{
          fontSize: 13,
          margin: "16px 0 0",
          color: "var(--dash-ink-soft)",
          lineHeight: 1.55,
        }}
      >
        {resolvedNothing ? (
          <>
            <span style={{ fontWeight: 600, color: "var(--dash-ink)" }}>
              {data.after.display}
            </span>{" "}
            still unexplained across {data.still_unexplained_count}{" "}
            {data.still_unexplained_count === 1 ? "row" : "rows"}.
          </>
        ) : (
          <>
            <span style={{ fontWeight: 600, color: "var(--dash-ink)" }}>
              {data.resolved.display}
            </span>{" "}
            resolved by joining {data.resolved_count} unexplained{" "}
            {data.resolved_count === 1 ? "row" : "rows"} to their payment records
            {data.still_unexplained_count > 0 && (
              <>
                {" · "}
                {data.still_unexplained_count} genuinely unexplained
              </>
            )}
          </>
        )}
      </p>

      {!compact && data.resolved_by_class.length > 0 && (
        <CategoryChart rows={data.resolved_by_class} />
      )}

      <p
        style={{
          fontSize: 11.5,
          lineHeight: 1.55,
          color: "var(--dash-ink-faint)",
          margin: "16px 0 0",
        }}
      >
        This is a join, not a judgment — order → payment → subscription, following
        identifiers only. Where the join does not land, the row stays unexplained.
      </p>
    </DashCard>
  );
}

/** How the resolved amount broke down, largest first, so the eye lands on the
 *  category that mattered most. */
function CategoryChart({ rows }: { rows: CorrelationData["resolved_by_class"] }) {
  const sorted = [...rows].sort((a, b) => b.amount.paise - a.amount.paise);
  const max = Math.max(...sorted.map((r) => r.amount.paise), 1);

  return (
    <div style={{ marginTop: 20 }}>
      <SectionLabel as="div" style={{ fontSize: 11, marginBottom: 12 }}>
        Resolved, by what it turned out to be
      </SectionLabel>
      <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
        {sorted.map((r, i) => (
          <div key={r.classification} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span
              style={{
                width: 250,
                flex: "none",
                fontSize: 12.5,
                color: "var(--dash-ink-soft)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {humanise(r.classification)}
            </span>
            <div
              style={{
                position: "relative",
                height: 18,
                flex: 1,
                borderRadius: 3,
                background: "var(--dash-well)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  height: "100%",
                  borderRadius: 3,
                  width: `${Math.max((r.amount.paise / max) * 100, r.amount.paise > 0 ? 2 : 0)}%`,
                  background: SERIES[i % SERIES.length],
                  transition: "width .7s cubic-bezier(.2,.7,.2,1)",
                }}
              />
            </div>
            <span
              style={{
                width: 96,
                flex: "none",
                textAlign: "right",
                fontFamily: "var(--dash-font-mono)",
                fontSize: 12,
                fontVariantNumeric: "tabular-nums",
                color: "var(--dash-ink-soft)",
              }}
            >
              {r.amount.display}
            </span>
            <span
              style={{
                width: 40,
                flex: "none",
                textAlign: "right",
                fontSize: 11.5,
                color: "var(--dash-ink-faint)",
              }}
            >
              {r.count}×
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Bar({
  label,
  value,
  widthPct,
  colour,
}: {
  label: string;
  value: string;
  widthPct: number;
  colour: string;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
      <span
        style={{
          width: 52,
          flex: "none",
          fontSize: 11,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--dash-ink-faint)",
        }}
      >
        {label}
      </span>
      <div
        style={{
          position: "relative",
          height: 26,
          flex: 1,
          borderRadius: 4,
          background: "var(--dash-line-soft)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            borderRadius: 4,
            width: `${widthPct}%`,
            background: colour,
            transition: "width .7s cubic-bezier(.2,.7,.2,1)",
          }}
        />
      </div>
      <span
        style={{
          width: 110,
          flex: "none",
          textAlign: "right",
          fontFamily: "var(--dash-font-mono)",
          fontSize: 13.5,
          fontWeight: 600,
          fontVariantNumeric: "tabular-nums",
          color: colour,
        }}
      >
        {value}
      </span>
    </div>
  );
}

/** Engine classification names are SCREAMING_SNAKE. Merchants are not. */
function humanise(classification: string): string {
  const copy: Record<string, string> = {
    HALTED_SUBSCRIPTION: "subscription stopped charging, invoices kept coming",
    PAYMENT_FAILED: "the customer's payment failed",
  };
  return copy[classification] ?? classification.toLowerCase().replace(/_/g, " ");
}
