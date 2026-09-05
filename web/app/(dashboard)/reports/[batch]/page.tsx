"use client";

/**
 * Reports — a summary view of one run, composed entirely from data other
 * screens already fetch (`api.verdict`, `api.actions`, `api.timeline`). No
 * new endpoint, per the plan.
 *
 * Three things the mockup drew that this engine cannot honestly back are cut
 * or replaced:
 *  - "Where issues cluster" was a 70-cell, 10-week weekday heatmap. The API
 *    has no per-weekday, multi-week granularity — `timeline.days` is one
 *    series for THIS run. Rather than invent ten weeks of history, this page
 *    buckets the real days of this run by weekday and says so.
 *  - "Report library" and "Scheduled delivery" assume a report store and an
 *    email-sending system this engine doesn't have. In their place: the one
 *    export that's real today, `GET /api/actions/{batch}/csv`.
 *  - The inline "Copilot: Fridays carry 3x the flags…" line described the
 *    fabricated heatmap. It's replaced by `verdict.summary` — the real,
 *    already-guarded prose the engine writes for this run — with the same
 *    model/template attribution used elsewhere (ADR-050).
 */

import { use, useEffect, useState } from "react";
import {
  DashCard,
  DASH_TONE,
  SectionLabel,
  ShareBar,
  StatusDot,
  severityOf,
} from "@/components/dash/primitives";
import { useCurrentBatch } from "@/lib/current-batch";
import { api, ApiError, type Actions, type Timeline, type Verdict } from "@/lib/api";

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** `day` is a YYYY-MM-DD string; parsed as UTC midnight so the weekday
 *  bucket never shifts with the viewer's timezone. */
function weekdayIndex(day: string): number {
  const jsDay = new Date(`${day}T00:00:00Z`).getUTCDay(); // 0 = Sunday
  return (jsDay + 6) % 7; // 0 = Monday .. 6 = Sunday
}

export default function ReportsPage({ params }: { params: Promise<{ batch: string }> }) {
  const { batch } = use(params);
  const { setBatch } = useCurrentBatch();
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [actions, setActions] = useState<Actions | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setBatch(batch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setVerdict(null);
    setTimeline(null);
    setActions(null);
    api.verdict(batch).then((v) => !cancelled && setVerdict(v)).catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : String(e)));
    api.timeline(batch).then((t) => !cancelled && setTimeline(t)).catch(() => !cancelled && setTimeline(null));
    api.actions(batch).then((a) => !cancelled && setActions(a)).catch(() => !cancelled && setActions(null));
    return () => {
      cancelled = true;
    };
  }, [batch]);

  if (error) {
    return (
      <div style={{ maxWidth: 640 }}>
        <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 32, fontWeight: 400, margin: "0 0 10px" }}>
          Can&rsquo;t reach the engine
        </h1>
        <p style={{ color: "var(--dash-ink-soft)", fontSize: 14 }}>{error}</p>
      </div>
    );
  }

  if (!verdict) {
    return <div style={{ color: "var(--dash-ink-faint)", fontSize: 13 }}>Loading report…</div>;
  }

  const lines = verdict.lines;
  const live = lines.filter((l) => l.amount.paise > 0);
  const offsets = lines.filter((l) => l.amount.paise < 0);
  const drawn = live.reduce((s, l) => s + l.amount.paise, 0);

  const days = timeline?.days ?? [];
  const weekdayOrders = Array(7).fill(0);
  for (const d of days) weekdayOrders[weekdayIndex(d.day)] += d.orders;
  const maxWeekdayOrders = Math.max(1, ...weekdayOrders);

  return (
    <div style={{ maxWidth: 1180 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.012em", margin: "0 0 8px" }}>
          Reports
        </h1>
        <p style={{ fontSize: 14, color: "var(--dash-ink-soft)", margin: 0 }}>
          {batch} — what actually happened this cycle, built only from what the engine
          already computed.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 16, marginBottom: 16 }}>
        {/* --------------------------------------------------------- gap by cause */}
        <DashCard style={{ padding: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 20 }}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700 }}>Gap by cause</div>
              <div style={{ fontSize: 12.5, color: "var(--dash-ink-faint)", marginTop: 3 }}>This run</div>
            </div>
            <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 12, color: "var(--dash-ink-faint)" }}>
              {verdict.gap.display} total
            </div>
          </div>

          {live.length === 0 && offsets.length === 0 && (
            <div style={{ fontSize: 13, color: "var(--dash-ink-faint)", fontStyle: "italic" }}>Nothing to explain.</div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {live
              .slice()
              .sort((a, b) => b.amount.paise - a.amount.paise)
              .map((l) => {
                const severity = severityOf(l);
                const pct = drawn > 0 ? Math.round((l.amount.paise / drawn) * 100) : 0;
                return (
                  <div key={l.classification}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 7, gap: 10 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "oklch(0.30 0.027 68)", minWidth: 0 }}>{l.label}</div>
                      <div style={{ display: "flex", alignItems: "baseline", gap: 9, flex: "none" }}>
                        <span style={{ fontFamily: "var(--dash-font-mono)", fontSize: 13, fontWeight: 600, color: DASH_TONE[severity] }}>
                          {l.amount.display}
                        </span>
                        <span style={{ fontSize: 11, fontFamily: "var(--dash-font-mono)", color: "var(--dash-ink-faint)" }}>{pct}%</span>
                      </div>
                    </div>
                    <ShareBar fraction={drawn > 0 ? l.amount.paise / drawn : 0} severity={severity} height={8} />
                  </div>
                );
              })}
          </div>

          {offsets.length > 0 && (
            <div style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--dash-line-soft)", display: "flex", flexDirection: "column", gap: 8 }}>
              {offsets.map((l) => (
                <div key={l.classification} style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 12, color: "var(--dash-ink-faint)" }}>
                  <span
                    aria-hidden
                    style={{ width: 9, height: 9, flex: "none", borderRadius: 2, border: "1px dashed var(--dash-ink-faint)" }}
                  />
                  <span style={{ minWidth: 0 }}>{l.label}</span>
                  <span style={{ fontFamily: "var(--dash-font-mono)", color: "var(--dash-ink-soft)" }}>{l.amount.display}</span>
                  <span>offsets the gap</span>
                </div>
              ))}
            </div>
          )}
        </DashCard>

        {/* --------------------------------------------------------- weekday distribution */}
        <DashCard style={{ padding: 24 }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Where issues cluster</div>
          <div style={{ fontSize: 12.5, color: "var(--dash-ink-faint)", marginTop: 3, marginBottom: 20 }}>
            Orders by weekday, this run only — {days.length} day{days.length === 1 ? "" : "s"} of history, not a
            multi-week trend
          </div>

          {days.length === 0 ? (
            <div style={{ fontSize: 13, color: "var(--dash-ink-faint)", fontStyle: "italic" }}>No dated activity to chart.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {WEEKDAY_LABELS.map((label, i) => {
                const count = weekdayOrders[i];
                const pct = Math.max(0, Math.min(1, count / maxWeekdayOrders));
                return (
                  <div key={label} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ width: 28, flex: "none", fontSize: 11, fontFamily: "var(--dash-font-mono)", color: "var(--dash-ink-faint)" }}>
                      {label}
                    </span>
                    <div style={{ flex: 1, height: 9, borderRadius: 999, background: "var(--dash-line-soft)", overflow: "hidden" }}>
                      <div
                        style={{
                          height: "100%",
                          width: `${pct * 100}%`,
                          borderRadius: 999,
                          background: count > 0 ? "var(--dash-action-soft)" : "transparent",
                        }}
                      />
                    </div>
                    <span style={{ width: 26, flex: "none", textAlign: "right", fontSize: 11, fontFamily: "var(--dash-font-mono)", color: "var(--dash-ink-faint)" }}>
                      {count}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {verdict.summary && (
            <div style={{ marginTop: 20, paddingTop: 18, borderTop: "1px solid var(--dash-line-soft)" }}>
              <div style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--dash-ink-soft)" }}>{verdict.summary}</div>
              <div style={{ fontSize: 11, color: "var(--dash-ink-faint)", marginTop: 8 }}>
                {verdict.summary_source === "model"
                  ? "Written by a language model. Every figure on this page is computed by the engine."
                  : "Template-generated, not a model. Every figure on this page is computed by the engine."}
              </div>
            </div>
          )}
        </DashCard>
      </div>

      {/* --------------------------------------------------------- the one real export */}
      <SectionLabel style={{ margin: "32px 0 14px" }}>Export</SectionLabel>
      <DashCard style={{ padding: "20px 22px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
          <StatusDot severity={actions && actions.chase_total.paise > 0 ? "action" : "benign"} size={9} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>Actionable worklist (CSV)</div>
            <div style={{ fontSize: 12.5, color: "var(--dash-ink-faint)", marginTop: 5, maxWidth: 480, lineHeight: 1.5 }}>
              {actions
                ? `${actions.count} order${actions.count === 1 ? "" : "s"}, ${actions.chase_total.display} worth chasing. `
                : ""}
              The one export this engine actually has — a report library and scheduled
              email delivery would need a backing store this build doesn&rsquo;t have.
            </div>
          </div>
        </div>
        <a
          href={api.actionsCsvUrl(batch)}
          style={{
            flex: "none",
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            background: "var(--dash-benign-soft)",
            color: "oklch(0.30 0.06 148)",
            borderRadius: 9,
            padding: "10px 16px",
            fontSize: 12.5,
            fontWeight: 700,
          }}
        >
          Download CSV
        </a>
      </DashCard>
    </div>
  );
}
