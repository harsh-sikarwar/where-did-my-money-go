"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type Verdict as VerdictData } from "@/lib/api";

/**
 * The default screen: four lines and a verdict. Deliberately NOT a dashboard.
 *
 * Hyperswitch and Cointab build for a finance operator who lives in the tool. This is
 * for a merchant who opens it for two minutes on Monday. The depth exists (one click
 * down) which is what proves the simplicity is a choice rather than a limitation.
 *
 * Data is fetched by the server component and passed in, so the numbers are present in
 * the initial HTML rather than flashing in after hydration. Only the drill-downs fetch
 * on the client, because those are genuinely on demand.
 */
export function Verdict({ data }: { data: VerdictData }) {
  const batch = data.batch;
  const benign = data.lines.filter((l) => !l.actionable);
  const actionable = data.lines.filter((l) => l.actionable);

  return (
    <main className="mx-auto max-w-2xl px-6 py-16 sm:py-24">
      <header className="mb-12">
        <h1 className="text-sm font-medium tracking-tight text-[var(--color-ink-faint)]">
          Where did my money go?
        </h1>
      </header>

      {/* The three numbers that frame everything else. */}
      <section className="mb-14">
        <div className="flex flex-wrap items-baseline gap-x-10 gap-y-3">
          <Figure label="Expected" value={data.expected.display} />
          <Figure label="Received" value={data.received.display} />
          <span
            className="self-center text-lg text-[var(--color-line)]"
            aria-hidden
          >
            /
          </span>
          <Figure label="Gap" value={data.gap.display} emphasis />
        </div>
      </section>

      {/* The lines. Benign first — the eye should land on "mostly fine". */}
      <section className="space-y-px">
        {benign.map((line) => (
          <Line key={line.classification} line={line} batch={batch} />
        ))}
        {actionable.length > 0 && benign.length > 0 && (
          <div className="h-6" aria-hidden />
        )}
        {actionable.map((line) => (
          <Line key={line.classification} line={line} batch={batch} />
        ))}

        <div className="flex items-baseline gap-4 px-3 py-3 text-[var(--color-ink-faint)]">
          <span className="tnum w-28 shrink-0 text-right text-sm">
            {data.unexplained.display}
          </span>
          <span className="text-sm">we can&rsquo;t explain</span>
        </div>
      </section>

      {/* The verdict. One thing, not a list — if everything is urgent, nothing is. */}
      <section className="mt-12 border-t border-[var(--color-line)] pt-8">
        <p className="text-lg leading-relaxed font-medium tracking-tight">
          {data.headline}
        </p>
      </section>

      <Provenance data={data} />
    </main>
  );
}

function Figure({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div>
      <div className="mb-1 text-xs tracking-wide text-[var(--color-ink-faint)] uppercase">
        {label}
      </div>
      <div
        className={`tnum tracking-tight ${
          emphasis ? "text-2xl font-semibold" : "text-2xl font-normal"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function Line({
  line,
  batch,
}: {
  line: import("@/lib/api").VerdictLine;
  batch: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div
      className={`rounded-md transition-colors ${
        line.actionable ? "bg-[var(--color-attention-bg)]" : "hover:bg-white"
      }`}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-baseline gap-4 px-3 py-3 text-left"
        aria-expanded={open}
      >
        <span
          className={`tnum w-28 shrink-0 text-right text-sm font-medium ${
            line.actionable ? "text-[var(--color-attention)]" : ""
          }`}
        >
          {line.amount.display}
        </span>
        <span className="flex-1 text-sm">
          <span className="text-[var(--color-ink-faint)]">{line.count}</span>{" "}
          {line.label}
        </span>
        <span className="shrink-0 text-xs text-[var(--color-ink-faint)]">
          {open ? "hide" : "detail"}
        </span>
      </button>

      {open && (
        <div className="px-3 pb-4 pl-35">
          <p className="mb-3 max-w-lg text-sm leading-relaxed text-[var(--color-ink-soft)]">
            {line.explanation}
          </p>
          <DetailRows batch={batch} classification={line.classification} />
        </div>
      )}
    </div>
  );
}

/**
 * The proof, one click down. Every finance term is explained above; the exact
 * arithmetic lives here. This is the layer that makes the top level defensible.
 */
function DetailRows({
  batch,
  classification,
}: {
  batch: string;
  classification: string;
}) {
  const [detail, setDetail] = useState<import("@/lib/api").Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .detail(batch, classification)
      .then((d) => !cancelled && setDetail(d))
      .catch((e: ApiError) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [batch, classification]);

  if (error) return <p className="text-xs text-[var(--color-attention)]">{error}</p>;
  if (!detail)
    return <div className="h-3 w-24 animate-pulse rounded bg-[var(--color-line)]" />;

  return (
    <div className="space-y-1">
      {detail.findings.slice(0, 6).map((f, i) => (
        <div
          key={f.order_id ?? i}
          className="flex items-baseline gap-3 font-mono text-xs text-[var(--color-ink-soft)]"
        >
          <span className="tnum w-24 shrink-0 text-right">
            {f.amount.display}
          </span>
          <span className="truncate">{proofLine(f.proof)}</span>
        </div>
      ))}
      {detail.count > 6 && (
        <p className="pt-1 text-xs text-[var(--color-ink-faint)]">
          + {detail.count - 6} more
        </p>
      )}
    </div>
  );
}

/**
 * Pull the human-readable proof out of a finding.
 *
 * The engine puts an `arithmetic` string on rule-based findings and a `correlation`
 * block on correlated ones. Neither is generated here — the frontend never composes a
 * number, it only chooses which engine-supplied string to show.
 */
function proofLine(proof: Record<string, unknown>): string {
  const correlation = proof.correlation as
    | Record<string, unknown>
    | undefined;

  if (correlation?.subscription_id) {
    return `${correlation.subscription_id} · ${correlation.subscription_status} · invoice ${correlation.invoice_id}`;
  }
  if (correlation?.error_reason) {
    return `${correlation.error_reason} · ${correlation.failure_bucket}`;
  }
  if (typeof proof.arithmetic === "string") return proof.arithmetic;
  if (typeof proof.reason === "string") return proof.reason;
  return "";
}

/**
 * Where the numbers came from. Small, at the bottom, always present.
 * "Every number traces back to a Razorpay record" has to be visible to be a claim.
 */
function Provenance({ data }: { data: VerdictData }) {
  return (
    <footer className="mt-16 border-t border-[var(--color-line)] pt-6 text-xs leading-relaxed text-[var(--color-ink-faint)]">
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span>
          {data.match.pass1.matched}/{data.match.pass1.total} orders reached
          Razorpay
        </span>
        <span>
          {data.match.pass2.matched}/{data.match.pass2.total} payouts reached the
          bank
        </span>
        <span className="tnum">
          {data.performance.rows_processed.toLocaleString()} rows in{" "}
          {(data.performance.elapsed_seconds * 1000).toFixed(0)}ms
        </span>
      </div>
      <p className="mt-2">
        Matching is identifier-based only, never fuzzy. Every number traces back to
        a Razorpay record.
      </p>
    </footer>
  );
}
