"use client";

/**
 * Rules — a read-only reflection of the engine's matching and classification
 * config (`GET /api/rules`). The doc comment on that endpoint says why
 * nothing here is editable: the engine's rules are code, reviewed and
 * tested (ADR-001), not a document a browser can rewrite. Rate-card changes
 * still go through Settings (`/api/rate-card`) — the one setting that is
 * genuinely a merchant input rather than an engine policy.
 *
 * Every toggle and value box below is rendered disabled with a tooltip
 * saying so, and the mockup's "Save as v5" / "v4 active since…" version
 * history is dropped outright — this engine has no versioned rule store to
 * report on, and inventing one would be exactly the kind of screen this
 * product exists to avoid.
 */

import { useEffect, useState } from "react";
import {
  DashCard,
  Pill,
  SectionLabel,
  Switch,
  type Severity,
} from "@/components/dash/primitives";
import { api, ApiError, type RulesConfig } from "@/lib/api";

const READONLY_TITLE = "Set in code, not from the browser — see docs/DECISIONS.md";

const POLICY_LABEL: Record<RulesConfig["classifications"][number]["policy"], string> = {
  always_benign: "Always benign",
  always_actionable: "Always actionable",
  threshold: "Threshold",
};

const POLICY_TONE: Record<RulesConfig["classifications"][number]["policy"], Severity> = {
  always_benign: "benign",
  always_actionable: "urgent",
  threshold: "neutral",
};

export default function RulesPage() {
  const [rules, setRules] = useState<RulesConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .rules()
      .then((r) => !cancelled && setRules(r))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

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

  if (!rules) {
    return <div style={{ color: "var(--dash-ink-faint)", fontSize: 13 }}>Loading rules…</div>;
  }

  return (
    <div style={{ maxWidth: 860 }}>
      <h1
        style={{
          fontFamily: "var(--dash-font-serif)",
          fontSize: 40,
          fontWeight: 400,
          letterSpacing: "-0.012em",
          margin: "0 0 8px",
        }}
      >
        Matching rules
      </h1>
      <p style={{ fontSize: 14, color: "var(--dash-ink-soft)", margin: "0 0 30px", maxWidth: 560, lineHeight: 1.55 }}>
        What the engine currently enforces — tolerances, the rate card, the classification
        vocabulary. Read-only: these are reviewed and tested code, not a document this
        screen can rewrite.
      </p>

      {/* --------------------------------------------------------- tolerances */}
      <SectionLabel style={{ marginBottom: 12 }}>Reconciliation tolerances</SectionLabel>
      <DashCard style={{ padding: "18px 20px", marginBottom: 30 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18 }}>
          <ToleranceInput
            label="Settlement cycle"
            value={String(rules.cycle_days)}
            unit={rules.cycle_days === 1 ? "day" : "days"}
          />
          <ToleranceInput
            label="Grace period"
            value={String(rules.grace_days)}
            unit={rules.grace_days === 1 ? "day" : "days"}
          />
          <ToleranceSwitch label="Count working days only" on={rules.count_working_days_only} />
          <ToleranceInput label="Rounding tolerance" value={rules.rounding.display} />
          <ToleranceInput label="Materiality floor" value={rules.material.display} />
          <ToleranceInput label="Actionable above" value={rules.actionable_above.display} />
        </div>
      </DashCard>

      {/* --------------------------------------------------------- classifications */}
      <SectionLabel style={{ marginBottom: 12 }}>Classification policy</SectionLabel>
      <DashCard style={{ overflow: "hidden", marginBottom: 30 }}>
        {rules.classifications.map((c, i) => (
          <div
            key={c.name}
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 16,
              padding: "16px 20px",
              borderBottom: i < rules.classifications.length - 1 ? "1px solid var(--dash-line-soft)" : "none",
            }}
          >
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
                <div style={{ fontSize: 14.5, fontWeight: 700 }}>{c.label}</div>
                <Pill tone={POLICY_TONE[c.policy]}>
                  {c.policy === "threshold"
                    ? `Actionable above ${rules.actionable_above.display}`
                    : POLICY_LABEL[c.policy]}
                </Pill>
              </div>
              <div style={{ fontSize: 13, color: "var(--dash-ink-faint)", marginTop: 7, lineHeight: 1.55, maxWidth: 520 }}>
                {c.hint}
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 14, flex: "none" }}>
              {c.policy === "threshold" && (
                <span title={READONLY_TITLE}>
                  <input
                    disabled
                    readOnly
                    value={rules.actionable_above.display}
                    title={READONLY_TITLE}
                    style={{
                      width: 92,
                      background: "var(--dash-well)",
                      border: "1px solid var(--dash-line-strong)",
                      borderRadius: 8,
                      padding: "7px 10px",
                      fontFamily: "var(--dash-font-mono)",
                      fontSize: 12.5,
                      color: "var(--dash-ink)",
                      textAlign: "right",
                      cursor: "not-allowed",
                    }}
                  />
                </span>
              )}
              <span title={READONLY_TITLE}>
                <Switch on disabled />
              </span>
            </div>
          </div>
        ))}
      </DashCard>

      {/* --------------------------------------------------------- rate card */}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 12 }}>
        <SectionLabel>Rate card</SectionLabel>
        <span style={{ fontSize: 12, color: "var(--dash-ink-faint)" }}>
          {rules.rate_card.is_merchant_supplied ? "your contract" : "standard pricing"} · {rules.rate_card.name}
        </span>
      </div>
      <DashCard style={{ overflow: "hidden", marginBottom: 12 }}>
        {rules.rate_card.methods.map((m, i) => (
          <div
            key={m.method}
            title={m.note || undefined}
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 16,
              padding: "12px 20px",
              borderBottom: i < rules.rate_card.methods.length - 1 ? "1px solid var(--dash-line-soft)" : "none",
            }}
          >
            <span style={{ width: 176, flex: "none", fontFamily: "var(--dash-font-mono)", fontSize: 12.5, color: "var(--dash-ink-soft)" }}>
              {m.method}
            </span>
            <span style={{ width: 76, flex: "none", textAlign: "right", fontFamily: "var(--dash-font-mono)", fontSize: 13, fontWeight: 600 }}>
              {m.percent.toFixed(2)}%
            </span>
            <span
              style={{
                width: 76,
                flex: "none",
                fontSize: 11.5,
                fontWeight: 600,
                color: m.source === "merchant" ? "var(--dash-benign)" : "var(--dash-ink-faint)",
              }}
            >
              {m.source === "merchant" ? "yours" : "standard"}
            </span>
            {m.note && (
              <span style={{ minWidth: 0, flex: 1, fontSize: 11.5, color: "var(--dash-ink-faint)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {m.note}
              </span>
            )}
          </div>
        ))}
      </DashCard>
      <p style={{ fontSize: 12, color: "var(--dash-ink-faint)", margin: "0 0 6px" }}>
        GST is {(rules.rate_card.gst_rate_bps / 100).toFixed(0)}% on the fee, never on the sale.
        {rules.rate_card.fixed_fee_paise > 0 ? " A fixed fee applies per settlement." : ""}
      </p>
      <p style={{ fontSize: 12, color: "var(--dash-ink-faint)", margin: 0 }}>
        To use your own contracted rates instead of standard pricing, set them in{" "}
        <a href="/settings" style={{ color: "var(--dash-accent-deep)", fontWeight: 600 }}>
          Settings
        </a>
        .
      </p>
    </div>
  );
}

function ToleranceInput({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div>
      <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--dash-ink-faint)", marginBottom: 8 }}>{label}</div>
      <span title={READONLY_TITLE} style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
        <input
          disabled
          readOnly
          value={value}
          title={READONLY_TITLE}
          style={{
            width: 92,
            background: "var(--dash-well)",
            border: "1px solid var(--dash-line-strong)",
            borderRadius: 8,
            padding: "7px 11px",
            fontFamily: "var(--dash-font-mono)",
            fontSize: 13,
            color: "var(--dash-ink)",
            textAlign: "right",
            cursor: "not-allowed",
          }}
        />
        {unit && <span style={{ fontSize: 11.5, color: "var(--dash-ink-faint)" }}>{unit}</span>}
      </span>
    </div>
  );
}

function ToleranceSwitch({ label, on }: { label: string; on: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--dash-ink-faint)", marginBottom: 8 }}>{label}</div>
      <span title={READONLY_TITLE}>
        <Switch on={on} disabled />
      </span>
    </div>
  );
}
