import type { Correlation as CorrelationData } from "@/lib/api";

/**
 * The differentiator, as a number a merchant can see move.
 *
 * The claim is: existing tools are architecturally siloed, so an anomaly spanning
 * reconciliation and recovery has no owner and reaches the merchant as "unexplained".
 * This screen is the measurement of how much of that we eliminate — before vs after,
 * on the same batch.
 *
 * Bars are proportional to the BEFORE figure so the shrink is visually honest. Scaling
 * each bar to its own width would make any gain look total.
 */
export function Correlation({ data }: { data: CorrelationData }) {
  const before = data.before.paise;
  const after = data.after.paise;
  const afterWidth = before > 0 ? Math.max((after / before) * 100, after > 0 ? 1.5 : 0) : 0;

  return (
    <section className="mt-16 border-t border-[var(--color-line)] pt-10">
      <h2 className="mb-1 text-sm font-medium tracking-tight">
        What we could explain by looking wider
      </h2>
      <p className="mb-8 max-w-lg text-sm leading-relaxed text-[var(--color-ink-soft)]">
        Reconciliation alone leaves a residual. Cross-referencing it against payment
        failures and subscription status resolves most of it — the same batch, before and
        after.
      </p>

      <div className="space-y-4">
        <Bar
          label="before"
          value={data.before.display}
          widthPct={before > 0 ? 100 : 0}
          tone="attention"
        />
        <Bar
          label="after"
          value={data.after.display}
          widthPct={afterWidth}
          tone="benign"
          empty={after === 0}
        />
      </div>

      <p className="mt-6 text-sm">
        <span className="font-medium">{data.resolved.display}</span>{" "}
        <span className="text-[var(--color-ink-soft)]">
          resolved by joining {data.resolved_count} unexplained{" "}
          {data.resolved_count === 1 ? "row" : "rows"} to their payment records
          {data.still_unexplained_count > 0 && (
            <> · {data.still_unexplained_count} genuinely unexplained</>
          )}
        </span>
      </p>

      {data.resolved_by_class.length > 0 && (
        <ul className="mt-5 space-y-1.5">
          {data.resolved_by_class.map((r) => (
            <li
              key={r.classification}
              className="flex items-baseline gap-3 text-sm"
            >
              <span className="tnum w-28 shrink-0 text-right text-[var(--color-ink-soft)]">
                {r.amount.display}
              </span>
              <span className="text-[var(--color-ink-soft)]">
                {r.count} × {humanise(r.classification)}
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="mt-6 text-xs leading-relaxed text-[var(--color-ink-faint)]">
        This is a join, not a judgment — order → payment → subscription, following
        identifiers only. Where the join does not land, the row stays unexplained.
      </p>
    </section>
  );
}

function Bar({
  label,
  value,
  widthPct,
  tone,
  empty,
}: {
  label: string;
  value: string;
  widthPct: number;
  tone: "attention" | "benign";
  empty?: boolean;
}) {
  const colour =
    tone === "attention" ? "var(--color-attention)" : "var(--color-benign)";

  return (
    <div className="flex items-center gap-4">
      <span className="w-14 shrink-0 text-xs tracking-wide text-[var(--color-ink-faint)] uppercase">
        {label}
      </span>
      <div className="relative h-7 flex-1 overflow-hidden rounded-sm bg-[var(--color-line)]/50">
        <div
          className="h-full rounded-sm transition-[width] duration-700"
          style={{ width: `${widthPct}%`, backgroundColor: colour }}
        />
      </div>
      <span
        className="tnum w-28 shrink-0 text-right text-sm font-medium"
        style={{ color: empty ? "var(--color-benign)" : colour }}
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
