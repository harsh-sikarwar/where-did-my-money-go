/**
 * API client.
 *
 * ADR-001: the engine is the project, this is presentation. Nothing in the frontend
 * computes a money value — every number arrives from the engine already formatted.
 *
 * Money crosses the wire as { paise, display }: paise so we never do currency
 * arithmetic in JavaScript floats, display so we never reimplement Indian digit
 * grouping. If you find yourself writing `/ 100` in a component, something has gone
 * wrong upstream.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Money {
  paise: number;
  display: string;
}

export interface VerdictLine {
  classification: string;
  label: string;
  explanation: string;
  count: number;
  amount: Money;
  actionable: boolean;
}

export interface PassSummary {
  leg: string;
  question: string;
  total: number;
  matched: number;
  unmatched: number;
  match_rate: number;
}

export interface Verdict {
  batch: string;
  expected: Money;
  received: Money;
  gap: Money;
  headline: string;
  actionable_total: Money;
  benign_total: Money;
  unexplained: Money;
  lines: VerdictLine[];
  match: { pass1: PassSummary; pass2: PassSummary };
  performance: {
    elapsed_seconds: number;
    rows_processed: number;
    rows_per_second: number;
  };
}

export interface Finding {
  order_id: string | null;
  settlement_id: string | null;
  amount: Money;
  proof: Record<string, unknown>;
  candidates: string[];
}

export interface Detail {
  batch: string;
  classification: string;
  label: string;
  explanation: string;
  count: number;
  total: Money;
  truncated: boolean;
  findings: Finding[];
}

export interface Correlation {
  batch: string;
  before: Money;
  after: Money;
  resolved: Money;
  gain_ratio: number;
  resolved_count: number;
  still_unexplained_count: number;
  resolved_by_class: {
    classification: string;
    count: number;
    amount: Money;
  }[];
  still_unexplained: {
    order_id: string | null;
    amount: Money;
    outcome: string;
  }[];
}

export interface AuditEvent {
  seq: number;
  at: string;
  batch: string;
  stage: string;
  event: string;
  order_id?: string;
  settlement_id?: string;
  detail: Record<string, unknown>;
}

export interface Audit {
  batch: string;
  manifest: {
    batch_id: string;
    created_at: string;
    sealed: boolean;
    sources: Record<
      string,
      { origin: string; rows: number; sha256: string; column_mapping: string }
    >;
  };
  total_events: number;
  by_stage: Record<string, number>;
  filtered_count: number;
  truncated: boolean;
  events: AuditEvent[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function get<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { cache: "no-store" });
  } catch {
    // A dead API is the single most likely failure in a live demo, so it gets a
    // message that says what to do rather than "Failed to fetch".
    throw new ApiError(
      `Cannot reach the engine at ${BASE}. Start it with: npm run api`,
      0,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      // The engine's errors name the offending column, row or key. Keep them.
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body; the status text will do */
    }
    throw new ApiError(detail, response.status);
  }

  return response.json() as Promise<T>;
}

export const api = {
  verdict: (batch: string) => get<Verdict>(`/api/verdict/${batch}`),
  detail: (batch: string, classification: string) =>
    get<Detail>(`/api/detail/${batch}/${classification}`),
  correlation: (batch: string) => get<Correlation>(`/api/correlation/${batch}`),
  batches: () =>
    get<{ batches: { name: string; has_ground_truth: boolean }[] }>(
      "/api/batches",
    ),
  audit: (batch: string, stage?: string) =>
    get<Audit>(`/api/audit/${batch}${stage ? `?stage=${stage}` : ""}`),
};
