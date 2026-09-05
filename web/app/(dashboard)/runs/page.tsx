"use client";

/**
 * Runs — every batch the engine can read, with the gap it left behind.
 * `api.batches()` lists what's on disk; each row's verdict is fetched
 * lazily so a long list doesn't block on the slowest batch.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { DashCard, StatusDot } from "@/components/dash/primitives";
import { useCurrentBatch } from "@/lib/current-batch";
import { api, type Verdict } from "@/lib/api";

type BatchRow = { name: string; uploaded: boolean; generated: boolean; has_ground_truth: boolean };
type Filter = "all" | "actionable" | "clean";

// The prerenderer has no query string to read `?q=` from, so the `useSearchParams()`
// caller needs its own boundary rather than stalling the whole page.
export default function Runs() {
  return (
    <Suspense fallback={<div style={{ color: "var(--dash-ink-faint)", fontSize: 13 }}>Loading runs…</div>}>
      <RunsInner />
    </Suspense>
  );
}

function RunsInner() {
  const { setBatch } = useCurrentBatch();
  const q = (useSearchParams().get("q") ?? "").toLowerCase();
  const [batches, setBatches] = useState<BatchRow[] | null>(null);
  const [verdicts, setVerdicts] = useState<Record<string, Verdict | null>>({});
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    api.batches().then((r) => setBatches(r.batches));
  }, []);

  useEffect(() => {
    if (!batches) return;
    let cancelled = false;
    (async () => {
      for (const b of batches) {
        try {
          const v = await api.verdict(b.name);
          if (!cancelled) setVerdicts((prev) => ({ ...prev, [b.name]: v }));
        } catch {
          if (!cancelled) setVerdicts((prev) => ({ ...prev, [b.name]: null }));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [batches]);

  if (!batches) {
    return <div style={{ color: "var(--dash-ink-faint)", fontSize: 13 }}>Loading runs…</div>;
  }

  const actionableCount = batches.filter((b) => (verdicts[b.name]?.actionable_total.paise ?? 0) > 0).length;
  const cleanCount = batches.filter((b) => verdicts[b.name] && verdicts[b.name]!.actionable_total.paise === 0).length;

  const filtered = batches
    .filter((b) => !q || b.name.toLowerCase().includes(q))
    .filter((b) => {
      const v = verdicts[b.name];
      if (filter === "actionable") return !!v && v.actionable_total.paise > 0;
      if (filter === "clean") return !!v && v.actionable_total.paise === 0;
      return true;
    });

  const filters: { key: Filter; label: string; count: number }[] = [
    { key: "all", label: "All", count: batches.length },
    { key: "actionable", label: "Actionable", count: actionableCount },
    { key: "clean", label: "Clean", count: cleanCount },
  ];

  return (
    <div style={{ maxWidth: 1180 }}>
      <h1 style={{ fontFamily: "var(--dash-font-serif)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.012em", margin: "0 0 8px" }}>
        Reconciliation runs
      </h1>
      <p style={{ fontSize: 14, color: "var(--dash-ink-soft)", margin: "0 0 28px" }}>
        Every cycle you've closed, with the gap it left behind.
      </p>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap", marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 8 }}>
          {filters.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              style={{
                borderRadius: 999,
                padding: "8px 14px",
                fontSize: 12.5,
                fontWeight: 600,
                cursor: "pointer",
                background: filter === f.key ? "var(--dash-ink)" : "var(--dash-raised)",
                color: filter === f.key ? "var(--dash-ground)" : "var(--dash-ink-soft)",
                border: filter === f.key ? "none" : "1px solid var(--dash-line-strong)",
              }}
            >
              {f.label} <span style={{ opacity: 0.6, fontFamily: "var(--dash-font-mono)" }}>{f.count}</span>
            </button>
          ))}
        </div>
        <Link
          href="/new-run"
          style={{
            background: "var(--dash-benign-soft)",
            color: "oklch(0.30 0.06 148)",
            borderRadius: 9,
            padding: "8px 15px",
            fontSize: 12.5,
            fontWeight: 700,
          }}
        >
          New run
        </Link>
      </div>

      <DashCard style={{ overflow: "hidden" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1.7fr 0.9fr 1fr 1.15fr 0.9fr",
            gap: 16,
            padding: "13px 20px",
            borderBottom: "1px solid var(--dash-line)",
            fontSize: 10.5,
            fontWeight: 700,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--dash-ink-faint)",
          }}
        >
          <div>Run</div>
          <div style={{ textAlign: "right" }}>Orders</div>
          <div style={{ textAlign: "right" }}>Expected</div>
          <div style={{ textAlign: "right" }}>Gap</div>
          <div style={{ textAlign: "right" }}>Status</div>
        </div>
        {filtered.length === 0 && (
          <div style={{ padding: 20, fontSize: 13, color: "var(--dash-ink-faint)", fontStyle: "italic" }}>
            No runs match this filter.
          </div>
        )}
        {filtered.map((b) => {
          const v = verdicts[b.name];
          return (
            <Link
              key={b.name}
              href={`/analysis/${encodeURIComponent(b.name)}`}
              onClick={() => setBatch(b.name)}
              className="dash-row"
              style={{
                display: "grid",
                gridTemplateColumns: "1.7fr 0.9fr 1fr 1.15fr 0.9fr",
                gap: 16,
                padding: "14px 20px",
                borderBottom: "1px solid var(--dash-line-soft)",
                alignItems: "center",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 11, minWidth: 0 }}>
                <StatusDot severity={v ? (v.actionable_total.paise > 0 ? "action" : "benign") : "neutral"} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {b.name}
                  </div>
                  <div style={{ fontSize: 11.5, color: "var(--dash-ink-faint)", marginTop: 3 }}>
                    {b.generated ? "generated" : b.uploaded ? "uploaded" : "seeded"}
                    {b.has_ground_truth ? " · has ground truth" : ""}
                  </div>
                </div>
              </div>
              <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 12.5, textAlign: "right" }}>
                {v ? v.performance.rows_processed : v === null ? "—" : "…"}
              </div>
              <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 12.5, textAlign: "right" }}>
                {v?.expected.display ?? (v === null ? "—" : "…")}
              </div>
              <div style={{ fontFamily: "var(--dash-font-mono)", fontSize: 13, fontWeight: 600, textAlign: "right", color: v && v.gap.paise !== 0 ? "var(--dash-action)" : "var(--dash-ink)" }}>
                {v?.gap.display ?? (v === null ? "—" : "…")}
              </div>
              <div style={{ textAlign: "right" }}>
                {v === undefined && <span style={{ fontSize: 12, color: "var(--dash-ink-faint)" }}>loading…</span>}
                {v === null && <span style={{ fontSize: 12, color: "var(--dash-urgent)" }}>unreadable</span>}
                {v && (
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      borderRadius: 999,
                      padding: "3px 10px",
                      color: v.actionable_total.paise > 0 ? "var(--dash-action)" : "var(--dash-benign)",
                      background:
                        v.actionable_total.paise > 0
                          ? "color-mix(in oklch, var(--dash-action) 14%, transparent)"
                          : "color-mix(in oklch, var(--dash-benign) 14%, transparent)",
                    }}
                  >
                    {v.actionable_total.paise > 0 ? "Needs review" : "Clean"}
                  </span>
                )}
              </div>
            </Link>
          );
        })}
      </DashCard>
    </div>
  );
}
