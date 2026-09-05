/**
 * Human phrasing for the `ActionItem` / `ActionGroup` classification
 * vocabulary (`api.actions()`), shared by the Exceptions queue and Order
 * detail screens. Mirrors the `LABELS` map in `components/Actions.tsx` so
 * the dark-theme and dashboard themes never name the same finding two
 * different ways.
 */

export const CLASSIFICATION_LABELS: Record<string, string> = {
  HALTED_SUBSCRIPTION: "Subscriptions that died silently",
  PAYMENT_FAILED: "Payments that failed",
  ON_HOLD: "Held by Razorpay — not on its way",
  DISPUTED: "Disputed by the customer — you have a deadline",
  REFUND: "Refunds you recorded that Razorpay paid out anyway",
  UNRECORDED_REFUND: "Refunds Razorpay paid out that you never recorded",
  MISSING: "No record at Razorpay at all",
  UNEXPECTED_SETTLEMENT: "Settled, but not in your ledger",
  NEEDS_REVIEW: "More than one explanation fits",
  DUPLICATE: "The same order twice in your ledger",
  UNEXPLAINED: "We could not account for this",
};

export function labelForClassification(classification: string): string {
  return (
    CLASSIFICATION_LABELS[classification] ??
    classification.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
  );
}

/**
 * Classifications where leaving the order open costs the merchant real,
 * time-sensitive money (a refund owed, a dispute deadline). Used only to
 * pick a warmer tone for a badge — never to compute a money value.
 */
const URGENT = new Set([
  "DISPUTED",
  "ON_HOLD",
  "REFUND",
  "UNRECORDED_REFUND",
  "MISSING",
]);

export type ActionSeverity = "urgent" | "action" | "neutral";

export function actionSeverity(classification: string | null | undefined): ActionSeverity {
  if (!classification) return "neutral";
  return URGENT.has(classification) ? "urgent" : "action";
}

/** `some_snake_case_event` -> `Some snake case event`. Used on free-form
 *  stage/event names from the trace, which are not in `CLASSIFICATION_LABELS`. */
export function humanize(s: string): string {
  return s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** Same cap the Audit log page uses for the same category of data (nested
 *  proof/correlation objects can run to hundreds of characters) — long
 *  values are truncated rather than left to wrap, so one field can't take
 *  over a row. */
function truncate(s: string, n = 90): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/**
 * A free-form `Record<string, unknown>` (a `Finding.proof` or a
 * `TraceEvent.detail`) rendered as plain `key: value` pairs — the engine's
 * own shape, not forced into copy we'd have to invent.
 */
export function describeDetail(detail: Record<string, unknown> | null | undefined): [string, string][] {
  if (!detail) return [];
  return Object.entries(detail)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => [humanize(k), truncate(typeof v === "object" ? JSON.stringify(v) : String(v))]);
}
