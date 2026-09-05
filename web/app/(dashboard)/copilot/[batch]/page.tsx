"use client";

/**
 * Ask Copilot — the full-page chat, vs. the docked drawer in `layout.tsx`.
 * Same `CopilotChat` component either way (see its own doc comment); this
 * page just gives it more room and a left rail of real context instead of
 * fabricated conversation history.
 *
 * There is no backend for persisted threads (no database, one in-memory
 * chat per page load — see the plan at
 * `/home/harsh/.claude/plans/fancy-sniffing-rossum.md`). The mockup's
 * "Threads" list of past conversations is not ported: showing conversations
 * that never happened would be exactly the kind of invented figure this
 * product refuses to put on screen elsewhere. "New thread" here does
 * something real instead — it clears the live conversation by remounting
 * `CopilotChat` (via `key`), nothing more.
 */

import { useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";
import { CopilotChat, CopilotHeader } from "@/components/dash/CopilotChat";
import { DashCard, SectionLabel } from "@/components/dash/primitives";
import { useCurrentBatch } from "@/lib/current-batch";
import { api, type RateCard, type Verdict } from "@/lib/api";

// The prerenderer has no query string to read `?ask=` from, so the `useSearchParams()`
// caller needs its own boundary rather than stalling the whole page.
export default function CopilotPage(props: { params: Promise<{ batch: string }> }) {
  return (
    <Suspense fallback={<div style={{ color: "var(--dash-ink-faint)", fontSize: 13 }}>Loading copilot…</div>}>
      <CopilotPageInner {...props} />
    </Suspense>
  );
}

function CopilotPageInner({
  params,
}: {
  params: Promise<{ batch: string }>;
}) {
  const { batch } = use(params);
  const { setBatch } = useCurrentBatch();
  const ask = useSearchParams().get("ask");

  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [rateCard, setRateCard] = useState<RateCard | null>(null);
  const [threadKey, setThreadKey] = useState(0);

  useEffect(() => {
    setBatch(batch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch]);

  useEffect(() => {
    let cancelled = false;
    api.verdict(batch).then((v) => !cancelled && setVerdict(v)).catch(() => {});
    api.rateCard().then((r) => !cancelled && setRateCard(r)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [batch]);

  const chips: string[] = [`Batch “${batch}”`];
  if (verdict) {
    chips.push(`${verdict.performance.rows_processed.toLocaleString("en-IN")} orders processed`);
    chips.push(
      verdict.actionable_total.paise > 0
        ? `${verdict.actionable_total.display} needs a decision`
        : "Nothing needs a decision",
    );
    if (verdict.missing_sources.length > 0) {
      chips.push(`Missing: ${verdict.missing_sources.join(", ")}`);
    }
  }
  if (rateCard) {
    chips.push(
      rateCard.is_merchant_supplied ? `Custom rate card: ${rateCard.name}` : `Standard rate card: ${rateCard.name}`,
    );
  }

  return (
    <div style={{ maxWidth: 1180 }}>
      <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 34, fontWeight: 400, letterSpacing: "-0.012em", margin: "0 0 6px" }}>
        Ask Copilot
      </h1>
      <p style={{ fontSize: 14, color: "var(--dash-ink-soft)", margin: "0 0 26px" }}>
        Ask about any line on this run — Copilot reads the same verdict you do, and never writes a figure of its own.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "230px 1fr", gap: 22, alignItems: "start" }}>
        <div>
          <SectionLabel style={{ marginBottom: 12 }}>Thread</SectionLabel>
          <button
            type="button"
            onClick={() => setThreadKey((k) => k + 1)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              width: "100%",
              border: "1px dashed var(--dash-line-strong)",
              borderRadius: 10,
              padding: "10px 12px",
              fontSize: 12.5,
              fontWeight: 600,
              color: "oklch(0.41 0.024 74)",
              background: "none",
              cursor: "pointer",
              marginBottom: 22,
            }}
          >
            + New thread
          </button>

          <div
            style={{
              background: "var(--dash-well)",
              border: "1px solid var(--dash-line)",
              borderRadius: 12,
              padding: 14,
            }}
          >
            <SectionLabel style={{ fontSize: 11, marginBottom: 10 }}>Context in scope</SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {chips.map((c) => (
                <div key={c} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12, color: "oklch(0.40 0.024 74)", lineHeight: 1.4 }}>
                  <span style={{ width: 6, height: 6, marginTop: 4, borderRadius: 999, background: "var(--dash-accent)", flex: "none" }} />
                  {c}
                </div>
              ))}
              {chips.length === 1 && (
                <div style={{ fontSize: 12, color: "var(--dash-ink-faint)", fontStyle: "italic" }}>Loading run details…</div>
              )}
            </div>
          </div>
        </div>

        <DashCard style={{ minHeight: 640, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ padding: "18px 24px", borderBottom: "1px solid var(--dash-line)", display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <CopilotHeader batch={batch} />
            </div>
            {verdict && (
              <div style={{ flex: "none", fontFamily: "var(--dash-font-mono)", fontSize: 11, color: "var(--dash-ink-faint)" }}>
                {verdict.performance.rows_processed.toLocaleString("en-IN")} orders in context
              </div>
            )}
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <CopilotChat key={threadKey} batch={batch} initialMessage={threadKey === 0 ? (ask ?? undefined) : undefined} />
          </div>
        </DashCard>
      </div>
    </div>
  );
}
