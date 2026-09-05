"use client";

/**
 * Settings — the rate card, and nothing pretending to be more than it is.
 *
 * The mockup's Settings screen has three sections: Workspace fields (name,
 * currency…), Team (invite teammates, roles), Alerts (notification
 * toggles). None of those have a backend — there's no auth, no team model,
 * no notification system in this engine (single-user demo tool, see
 * `api/main.py`'s CORS comment). Rather than build inputs that silently do
 * nothing when "saved", they're dropped. The one thing on this screen that
 * IS real is the rate card — `api.rateCard()` / `setRateCard()` /
 * `clearRateCard()`, exactly the flow `components/RateCard.tsx` already
 * implements (loading, error handling, editable-vs-standard). This page
 * ports that logic rather than re-deriving it, restyled for the dashboard.
 */

import { useEffect, useState } from "react";
import { DashButton, DashCard, Pill } from "@/components/dash/primitives";
import { api, ApiError, type RateCard as RateCardData } from "@/lib/api";

export default function SettingsPage() {
  const [card, setCard] = useState<RateCardData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    api
      .rateCard()
      .then(setCard)
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : "Could not load the rate card."));
  }, []);

  async function save() {
    setBusy(true);
    setSaveError(null);
    setJustSaved(false);
    try {
      const methods: Record<string, number> = {};
      for (const [method, value] of Object.entries(edits)) {
        const percent = Number(value);
        if (value.trim() === "" || Number.isNaN(percent)) continue;
        // Percent -> basis points, rounded: 1.755% is not a rate anyone has.
        methods[method] = Math.round(percent * 100);
      }
      if (Object.keys(methods).length === 0) {
        setSaveError("Enter at least one rate, or use “Use standard pricing” to clear the card.");
        setBusy(false);
        return;
      }
      setCard(await api.setRateCard({ name: "your-contract", methods }));
      setEdits({});
      setJustSaved(true);
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.message : "Could not save those rates.");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    setSaveError(null);
    setJustSaved(false);
    try {
      setCard(await api.clearRateCard());
      setEdits({});
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.message : "Could not clear the rate card.");
    } finally {
      setBusy(false);
    }
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
        Settings
      </h1>
      <p style={{ fontSize: 14, color: "var(--dash-ink-soft)", margin: "0 0 30px", maxWidth: 560 }}>
        One thing here is configurable: what this workspace actually pays. Fees are
        checked against it, not just Razorpay&rsquo;s standard rates.
      </p>

      <DashCard style={{ padding: 24, marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, marginBottom: 6 }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Your rate card</div>
          {card && <Pill tone={card.is_merchant_supplied ? "benign" : "neutral"}>{card.is_merchant_supplied ? "Your contract" : "Standard pricing"}</Pill>}
        </div>
        <p style={{ fontSize: 12.5, color: "var(--dash-ink-faint)", margin: "0 0 20px", lineHeight: 1.55, maxWidth: 520 }}>
          Enter only what you negotiated. Anything left blank keeps Razorpay&rsquo;s standard
          rate for that method — a merchant contracted at 1.75% and billed 2% sees nothing
          from a standard card, because 2% is exactly what it expects.
        </p>

        {loadError && (
          <p style={{ fontSize: 13, color: "var(--dash-urgent)", margin: "0 0 16px" }}>{loadError}</p>
        )}

        {!card && !loadError && (
          <div style={{ fontSize: 13, color: "var(--dash-ink-faint)" }}>Loading rate card…</div>
        )}

        {card && (
          <>
            <div>
              {card.methods.map((m) => (
                <div
                  key={m.method}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 16,
                    padding: "12px 0",
                    borderTop: "1px solid var(--dash-line)",
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0, fontSize: 13.5, fontWeight: 600 }}>{m.method}</div>
                  <div
                    style={{
                      fontFamily: "var(--dash-font-mono)",
                      fontSize: 13,
                      fontVariantNumeric: "tabular-nums",
                      width: 64,
                      textAlign: "right",
                      flex: "none",
                    }}
                  >
                    {m.percent.toFixed(2)}%
                  </div>
                  <div
                    style={{
                      width: 72,
                      flex: "none",
                      fontSize: 11.5,
                      fontWeight: 700,
                      color: m.source === "merchant" ? "var(--dash-benign)" : "var(--dash-ink-faint)",
                    }}
                  >
                    {m.source === "merchant" ? "yours" : "standard"}
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 7,
                      background: "var(--dash-ground)",
                      border: "1px solid var(--dash-line-strong)",
                      borderRadius: 8,
                      padding: "6px 10px",
                      flex: "none",
                    }}
                  >
                    <input
                      inputMode="decimal"
                      value={edits[m.method] ?? ""}
                      onChange={(e) => setEdits((c) => ({ ...c, [m.method]: e.target.value }))}
                      placeholder="e.g. 1.75"
                      style={{
                        width: 60,
                        background: "transparent",
                        border: "none",
                        outline: "none",
                        color: "var(--dash-ink)",
                        fontFamily: "var(--dash-font-mono)",
                        fontSize: 13,
                        textAlign: "right",
                      }}
                    />
                    <span style={{ fontSize: 11.5, color: "var(--dash-ink-faint)" }}>%</span>
                  </div>
                </div>
              ))}
            </div>

            <p style={{ fontSize: 11.5, color: "var(--dash-ink-faint)", marginTop: 16 }}>
              GST is {(card.gst_rate_bps / 100).toFixed(0)}% on the fee, never on the sale.
            </p>

            {saveError && (
              <p style={{ fontSize: 13, color: "var(--dash-urgent)", marginTop: 14 }}>{saveError}</p>
            )}

            <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 22 }}>
              <DashButton variant="primary" onClick={save} disabled={busy}>
                {busy ? "Saving…" : "Save rates"}
              </DashButton>
              {card.is_merchant_supplied && (
                <button
                  type="button"
                  onClick={reset}
                  disabled={busy}
                  style={{
                    background: "none",
                    border: "none",
                    fontSize: 12.5,
                    color: "var(--dash-ink-faint)",
                    textDecoration: "underline",
                    cursor: busy ? "not-allowed" : "pointer",
                  }}
                >
                  Use standard pricing
                </button>
              )}
              {justSaved && !saveError && (
                <span style={{ fontSize: 12, color: "var(--dash-benign)", fontWeight: 600 }}>Saved.</span>
              )}
            </div>
          </>
        )}
      </DashCard>

      <DashCard style={{ padding: 24, fontSize: 12.5, color: "var(--dash-ink-faint)", lineHeight: 1.6 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--dash-ink-soft)", marginBottom: 8 }}>
          About this workspace
        </div>
        This is a single-user demo tool — no accounts, no team roles, no email or
        notification delivery. If those become real, they&rsquo;ll show up here; until then
        the rate card above is the only setting on this page that actually saves anything.
      </DashCard>
    </div>
  );
}
