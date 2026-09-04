"use client";

import { useEffect, useState } from "react";
import { ChevronDownIcon, Skeleton } from "@/components/ui";
import { api, ApiError, type Audit as AuditData } from "@/lib/api";

/**
 * The audit trail. Collapsed by default — a merchant does not want it, and a judge
 * asking "how do I know that's true?" does.
 *
 * Fetched on demand rather than with the verdict: it is the one view nobody opens on a
 * normal Monday, so paying for it on every page load would be backwards.
 */
export function Audit({ batch }: { batch: string }) {
  const [open, setOpen] = useState(false);

  return (
    <section className="mt-16 border-t border-[var(--color-line-strong)] pt-8">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-baseline justify-between text-left"
        aria-expanded={open}
      >
        <span className="text-title">How do I know this is true?</span>
        <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-accent)]">
          {open ? "hide" : "show the audit trail"}
          <ChevronDownIcon
            size={13}
            className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          />
        </span>
      </button>
      {open && <AuditBody batch={batch} />}
    </section>
  );
}

function AuditBody({ batch }: { batch: string }) {
  const [data, setData] = useState<AuditData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .audit(batch, stage ?? undefined)
      .then((d) => !cancelled && setData(d))
      .catch((e: ApiError) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [batch, stage]);

  if (error)
    return (
      <p className="mt-4 text-sm font-medium text-[var(--color-urgent)]">{error}</p>
    );
  if (!data)
    return (
      <Skeleton className="mt-4 h-3 w-32" />
    );

  return (
    <div className="mt-6">
      {/* What was ingested. The answer to "which column did you read as the amount?" */}
      <h3 className="text-label mb-3 text-[var(--color-ink-faint)]">What we read</h3>
      <div className="mb-8 space-y-1.5">
        {Object.entries(data.manifest.sources).map(([name, src]) => (
          <div
            key={name}
            className="flex flex-wrap items-baseline gap-x-3 font-mono text-xs text-[var(--color-ink-soft)]"
          >
            <span className="w-28 shrink-0">{name}</span>
            <span className="tnum w-16 shrink-0 text-right">
              {src.rows.toLocaleString()} rows
            </span>
            <span className="text-[var(--color-ink-faint)]">
              sha256 {src.sha256.slice(0, 12)}
            </span>
            {src.column_mapping && (
              <span className="w-full pl-28 text-[var(--color-ink-faint)]">
                {src.column_mapping}
              </span>
            )}
          </div>
        ))}
      </div>

      <h3 className="text-label mb-3 text-[var(--color-ink-faint)]">
        Every decision · {data.total_events} events
      </h3>

      <div className="mb-3 flex flex-wrap gap-1.5">
        <StageChip
          label="all"
          count={data.total_events}
          active={stage === null}
          onClick={() => setStage(null)}
        />
        {Object.entries(data.by_stage).map(([name, count]) => (
          <StageChip
            key={name}
            label={name}
            count={count}
            active={stage === name}
            onClick={() => setStage(name)}
          />
        ))}
      </div>

      <div className="max-h-96 overflow-y-auto rounded-xl border border-[var(--color-line)] bg-[var(--color-well)]">
        {data.events.map((e) => (
          <div
            key={e.seq}
            className="border-b border-[var(--color-line)] px-3 py-1.5 font-mono text-xs last:border-0"
          >
            <div className="flex items-baseline gap-2">
              <span className="tnum w-8 shrink-0 text-right text-[var(--color-ink-faint)]">
                {e.seq}
              </span>
              <span className="w-16 shrink-0 text-[var(--color-ink-faint)]">
                {e.stage}
              </span>
              <span className="flex-1 break-all">{e.event}</span>
              {e.order_id && (
                <span className="shrink-0 text-[var(--color-ink-faint)]">
                  {e.order_id}
                </span>
              )}
            </div>
            {summarise(e.detail) && (
              <div className="pl-26 text-[var(--color-ink-faint)]">
                {summarise(e.detail)}
              </div>
            )}
          </div>
        ))}
      </div>

      {data.truncated && (
        <p className="mt-2 text-xs text-[var(--color-ink-faint)]">
          showing the first {data.events.length} of {data.filtered_count}
        </p>
      )}

      <p className="mt-4 text-xs leading-relaxed text-[var(--color-ink-faint)]">
        Written as JSON Lines, append-only. The full log is on disk — this view is a
        reader, not the record.
      </p>
    </div>
  );
}

function StageChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`pressable rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
        active
          ? "bg-[var(--color-ink)] text-[var(--color-ground)]"
          : "bg-[var(--color-line)]/60 text-[var(--color-ink-soft)] hover:bg-[var(--color-line)]"
      }`}
    >
      {label} <span className="tnum opacity-60">{count}</span>
    </button>
  );
}

/**
 * One line of the most useful thing in an event's detail.
 *
 * The frontend picks WHICH engine-supplied string to show; it never composes one. Full
 * detail lives in the JSONL file, which this view deliberately does not try to replace.
 */
function summarise(detail: Record<string, unknown>): string {
  const proof = detail.proof as Record<string, unknown> | undefined;
  const correlation = detail.correlation as Record<string, unknown> | undefined;

  if (correlation?.join_chain) {
    return `${correlation.join_chain} → ${correlation.subscription_status ?? correlation.error_reason ?? ""}`;
  }
  if (typeof proof?.arithmetic === "string") return proof.arithmetic;
  if (typeof proof?.reason === "string") return proof.reason;
  if (typeof detail.column_mapping === "string" && detail.column_mapping) {
    return detail.column_mapping;
  }
  if (typeof detail.match_rate === "number") {
    return `${detail.matched}/${detail.total} matched (${(detail.match_rate * 100).toFixed(1)}%)`;
  }
  if (typeof detail.text === "string") return detail.text;
  return "";
}
