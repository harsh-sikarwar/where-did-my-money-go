"use client";

import { useState } from "react";
import {
  api,
  ApiError,
  type UnmappedColumns,
  type UploadResult,
} from "@/lib/api";

/**
 * Upload a merchant's own files and reconcile them.
 *
 * The whole point of this screen is the middle step. When the engine cannot map a
 * column it refuses — correctly, because a silently mapped column produces a confident
 * wrong reconciliation (BEHAVIOR.md, stage `normalize`). That refusal is only useful if
 * a human can answer it, so the 422 becomes a picker rather than a dead end, and the
 * answer is remembered against the file's shape so it is asked once. ADR-044, ADR-045.
 *
 * Only the ledger is required. The engine has a real answer for every other absence —
 * no bank file means money is reported in flight rather than missing — and that answer
 * is better than refusing the upload.
 */

const SLOTS = [
  { key: "ledger", label: "Your ledger", accept: ".csv,.xlsx,.xlsm", required: true,
    hint: "What you recorded. CSV or Excel." },
  { key: "recon", label: "Settlement recon", accept: ".json", required: false,
    hint: "Razorpay's settlement report (JSON)." },
  { key: "bank", label: "Bank statement", accept: ".csv,.xlsx,.xlsm", required: false,
    hint: "What actually arrived. Optional." },
  { key: "payments", label: "Payments", accept: ".json", required: false,
    hint: "Needed to explain failed payments." },
  { key: "subscriptions", label: "Subscriptions", accept: ".json", required: false,
    hint: "Needed to find halted subscriptions." },
] as const;

/** Human names for the canonical fields a merchant is asked to identify. */
const FIELD_LABELS: Record<string, string> = {
  order_id: "Order reference",
  amount_paise: "Sale amount",
  captured_at: "Date",
  customer_id: "Customer",
  payment_method: "Payment method",
  utr: "Bank reference (UTR)",
  credit_paise: "Amount credited",
  value_date: "Value date",
};

export function Upload({ onDone }: { onDone: (batch: string) => void }) {
  const [batch, setBatch] = useState("");
  const [files, setFiles] = useState<Record<string, File>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState<UnmappedColumns | null>(null);
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [result, setResult] = useState<UploadResult | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    setQuestion(null);
    try {
      const body = await api.upload(batch.trim(), files);
      setResult(body);
      onDone(body.batch);
    } catch (e) {
      if (e instanceof ApiError) {
        const unmapped = e.unmappedColumns;
        // The one error a merchant can fix from here. Everything else is reported.
        if (unmapped) setQuestion(unmapped);
        else setError(e.message);
      } else {
        setError("Something went wrong.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirmMapping() {
    if (!question) return;
    setBusy(true);
    setError(null);
    try {
      await api.rememberMapping(question.source, question.headers, choice);
      setQuestion(null);
      setChoice({});
      await submit();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save that mapping.");
      setBusy(false);
    }
  }

  if (result) {
    return <Done result={result} onAgain={() => { setResult(null); setFiles({}); setBatch(""); }} />;
  }

  if (question) {
    return (
      <MappingPicker
        question={question}
        choice={choice}
        onChoose={(field, column) => setChoice((c) => ({ ...c, [field]: column }))}
        onConfirm={confirmMapping}
        onCancel={() => { setQuestion(null); setChoice({}); }}
        busy={busy}
        error={error}
      />
    );
  }

  const ready = batch.trim().length > 0 && Boolean(files.ledger);

  return (
    <section className="mb-14">
      <h2 className="mb-1 text-sm font-medium">Reconcile your own files</h2>
      <p className="mb-6 text-sm text-[var(--color-ink-faint)]">
        Upload what you have. Only your ledger is required — the engine says what it
        could not answer rather than refusing what it can.
      </p>

      <label className="mb-6 block">
        <span className="mb-1 block text-xs text-[var(--color-ink-faint)]">
          Name this run
        </span>
        <input
          value={batch}
          onChange={(e) => setBatch(e.target.value)}
          placeholder="september-week-1"
          className="w-full max-w-sm rounded border border-[var(--color-line)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--color-ink-faint)]"
        />
        <span className="mt-1 block text-xs text-[var(--color-ink-faint)]">
          Letters, digits, hyphens. Each run is kept, so names cannot be reused.
        </span>
      </label>

      <div className="space-y-px">
        {SLOTS.map((slot) => (
          <FileRow
            key={slot.key}
            slot={slot}
            file={files[slot.key]}
            onPick={(f) =>
              setFiles((current) => {
                const next = { ...current };
                if (f) next[slot.key] = f;
                else delete next[slot.key];
                return next;
              })
            }
          />
        ))}
      </div>

      {error && (
        <p className="mt-5 whitespace-pre-wrap text-sm text-[var(--color-attention)]">
          {error}
        </p>
      )}

      <button
        onClick={submit}
        disabled={!ready || busy}
        className="mt-6 rounded bg-[var(--color-ink)] px-4 py-2 text-sm text-white disabled:opacity-30"
      >
        {busy ? "Reconciling…" : "Reconcile"}
      </button>
    </section>
  );
}

function FileRow({
  slot,
  file,
  onPick,
}: {
  slot: (typeof SLOTS)[number];
  file?: File;
  onPick: (f: File | null) => void;
}) {
  return (
    <div className="flex items-baseline gap-4 border-b border-[var(--color-line)] py-3">
      <div className="w-40 shrink-0">
        <span className="text-sm">{slot.label}</span>
        {slot.required && (
          <span className="ml-1 text-xs text-[var(--color-attention)]">required</span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <input
          type="file"
          accept={slot.accept}
          onChange={(e) => onPick(e.target.files?.[0] ?? null)}
          className="block w-full text-xs text-[var(--color-ink-soft)] file:mr-3 file:rounded file:border file:border-[var(--color-line)] file:bg-white file:px-3 file:py-1 file:text-xs"
        />
        <span className="mt-1 block text-xs text-[var(--color-ink-faint)]">
          {file ? `${file.name} · ${Math.max(1, Math.round(file.size / 1024))} KB` : slot.hint}
        </span>
      </div>
    </div>
  );
}

/**
 * The mapping question. Every unclaimed column is offered, in file order — deliberately
 * not a ranked guess, because a plausible wrong suggestion accepted without thought is
 * worse than no suggestion, and the person is being asked precisely because the engine
 * cannot tell (ADR-045).
 */
function MappingPicker({
  question,
  choice,
  onChoose,
  onConfirm,
  onCancel,
  busy,
  error,
}: {
  question: UnmappedColumns;
  choice: Record<string, string>;
  onChoose: (field: string, column: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
  error: string | null;
}) {
  const complete = question.unmapped.every((u) => choice[u.canonical]);

  return (
    <section className="mb-14">
      <h2 className="mb-1 text-sm font-medium">
        Which column is which?
      </h2>
      <p className="mb-6 text-sm text-[var(--color-ink-faint)]">
        The engine will not guess at a column it does not recognise — a wrong guess
        produces a confident wrong answer you could not tell from a right one. Tell it
        once and it will remember this file&rsquo;s shape.
      </p>

      <div className="space-y-5">
        {question.unmapped.map((field) => (
          <div key={field.canonical}>
            <div className="mb-2 flex items-baseline gap-2">
              <span className="text-sm">
                {FIELD_LABELS[field.canonical] ?? field.canonical}
              </span>
              <span className="font-mono text-xs text-[var(--color-ink-faint)]">
                {field.canonical}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {field.candidates.map((column) => {
                const picked = choice[field.canonical] === column;
                return (
                  <button
                    key={column}
                    onClick={() => onChoose(field.canonical, column)}
                    className={`rounded border px-3 py-1.5 font-mono text-xs ${
                      picked
                        ? "border-[var(--color-ink)] bg-[var(--color-ink)] text-white"
                        : "border-[var(--color-line)] bg-white text-[var(--color-ink-soft)]"
                    }`}
                  >
                    {column}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {Object.keys(question.already_mapped).length > 0 && (
        <p className="mt-6 text-xs text-[var(--color-ink-faint)]">
          Already recognised:{" "}
          {Object.entries(question.already_mapped)
            .map(([field, column]) => `${column} → ${field}`)
            .join(", ")}
        </p>
      )}

      {error && (
        <p className="mt-5 text-sm text-[var(--color-attention)]">{error}</p>
      )}

      <div className="mt-7 flex items-center gap-3">
        <button
          onClick={onConfirm}
          disabled={!complete || busy}
          className="rounded bg-[var(--color-ink)] px-4 py-2 text-sm text-white disabled:opacity-30"
        >
          {busy ? "Saving…" : "Remember and reconcile"}
        </button>
        <button
          onClick={onCancel}
          className="text-sm text-[var(--color-ink-faint)] underline underline-offset-4"
        >
          Back
        </button>
      </div>
    </section>
  );
}

function Done({
  result,
  onAgain,
}: {
  result: UploadResult;
  onAgain: () => void;
}) {
  return (
    <section className="mb-14">
      <h2 className="mb-1 text-sm font-medium">{result.headline}</h2>
      <p className="mb-4 text-sm text-[var(--color-ink-faint)]">
        {result.rows_processed.toLocaleString()} rows read from{" "}
        {Object.keys(result.files).length} file
        {Object.keys(result.files).length === 1 ? "" : "s"}.
      </p>

      {/* What the answer does NOT cover. Named, never left to be assumed. */}
      {result.note && (
        <p className="mb-4 border-l-2 border-[var(--color-line)] pl-3 text-sm text-[var(--color-ink-soft)]">
          {result.note}
        </p>
      )}

      <button
        onClick={onAgain}
        className="text-sm text-[var(--color-ink-faint)] underline underline-offset-4"
      >
        Upload another
      </button>
    </section>
  );
}
