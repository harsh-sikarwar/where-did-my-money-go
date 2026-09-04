"use client";

import { useEffect, useState } from "react";
import { ChevronDownIcon } from "@/components/ui";
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
        className="flex w-full items-baseline justify-between border-b border-[var(--color-line-strong)] pb-3 text-left"
      >
        <span className="text-title">Your rates</span>
        <span className="text-xs font-medium text-[var(--color-ink-faint)]">
          {card.is_merchant_supplied ? "your contract" : "standard pricing"}
          {" · "}
          <span className="inline-flex items-center gap-1 text-[var(--color-accent)]">
            {open ? "hide" : "edit"}
            <ChevronDownIcon
              size={12}
              className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}
            />
          </span>
        </span>
      </button>

      {!open && !card.is_merchant_supplied && (
        <p className="text-body mt-4 max-w-md text-[var(--color-ink-soft)]">
          Fees are being checked against Razorpay&rsquo;s standard rates. If you
          negotiated different ones, say so — otherwise an overcharge against{" "}
          <em>your</em> contract is invisible.
        </p>
      )}

      {open && (
        <div className="mt-5">
          <p className="text-body mb-5 max-w-md text-[var(--color-ink-soft)]">
            Enter only what you negotiated. Anything left blank keeps the standard rate.
          </p>

          <div className="space-y-px">
            {card.methods.map((m) => (
              <div
                key={m.method}
                className="flex items-baseline gap-4 border-b border-[var(--color-line)] py-3"
              >
                <span className="w-44 shrink-0 font-mono text-xs text-[var(--color-ink-soft)]">
                  {m.method}
                </span>
                <span className="tnum w-20 shrink-0 text-right text-sm font-medium">
                  {m.percent.toFixed(2)}%
                </span>
                <span
                  className={`w-20 shrink-0 text-xs font-medium ${
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
                  className="w-24 rounded-lg border border-[var(--color-line-strong)] bg-[var(--color-raised)] px-2.5 py-1.5 text-right text-sm text-[var(--color-ink)] outline-none transition-colors focus:border-[var(--color-accent)]"
                />
                <span className="text-xs text-[var(--color-ink-faint)]">%</span>
              </div>
            ))}
          </div>

          {error && (
            <p className="mt-5 text-sm font-medium text-[var(--color-urgent)]">
              {error}
            </p>
          )}

          <div className="mt-7 flex items-center gap-4">
            <button
              onClick={save}
              disabled={busy}
              className="pressable rounded-lg bg-[var(--color-ink)] px-5 py-2.5 text-sm font-medium text-[var(--color-ground)] disabled:cursor-not-allowed disabled:opacity-30"
            >
              {busy ? "Saving…" : "Save my rates"}
            </button>
            {card.is_merchant_supplied && (
              <button
                onClick={reset}
                disabled={busy}
                className="text-sm text-[var(--color-ink-faint)] underline underline-offset-4 hover:text-[var(--color-ink)]"
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
