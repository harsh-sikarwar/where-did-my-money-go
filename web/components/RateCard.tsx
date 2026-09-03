"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type RateCard as RateCardData } from "@/lib/api";

/**
 * The merchant's contracted rates.
 *
 * Without this the fee check answers "was this the standard rate?" — a different, and
 * much less useful, question than "was this MY contracted rate?" for anyone who has
 * negotiated. A merchant contracted at 1.75% and billed 2% sees nothing from a standard
 * card, because 2% is exactly what it expects. ADR-046.
 *
 * Rates are entered as PERCENTAGES here and converted to basis points on the way out.
 * The API takes basis points because integers avoid float arithmetic on money, but no
 * merchant thinks in bps, and asking them to would invite the exact unit error the API
 * refuses (entering "2" for 2% is 0.02%).
 */
export function RateCard() {
  const [card, setCard] = useState<RateCardData | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.rateCard().then(setCard).catch(() => setCard(null));
  }, []);

  if (!card) return null;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const methods: Record<string, number> = {};
      for (const [method, value] of Object.entries(edits)) {
        const percent = Number(value);
        if (value.trim() === "" || Number.isNaN(percent)) continue;
        // Percent -> basis points. Rounded because 1.755% is not a rate anyone has.
        methods[method] = Math.round(percent * 100);
      }
      if (Object.keys(methods).length === 0) {
        setError("Enter at least one rate, or clear the card to use standard pricing.");
        setBusy(false);
        return;
      }
      setCard(await api.setRateCard({ name: "your-contract", methods }));
      setEdits({});
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save those rates.");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    setError(null);
    try {
      setCard(await api.clearRateCard());
      setEdits({});
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not clear the rate card.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mb-14">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-baseline justify-between border-b border-[var(--color-line)] pb-2 text-left"
      >
        <span className="text-sm font-medium">Your rates</span>
        <span className="text-xs text-[var(--color-ink-faint)]">
          {card.is_merchant_supplied ? "your contract" : "standard pricing"}
          {" · "}
          {open ? "hide" : "edit"}
        </span>
      </button>

      {!open && !card.is_merchant_supplied && (
        <p className="mt-3 text-sm text-[var(--color-ink-faint)]">
          Fees are being checked against Razorpay&rsquo;s standard rates. If you
          negotiated different ones, say so — otherwise an overcharge against{" "}
          <em>your</em> contract is invisible.
        </p>
      )}

      {open && (
        <div className="mt-5">
          <p className="mb-5 text-sm text-[var(--color-ink-faint)]">
            Enter only what you negotiated. Anything left blank keeps the standard rate.
          </p>

          <div className="space-y-px">
            {card.methods.map((m) => (
              <div
                key={m.method}
                className="flex items-baseline gap-4 border-b border-[var(--color-line)] py-2.5"
              >
                <span className="w-44 shrink-0 font-mono text-xs text-[var(--color-ink-soft)]">
                  {m.method}
                </span>
                <span className="tnum w-20 shrink-0 text-right text-sm">
                  {m.percent.toFixed(2)}%
                </span>
                <span
                  className={`w-20 shrink-0 text-xs ${
                    m.source === "merchant"
                      ? "text-[var(--color-benign)]"
                      : "text-[var(--color-ink-faint)]"
                  }`}
                >
                  {m.source === "merchant" ? "yours" : "standard"}
                </span>
                <input
                  inputMode="decimal"
                  value={edits[m.method] ?? ""}
                  onChange={(e) =>
                    setEdits((c) => ({ ...c, [m.method]: e.target.value }))
                  }
                  placeholder="e.g. 1.75"
                  className="w-24 rounded border border-[var(--color-line)] bg-white px-2 py-1 text-right text-sm outline-none focus:border-[var(--color-ink-faint)]"
                />
                <span className="text-xs text-[var(--color-ink-faint)]">%</span>
              </div>
            ))}
          </div>

          {error && (
            <p className="mt-5 text-sm text-[var(--color-attention)]">{error}</p>
          )}

          <div className="mt-6 flex items-center gap-4">
            <button
              onClick={save}
              disabled={busy}
              className="rounded bg-[var(--color-ink)] px-4 py-2 text-sm text-white disabled:opacity-30"
            >
              {busy ? "Saving…" : "Save my rates"}
            </button>
            {card.is_merchant_supplied && (
              <button
                onClick={reset}
                disabled={busy}
                className="text-sm text-[var(--color-ink-faint)] underline underline-offset-4"
              >
                Use standard pricing
              </button>
            )}
          </div>

          <p className="mt-5 text-xs text-[var(--color-ink-faint)]">
            GST is {(card.gst_rate_bps / 100).toFixed(0)}% on the fee, never on the sale.
          </p>
        </div>
      )}
    </section>
  );
}
