"use client";

/**
 * Audit log — every ingest/match/classify/correlate/rank event the engine
 * recorded for this batch, grouped by calendar day. `api.audit(batch)` is a
 * thin wrapper on an endpoint that already existed (see `components/Audit.tsx`
 * for the original data-shaping); this page re-skins that same data rather
 * than inventing anything new.
 *
 * The mockup's per-entry avatar + name ("Anika resolved…") is fabricated for
 * a multi-user product this isn't — there is no auth, no team, one browser
 * session per merchant (see `api/main.py`'s CORS comment). It's dropped
 * entirely in favour of something real and structural: the pipeline `stage`
 * that produced the event.
 */

import { use, useEffect, useMemo, useState } from "react";
import { DashCard, Pill, SectionLabel } from "@/components/dash/primitives";
import { useCurrentBatch } from "@/lib/current-batch";
import { api, ApiError, type Audit, type AuditEvent } from "@/lib/api";

const STAGE_TONE: Record<string, "benign" | "action" | "urgent" | "neutral"> = {
  ingest: "neutral",
  match: "action",
  classify: "action",
  correlate: "action",
  rank: "benign",
};

export default function AuditLogPage({
  params,
}: {
  params: Promise<{ batch: string }>;
}) {
  const { batch } = use(params);
  const { setBatch } = useCurrentBatch();
  const [data, setData] = useState<Audit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);

  useEffect(() => {
    setBatch(batch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch]);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    api
      .audit(batch)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Something went wrong."));
    return () => {
      cancelled = true;
    };
  }, [batch]);

  const days = useMemo(() => {
    if (!data) return [];
    const filtered = stage ? data.events.filter((e) => e.stage === stage) : data.events;
    const map = new Map<string, AuditEvent[]>();
    for (const e of filtered) {
      const day = e.at.slice(0, 10);
      if (!map.has(day)) map.set(day, []);
      map.get(day)!.push(e);
    }
    return Array.from(map.entries())
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([day, entries]) => ({
        day,
        entries: entries.slice().sort((a, b) => b.seq - a.seq),
      }));
  }, [data, stage]);

  return (
    <div style={{ maxWidth: 900 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          gap: 20,
          flexWrap: "wrap",
          marginBottom: 22,
        }}
      >
        <div>
          <h1
            style={{
              fontFamily: "var(--dash-font-serif)",
              fontSize: 40,
              fontWeight: 400,
              letterSpacing: "-0.012em",
              margin: "0 0 8px",
            }}
          >
            Audit log
          </h1>
          <p style={{ fontSize: 14, color: "var(--dash-ink-soft)", margin: 0 }}>
            Every ingest, match and classification decision the engine made — append-only,
            and what an auditor would ask for.
          </p>
        </div>
        {data && (
          <button
            type="button"
            onClick={() => downloadLog(batch, data)}
            className="dash-pressable"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 7,
              border: "1px solid var(--dash-line-strong)",
              borderRadius: 9,
              padding: "8px 13px",
              fontSize: 12.5,
              color: "var(--dash-ink-soft)",
              background: "none",
              cursor: "pointer",
            }}
          >
            Export log
          </button>
        )}
      </div>

      {error && (
        <DashCard style={{ padding: 18, marginBottom: 20, color: "var(--dash-urgent)", fontSize: 13.5 }}>
          {error}
        </DashCard>
      )}

      {!data && !error && (
        <div style={{ color: "var(--dash-ink-faint)", fontSize: 13 }}>Loading audit log…</div>
      )}

      {data && (
        <>
          {/* Manifest — real, and the one piece of context the mockup has no slot
              for: what batch this is, whether it's sealed, and when it was staged. */}
          <DashCard
            style={{
              padding: "14px 18px",
              marginBottom: 24,
              display: "flex",
              flexWrap: "wrap",
              gap: 24,
              alignItems: "center",
            }}
          >
            <InfoItem label="Batch" value={data.manifest.batch_id} mono />
            <InfoItem
              label="Sealed"
              value={data.manifest.sealed ? "Yes — immutable" : "Not sealed"}
            />
            <InfoItem label="Staged" value={formatDateTime(data.manifest.created_at)} mono />
            <InfoItem label="Sources" value={String(Object.keys(data.manifest.sources).length)} />
            <InfoItem label="Events" value={String(data.total_events)} />
          </DashCard>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 22 }}>
            <StageChip label="All" count={data.total_events} active={stage === null} onClick={() => setStage(null)} />
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

          {days.length === 0 && (
            <div style={{ fontSize: 13, color: "var(--dash-ink-faint)", fontStyle: "italic" }}>
              No events for this filter.
            </div>
          )}

          {days.map((d) => (
            <div key={d.day} style={{ marginBottom: 26 }}>
              <div
                style={{
                  fontSize: 10.5,
                  fontWeight: 700,
                  letterSpacing: "0.13em",
                  textTransform: "uppercase",
                  color: "var(--dash-neutral)",
                  marginBottom: 10,
                }}
              >
                {formatDayHeading(d.day)}
              </div>
              <DashCard style={{ overflow: "hidden" }}>
                {d.entries.map((e) => (
                  <AuditRow key={e.seq} event={e} />
                ))}
              </DashCard>
            </div>
          ))}

          {data.truncated && (
            <p style={{ fontSize: 12, color: "var(--dash-ink-faint)", marginTop: 8 }}>
              Showing the first {data.events.length} of {data.filtered_count} events.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function AuditRow({ event }: { event: AuditEvent }) {
  const objectId = event.order_id ?? event.settlement_id ?? null;
  const detail = formatDetail(event.detail);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 14,
        padding: "14px 20px",
        borderBottom: "1px solid var(--dash-line)",
      }}
    >
      <Pill tone={STAGE_TONE[event.stage] ?? "neutral"} style={{ marginTop: 1, flex: "none" }}>
        {event.stage}
      </Pill>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13.5, lineHeight: 1.5 }}>
          <span style={{ fontWeight: 700 }}>{formatEventName(event.event)}</span>
          {objectId && (
            <span
              style={{
                fontFamily: "var(--dash-font-mono)",
                fontSize: 12.5,
                marginLeft: 8,
                color: "var(--dash-ink-soft)",
              }}
            >
              {objectId}
            </span>
          )}
        </div>
        {detail && (
          <div style={{ fontSize: 11.5, color: "var(--dash-ink-dim)", marginTop: 4, lineHeight: 1.5 }}>
            {detail}
          </div>
        )}
      </div>
      <div
        style={{
          fontFamily: "var(--dash-font-mono)",
          fontSize: 11.5,
          color: "var(--dash-ink-dim)",
          flex: "none",
        }}
      >
        {formatTime(event.at)}
      </div>
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
      type="button"
      onClick={onClick}
      className="dash-pressable"
      style={{
        border: "none",
        borderRadius: 999,
        padding: "7px 13px",
        fontSize: 12,
        fontWeight: 600,
        cursor: "pointer",
        background: active ? "var(--dash-ink)" : "var(--dash-well)",
        color: active ? "var(--dash-ground)" : "var(--dash-ink-soft)",
      }}
    >
      {label} <span style={{ opacity: 0.65, fontFamily: "var(--dash-font-mono)" }}>{count}</span>
    </button>
  );
}

function InfoItem({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div
        style={{
          fontSize: 10.5,
          fontWeight: 700,
          letterSpacing: "0.09em",
          textTransform: "uppercase",
          color: "var(--dash-ink-faint)",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 12.5,
          marginTop: 3,
          fontFamily: mono ? "var(--dash-font-mono)" : undefined,
          maxWidth: 260,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ formatting */

function formatEventName(event: string): string {
  return event.replace(/_/g, " ");
}

function formatDayHeading(day: string): string {
  const d = new Date(`${day}T00:00:00`);
  if (Number.isNaN(d.getTime())) return day;
  return d
    .toLocaleDateString("en-IN", { year: "numeric", month: "long", day: "numeric" })
    .toUpperCase();
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toLocaleDateString("en-IN", { year: "numeric", month: "short", day: "numeric" })} · ${d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false })}`;
}

/** One line of an event's free-form detail dict, rendered plainly as
 *  `key: value` pairs — never forced into a sentence template (the engine's
 *  words stay the engine's words). Long strings and nested structures are
 *  truncated so a wall of JSON doesn't take over the row. */
function formatDetail(detail: Record<string, unknown>): string {
  const skip = new Set(["order_id", "settlement_id"]);
  const parts: string[] = [];
  for (const [key, value] of Object.entries(detail)) {
    if (skip.has(key)) continue;
    const formatted = formatValue(value);
    if (formatted === "") continue;
    parts.push(`${key}: ${formatted}`);
  }
  return parts.join(" · ");
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "number") return value.toLocaleString("en-IN");
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string") return truncate(value, 70);
  return truncate(JSON.stringify(value), 90);
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function downloadLog(batch: string, data: Audit) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${batch}-audit-log.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
