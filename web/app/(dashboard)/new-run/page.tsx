"use client";

/**
 * New run — the two-mode wizard that replaces `/upload` and `/generate`.
 * "Upload files" ports `components/Upload.tsx`'s real logic (file slots,
 * unmapped-columns picker, error states) restyled to the dashboard theme.
 * "Generate scenario" ports `app/generate/page.tsx`'s real logic (archetype /
 * payment-mix / defect-profile controls, all read from `api.generateOptions()`
 * so this form can never offer something the engine doesn't accept).
 *
 * Both modes end in the same real network call (`api.upload` or
 * `api.generate`) and the same "run in progress" transition state below.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CheckIcon,
  DashButton,
  DashCard,
  Pill,
  SectionLabel,
  StatusDot,
} from "@/components/dash/primitives";
import { useCurrentBatch } from "@/lib/current-batch";
import {
  api,
  ApiError,
  type GenerateOptions,
  type UnmappedColumns,
} from "@/lib/api";

/* ------------------------------------------------------------------ upload constants */

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

type DefectCounts = Record<string, { count: number }>;
type Mode = "upload" | "generate";
type Phase = "setup" | "mapping" | "running";

/* ------------------------------------------------------------------ shared input style */

const inputStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  background: "var(--dash-raised)",
  border: "1px solid var(--dash-line-strong)",
  borderRadius: 10,
  padding: "13px 15px",
  color: "var(--dash-ink)",
  fontSize: 14.5,
  outline: "none",
};

const labelStyle: React.CSSProperties = {
  fontSize: 12.5,
  fontWeight: 600,
  color: "var(--dash-ink-soft)",
};

export default function NewRun() {
  const router = useRouter();
  const { setBatch } = useCurrentBatch();
  const [mode, setMode] = useState<Mode>("upload");
  const [phase, setPhase] = useState<Phase>("setup");
  const [error, setError] = useState<string | null>(null);

  /* ------------------------------------------------------------ upload state */
  const [uploadBatch, setUploadBatch] = useState("");
  const [files, setFiles] = useState<Record<string, File>>({});
  const [question, setQuestion] = useState<UnmappedColumns | null>(null);
  const [choice, setChoice] = useState<Record<string, string>>({});

  /* ----------------------------------------------------------- generate state */
  const [options, setOptions] = useState<GenerateOptions | null>(null);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [genBatch, setGenBatch] = useState("");
  const [archetype, setArchetype] = useState("");
  const [paymentMix, setPaymentMix] = useState("");
  const [volume, setVolume] = useState(200);
  const [cycleDays, setCycleDays] = useState<number | "">("");
  const [seed, setSeed] = useState(0);
  const [profile, setProfile] = useState("");
  const [defects, setDefects] = useState<DefectCounts>({});
  const [defectOrder, setDefectOrder] = useState<string[]>([]);
  const [showDecoys, setShowDecoys] = useState(false);

  useEffect(() => {
    api
      .generateOptions()
      .then((o) => {
        setOptions(o);
        setGenBatch(suggestName());
        setArchetype(o.defaults.archetype);
        setVolume(o.defaults.volume);
        setSeed(o.defaults.seed);
        setProfile(o.defaults.defect_profile);
        const applied = applyProfile(o, o.defaults.defect_profile);
        setDefects(applied);
        setDefectOrder(orderByCount(o, applied));
      })
      .catch((e) =>
        setOptionsError(e instanceof ApiError ? e.message : "Could not reach the engine."),
      );
  }, []);

  const activeArchetype = useMemo(
    () => options?.archetypes.find((a) => a.name === archetype) ?? null,
    [options, archetype],
  );

  const activeMix = useMemo(() => {
    if (!options) return null;
    if (paymentMix) return options.payment_mixes.find((m) => m.name === paymentMix)?.mix ?? null;
    return activeArchetype?.default_mix ?? null;
  }, [options, paymentMix, activeArchetype]);

  const volumeError = useMemo(() => {
    if (!options) return null;
    const { min_volume, max_volume } = options.limits;
    if (!Number.isFinite(volume) || volume < min_volume) {
      return `Order count must be at least ${min_volume.toLocaleString("en-IN")}.`;
    }
    if (volume > max_volume) {
      return `Order count tops out at ${max_volume.toLocaleString("en-IN")} here — larger runs are a CLI job.`;
    }
    return null;
  }, [options, volume]);

  function pickProfile(name: string) {
    setProfile(name);
    if (!options) return;
    const applied = applyProfile(options, name);
    setDefects(applied);
    setDefectOrder(orderByCount(options, applied));
  }

  /* ------------------------------------------------------------------ submit: upload */

  async function submitUpload() {
    setPhase("running");
    setError(null);
    try {
      const body = await api.upload(uploadBatch.trim(), files);
      setBatch(body.batch);
      router.push(`/analysis/${encodeURIComponent(body.batch)}`);
    } catch (e) {
      if (e instanceof ApiError) {
        const unmapped = e.unmappedColumns;
        if (unmapped) {
          setQuestion(unmapped);
          setPhase("mapping");
        } else {
          setError(e.message);
          setPhase("setup");
        }
      } else {
        setError("Something went wrong.");
        setPhase("setup");
      }
    }
  }

  async function confirmMapping() {
    if (!question) return;
    setPhase("running");
    setError(null);
    try {
      await api.rememberMapping(question.source, question.headers, choice);
      setQuestion(null);
      setChoice({});
      await submitUpload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save that mapping.");
      setPhase("mapping");
    }
  }

  /* ----------------------------------------------------------------- submit: generate */

  async function submitGenerate() {
    if (!options) return;
    setPhase("running");
    setError(null);
    try {
      const activeDefects = Object.fromEntries(
        Object.entries(defects).filter(([, v]) => v.count > 0),
      );
      const body = await api.generate({
        batch: genBatch.trim(),
        archetype,
        payment_mix: paymentMix || null,
        volume,
        cycle_days: cycleDays === "" ? null : cycleDays,
        seed,
        defects: Object.keys(activeDefects).length > 0 ? activeDefects : undefined,
        defect_profile: Object.keys(activeDefects).length > 0 ? undefined : profile,
      });
      setBatch(body.batch);
      router.push(`/analysis/${encodeURIComponent(body.batch)}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setPhase("setup");
    }
  }

  const uploadReady = uploadBatch.trim().length > 0 && Boolean(files.ledger);
  const generateReady = Boolean(options) && genBatch.trim().length > 0 && volumeError === null;

  const steps =
    mode === "upload"
      ? [
          { key: "setup", label: "Setup" },
          { key: "mapping", label: "Mapping" },
          { key: "running", label: "Reconcile" },
        ]
      : [
          { key: "setup", label: "Setup" },
          { key: "running", label: "Reconcile" },
        ];
  const activeStepIndex = steps.findIndex((s) => s.key === phase);

  return (
    <div style={{ maxWidth: 760, margin: "0 auto" }}>
      <h1
        style={{
          fontFamily: "var(--dash-font-serif)",
          fontSize: 40,
          fontWeight: 400,
          letterSpacing: "-0.012em",
          margin: "0 0 8px",
        }}
      >
        New reconciliation
      </h1>
      <p style={{ fontSize: 14, color: "var(--dash-ink-soft)", margin: "0 0 26px" }}>
        Bring your own exports, or generate a scenario with defects planted in.
      </p>

      {phase !== "running" && (
        <>
          <ModeSwitch
            mode={mode}
            onChange={(m) => {
              setMode(m);
              setError(null);
            }}
          />
          <StepIndicator steps={steps} activeIndex={activeStepIndex < 0 ? 0 : activeStepIndex} />
        </>
      )}

      {phase === "running" && <RunProgress mode={mode} />}

      {phase === "mapping" && question && (
        <MappingPicker
          question={question}
          choice={choice}
          onChoose={(field, column) => setChoice((c) => ({ ...c, [field]: column }))}
          onConfirm={confirmMapping}
          onCancel={() => {
            setQuestion(null);
            setChoice({});
            setPhase("setup");
          }}
          error={error}
        />
      )}

      {phase === "setup" && mode === "upload" && (
        <UploadForm
          batch={uploadBatch}
          onBatch={setUploadBatch}
          files={files}
          onFiles={setFiles}
          ready={uploadReady}
          error={error}
          onSubmit={submitUpload}
        />
      )}

      {phase === "setup" && mode === "generate" && (
        <GenerateForm
          options={options}
          optionsError={optionsError}
          batch={genBatch}
          onBatch={setGenBatch}
          archetype={archetype}
          onArchetype={setArchetype}
          activeArchetype={activeArchetype}
          paymentMix={paymentMix}
          onPaymentMix={setPaymentMix}
          activeMix={activeMix}
          volume={volume}
          onVolume={setVolume}
          volumeError={volumeError}
          cycleDays={cycleDays}
          onCycleDays={setCycleDays}
          seed={seed}
          onSeed={setSeed}
          profile={profile}
          onProfile={pickProfile}
          defects={defects}
          onDefect={(type, count) => setDefects((d) => ({ ...d, [type]: { count } }))}
          defectOrder={defectOrder}
          showDecoys={showDecoys}
          onShowDecoys={setShowDecoys}
          ready={generateReady}
          error={error}
          onSubmit={submitGenerate}
        />
      )}
    </div>
  );
}

/* ==================================================================== mode switch */

function ModeSwitch({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  return (
    <div
      style={{
        display: "flex",
        gap: 6,
        background: "var(--dash-raised)",
        border: "1px solid var(--dash-line-strong)",
        borderRadius: 11,
        padding: 5,
        marginBottom: 30,
        width: "fit-content",
      }}
    >
      {(
        [
          { key: "upload", label: "Upload files" },
          { key: "generate", label: "Generate scenario" },
        ] as const
      ).map((m) => {
        const active = mode === m.key;
        return (
          <button
            key={m.key}
            type="button"
            onClick={() => onChange(m.key)}
            style={{
              borderRadius: 8,
              padding: "9px 16px",
              fontSize: 13,
              fontWeight: active ? 700 : 600,
              cursor: "pointer",
              border: "none",
              background: active ? "var(--dash-benign-soft)" : "transparent",
              color: active ? "oklch(0.30 0.06 148)" : "var(--dash-ink-soft)",
              transition: "background .2s",
            }}
          >
            {m.label}
          </button>
        );
      })}
    </div>
  );
}

/* ==================================================================== step indicator */

function StepIndicator({
  steps,
  activeIndex,
}: {
  steps: { key: string; label: string }[];
  activeIndex: number;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 30 }}>
      {steps.map((st, i) => (
        <div key={st.key} style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 24,
              height: 24,
              borderRadius: 999,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "var(--dash-font-mono)",
              fontSize: 11.5,
              fontWeight: 700,
              flex: "none",
              background: i === activeIndex ? "var(--dash-benign-soft)" : "var(--dash-line-soft)",
              color: i === activeIndex ? "oklch(0.30 0.06 148)" : "var(--dash-ink-faint)",
            }}
          >
            {i < activeIndex ? <CheckIcon size={11} /> : i + 1}
          </div>
          <div
            style={{
              fontSize: 12.5,
              fontWeight: 600,
              color: i === activeIndex ? "var(--dash-ink)" : "var(--dash-ink-faint)",
              whiteSpace: "nowrap",
            }}
          >
            {st.label}
          </div>
          {i < steps.length - 1 && (
            <div style={{ width: 34, height: 1, background: "var(--dash-line-strong)" }} />
          )}
        </div>
      ))}
    </div>
  );
}

/* ==================================================================== upload mode */

function UploadForm({
  batch,
  onBatch,
  files,
  onFiles,
  ready,
  error,
  onSubmit,
}: {
  batch: string;
  onBatch: (v: string) => void;
  files: Record<string, File>;
  onFiles: (updater: (f: Record<string, File>) => Record<string, File>) => void;
  ready: boolean;
  error: string | null;
  onSubmit: () => void;
}) {
  return (
    <div>
      <div style={{ marginBottom: 26 }}>
        <label style={labelStyle}>Name this run</label>
        <input
          type="text"
          value={batch}
          onChange={(e) => onBatch(e.target.value)}
          placeholder="Sept settlement check"
          style={{ ...inputStyle, marginTop: 9 }}
        />
      </div>

      {SLOTS.map((slot) => (
        <FileRow
          key={slot.key}
          slot={slot}
          file={files[slot.key]}
          onPick={(file) =>
            onFiles((f) => {
              if (!file) {
                const { [slot.key]: _removed, ...rest } = f;
                return rest;
              }
              return { ...f, [slot.key]: file };
            })
          }
        />
      ))}

      {error && <ErrorBanner>{error}</ErrorBanner>}

      <DashButton variant="primary" size="md" full disabled={!ready} onClick={onSubmit} style={{ marginTop: 28, padding: "15px" }}>
        Reconcile
      </DashButton>
      <div style={{ textAlign: "center", fontSize: 12, color: "var(--dash-ink-faint)", marginTop: 12 }}>
        Nothing leaves this workspace. Typical run: under a second.
      </div>
    </div>
  );
}

function FileRow({
  slot,
  file,
  onPick,
}: {
  slot: (typeof SLOTS)[number];
  file?: File;
  onPick: (file: File | null) => void;
}) {
  return (
    <DashCard style={{ padding: "18px 20px", marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 20 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
          <div style={{ fontSize: 14.5, fontWeight: 600, lineHeight: 1.35 }}>
            {slot.label}{" "}
            <span
              style={
                slot.required
                  ? { color: "var(--dash-action)", fontWeight: 700 }
                  : { fontSize: 11.5, fontWeight: 600, color: "var(--dash-ink-faint)" }
              }
            >
              {slot.required ? "*" : "optional"}
            </span>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--dash-ink-soft)", lineHeight: 1.4 }}>{slot.hint}</div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 7,
              fontFamily: "var(--dash-font-mono)",
              fontSize: 12,
              color: file ? "var(--dash-benign)" : "var(--dash-ink-faint)",
              marginTop: 2,
            }}
          >
            {file && <StatusDot severity="benign" size={6} />}
            {file ? file.name : "No file selected"}
          </div>
        </div>

        <label
          style={{
            flex: "none",
            border: "1px solid var(--dash-line-strong)",
            borderRadius: 999,
            padding: "9px 18px",
            fontSize: 12.5,
            fontWeight: 600,
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          {file ? "Replace" : "Choose file"}
          <input
            type="file"
            accept={slot.accept}
            className="sr-only"
            style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0,0,0,0)" }}
            onChange={(e) => onPick(e.target.files?.[0] ?? null)}
          />
        </label>
      </div>
    </DashCard>
  );
}

/* ==================================================================== mapping picker */

function MappingPicker({
  question,
  choice,
  onChoose,
  onConfirm,
  onCancel,
  error,
}: {
  question: UnmappedColumns;
  choice: Record<string, string>;
  onChoose: (field: string, column: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  error: string | null;
}) {
  const answered = question.unmapped.every((f) => choice[f.canonical]);

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 700, margin: "0 0 10px" }}>Which column is which?</h2>
      <p style={{ fontSize: 14, lineHeight: 1.6, color: "var(--dash-ink-soft)", margin: "0 0 28px" }}>
        {question.message}
      </p>

      {question.unmapped.map((field) => (
        <div key={field.canonical} style={{ marginBottom: 22 }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 14, fontWeight: 700 }}>{FIELD_LABELS[field.canonical] ?? field.canonical}</span>
            <span style={{ fontFamily: "var(--dash-font-mono)", fontSize: 11.5, color: "var(--dash-ink-faint)" }}>
              {field.canonical}
            </span>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {field.candidates.map((column) => {
              const picked = choice[field.canonical] === column;
              return (
                <button
                  key={column}
                  type="button"
                  aria-pressed={picked}
                  onClick={() => onChoose(field.canonical, column)}
                  style={{
                    borderRadius: 999,
                    padding: "9px 15px",
                    fontSize: 13,
                    cursor: "pointer",
                    transition: "background .2s, color .2s",
                    border: picked ? "none" : "1px solid var(--dash-line-strong)",
                    background: picked ? "var(--dash-ink)" : "var(--dash-raised)",
                    color: picked ? "var(--dash-ground)" : "var(--dash-ink)",
                    fontWeight: picked ? 700 : 500,
                  }}
                >
                  {column}
                </button>
              );
            })}
          </div>
        </div>
      ))}

      <p style={{ marginTop: 18, fontSize: 12.5, color: "var(--dash-ink-faint)" }}>
        We&rsquo;ll remember this for files shaped like this one, so you are asked once.
      </p>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      <DashButton variant="primary" size="md" full disabled={!answered} onClick={onConfirm} style={{ marginTop: 22, padding: "15px" }}>
        Remember and reconcile
      </DashButton>
      <div style={{ textAlign: "center", marginTop: 12 }}>
        <DashButton variant="ghost" size="sm" onClick={onCancel}>
          Back
        </DashButton>
      </div>
    </div>
  );
}

/* ==================================================================== generate mode */

function GenerateForm({
  options,
  optionsError,
  batch,
  onBatch,
  archetype,
  onArchetype,
  activeArchetype,
  paymentMix,
  onPaymentMix,
  activeMix,
  volume,
  onVolume,
  volumeError,
  cycleDays,
  onCycleDays,
  seed,
  onSeed,
  profile,
  onProfile,
  defects,
  onDefect,
  defectOrder,
  showDecoys,
  onShowDecoys,
  ready,
  error,
  onSubmit,
}: {
  options: GenerateOptions | null;
  optionsError: string | null;
  batch: string;
  onBatch: (v: string) => void;
  archetype: string;
  onArchetype: (v: string) => void;
  activeArchetype: GenerateOptions["archetypes"][number] | null;
  paymentMix: string;
  onPaymentMix: (v: string) => void;
  activeMix: Record<string, number> | null;
  volume: number;
  onVolume: (v: number) => void;
  volumeError: string | null;
  cycleDays: number | "";
  onCycleDays: (v: number | "") => void;
  seed: number;
  onSeed: (v: number) => void;
  profile: string;
  onProfile: (v: string) => void;
  defects: DefectCounts;
  onDefect: (type: string, count: number) => void;
  defectOrder: string[];
  showDecoys: boolean;
  onShowDecoys: (v: boolean) => void;
  ready: boolean;
  error: string | null;
  onSubmit: () => void;
}) {
  if (optionsError) return <ErrorBanner>{optionsError}</ErrorBanner>;
  if (!options) {
    return <div style={{ color: "var(--dash-ink-faint)", fontSize: 13, padding: "20px 0" }}>Loading generator options…</div>;
  }

  const activeProfile = options.defect_profiles.find((p) => p.name === profile);
  const defectTypes = defectOrder
    .map((name) => options.defect_types.find((d) => d.name === name))
    .filter((d): d is GenerateOptions["defect_types"][number] => Boolean(d))
    .filter((d) => showDecoys || d.is_defect);

  return (
    <div>
      <div style={{ marginBottom: 26 }}>
        <label style={labelStyle}>Name this run</label>
        <input
          type="text"
          value={batch}
          onChange={(e) => onBatch(e.target.value)}
          placeholder="my-scenario"
          style={{ ...inputStyle, marginTop: 9 }}
        />
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 26 }}>
        <div style={{ flex: 2 }}>
          <label style={labelStyle}>Archetype</label>
          <select
            value={archetype}
            onChange={(e) => onArchetype(e.target.value)}
            style={{ ...inputStyle, marginTop: 9, fontSize: 14, cursor: "pointer" }}
          >
            {options.archetypes.map((a) => (
              <option key={a.name} value={a.name}>
                {a.name}
              </option>
            ))}
          </select>
          {activeArchetype && (
            <p style={{ marginTop: 8, fontSize: 12.5, lineHeight: 1.5, color: "var(--dash-ink-faint)" }}>
              {activeArchetype.description} Stresses: {activeArchetype.stresses}
            </p>
          )}
        </div>
        <div style={{ flex: 1 }}>
          <label style={labelStyle}>Seed</label>
          <input
            type="number"
            value={seed}
            onChange={(e) => onSeed(Number(e.target.value) || 0)}
            style={{ ...inputStyle, marginTop: 9, fontFamily: "var(--dash-font-mono)", fontSize: 14 }}
          />
          <button
            type="button"
            onClick={() => onSeed(Math.floor(Math.random() * 2 ** 31))}
            style={{
              marginTop: 6,
              background: "none",
              border: "none",
              padding: 0,
              fontSize: 11.5,
              fontWeight: 600,
              color: "var(--dash-ink-faint)",
              cursor: "pointer",
              textDecoration: "underline",
            }}
          >
            Randomize
          </button>
        </div>
      </div>
      <p style={{ marginTop: -16, marginBottom: 26, fontSize: 12, color: "var(--dash-ink-faint)" }}>
        Same seed, same scenario, every time.
      </p>

      <div style={{ marginBottom: 26 }}>
        <label style={labelStyle}>Payment mix</label>
        <select
          value={paymentMix}
          onChange={(e) => onPaymentMix(e.target.value)}
          style={{ ...inputStyle, marginTop: 9, fontSize: 14, cursor: "pointer" }}
        >
          <option value="">Archetype default</option>
          {options.payment_mixes.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </select>
        <MixBar mix={activeMix} />
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 26 }}>
        <div style={{ flex: 1 }}>
          <label style={labelStyle}>Order count</label>
          <input
            type="number"
            value={volume}
            onChange={(e) => onVolume(Number(e.target.value) || 0)}
            min={options.limits.min_volume}
            max={options.limits.max_volume}
            style={{ ...inputStyle, marginTop: 9 }}
          />
          {volumeError && (
            <p style={{ marginTop: 8, fontSize: 12.5, fontWeight: 600, color: "var(--dash-urgent)" }}>{volumeError}</p>
          )}
        </div>
        <div style={{ flex: 1 }}>
          <label style={labelStyle}>Settlement cycle (days)</label>
          <input
            type="number"
            value={cycleDays}
            onChange={(e) => onCycleDays(e.target.value === "" ? "" : Number(e.target.value) || 0)}
            min={0}
            max={30}
            placeholder={String(options.defaults.cycle_days)}
            style={{ ...inputStyle, marginTop: 9 }}
          />
        </div>
      </div>
      <p style={{ marginTop: -16, marginBottom: 26, fontSize: 12, color: "var(--dash-ink-faint)" }}>
        Up to {options.limits.max_volume.toLocaleString("en-IN")} — larger runs are a CLI job.
      </p>

      <SectionLabel style={{ marginBottom: 12 }}>What to plant</SectionLabel>
      <select
        value={profile}
        onChange={(e) => onProfile(e.target.value)}
        style={{ ...inputStyle, fontSize: 14, cursor: "pointer", marginBottom: 8 }}
      >
        {options.defect_profiles.map((p) => (
          <option key={p.name} value={p.name}>
            {p.name}
          </option>
        ))}
      </select>
      {activeProfile && (
        <p style={{ marginBottom: 16, fontSize: 12.5, lineHeight: 1.5, color: "var(--dash-ink-faint)" }}>
          {activeProfile.description}
        </p>
      )}

      <div>
        {defectTypes.map((d) => {
          const count = defects[d.name]?.count ?? 0;
          const active = count > 0;
          return (
            <div
              key={d.name}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "14px 16px",
                borderRadius: 11,
                marginBottom: 8,
                background: active ? "var(--dash-raised)" : "transparent",
                border: `1px solid ${active ? "var(--dash-line)" : "transparent"}`,
              }}
            >
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 14, fontWeight: active ? 600 : 400, color: active ? "var(--dash-ink)" : "var(--dash-ink-faint)" }}>
                    {d.label}
                  </span>
                  {!d.is_defect && <Pill accent>decoy</Pill>}
                </div>
                {d.hint && active && (
                  <p style={{ marginTop: 5, maxWidth: 420, fontSize: 12, lineHeight: 1.5, color: "var(--dash-ink-faint)" }}>
                    {d.hint}
                  </p>
                )}
              </div>
              <input
                type="number"
                value={count}
                onChange={(e) => onDefect(d.name, Math.max(0, Number(e.target.value) || 0))}
                min={0}
                style={{
                  width: 100,
                  boxSizing: "border-box",
                  background: "var(--dash-ground)",
                  border: "1px solid var(--dash-line-strong)",
                  borderRadius: 8,
                  padding: "8px 10px",
                  color: "var(--dash-ink)",
                  fontFamily: "var(--dash-font-mono)",
                  fontSize: 13,
                  textAlign: "right",
                  outline: "none",
                }}
              />
            </div>
          );
        })}
      </div>

      <button
        type="button"
        onClick={() => onShowDecoys(!showDecoys)}
        style={{
          marginTop: 10,
          background: "none",
          border: "none",
          padding: 0,
          fontSize: 12,
          fontWeight: 600,
          color: "var(--dash-accent-deep)",
          cursor: "pointer",
          textDecoration: "underline",
        }}
      >
        {showDecoys ? "Hide decoys" : "Show decoys (non-defects the engine must not flag)"}
      </button>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      <DashButton variant="primary" size="md" full disabled={!ready} onClick={onSubmit} style={{ marginTop: 28, padding: "15px" }}>
        Generate &amp; reconcile
      </DashButton>
    </div>
  );
}

function MixBar({ mix }: { mix: Record<string, number> | null }) {
  if (!mix) return null;
  const entries = Object.entries(mix).filter(([, share]) => share > 0);
  if (entries.length === 0) return null;
  const total = entries.reduce((sum, [, share]) => sum + share, 0);

  return (
    <>
      <div style={{ display: "flex", height: 9, borderRadius: 999, overflow: "hidden", marginTop: 12, gap: 2 }}>
        {entries.map(([method, share], i) => (
          <div
            key={method}
            title={`${method} — ${Math.round((share / total) * 100)}%`}
            style={{
              flex: share,
              background: `color-mix(in oklch, var(--dash-benign) ${100 - i * 22}%, transparent)`,
              transformOrigin: "left",
              animation: `growX .6s cubic-bezier(.2,.7,.2,1) ${i * 0.1}s both`,
            }}
          />
        ))}
      </div>
      <div style={{ display: "flex", gap: 18, marginTop: 11, fontSize: 12, color: "var(--dash-ink-faint)", flexWrap: "wrap" }}>
        {entries.map(([m, share]) => (
          <span key={m}>
            {Math.round((share / total) * 100)}% {m}
          </span>
        ))}
      </div>
    </>
  );
}

/* ==================================================================== run in progress */

/**
 * Both `api.upload` and `api.generate` are one synchronous HTTP call — the
 * engine reconciles inline, typically well under a second (README). There is
 * no multi-step backend job to poll and no per-order counter the frontend can
 * honestly report. What follows is a real request behind a progress
 * *illusion*: a rotating status line and an indeterminate bar that loop on a
 * timer purely for visual continuity while the one request is in flight.
 * Nothing here is a percentage or a count — that would imply knowledge the
 * app doesn't have (plan: "Run in progress", ADR-001).
 */
const STAGES: Record<Mode, string[]> = {
  upload: [
    "Reading your files…",
    "Mapping columns to the ledger…",
    "Matching orders to settlements…",
    "Classifying the gap…",
  ],
  generate: [
    "Generating synthetic orders…",
    "Planting the requested defects…",
    "Matching orders to settlements…",
    "Classifying the gap…",
  ],
};

function RunProgress({ mode }: { mode: Mode }) {
  const stages = STAGES[mode];
  const [i, setI] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setI((n) => (n + 1) % stages.length), 900);
    return () => clearInterval(id);
  }, [stages.length]);

  return (
    <div>
      <style>{`
        @keyframes newRunIndeterminate {
          0%   { transform: translateX(-40%); }
          100% { transform: translateX(250%); }
        }
      `}</style>

      <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 14 }}>
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: 999,
            background: "var(--dash-benign)",
            animation: "pulse 1.4s ease-in-out infinite",
          }}
        />
        <span
          style={{
            fontFamily: "var(--dash-font-mono)",
            fontSize: 11.5,
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--dash-accent-deep)",
          }}
        >
          {mode === "upload" ? "Reconciling" : "Generating"}
        </span>
      </div>

      <DashCard style={{ padding: 24 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>{stages[i]}</div>
        <div style={{ fontSize: 12.5, color: "var(--dash-ink-faint)", marginBottom: 18 }}>
          One request to the engine — typically under a second. There's no multi-step job
          running behind this; the line above just keeps you company while it works.
        </div>
        <div style={{ height: 6, borderRadius: 999, background: "var(--dash-line-soft)", overflow: "hidden" }}>
          <div
            style={{
              height: "100%",
              width: "40%",
              borderRadius: 999,
              background: "linear-gradient(90deg, var(--dash-benign), oklch(0.615 0.10 168))",
              animation: "newRunIndeterminate 1.3s ease-in-out infinite",
            }}
          />
        </div>
      </DashCard>
    </div>
  );
}

/* ==================================================================== misc */

function ErrorBanner({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        marginTop: 24,
        border: "1px solid color-mix(in oklch, var(--dash-urgent) 35%, transparent)",
        background: "color-mix(in oklch, var(--dash-urgent) 8%, transparent)",
        borderRadius: 10,
        padding: "12px 15px",
        fontSize: 13,
        lineHeight: 1.5,
        color: "var(--dash-ink)",
      }}
    >
      {children}
    </div>
  );
}

function suggestName(): string {
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
  return `scenario-${stamp}`;
}

function applyProfile(options: GenerateOptions, name: string): DefectCounts {
  const preset = options.defect_profiles.find((p) => p.name === name);
  if (!preset) return {};
  const volume = options.defaults.volume;
  const next: DefectCounts = {};
  for (const [type, spec] of Object.entries(preset.defects)) {
    if (typeof spec.count === "number") next[type] = { count: spec.count };
    else if (typeof spec.rate === "number") {
      next[type] = { count: Math.max(1, Math.round(spec.rate * volume)) };
    }
  }
  return next;
}

function orderByCount(options: GenerateOptions, defects: DefectCounts): string[] {
  return options.defect_types
    .map((d) => d.name)
    .sort((a, b) => (defects[b]?.count ?? 0) - (defects[a]?.count ?? 0));
}
