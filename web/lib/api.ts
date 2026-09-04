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
  /** Summary prose. Written by an LLM where one is configured, otherwise a
   *  deterministic template. Never contains a figure — the engine renders those. */
  summary?: string;
  /** "model" or "template". Shown to the reader rather than hidden: a product that
   *  cannot say whether a model wrote something is not one you can audit. */
  summary_source?: "model" | "template";
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

/** What a merchant is asked when the engine cannot map a column. ADR-045. */
export interface UnmappedColumns {
  error: "unmapped_columns";
  source: string;
  message: string;
  unmapped: {
    canonical: string;
    accepted_spellings: string[];
    candidates: string[];
  }[];
  already_mapped: Record<string, string>;
  headers: string[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /**
     * The structured body, when the API sent one. `detail` is usually a string, but
     * an unmappable upload returns an object a picker can render — the engine's
     * refusal to guess is only useful if the UI can act on it.
     */
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** The mapping question, if that is what this error is. */
  get unmappedColumns(): UnmappedColumns | null {
    const d = this.detail as UnmappedColumns | undefined;
    return d && typeof d === "object" && d.error === "unmapped_columns" ? d : null;
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

  return unwrap<T>(response);
}

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      const body = await response.json();
      // The engine's errors name the offending column, row or key. Keep them —
      // including when `detail` is an object rather than a string (ADR-045).
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body; the status text will do */
    }
    const message =
      typeof detail === "string"
        ? detail
        : ((detail as { message?: string })?.message ?? response.statusText);
    throw new ApiError(message, response.status, detail);
  }

  return response.json() as Promise<T>;
}

async function send<T>(
  path: string,
  init: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(
      `Cannot reach the engine at ${BASE}. Start it with: npm run api`,
      0,
    );
  }
  return unwrap<T>(response);
}

export interface RateCardMethod {
  method: string;
  mdr_bps: number;
  percent: number;
  source: "merchant" | "standard";
  note: string;
}

export interface RateCard {
  name: string;
  is_merchant_supplied: boolean;
  gst_rate_bps: number;
  fixed_fee_paise: number;
  methods: RateCardMethod[];
}

export interface ActionItem {
  order_id: string | null;
  classification: string;
  amount: Money;
  customer_id: string | null;
  email: string | null;
  contact: string | null;
  subscription_id: string | null;
  payment_id: string | null;
  reason: string | null;
  detail: string | null;
}

export interface ActionGroup {
  classification: string;
  next_step: string;
  count: number;
  total: Money;
  items: ActionItem[];
}

export interface Actions {
  batch: string;
  headline: string;
  /** The signed sum across every group, offsets included. */
  total: Money;
  /** Only the groups that ADD to the gap — the money actually worth chasing. */
  chase_total: Money;
  chase_count: number;
  count: number;
  groups: ActionGroup[];
}

export interface Inspected {
  source: string;
  headers: string[];
  row_count: number;
  fingerprint: string;
  remembered_mapping: Record<string, string> | null;
  sample_rows: Record<string, string>[];
}

export interface UploadResult {
  batch: string;
  files: Record<string, { filename: string; bytes: number }>;
  rows_processed: number;
  missing_sources: string[];
  note: string | null;
  headline: string;
  manifest: Audit["manifest"];
}

/* ------------------------------------------------------------------ synthetic generator */

export interface Archetype {
  name: string;
  description: string;
  stresses: string;
  expected_correlation_gain: string;
  ticket_min_paise: number;
  ticket_max_paise: number;
  default_mix: Record<string, number>;
}

export interface PaymentMix {
  name: string;
  description: string;
  mix: Record<string, number>;
}

export interface DefectProfile {
  name: string;
  description: string;
  defects: Record<string, { count?: number; rate?: number; [k: string]: unknown }>;
}

export interface DefectTypeOption {
  name: string;
  label: string;
  hint: string;
  is_defect: boolean;
}

export interface GenerateOptions {
  archetypes: Archetype[];
  payment_mixes: PaymentMix[];
  defect_profiles: DefectProfile[];
  defect_types: DefectTypeOption[];
  defaults: {
    archetype: string;
    payment_mix: string | null;
    defect_profile: string;
    volume: number;
    cycle_days: number;
    seed: number;
  };
  limits: { max_volume: number; min_volume: number };
}

export interface GenerateRequest {
  batch: string;
  archetype: string;
  payment_mix?: string | null;
  volume: number;
  cycle_days?: number | null;
  seed: number;
  defect_profile?: string;
  defects?: Record<string, { count?: number; rate?: number }>;
}

export interface GenerateResult {
  batch: string;
  generated: true;
  rows_processed: number;
  missing_sources: string[];
  note: string | null;
  headline: string;
  manifest: Audit["manifest"];
  files: Record<string, { filename: string; rows: number }>;
  scenario: {
    archetype: string;
    payment_mix: string;
    volume: number;
    settlement_cycle_days: number;
    defect_profile: string;
    seed: number;
    gross: Money;
    expected_fees: Money;
    defect_count: number;
    decoy_count: number;
    adjusted: { type: string; label: string; asked: number; planted: number }[];
    planted: { type: string; label: string; count: number; impact: Money }[];
  };
}

export const api = {
  verdict: (batch: string) => get<Verdict>(`/api/verdict/${batch}`),
  detail: (batch: string, classification: string) =>
    get<Detail>(`/api/detail/${batch}/${classification}`),
  correlation: (batch: string) => get<Correlation>(`/api/correlation/${batch}`),
  batches: () =>
    get<{
      batches: {
        name: string;
        has_ground_truth: boolean;
        uploaded: boolean;
        generated: boolean;
      }[];
    }>("/api/batches"),
  audit: (batch: string, stage?: string) =>
    get<Audit>(`/api/audit/${batch}${stage ? `?stage=${stage}` : ""}`),

  upload: (batch: string, files: Record<string, File>) => {
    const form = new FormData();
    form.append("batch", batch);
    for (const [slot, file] of Object.entries(files)) form.append(slot, file);
    return send<UploadResult>("/api/upload", { method: "POST", body: form });
  },

  inspect: (source: string, file: File) => {
    const form = new FormData();
    form.append("source", source);
    form.append("file", file);
    return send<Inspected>("/api/inspect", { method: "POST", body: form });
  },

  rememberMapping: (
    source: string,
    headers: string[],
    mapping: Record<string, string>,
  ) =>
    send<{ remembered: unknown }>("/api/mappings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, headers, mapping }),
    }),

  actions: (batch: string) => get<Actions>(`/api/actions/${batch}`),

  /** The CSV lives at a URL so the browser downloads it rather than us building a blob. */
  actionsCsvUrl: (batch: string) => `${BASE}/api/actions/${batch}/csv`,

  rateCard: () => get<RateCard>("/api/rate-card"),

  setRateCard: (card: Record<string, unknown>) =>
    send<RateCard>("/api/rate-card", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(card),
    }),

  clearRateCard: () => send<RateCard>("/api/rate-card", { method: "DELETE" }),

  generateOptions: () => get<GenerateOptions>("/api/generate/options"),

  generate: (req: GenerateRequest) =>
    send<GenerateResult>("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),
};
