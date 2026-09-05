"use client";

/**
 * Analysis — a run's full breakdown: Summary / Line items / Evidence.
 *
 * The single largest screen in the rebuild, direct supersede of the old
 * `Verdict`/`Correlation`/`Actions`/`ExpectedVsReceived`/`GapByDay`/`RateCard`
 * stack (see `/home/harsh/.claude/plans/fancy-sniffing-rossum.md`). Data
 * shaping is ported from those components; the visuals are rebuilt to match
 * the "Reconciliation tool" mockup (recon-tool.dc.html, lines 305-560) with
 * `--dash-*` tokens and inline styles, not Tailwind.
 *
 * ADR-001 still applies here: every money figure rendered is a `Money.display`
 * from the API. Nothing in this file adds, subtracts or divides paise.
 */

import Link from "next/link";
import { use, useEffect, useMemo, useState } from "react";
import { shortDay } from "@/components/GapByDay";
import { CorrelationBand } from "@/components/dash/Correlation";
import {
  DASH_TONE,
  DashButton,
  DashCard,
  DashTabs,
  EmptyNote,
  Pill,
  SectionLabel,
  SparkleIcon,
  StatusDot,
  dashToneAlpha,
  severityOf,
  type Severity,
} from "@/components/dash/primitives";
import { useCurrentBatch } from "@/lib/current-batch";
import {
  api,
  ApiError,
  type ActionGroup,
  type Actions,
  type Audit,
  type Correlation,
  type Detail,
  type RateCard,
  type Timeline,
  type TimelineDay,
  type Verdict,
  type VerdictLine,
} from "@/lib/api";

type TabKey = "summary" | "lines" | "evidence";

function askHref(batch: string, question: string): string {
  return `/copilot/${encodeURIComponent(batch)}?ask=${encodeURIComponent(question)}`;
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "just now";
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function hhmmss(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("en-IN", { hour12: false });
}

/** The engine already names each classification (`VerdictLine.label`); an
 *  `ActionGroup` carries only the classification code, so this looks the
 *  human label up from the verdict rather than re-deriving one. */
function labelForClassification(cls: string, verdict: Verdict): string {
  const line = verdict.lines.find((l) => l.classification === cls);
  if (line) return line.label;
  return cls.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export default function AnalysisPage({
  params,
}: {
  params: Promise<{ batch: string }>;
}) {
  const { batch } = use(params);
  const { setBatch } = useCurrentBatch();

  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [actions, setActions] = useState<Actions | null>(null);
  const [rateCard, setRateCard] = useState<RateCard | null>(null);
  const [audit, setAudit] = useState<Audit | null>(null);
  const [correlation, setCorrelation] = useState<Correlation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("summary");

  useEffect(() => {
    setBatch(batch);
  }, [batch, setBatch]);

  useEffect(() => {
    let cancelled = false;
    setVerdict(null);
    setTimeline(null);
    setActions(null);
    setRateCard(null);
    setAudit(null);
    setCorrelation(null);
    setError(null);
    setTab("summary");

    api
      .verdict(batch)
      .then((v) => !cancelled && setVerdict(v))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Something went wrong."));
    api.timeline(batch).then((t) => !cancelled && setTimeline(t)).catch(() => {});
    api.actions(batch).then((a) => !cancelled && setActions(a)).catch(() => {});
    api.rateCard().then((r) => !cancelled && setRateCard(r)).catch(() => {});
    api.audit(batch).then((a) => !cancelled && setAudit(a)).catch(() => {});
    api.correlation(batch).then((c) => !cancelled && setCorrelation(c)).catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [batch]);

  if (error) {
    return (
      <div style={{ maxWidth: 640 }}>
        <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 32, fontWeight: 400, margin: "0 0 10px" }}>
          Can&rsquo;t open this run
        </h1>
        <p style={{ color: "var(--dash-ink-soft)", fontSize: 14 }}>{error}</p>
      </div>
    );
  }

  if (!verdict) {
    return <div style={{ color: "var(--dash-ink-faint)", fontSize: 13 }}>Loading run…</div>;
  }

  const issueCount = verdict.lines.filter((l) => l.actionable).length;

  return (
    <div style={{ maxWidth: 1120 }}>
      {/* ---------------------------------------------------------- header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24, flexWrap: "wrap", marginBottom: 26 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <Pill tone={issueCount > 0 ? "action" : "benign"}>
              {issueCount} {issueCount === 1 ? "ISSUE" : "ISSUES"} OPEN
            </Pill>
            <span style={{ fontFamily: "var(--dash-font-mono)", fontSize: 11.5, color: "var(--dash-ink-dim)" }}>
              {audit ? `closed ${timeAgo(audit.manifest.created_at)} · ` : ""}
              {Math.round(verdict.performance.elapsed_seconds * 1000)}ms
            </span>
          </div>
          <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.012em", margin: 0 }}>
            {batch}
          </h1>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href={`/reports/${encodeURIComponent(batch)}`}>
            <DashButton variant="secondary">Build report</DashButton>
          </Link>
          <Link href={askHref(batch, "Explain this run")}>
            <DashButton variant="ai">
              <SparkleIcon size={13} /> Explain this run
            </DashButton>
          </Link>
        </div>
      </div>

      <div style={{ marginBottom: 30 }}>
        <DashTabs
          tabs={[
            { key: "summary", label: "Summary" },
            { key: "lines", label: "Line items" },
            { key: "evidence", label: "Evidence" },
          ]}
          active={tab}
          onChange={(k) => setTab(k as TabKey)}
        />
      </div>

      {tab === "summary" && <SummaryTab batch={batch} verdict={verdict} timeline={timeline} actions={actions} audit={audit} correlation={correlation} />}
      {tab === "lines" && <LineItemsTab batch={batch} verdict={verdict} />}
      {tab === "evidence" && <EvidenceTab rateCard={rateCard} audit={audit} />}
    </div>
  );
}

/* ==================================================================== SUMMARY */

function SummaryTab({
  batch,
  verdict,
  timeline,
  actions,
  audit,
  correlation,
}: {
  batch: string;
  verdict: Verdict;
  timeline: Timeline | null;
  actions: Actions | null;
  audit: Audit | null;
  correlation: Correlation | null;
}) {
  const gapPct =
    verdict.expected.paise > 0
      ? (verdict.gap.paise / verdict.expected.paise) * 100
      : null;

  const sourceCount = audit ? Object.keys(audit.manifest.sources).length : null;

  const suggestions = useMemo(() => {
    const qs = [{ label: "Explain this run", q: "Explain this run" }];
    const topLine = [...verdict.lines].filter((l) => l.actionable).sort((a, b) => b.amount.paise - a.amount.paise)[0];
    if (topLine) qs.push({ label: `Explain "${topLine.label}"`, q: `Explain the "${topLine.label}" line` });
    if (verdict.late) qs.push({ label: "Why are payouts late?", q: "Why did payouts arrive late this cycle?" });
    else qs.push({ label: "What changed vs. last cycle?", q: "What changed in this cycle compared to the last one?" });
    return qs.slice(0, 3);
  }, [verdict]);

  return (
    <div>
      {/* KPI trio */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1.4fr", gap: 22, alignItems: "end", marginBottom: 30 }}>
        <div style={{ animation: "fadeUp .5s cubic-bezier(.2,.7,.2,1) .05s both" }}>
          <SectionLabel style={{ marginBottom: 11 }}>Expected</SectionLabel>
          <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 29, fontWeight: 400, fontVariantNumeric: "tabular-nums" }}>
            {verdict.expected.display}
          </div>
        </div>
        <div style={{ animation: "fadeUp .5s cubic-bezier(.2,.7,.2,1) .1s both" }}>
          <SectionLabel style={{ marginBottom: 11 }}>Received</SectionLabel>
          <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 29, fontWeight: 400, fontVariantNumeric: "tabular-nums" }}>
            {verdict.received.display}
          </div>
        </div>
        <div style={{ animation: "fadeUp .5s cubic-bezier(.2,.7,.2,1) .16s both" }}>
          <SectionLabel style={{ marginBottom: 11, color: "var(--dash-action)" }}>Unmatched gap</SectionLabel>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 14, flexWrap: "wrap" }}>
            <div
              style={{
                fontFamily: "var(--dash-font-mono)",
                fontSize: 54,
                fontWeight: 600,
                fontVariantNumeric: "tabular-nums",
                letterSpacing: "-0.02em",
                lineHeight: 0.95,
                color: "var(--dash-action)",
              }}
            >
              {verdict.gap.display}
            </div>
            {gapPct !== null && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingBottom: 5 }}>
                <Pill tone="action">{gapPct < 0.01 ? "<0.01" : gapPct.toFixed(2)}% of expected</Pill>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* AI explanation card */}
      <div
        style={{
          position: "relative",
          background: "linear-gradient(150deg, color-mix(in oklch, var(--dash-accent) 11%, transparent), color-mix(in oklch, var(--dash-accent) 3%, transparent))",
          border: "1px solid color-mix(in oklch, var(--dash-accent) 28%, transparent)",
          borderRadius: 16,
          padding: "22px 24px",
          marginBottom: 34,
          animation: "fadeUp .5s cubic-bezier(.2,.7,.2,1) .22s both",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 14 }}>
          <span
            style={{
              width: 24,
              height: 24,
              borderRadius: 7,
              background: "var(--dash-benign)",
              color: "oklch(0.985 0.014 88)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flex: "none",
              animation: "floatY 4s ease-in-out infinite",
            }}
          >
            <SparkleIcon size={14} />
          </span>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--dash-accent-deep)" }}>Copilot read this run</div>
          <span style={{ fontFamily: "var(--dash-font-mono)", fontSize: 10.5, color: "var(--dash-ink-faint)", marginLeft: "auto" }}>
            {verdict.performance.rows_processed.toLocaleString("en-IN")} rows
            {sourceCount !== null ? ` · ${sourceCount} source${sourceCount === 1 ? "" : "s"}` : ""}
          </span>
        </div>
        <p style={{ fontSize: 15.5, lineHeight: 1.6, margin: "0 0 16px", maxWidth: 760 }}>
          {verdict.summary ?? verdict.headline}
        </p>
        {verdict.summary && verdict.summary_source === "template" && (
          <p style={{ fontSize: 11.5, color: "var(--dash-ink-faint)", margin: "-10px 0 16px" }}>
            Written from a template, not a model — no LLM configured for this run.
          </p>
        )}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {suggestions.map((s) => (
            <Link
              key={s.label}
              href={askHref(batch, s.q)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                background: "color-mix(in oklch, var(--dash-raised) 75%, transparent)",
                border: "1px solid color-mix(in oklch, var(--dash-accent) 30%, transparent)",
                borderRadius: 999,
                padding: "8px 14px",
                fontSize: 12.5,
                color: "var(--dash-accent-deep)",
              }}
            >
              {s.label} <span style={{ opacity: 0.5 }}>→</span>
            </Link>
          ))}
        </div>
      </div>

      {/* Before the waterfall, not after. The waterfall explains the gap using the
          settlement file alone; this explains what that file could never have said,
          and burying it under a chart every competitor also draws would be the wrong
          order to read them in. */}
      {correlation && <CorrelationBand data={correlation} />}

      <Waterfall verdict={verdict} />

      {timeline && timeline.days.length > 1 && <DailyGapChart timeline={timeline} />}

      <WhatNeedsYou batch={batch} verdict={verdict} actions={actions} />
    </div>
  );
}

function Waterfall({ verdict }: { verdict: Verdict }) {
  const steps = useMemo(() => {
    const scale = Math.max(
      verdict.expected.paise,
      verdict.received.paise,
      ...verdict.lines.map((l) => Math.abs(l.amount.paise)),
      1,
    );
    const out: { label: string; amount: string; paise: number; tone: string }[] = [
      { label: "Expected", amount: verdict.expected.display, paise: verdict.expected.paise, tone: "var(--dash-ink)" },
      ...verdict.lines.map((l) => ({
        label: l.label,
        amount: l.amount.display,
        paise: Math.abs(l.amount.paise),
        tone: DASH_TONE[severityOf(l)],
      })),
      { label: "Received", amount: verdict.received.display, paise: verdict.received.paise, tone: "var(--dash-benign)" },
    ];
    return { steps: out, scale };
  }, [verdict]);

  return (
    <DashCard style={{ padding: "22px 24px 18px", marginBottom: 16, animation: "fadeUp .5s cubic-bezier(.2,.7,.2,1) .28s both" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 22 }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>Expected → received, step by step</div>
        <div style={{ fontSize: 12, color: "var(--dash-ink-dim)" }}>each bar is the size of one cause</div>
      </div>
      <div style={{ display: "flex", gap: 10, height: 190, alignItems: "stretch" }}>
        {steps.steps.map((s, i) => (
          <div key={`${s.label}-${i}`} style={{ flex: 1, position: "relative", display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>
            <div
              style={{
                height: Math.max(6, (s.paise / steps.scale) * 130),
                borderRadius: "5px 5px 2px 2px",
                background: s.tone,
                animation: `growY .6s cubic-bezier(.2,.7,.2,1) ${0.3 + i * 0.04}s both`,
                transformOrigin: "bottom",
              }}
            />
            <div style={{ paddingTop: 8 }}>
              <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 12, fontWeight: 600, fontVariantNumeric: "tabular-nums", color: s.tone }}>
                {s.amount}
              </div>
              <div style={{ fontSize: 11, color: "var(--dash-ink-faint)", marginTop: 4, lineHeight: 1.3 }}>{s.label}</div>
            </div>
          </div>
        ))}
      </div>
    </DashCard>
  );
}

const MIN_BAR_PCT = 6;

function dayTone(day: TimelineDay, peakDay: string | null): Severity {
  if (day.amount.paise < 0) return "benign";
  if (day.actionable.paise !== 0) return day.day === peakDay ? "urgent" : "action";
  return "neutral";
}

function DailyGapChart({ timeline }: { timeline: Timeline }) {
  const [hover, setHover] = useState<number | null>(null);

  const bars = useMemo(() => {
    const max = Math.max(...timeline.days.map((d) => Math.abs(d.amount.paise)), 1);
    const peakDay = timeline.peak?.day ?? null;
    return timeline.days.map((day) => ({
      day,
      empty: day.amount.paise === 0,
      heightPct: Math.max(MIN_BAR_PCT, (Math.abs(day.amount.paise) / max) * 100),
      tone: dayTone(day, peakDay),
    }));
  }, [timeline]);

  const hovered = hover === null ? null : bars[hover].day;
  const readout = hovered
    ? `${shortDay(hovered.day)} · ${hovered.amount.display}${hovered.orders ? ` · ${hovered.orders} order${hovered.orders === 1 ? "" : "s"}` : ""}`
    : timeline.peak
      ? `worst day ${timeline.peak.amount.display} on ${shortDay(timeline.peak.day)}`
      : "no single day dominates";
  const readoutTone = hovered ? DASH_TONE[dayTone(hovered, timeline.peak?.day ?? null)] : "var(--dash-ink-soft)";

  const first = timeline.days[0].day;
  const last = timeline.days[timeline.days.length - 1].day;

  return (
    <DashCard style={{ padding: "22px 24px 18px", marginBottom: 38, animation: "fadeUp .5s cubic-bezier(.2,.7,.2,1) .32s both" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 18 }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>Gap by day</div>
        <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 12.5, fontVariantNumeric: "tabular-nums", color: readoutTone }}>{readout}</div>
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 118 }} onMouseLeave={() => setHover(null)}>
        {bars.map((bar, i) => (
          <div
            key={bar.day.day}
            onMouseEnter={() => setHover(i)}
            title={`${shortDay(bar.day.day)} — ${bar.day.amount.display}`}
            style={{
              flex: 1,
              minWidth: 0,
              borderRadius: 3,
              height: bar.empty ? 2 : `${bar.heightPct}%`,
              background: bar.empty ? "var(--dash-line-strong)" : DASH_TONE[bar.tone],
              opacity: hover === null || hover === i ? 1 : 0.45,
              filter: hover === i ? "brightness(1.15)" : undefined,
              transition: "opacity .15s, filter .15s",
              animation: `growY .55s cubic-bezier(.2,.7,.2,1) ${0.35 + i * 0.015}s both`,
              transformOrigin: "bottom",
            }}
          />
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--dash-font-mono)", fontSize: 10.5, color: "var(--dash-ink-dim)", marginTop: 11 }}>
        <span>{shortDay(first)}</span>
        <span>{shortDay(last)}</span>
      </div>
    </DashCard>
  );
}

function WhatNeedsYou({ batch, verdict, actions }: { batch: string; verdict: Verdict; actions: Actions | null }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [reviewed, setReviewed] = useState<Set<string>>(new Set());

  const sorted = useMemo(
    () => (actions ? [...actions.groups].sort((a, b) => Math.abs(b.total.paise) - Math.abs(a.total.paise)) : []),
    [actions],
  );

  useEffect(() => {
    const top = sorted[0];
    if (top) setExpanded(new Set([top.classification]));
  }, [sorted]);

  const maxPaise = Math.abs(sorted[0]?.total.paise ?? 1) || 1;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 18, gap: 16 }}>
        <SectionLabel>What needs you</SectionLabel>
        <a
          href={api.actionsCsvUrl(batch)}
          style={{ fontSize: 12.5, fontWeight: 600, color: "var(--dash-ink-soft)", whiteSpace: "nowrap" }}
        >
          Download worklist
        </a>
      </div>

      {!actions && <EmptyNote>Loading what needs a decision…</EmptyNote>}
      {/* Two different facts, and the empty list only establishes the first. "Nothing to
          chase" is a statement about the action queue; "every rupee is explained" is a
          statement about the residual, and a batch can have an UNEXPLAINED remainder
          with nothing actionable in it — an upload missing its payments feed is the
          ordinary way there. Making the second claim on the strength of the first would
          print the project's central promise as a falsehood on the screen that exists
          to demonstrate it, so the residual is read directly. */}
      {actions && sorted.length === 0 && (
        verdict.unexplained.paise === 0 ? (
          <EmptyNote>
            Nothing needs chasing this cycle — every rupee of the gap is explained.
          </EmptyNote>
        ) : (
          <EmptyNote>
            Nothing here needs chasing — but {verdict.unexplained.display} of the gap
            {verdict.unexplained_count > 0 && (
              <> across {verdict.unexplained_count} order
                {verdict.unexplained_count === 1 ? "" : "s"}</>
            )}{" "}
            is still unexplained. The engine could not attribute it to a cause it can
            prove, which is not the same as there being nothing wrong.
          </EmptyNote>
        )
      )}

      {sorted.map((group, i) => {
        const offset = group.total.paise < 0;
        const top = i === 0 && !offset;
        const severity: Severity = offset ? "neutral" : top ? "urgent" : "action";
        const tone = offset ? "var(--dash-ink-soft)" : DASH_TONE[severity];
        const width = Math.min(Math.abs(group.total.paise) / maxPaise, 1) * 100;
        const isOpen = expanded.has(group.classification);
        const isReviewed = reviewed.has(group.classification);
        const label = labelForClassification(group.classification, verdict);

        return (
          <DashCard key={group.classification} style={{ marginBottom: 10, overflow: "hidden" }}>
            <div
              onClick={() =>
                setExpanded((prev) => {
                  const next = new Set(prev);
                  if (next.has(group.classification)) next.delete(group.classification);
                  else next.add(group.classification);
                  return next;
                })
              }
              style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: 20, cursor: "pointer", gap: 16 }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 13, minWidth: 0 }}>
                {isReviewed ? (
                  <span
                    style={{
                      flex: "none",
                      border: "1px solid var(--dash-line-strong)",
                      color: "var(--dash-ink-faint)",
                      fontSize: 10,
                      fontWeight: 800,
                      letterSpacing: "0.06em",
                      borderRadius: 5,
                      padding: "3px 7px",
                    }}
                  >
                    DONE
                  </span>
                ) : (
                  top && (
                    <span
                      style={{
                        flex: "none",
                        background: "var(--dash-urgent)",
                        color: "oklch(0.985 0.014 88)",
                        fontSize: 10,
                        fontWeight: 800,
                        letterSpacing: "0.06em",
                        borderRadius: 5,
                        padding: "3px 7px",
                        animation: "ring 2.8s ease-out infinite",
                      }}
                    >
                      TOP
                    </span>
                  )
                )}
                <div style={{ display: "flex", flexDirection: "column", gap: 7, minWidth: 0 }}>
                  <div style={{ fontSize: 15, fontWeight: 700, lineHeight: 1.35 }}>{label}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 11.5, fontWeight: 700, borderRadius: 999, padding: "3px 10px", color: tone, background: dashToneAlpha(severity, 0.14) }}>
                      {group.count} {group.count === 1 ? "order" : "orders"}
                    </span>
                    <span style={{ fontSize: 12.5, color: "var(--dash-ink-faint)" }}>{group.next_step}</span>
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 14, flex: "none" }}>
                <Link
                  href={askHref(batch, `Explain "${label}"`)}
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    border: "1px solid color-mix(in oklch, var(--dash-accent) 32%, transparent)",
                    color: "var(--dash-accent-deep)",
                    borderRadius: 999,
                    padding: "6px 12px",
                    fontSize: 11.5,
                    fontWeight: 700,
                    whiteSpace: "nowrap",
                  }}
                >
                  <SparkleIcon size={11} /> Ask
                </Link>
                <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 16, fontWeight: 700, fontVariantNumeric: "tabular-nums", color: tone }}>
                  {group.total.display}
                </div>
              </div>
            </div>
            <div style={{ height: 3, background: "var(--dash-line-soft)" }}>
              <div style={{ height: "100%", width: `${width}%`, background: tone, animation: "growX .8s cubic-bezier(.2,.7,.2,1) .2s both", transformOrigin: "left" }} />
            </div>
            {isOpen && (
              <div style={{ borderTop: "1px solid var(--dash-line)", padding: "8px 20px 14px", animation: "fadeIn .25s ease both" }}>
                {group.items.slice(0, 3).map((it, i) => (
                  <div
                    key={`${it.order_id ?? "row"}-${i}`}
                    className="dash-row"
                    style={{
                      display: "grid",
                      gridTemplateColumns: "88px 1.4fr 1fr 92px",
                      gap: 12,
                      padding: "11px 0",
                      borderBottom: "1px solid var(--dash-line-soft)",
                      fontFamily: "var(--dash-font-mono)",
                      fontSize: 12,
                      color: "var(--dash-ink-soft)",
                      alignItems: "center",
                    }}
                  >
                    <span style={{ fontWeight: 700, color: "var(--dash-ink)" }}>{it.amount.display}</span>
                    <span>{it.email ?? it.contact ?? it.customer_id ?? "—"}</span>
                    <span style={{ color: "var(--dash-accent-deep)" }}>{it.reason ?? group.classification}</span>
                    <span style={{ color: "var(--dash-ink-dim)" }}>{it.order_id ?? "—"}</span>
                  </div>
                ))}
                {group.count > 3 && (
                  <p style={{ fontSize: 11.5, color: "var(--dash-ink-faint)", margin: "10px 0 0" }}>
                    Showing 3 of {group.count} — the CSV has all of them.
                  </p>
                )}
                <div style={{ display: "flex", gap: 10, padding: "16px 0 6px", flexWrap: "wrap" }}>
                  <a href={api.actionsCsvUrl(batch)}>
                    <DashButton
                      size="sm"
                      style={{ background: tone, color: "oklch(0.985 0.014 88)" }}
                    >
                      Download worklist
                    </DashButton>
                  </a>
                  <DashButton
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      setReviewed((prev) => {
                        const next = new Set(prev);
                        if (next.has(group.classification)) next.delete(group.classification);
                        else next.add(group.classification);
                        return next;
                      })
                    }
                  >
                    {isReviewed ? "Reviewed" : "Mark reviewed"}
                  </DashButton>
                  <Link href={askHref(batch, `Draft an email for "${label}"`)}>
                    <DashButton size="sm" style={{ border: "1px solid color-mix(in oklch, var(--dash-accent) 30%, transparent)", color: "var(--dash-accent-deep)", background: "transparent" }}>
                      Draft the email
                    </DashButton>
                  </Link>
                </div>
              </div>
            )}
          </DashCard>
        );
      })}
    </div>
  );
}

/* ==================================================================== LINE ITEMS */

function LineItemsTab({ batch, verdict }: { batch: string; verdict: Verdict }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [details, setDetails] = useState<Record<string, Detail | "loading" | "error">>({});

  const live = verdict.lines.filter((l) => l.amount.paise > 0);
  const offsets = verdict.lines.filter((l) => l.amount.paise < 0);
  const drawn = live.reduce((sum, l) => sum + l.amount.paise, 0);
  const maxAbs = Math.max(...verdict.lines.map((l) => Math.abs(l.amount.paise)), 1);
  const gapPaise = verdict.gap.paise;

  function toggle(line: VerdictLine) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(line.classification)) {
        next.delete(line.classification);
      } else {
        next.add(line.classification);
        if (!details[line.classification]) {
          setDetails((d) => ({ ...d, [line.classification]: "loading" }));
          api
            .detail(batch, line.classification)
            .then((det) => setDetails((d) => ({ ...d, [line.classification]: det })))
            .catch(() => setDetails((d) => ({ ...d, [line.classification]: "error" })));
        }
      }
      return next;
    });
  }

  return (
    <div>
      {/* gap composition strip */}
      <div style={{ marginBottom: 30 }}>
        <div style={{ display: "flex", gap: 3, height: 13, borderRadius: 999, overflow: "hidden" }}>
          {live.map((l, i) => (
            <div
              key={l.classification}
              title={`${l.label} — ${l.amount.display}`}
              style={{
                flex: l.amount.paise,
                background: DASH_TONE[severityOf(l)],
                animation: `growX .7s cubic-bezier(.2,.7,.2,1) ${0.1 + i * 0.07}s both`,
                transformOrigin: "left",
              }}
            />
          ))}
        </div>
        <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginTop: 14 }}>
          {live.map((l) => (
            <div key={l.classification} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--dash-ink-soft)" }}>
              <StatusDot severity={severityOf(l)} />
              {l.label}
              <span style={{ fontFamily: "var(--dash-font-mono)", fontVariantNumeric: "tabular-nums", color: "var(--dash-ink)" }}>{l.amount.display}</span>
              <span className="sr-only">, {drawn > 0 ? Math.round((l.amount.paise / drawn) * 100) : 0}% of the bar</span>
            </div>
          ))}
        </div>
        {offsets.length > 0 && (
          <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginTop: 10 }}>
            {offsets.map((l) => (
              <div key={l.classification} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--dash-ink-faint)" }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, border: "1px dashed var(--dash-ink-faint)", display: "inline-block" }} />
                {l.label}
                <span style={{ fontFamily: "var(--dash-font-mono)", color: "var(--dash-ink-soft)" }}>{l.amount.display}</span>
                offsets the gap
              </div>
            ))}
          </div>
        )}
      </div>

      {verdict.lines.map((line) => {
        const isOpen = expanded.has(line.classification);
        const severity = severityOf(line);
        const share = gapPaise > 0 ? line.amount.paise / gapPaise : 0;
        const width = Math.min(Math.abs(line.amount.paise) / maxAbs, 1) * 100;
        const det = details[line.classification];

        return (
          <DashCard key={line.classification} style={{ marginBottom: 8, overflow: "hidden" }}>
            <div onClick={() => toggle(line)} className="dash-row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: 17, cursor: "pointer", gap: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                <span
                  aria-hidden
                  style={{
                    display: "inline-block",
                    width: 6,
                    height: 6,
                    borderRight: "2px solid var(--dash-ink-faint)",
                    borderBottom: "2px solid var(--dash-ink-faint)",
                    transform: isOpen ? "rotate(225deg)" : "rotate(-45deg)",
                    transition: "transform .2s",
                  }}
                />
                <div style={{ display: "flex", flexDirection: "column", gap: 5, minWidth: 0 }}>
                  <div style={{ fontSize: 14.5, fontWeight: line.actionable ? 700 : 400, lineHeight: 1.35, display: "flex", alignItems: "center", gap: 9 }}>
                    <StatusDot severity={line.actionable ? severity : "neutral"} />
                    {line.label}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--dash-ink-faint)" }}>
                    {line.count} {line.count === 1 ? "order" : "orders"} · {Math.round(share * 100)}% of gap
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 14, flex: "none" }}>
                <div style={{ width: 76, height: 5, borderRadius: 999, background: "var(--dash-line-soft)", overflow: "hidden" }}>
                  <div style={{ width: `${width}%`, height: "100%", background: line.actionable ? DASH_TONE[severity] : "var(--dash-neutral)", borderRadius: 999 }} />
                </div>
                <div
                  style={{
                    fontFamily: "var(--dash-font-mono)",
                    fontSize: 15,
                    fontWeight: line.actionable ? 700 : 400,
                    fontVariantNumeric: "tabular-nums",
                    color: line.actionable ? DASH_TONE[severity] : "var(--dash-ink)",
                    minWidth: 74,
                    textAlign: "right",
                  }}
                >
                  {line.amount.display}
                </div>
              </div>
            </div>
            {isOpen && (
              <div style={{ padding: "0 17px 20px 42px", animation: "fadeIn .25s ease both" }}>
                <p style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--dash-ink-soft)", margin: "0 0 12px", maxWidth: 560 }}>{line.explanation}</p>

                {det === "loading" && <div style={{ fontSize: 12, color: "var(--dash-ink-faint)" }}>Loading findings…</div>}
                {det === "error" && <div style={{ fontSize: 12, color: "var(--dash-urgent)" }}>Could not load findings for this line.</div>}
                {det && det !== "loading" && det !== "error" && (
                  <div style={{ display: "flex", alignItems: "center", gap: 20, flexWrap: "wrap" }}>
                    {det.findings.slice(0, 4).map((f, i) => (
                      <div key={`${f.order_id ?? f.settlement_id ?? "f"}-${i}`} style={{ fontFamily: "var(--dash-font-mono)", fontSize: 12, color: "var(--dash-ink-faint)" }}>
                        {f.order_id ?? f.settlement_id ?? "—"} · {f.amount.display}
                      </div>
                    ))}
                    {det.count > det.findings.slice(0, 4).length && (
                      <span style={{ fontSize: 11.5, color: "var(--dash-ink-faint)" }}>+{det.count - Math.min(4, det.findings.length)} more</span>
                    )}
                    <Link
                      href={askHref(batch, `Explain the "${line.label}" line`)}
                      style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--dash-accent-deep)", fontSize: 12, fontWeight: 700 }}
                    >
                      <SparkleIcon size={11} /> Ask Copilot about this
                    </Link>
                  </div>
                )}
              </div>
            )}
          </DashCard>
        );
      })}

      {verdict.unexplained_count > 0 && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: 17 }}>
          <div>
            <div style={{ fontSize: 14.5, fontStyle: "italic", color: "var(--dash-ink-soft)" }}>Unexplained</div>
            <div style={{ fontSize: 12, color: "var(--dash-ink-faint)", marginTop: 3 }}>
              {verdict.unexplained_count} {verdict.unexplained_count === 1 ? "order" : "orders"}
            </div>
          </div>
          <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 15, fontVariantNumeric: "tabular-nums", color: "var(--dash-ink-soft)" }}>
            {verdict.unexplained.display}
          </div>
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "18px 17px 0", borderTop: "1px solid var(--dash-line-strong)", marginTop: 6, gap: 16 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--dash-ink-soft)" }}>Total accounted — sums to the gap exactly</div>
        <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 16, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{verdict.gap.display}</div>
      </div>
    </div>
  );
}

/* ==================================================================== EVIDENCE */

function EvidenceTab({ rateCard, audit }: { rateCard: RateCard | null; audit: Audit | null }) {
  return (
    <div>
      <SectionLabel style={{ marginBottom: 14 }}>Rate card applied</SectionLabel>
      {!rateCard && <EmptyNote>Loading rate card…</EmptyNote>}
      {rateCard && (
        <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 12, fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--dash-line-strong)" }}>
              <th style={{ padding: "11px 0", textAlign: "left", color: "var(--dash-ink-dim)", fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>Method</th>
              <th style={{ padding: "11px 0", textAlign: "left", color: "var(--dash-ink-dim)", fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>Rate</th>
              <th style={{ padding: "11px 0", textAlign: "right", color: "var(--dash-ink-dim)", fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>Source</th>
            </tr>
          </thead>
          <tbody>
            {rateCard.methods.map((m) => (
              <tr key={m.method} style={{ borderBottom: "1px solid var(--dash-line-soft)" }}>
                <td style={{ padding: "12px 0" }}>{m.method}</td>
                <td style={{ padding: "12px 0", fontFamily: "var(--dash-font-mono)" }}>{m.percent.toFixed(2)}%</td>
                <td
                  style={{
                    padding: "12px 0",
                    textAlign: "right",
                    fontFamily: "var(--dash-font-mono)",
                    fontWeight: m.source === "merchant" ? 700 : 400,
                    color: m.source === "merchant" ? "var(--dash-benign)" : "var(--dash-ink-faint)",
                  }}
                >
                  {m.source === "merchant" ? "yours" : "standard"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {rateCard && (
        <p style={{ fontSize: 12, color: "var(--dash-ink-faint)", marginBottom: 34 }}>
          GST is {(rateCard.gst_rate_bps / 100).toFixed(0)}% on the fee, never on the sale.
          {!rateCard.is_merchant_supplied && " Checked against Razorpay's standard rates — set yours in Settings if you negotiated different ones."}
        </p>
      )}

      <SectionLabel style={{ marginBottom: 14 }}>Audit trail</SectionLabel>
      {!audit && <EmptyNote>Loading audit trail…</EmptyNote>}
      {audit && (
        <div
          style={{
            background: "var(--dash-well)",
            border: "1px solid var(--dash-line)",
            borderRadius: 12,
            padding: "18px 20px",
            display: "flex",
            flexDirection: "column",
            gap: 9,
            fontFamily: "var(--dash-font-mono)",
            fontSize: 12,
            color: "var(--dash-ink-dim)",
          }}
        >
          {audit.events.slice(-8).map((e) => (
            <div key={e.seq}>
              {hhmmss(e.at)} &nbsp;{e.event}
              {e.order_id ? ` · ${e.order_id}` : ""}
            </div>
          ))}
          {audit.events.length === 0 && <div>No events recorded for this run yet.</div>}
          {audit.truncated && (
            <div style={{ color: "var(--dash-ink-faint)" }}>
              showing the last {Math.min(8, audit.events.length)} of {audit.filtered_count}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
