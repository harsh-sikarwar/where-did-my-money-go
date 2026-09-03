"use client";

import { useRef, useState } from "react";
import { Button, Dot, ErrorNote, Field, TextInput } from "@/components/ui";
import { api, ApiError, type UnmappedColumns, type UploadResult } from "@/lib/api";

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
  {
    key: "ledger",
    label: "Your ledger",
    accept: ".csv,.xlsx,.xlsm",
    required: true,
    hint: "Full order-level export from your system",
  },
  {
    key: "recon",
    label: "Settlement recon",
    accept: ".json",
    required: false,
    hint: "Razorpay's settlement report (JSON)",
  },
  {
    key: "bank",
    label: "Bank statement",
    accept: ".csv,.xlsx,.xlsm",
    required: false,
    hint: "Optional — for final bank-credit matching",
  },
  {
    key: "payments",
    label: "Payments",
    accept: ".json",
    required: false,
    hint: "Needed to explain failed payments",
  },
  {
    key: "subscriptions",
    label: "Subscriptions",
    accept: ".json",
    required: false,
    hint: "Needed to find halted subscriptions",
  },
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
    return (
      <Done
        result={result}
        onAgain={() => {
          setResult(null);
          setFiles({});
          setBatch("");
        }}
      />
    );
  }

  if (question) {
    return (
      <MappingPicker
        question={question}
        choice={choice}
        onChoose={(field, column) => setChoice((c) => ({ ...c, [field]: column }))}
        onConfirm={confirmMapping}
        onCancel={() => {
          setQuestion(null);
          setChoice({});
        }}
        busy={busy}
        error={error}
      />
    );
  }

  const ready = batch.trim().length > 0 && Boolean(files.ledger);

  return (
    <section>
      <div className="mb-8">
        <Field label="Name this run">
          <TextInput
            value={batch}
            onChange={setBatch}
            placeholder="Sept settlement check"
          />
        </Field>
      </div>

      <div className="border-t border-[var(--color-line)]">
        {SLOTS.map((slot) => (
          <FileRow
            key={slot.key}
            slot={slot}
            file={files[slot.key]}
            onPick={(file) =>
              setFiles((f) => {
                if (!file) {
                  const { [slot.key]: _removed, ...rest } = f;
                  return rest;
                }
                return { ...f, [slot.key]: file };
              })
            }
          />
        ))}
      </div>

      {error && (
        <div className="mt-6">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      <Button
        onClick={submit}
        disabled={!ready || busy}
        size="lg"
        full
        className="mt-10"
      >
        {busy ? "Reconciling…" : "Reconcile"}
      </Button>
    </section>
  );
}

/**
 * One file slot. The chosen filename replaces the empty state in place and turns
 * green — the row itself reports its status, so there is no separate checklist to
 * cross-reference.
 */
function FileRow({
  slot,
  file,
  onPick,
}: {
  slot: (typeof SLOTS)[number];
  file?: File;
  onPick: (file: File | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);

  return (
    <div className="flex items-start justify-between gap-5 border-b border-[var(--color-line)] py-6">
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="text-[15px] leading-snug font-semibold">
          {slot.label}
          {slot.required && (
            <span className="ml-1 font-semibold text-[var(--color-action)]">*</span>
          )}
        </div>
        <div className="text-[13px] leading-snug text-[var(--color-ink-faint)]">
          {slot.hint}
        </div>
        {file ? (
          <div className="tnum flex min-w-0 items-center gap-2 text-[12.5px] text-[var(--color-benign)]">
            <Dot severity="benign" />
            <span className="truncate">{file.name}</span>
          </div>
        ) : (
          <div className="text-[12.5px] text-[var(--color-ink-faint)]">
            No file selected
          </div>
        )}
      </div>

      <input
        ref={input}
        type="file"
        accept={slot.accept}
        className="sr-only"
        onChange={(e) => onPick(e.target.files?.[0] ?? null)}
      />
      <Button variant="secondary" size="sm" onClick={() => input.current?.click()}>
        {file ? "Replace" : "Choose file"}
      </Button>
    </div>
  );
}

/**
 * The refusal, made answerable. Each unmapped field offers the columns the engine
 * actually saw — picking one is a chip, not a dropdown, because the whole set is
 * short and comparing them side by side is the task.
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
  const answered = question.unmapped.every((f) => choice[f.canonical]);

  return (
    <section>
      <h2 className="text-headline mb-3">Which column is which?</h2>
      <p className="mb-10 text-[15px] leading-relaxed text-pretty text-[var(--color-ink-soft)]">
        {question.message}
      </p>

      {question.unmapped.map((field) => (
        <div key={field.canonical} className="mb-8">
          <div className="mb-3 flex flex-wrap items-baseline gap-2">
            <span className="text-[14.5px] font-semibold">
              {FIELD_LABELS[field.canonical] ?? field.canonical}
            </span>
            <span className="money text-xs text-[var(--color-ink-faint)]">
              {field.canonical}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {field.candidates.map((column) => {
              const picked = choice[field.canonical] === column;
              return (
                <button
                  key={column}
                  type="button"
                  aria-pressed={picked}
                  onClick={() => onChoose(field.canonical, column)}
                  className={`pressable rounded-full px-4 py-2.5 text-[13.5px] transition-[filter,background-color,color] duration-200 hover:brightness-125 ${
                    picked
                      ? "bg-[var(--color-ink)] font-bold text-[var(--color-ground)]"
                      : "border border-[var(--color-line)] bg-[var(--color-raised)] text-[var(--color-ink)]"
                  }`}
                >
                  {column}
                </button>
              );
            })}
          </div>
        </div>
      ))}

      <p className="mt-6 text-[12.5px] text-[var(--color-ink-faint)]">
        We&rsquo;ll remember this for files shaped like this one, so you are asked once.
      </p>

      {error && (
        <div className="mt-6">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      <Button
        onClick={onConfirm}
        disabled={!answered || busy}
        size="lg"
        full
        className="mt-8"
      >
        {busy ? "Reconciling…" : "Remember and reconcile"}
      </Button>
      <div className="mt-4 text-center">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Back
        </Button>
      </div>
    </section>
  );
}

function Done({ result, onAgain }: { result: UploadResult; onAgain: () => void }) {
  const fileCount = Object.keys(result.files).length;

  return (
    <section>
      <h2 className="text-title mb-2">{result.headline}</h2>
      <p className="tnum mb-4 text-[15px] text-[var(--color-ink-soft)]">
        {result.rows_processed.toLocaleString("en-IN")} rows read from {fileCount} file
        {fileCount === 1 ? "" : "s"}.
      </p>

      {/* What the answer does NOT cover. Named, never left to be assumed. */}
      {result.note && (
        <p className="mb-5 border-l-2 border-[var(--color-line-strong)] pl-3 text-[15px] leading-relaxed text-[var(--color-ink-soft)]">
          {result.note}
        </p>
      )}

      <Button variant="ghost" size="sm" onClick={onAgain}>
        Upload another
      </Button>
    </section>
  );
}
