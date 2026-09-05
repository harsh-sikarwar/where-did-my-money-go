"use client";

/**
 * Overview — the dashboard's front door, replacing the old mode-select
 * landing page. Everything here is the featured run's own numbers
 * (`useCurrentBatch`, same "first listed = latest" convention the old
 * landing page used) plus a short list of other runs. No client-side money
 * arithmetic (ADR-001) — every figure is a `Money.display` from the API.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  DASH_TONE,
  DashCard,
  KpiCard,
  SectionLabel,
  StatusDot,
  type Severity,
  severityOf,
} from "@/components/dash/primitives";
import { useCurrentBatch } from "@/lib/current-batch";
import { api, ApiError, type Correlation, type Timeline, type Verdict } from "@/lib/api";
import { GapTrendChart } from "@/components/dash/charts";
import { CorrelationBand } from "@/components/dash/Correlation";

type BatchRow = { name: string; uploaded: boolean; generated: boolean };

const RECENT_LIMIT = 5;

export default function Overview() {
  const { batch: featured } = useCurrentBatch();
  const [batches, setBatches] = useState<BatchRow[]>([]);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [correlation, setCorrelation] = useState<Correlation | null>(null);
  const [rowVerdicts, setRowVerdicts] = useState<Record<string, Verdict | null>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .batches()
      .then((r) => {
        if (!cancelled) setBatches(r.batches);
      })
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!featured) return;
    let cancelled = false;
    api.verdict(featured).then((v) => !cancelled && setVerdict(v)).catch(() => {});
    api.timeline(featured).then((t) => !cancelled && setTimeline(t)).catch(() => {});
    api.correlation(featured).then((c) => !cancelled && setCorrelation(c)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [featured]);

  const recent = batches.slice(0, RECENT_LIMIT);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      for (const b of recent) {
        if (rowVerdicts[b.name] !== undefined) continue;
        try {
          const v = await api.verdict(b.name);
          if (!cancelled) setRowVerdicts((prev) => ({ ...prev, [b.name]: v }));
        } catch {
          if (!cancelled) setRowVerdicts((prev) => ({ ...prev, [b.name]: null }));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batches]);

  if (error) {
    return (
      <div style={{ maxWidth: 640 }}>
        <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 32, fontWeight: 400, margin: "0 0 10px" }}>
          Can't reach the engine
        </h1>
        <p style={{ color: "var(--dash-ink-soft)", fontSize: 14 }}>{error}</p>
      </div>
    );
  }

  if (batches.length === 0) {
    return (
      <div style={{ maxWidth: 640 }}>
        <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 40, fontWeight: 400, margin: "0 0 10px" }}>
          No runs yet.
        </h1>
        <p style={{ color: "var(--dash-ink-soft)", fontSize: 14.5, marginBottom: 22 }}>
          Upload your ledger and settlement files, or generate a scenario to see this
          dashboard populated with a real run.
        </p>
        <Link
          href="/new-run"
          style={{
            display: "inline-flex",
            background: "var(--dash-benign-soft)",
            color: "oklch(0.30 0.06 148)",
            borderRadius: 10,
            padding: "12px 20px",
            fontWeight: 700,
            fontSize: 14,
          }}
        >
          Start a reconciliation
        </Link>
      </div>
    );
  }

  const gapPct =
    verdict && verdict.expected.paise > 0
      ? (verdict.gap.paise / verdict.expected.paise) * 100
      : null;
  const matchRate = verdict ? verdict.match.pass1.match_rate : null;

  const lines = verdict?.lines.filter((l) => l.actionable) ?? [];
  const donutSegments = (verdict?.lines ?? [])
    .filter((l) => l.amount.paise > 0)
    .map((l) => ({ label: l.label, paise: l.amount.paise, amount: l.amount.display, severity: severityOf(l) }));

  return (
    <div style={{ maxWidth: 1180 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 24, flexWrap: "wrap", marginBottom: 30 }}>
        <div>
          <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 46, fontWeight: 400, letterSpacing: "-0.012em", lineHeight: 1.05, margin: 0 }}>
            Where did your money go?
          </h1>
          {verdict && (
            <p style={{ fontSize: 14.5, color: "var(--dash-ink-soft)", margin: "11px 0 0" }}>
              {featured} closed most recently.{" "}
              {verdict.actionable_total.paise > 0 ? (
                <span style={{ color: "var(--dash-action)", fontWeight: 600 }}>
                  {verdict.actionable_total.display} needs a decision.
                </span>
              ) : (
                <span style={{ color: "var(--dash-benign)", fontWeight: 600 }}>Nothing needs a decision.</span>
              )}
            </p>
          )}
        </div>
      </div>

      {verdict && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14, marginBottom: 16 }}>
            <KpiCard
              label="Unmatched gap"
              value={verdict.gap.display}
              tone="var(--dash-action)"
              sub={gapPct !== null ? `${gapPct < 0.01 ? "<0.01" : gapPct.toFixed(2)}% of expected` : undefined}
            />
            <KpiCard
              label="Needs a decision"
              value={verdict.actionable_total.display}
              tone={verdict.actionable_total.paise > 0 ? "var(--dash-urgent)" : "var(--dash-benign)"}
              sub={`${lines.length} line${lines.length === 1 ? "" : "s"} actionable`}
            />
            <KpiCard
              label="Order match rate"
              value={matchRate !== null ? `${(matchRate * 100).toFixed(1)}%` : "—"}
              sub={`${verdict.match.pass1.matched} / ${verdict.match.pass1.total} orders`}
            />
            {/* The fourth slot was "rows processed / rows per second" — a number about
                us, in the row a merchant scans first. Throughput is still on the
                analysis screen and on every run row; this slot now carries the one
                measurement no reconciliation tool alone can produce. */}
            <KpiCard
              label="Explained by correlation"
              value={
                !correlation
                  ? "—"
                  : correlation.before.paise === 0
                    ? "n/a"
                    : `${(correlation.gain_ratio * 100).toFixed(1)}%`
              }
              tone="var(--dash-benign)"
              sub={
                !correlation
                  ? undefined
                  : correlation.before.paise === 0
                    ? "nothing was left unexplained to correlate"
                    : `${correlation.resolved.display} of ${correlation.before.display} unexplained`
              }
            />
          </div>

          {/* The differentiator, in the first position that has a shape. Everything
              above this is reconciliation, which every tool in the category does;
              this is the part that reads the payment records the reconciler never
              opens. It goes above the trend chart deliberately. */}
          {correlation && <CorrelationBand data={correlation} />}

          <div style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 14, marginBottom: 16 }}>
            <DashCard style={{ padding: "22px 24px 16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 700 }}>Gap trend</div>
                  <div style={{ fontSize: 12.5, color: "var(--dash-ink-faint)", marginTop: 3 }}>
                    Daily gap vs. expected value
                  </div>
                </div>
                <div style={{ display: "flex", gap: 14, fontSize: 11.5, color: "oklch(0.43 0.024 74)" }}>
                  <Legend color="var(--dash-benign)" label="Expected" />
                  <Legend color="var(--dash-action)" label="Gap" />
                </div>
              </div>
              {timeline && timeline.days.length > 1 ? (
                <GapTrendChart timeline={timeline} />
              ) : (
                <div style={{ height: 212, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--dash-ink-faint)", fontSize: 13 }}>
                  Not enough days to chart yet.
                </div>
              )}
            </DashCard>

            <DashCard style={{ padding: "22px 24px" }}>
              <div style={{ fontSize: 15, fontWeight: 700 }}>Where the gap sits</div>
              <div style={{ display: "flex", alignItems: "center", gap: 20, margin: "18px 0 20px" }}>
                <Donut segments={donutSegments} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 24, fontWeight: 600 }}>
                    {matchRate !== null ? `${(matchRate * 100).toFixed(2)}%` : "—"}
                  </div>
                  <div style={{ fontSize: 12.5, color: "var(--dash-ink-faint)", marginTop: 4, lineHeight: 1.45 }}>
                    of orders matched cleanly
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                {donutSegments.length === 0 && <div style={{ fontSize: 12.5, color: "var(--dash-ink-faint)" }}>Nothing unexplained.</div>}
                {donutSegments.map((d) => (
                  <div key={d.label} style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 12.5, color: "oklch(0.41 0.024 74)" }}>
                    <StatusDot severity={d.severity} size={8} />
                    {d.label}
                    <span style={{ marginLeft: "auto", fontFamily: "var(--dash-font-mono)", color: "oklch(0.29 0.027 68)" }}>
                      {d.amount}
                    </span>
                  </div>
                ))}
              </div>
            </DashCard>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 }}>
                <SectionLabel>Needs attention</SectionLabel>
                {featured && (
                  <Link href={`/analysis/${encodeURIComponent(featured)}`} style={{ fontSize: 12.5, fontWeight: 600, color: "oklch(0.43 0.024 74)" }}>
                    Open analysis →
                  </Link>
                )}
              </div>
              {lines.length === 0 && <EmptyCard>Nothing needs you this week.</EmptyCard>}
              {lines
                .sort((a, b) => b.amount.paise - a.amount.paise)
                .slice(0, 4)
                .map((l) => (
                  <DashCard key={l.classification} style={{ padding: "14px 16px", marginBottom: 8, display: "flex", alignItems: "center", gap: 14 }}>
                    <StatusDot severity={severityOf(l)} />
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.35 }}>{l.label}</div>
                      <div style={{ fontSize: 12, color: "var(--dash-ink-faint)", marginTop: 4 }}>
                        {l.count} order{l.count === 1 ? "" : "s"}
                      </div>
                    </div>
                    <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 13.5, fontWeight: 600, color: severityOf(l) === "urgent" ? "var(--dash-urgent)" : "var(--dash-action)" }}>
                      {l.amount.display}
                    </div>
                  </DashCard>
                ))}
            </div>

            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 }}>
                <SectionLabel>Recent runs</SectionLabel>
                <Link href="/runs" style={{ fontSize: 12.5, fontWeight: 600, color: "oklch(0.43 0.024 74)" }}>
                  All runs →
                </Link>
              </div>
              <DashCard style={{ overflow: "hidden" }}>
                {recent.map((b) => {
                  const v = rowVerdicts[b.name];
                  return (
                    <Link
                      key={b.name}
                      href={`/analysis/${encodeURIComponent(b.name)}`}
                      className="dash-row"
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 14,
                        padding: "14px 16px",
                        borderBottom: "1px solid var(--dash-line-soft)",
                      }}
                    >
                      <StatusDot severity={v ? (v.actionable_total.paise > 0 ? "action" : "benign") : "neutral"} />
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                          {b.name}
                        </div>
                        <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 11, color: "var(--dash-ink-faint)", marginTop: 3 }}>
                          {b.generated ? "generated" : b.uploaded ? "uploaded" : "seeded"}
                          {v ? ` · ${v.performance.rows_processed} orders` : ""}
                        </div>
                      </div>
                      <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 12.5, color: v ? undefined : "var(--dash-ink-faint)" }}>
                        {v === undefined ? "…" : v === null ? "unreadable" : v.gap.display}
                      </div>
                    </Link>
                  );
                })}
              </DashCard>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 13, height: 2, background: color, display: "inline-block" }} />
      {label}
    </span>
  );
}

function EmptyCard({ children }: { children: React.ReactNode }) {
  return (
    <DashCard style={{ padding: "18px 16px", fontSize: 13, color: "var(--dash-ink-faint)", fontStyle: "italic" }}>
      {children}
    </DashCard>
  );
}

/** Share of the gap by classification — same shape as `GapComposition`'s bar,
 *  drawn as a ring instead of a track. */
function Donut({
  segments,
}: {
  segments: { label: string; paise: number; severity: Severity }[];
}) {
  const r = 40;
  const c = 2 * Math.PI * r;
  const total = segments.reduce((s, d) => s + d.paise, 0);
  let offset = 0;
  return (
    <svg viewBox="0 0 100 100" style={{ width: 112, height: 112, flex: "none", transform: "rotate(-90deg)" }}>
      <circle cx={50} cy={50} r={r} fill="none" stroke="oklch(0.5 0.045 72 / 0.12)" strokeWidth={13} />
      {total > 0 &&
        segments.map((s) => {
          const dash = (s.paise / total) * c;
          const el = (
            <circle
              key={s.label}
              cx={50}
              cy={50}
              r={r}
              fill="none"
              stroke={DASH_TONE[s.severity]}
              strokeWidth={13}
              strokeDasharray={`${dash} ${c - dash}`}
              strokeDashoffset={-offset}
            />
          );
          offset += dash;
          return el;
        })}
    </svg>
  );
}
