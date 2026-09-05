"use client";

/**
 * Order detail — one order's full story, from `api.trace(batch, orderId)`.
 *
 * The mockup also has a refund-receipt image slot and "Add a note" / "Save
 * note" / "Release refund" / "Re-run match" controls. None of those have a
 * backend — no file storage, no write-side mutation endpoint, nothing to
 * re-run against, nothing to release. Rather than fake persistence behind a
 * button that quietly does nothing (the failure mode this codebase's own
 * `Actions.tsx` explicitly writes about avoiding), this screen drops them
 * and shows only what the trace actually contains: the three legs (ledger,
 * settlement, outcome), the engine's own proof for its classification, and
 * the event-by-event timeline.
 */

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { DashCard, Pill, SectionLabel, ArrowLeftIcon, type Severity } from "@/components/dash/primitives";
import {
  actionSeverity,
  describeDetail,
  humanize,
  labelForClassification,
  type ActionSeverity,
} from "@/components/dash/action-labels";
import { api, ApiError, type Trace } from "@/lib/api";

const TONE: Record<ActionSeverity, string> = {
  urgent: "var(--dash-urgent)",
  action: "var(--dash-action)",
  neutral: "var(--dash-ink)",
};

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function OrderDetailPage({
  params,
}: {
  params: Promise<{ batch: string; orderId: string }>;
}) {
  const { batch, orderId } = use(params);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTrace(null);
    setError(null);
    api
      .trace(batch, orderId)
      .then(setTrace)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load this order."));
  }, [batch, orderId]);

  if (error) {
    return (
      <div style={{ maxWidth: 640 }}>
        <BackLink batch={batch} />
        <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 32, fontWeight: 400, margin: "18px 0 10px" }}>
          Can&apos;t load {orderId}
        </h1>
        <p style={{ color: "var(--dash-ink-soft)", fontSize: 14 }}>{error}</p>
      </div>
    );
  }

  if (!trace) {
    return <div style={{ color: "var(--dash-ink-faint)", fontSize: 13 }}>Loading order…</div>;
  }

  const severity = actionSeverity(trace.outcome?.classification);
  const tone = TONE[severity];
  const events = [...trace.events].sort((a, b) => a.seq - b.seq);
  const proof = describeDetail(trace.outcome?.proof);

  return (
    <div style={{ maxWidth: 1080, animation: "fadeUp .45s cubic-bezier(.2,.7,.2,1) both" }}>
      <BackLink batch={batch} />

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24, flexWrap: "wrap", marginBottom: 26 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
            {trace.outcome ? (
              <Pill tone={severity === "neutral" ? undefined : severity} style={{ padding: "4px 11px" }}>
                {labelForClassification(trace.outcome.classification).toUpperCase()}
              </Pill>
            ) : (
              <Pill style={{ padding: "4px 11px" }}>NO OUTCOME RECORDED</Pill>
            )}
            {trace.settlement && (
              <span style={{ fontFamily: "var(--dash-font-mono)", fontSize: 11.5, color: "var(--dash-ink-faint)" }}>
                {trace.settlement.matched ? "settlement matched" : "settlement not matched"}
              </span>
            )}
          </div>
          <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.012em", margin: 0 }}>
            {orderId}
          </h1>
          <p style={{ fontSize: 13.5, color: "var(--dash-ink-soft)", margin: "8px 0 0" }}>
            {trace.ledger?.method ? `${trace.ledger.method} · ` : ""}
            {events.length} event{events.length === 1 ? "" : "s"} recorded
          </p>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14, marginBottom: 14 }}>
        <Leg
          leg="Ledger"
          state={trace.ledger ? "Recorded" : "Missing"}
          stateTone={trace.ledger ? undefined : "urgent"}
          amount={trace.ledger?.amount.display ?? "—"}
          amountTone={trace.ledger ? "var(--dash-ink)" : "var(--dash-ink-faint)"}
          source={trace.ledger?.method ?? "No method recorded"}
          ref={orderId}
        />
        <Leg
          leg="Settlement"
          state={trace.settlement ? (trace.settlement.matched ? "Matched" : "Not matched") : "No settlement"}
          stateTone={trace.settlement ? (trace.settlement.matched ? "benign" : "urgent") : "urgent"}
          amount={trace.settlement?.gross.display ?? "—"}
          amountTone={trace.settlement ? "var(--dash-ink)" : "var(--dash-ink-faint)"}
          source={
            trace.settlement
              ? `Net ${trace.settlement.net.display} · Fee ${trace.settlement.fee.display}`
              : "No settlement matched to this order"
          }
          ref={trace.settlement?.utrs.length ? trace.settlement.utrs.join(", ") : trace.settlement?.settlement_ids.join(", ") || "—"}
        />
        <Leg
          leg="Outcome"
          state={trace.outcome ? labelForClassification(trace.outcome.classification) : "Unclassified"}
          stateTone={severity === "neutral" ? undefined : severity}
          amount={trace.outcome?.amount.display ?? "—"}
          amountTone={tone}
          source={trace.outcome ? `${proof.length} field${proof.length === 1 ? "" : "s"} of proof from the engine` : "The engine has not classified this order"}
          ref={trace.outcome?.classification ?? "—"}
        />
      </div>

      {trace.outcome && (
        <div
          style={{
            background: `color-mix(in oklch, ${tone} 7%, var(--dash-raised))`,
            border: `1px solid color-mix(in oklch, ${tone} 22%, transparent)`,
            borderRadius: 14,
            padding: "16px 20px",
            marginBottom: 22,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 20, fontWeight: 600, color: tone }}>
              {trace.outcome.amount.display}
            </div>
            <div style={{ fontSize: 13, color: "var(--dash-ink)", lineHeight: 1.5 }}>
              The engine classified this order as{" "}
              <strong>{labelForClassification(trace.outcome.classification)}</strong>.
            </div>
          </div>
          {proof.length > 0 && (
            <dl
              style={{
                display: "grid",
                gridTemplateColumns: "max-content 1fr",
                columnGap: 14,
                rowGap: 5,
                marginTop: 14,
                paddingTop: 12,
                borderTop: `1px solid color-mix(in oklch, ${tone} 18%, transparent)`,
              }}
            >
              {proof.map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt style={{ fontSize: 11.5, color: "var(--dash-ink-faint)", margin: 0 }}>{k}</dt>
                  <dd style={{ fontSize: 12, fontFamily: "var(--dash-font-mono)", color: "var(--dash-ink)", margin: 0, wordBreak: "break-word" }}>
                    {v}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}

      <DashCard style={{ padding: 22 }}>
        <div style={{ fontSize: 14.5, fontWeight: 700, marginBottom: 18 }}>What happened</div>
        {events.length === 0 && (
          <div style={{ fontSize: 13, color: "var(--dash-ink-faint)", fontStyle: "italic" }}>
            No events recorded for this order.
          </div>
        )}
        {events.map((t, i) => {
          const isLast = i === events.length - 1;
          const detailPairs = describeDetail(t.detail);
          return (
            <div key={t.seq} style={{ display: "grid", gridTemplateColumns: "84px 18px 1fr", gap: 12, alignItems: "start" }}>
              <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 11.5, color: "var(--dash-ink-faint)", paddingTop: 1 }}>
                {formatWhen(t.at)}
              </div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", height: "100%" }}>
                <span style={{ width: 8, height: 8, borderRadius: 999, background: "var(--dash-benign)", flex: "none" }} />
                {!isLast && <span style={{ width: 1, flex: 1, background: "var(--dash-line)", marginTop: 4 }} />}
              </div>
              <div style={{ paddingBottom: 18, minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600 }}>{humanize(t.event)}</div>
                <div style={{ fontSize: 12.5, color: "var(--dash-ink-faint)", marginTop: 4, lineHeight: 1.5, overflowWrap: "anywhere" }}>
                  {humanize(t.stage)}
                  {detailPairs.length > 0 && ` · ${detailPairs.map(([k, v]) => `${k}: ${v}`).join(" · ")}`}
                </div>
              </div>
            </div>
          );
        })}
      </DashCard>
    </div>
  );
}

function BackLink({ batch }: { batch: string }) {
  return (
    <Link
      href={`/exceptions/${encodeURIComponent(batch)}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 7,
        fontSize: 12.5,
        fontWeight: 600,
        color: "var(--dash-ink-soft)",
        marginBottom: 18,
      }}
    >
      <ArrowLeftIcon size={14} />
      Exception queue
    </Link>
  );
}

function Leg({
  leg,
  state,
  stateTone,
  amount,
  amountTone,
  source,
  ref,
}: {
  leg: string;
  state: string;
  stateTone?: Severity;
  amount: string;
  amountTone: string;
  source: string;
  ref: string;
}) {
  return (
    <DashCard style={{ padding: 18 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 14 }}>
        <SectionLabel as="div" style={{ fontSize: 10.5 }}>
          {leg}
        </SectionLabel>
        <Pill tone={stateTone}>{state}</Pill>
      </div>
      <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 26, fontWeight: 500, fontVariantNumeric: "tabular-nums", letterSpacing: "-0.02em", color: amountTone }}>
        {amount}
      </div>
      <div style={{ fontSize: 12, color: "var(--dash-ink-faint)", marginTop: 8 }}>{source}</div>
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--dash-line-soft)", fontFamily: "var(--dash-font-mono)", fontSize: 11.5, color: "var(--dash-ink-soft)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {ref}
      </div>
    </DashCard>
  );
}
