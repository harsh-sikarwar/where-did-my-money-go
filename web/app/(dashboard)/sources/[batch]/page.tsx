"use client";

/**
 * Sources — what was actually fed into this run, and what wasn't.
 *
 * The mockup frames this as "connected sources" with a live sync status per
 * card ("Last sync", "Manage"). That implies an ongoing sync relationship
 * this tool doesn't have: files are uploaded or generated once per batch,
 * not continuously polled. Reframed honestly as "supplied for this run" —
 * each card is a fact about one ingest, not a connection.
 *
 * `manifest.sources` (from `api.audit`) lists what WAS supplied; the missing
 * ones come from `verdict.missing_sources` / `missing_note`, which the
 * engine already computes (see `_missing_sources`/`_missing_note` in
 * `api/main.py`) — nothing here is inferred client-side.
 */

import { use, useEffect, useState } from "react";
import { DashCard, Pill, type Severity } from "@/components/dash/primitives";
import { useCurrentBatch } from "@/lib/current-batch";
import { api, ApiError, type Audit, type Verdict } from "@/lib/api";

const SOURCE_META: Record<string, { label: string; kind: string; severity: Severity }> = {
  ledger: { label: "Ledger", kind: "What you sold", severity: "urgent" },
  recon: { label: "Settlement recon", kind: "What Razorpay settled", severity: "urgent" },
  bank: { label: "Bank statement", kind: "What the bank credited", severity: "action" },
  payments: { label: "Payments", kind: "Razorpay payment records", severity: "action" },
  subscriptions: { label: "Subscriptions", kind: "Subscription status", severity: "action" },
};

const SOURCE_ORDER = ["ledger", "recon", "bank", "payments", "subscriptions"];

export default function SourcesPage({
  params,
}: {
  params: Promise<{ batch: string }>;
}) {
  const { batch } = use(params);
  const { setBatch } = useCurrentBatch();
  const [audit, setAudit] = useState<Audit | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setBatch(batch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch]);

  useEffect(() => {
    let cancelled = false;
    setAudit(null);
    setVerdict(null);
    setError(null);
    Promise.all([api.audit(batch), api.verdict(batch)])
      .then(([a, v]) => {
        if (cancelled) return;
        setAudit(a);
        setVerdict(v);
      })
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Something went wrong."));
    return () => {
      cancelled = true;
    };
  }, [batch]);

  const loading = !audit || !verdict;

  return (
    <div style={{ maxWidth: 1000 }}>
      <h1
        style={{
          fontFamily: "var(--dash-font-serif)",
          fontSize: 40,
          fontWeight: 400,
          letterSpacing: "-0.012em",
          margin: "0 0 8px",
        }}
      >
        Sources
      </h1>
      <p style={{ fontSize: 14, color: "var(--dash-ink-soft)", margin: "0 0 30px", maxWidth: 620 }}>
        The files behind this run. Each one was supplied once, for this batch — not a live
        connection this tool keeps polling.
      </p>

      {error && (
        <DashCard style={{ padding: 18, marginBottom: 20, color: "var(--dash-urgent)", fontSize: 13.5 }}>
          {error}
        </DashCard>
      )}

      {loading && !error && (
        <div style={{ color: "var(--dash-ink-faint)", fontSize: 13 }}>Loading sources…</div>
      )}

      {audit && verdict && (
        <>
          {verdict.missing_sources.length > 0 && verdict.missing_note && (
            <DashCard
              style={{
                padding: "16px 20px",
                marginBottom: 22,
                borderLeft: "3px solid var(--dash-urgent)",
                fontSize: 13,
                lineHeight: 1.6,
                color: "var(--dash-ink-soft)",
              }}
            >
              <div style={{ fontWeight: 700, color: "var(--dash-ink)", marginBottom: 6, fontSize: 13.5 }}>
                {verdict.missing_sources.length} source{verdict.missing_sources.length === 1 ? "" : "s"} not
                supplied
              </div>
              {verdict.missing_note}
            </DashCard>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 14 }}>
            {SOURCE_ORDER.map((key) => {
              const meta = SOURCE_META[key];
              const supplied = audit.manifest.sources[key];
              const missing = verdict.missing_sources.includes(key);
              return (
                <SourceCard
                  key={key}
                  label={meta.label}
                  kind={meta.kind}
                  severity={meta.severity}
                  supplied={supplied}
                  missing={missing}
                />
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function SourceCard({
  label,
  kind,
  severity,
  supplied,
  missing,
}: {
  label: string;
  kind: string;
  severity: Severity;
  supplied?: { origin: string; rows: number; sha256: string; column_mapping: string };
  missing: boolean;
}) {
  const filename = supplied ? supplied.origin.split("/").pop() ?? supplied.origin : null;

  return (
    <DashCard
      interactive={!!supplied}
      style={{
        padding: 22,
        opacity: missing ? 0.7 : 1,
        borderStyle: missing ? "dashed" : "solid",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <div
          style={{
            flex: "none",
            width: 34,
            height: 34,
            borderRadius: 9,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 14,
            fontWeight: 700,
            background: supplied ? "var(--dash-benign-soft)" : "var(--dash-well)",
            color: supplied ? "oklch(0.30 0.06 148)" : "var(--dash-ink-faint)",
          }}
        >
          {label[0]}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 14.5, fontWeight: 700 }}>{label}</div>
          <div style={{ fontSize: 12, color: "var(--dash-ink-faint)", marginTop: 3 }}>{kind}</div>
        </div>
        {supplied ? (
          <Pill tone="benign">Supplied</Pill>
        ) : (
          <Pill tone={severity}>Not supplied</Pill>
        )}
      </div>

      {supplied ? (
        <div style={{ display: "flex", gap: 22, paddingTop: 16, borderTop: "1px solid var(--dash-line)" }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div
              style={{
                fontSize: 10.5,
                fontWeight: 700,
                letterSpacing: "0.09em",
                textTransform: "uppercase",
                color: "var(--dash-ink-faint)",
              }}
            >
              File
            </div>
            <div
              style={{
                fontFamily: "var(--dash-font-mono)",
                fontSize: 12.5,
                marginTop: 5,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={supplied.origin}
            >
              {filename}
            </div>
          </div>
          <div style={{ flex: "none" }}>
            <div
              style={{
                fontSize: 10.5,
                fontWeight: 700,
                letterSpacing: "0.09em",
                textTransform: "uppercase",
                color: "var(--dash-ink-faint)",
              }}
            >
              Rows
            </div>
            <div
              style={{
                fontFamily: "var(--dash-font-mono)",
                fontSize: 13,
                marginTop: 5,
                fontVariantNumeric: "tabular-nums",
                textAlign: "right",
              }}
            >
              {supplied.rows.toLocaleString("en-IN")}
            </div>
          </div>
          <div style={{ flex: "none", maxWidth: 150 }}>
            <div
              style={{
                fontSize: 10.5,
                fontWeight: 700,
                letterSpacing: "0.09em",
                textTransform: "uppercase",
                color: "var(--dash-ink-faint)",
              }}
            >
              Columns
            </div>
            <div style={{ fontSize: 12, marginTop: 5, color: "var(--dash-ink-soft)" }}>
              {supplied.column_mapping ? "Custom mapping" : "Standard headers"}
            </div>
          </div>
        </div>
      ) : (
        <div style={{ fontSize: 12.5, color: "var(--dash-ink-faint)", paddingTop: 16, borderTop: "1px solid var(--dash-line)" }}>
          Not supplied for this run — see the note above.
        </div>
      )}
    </DashCard>
  );
}
