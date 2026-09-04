"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowRightIcon,
  BackLink,
  Badge,
  Button,
  CheckIcon,
  Card,
  ErrorNote,
  Eyebrow,
  Field,
  NumberInput,
  RefreshIcon,
  Select,
  ShareBar,
  Skeleton,
  TextInput,
} from "@/components/ui";
import {
  api,
  ApiError,
  type GenerateOptions,
  type GenerateResult,
} from "@/lib/api";

/**
 * The synthetic data control panel.
 *
 * Every option rendered here is read from `/api/generate/options`, which reads it from
 * the same YAML the engine and the CLI use — nothing in this file hardcodes an
 * archetype name or a defect type, so the dropdown cannot drift from what the engine
 * will accept (ADR-004: the generator is not a mock).
 *
 * The defect-count fields are the point of the whole screen: a preset prefills them,
 * but every field stays a live number a person can change, because "prefilled but
 * tweakable" is the brief, not "pick a preset and go".
 */

type DefectCounts = Record<string, { count: number }>;

export default function GeneratePage() {
  const router = useRouter();
  const [options, setOptions] = useState<GenerateOptions | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [batchName, setBatchName] = useState("");
  const [archetype, setArchetype] = useState("");
  const [paymentMix, setPaymentMix] = useState<string>(""); // "" = archetype default
  const [volume, setVolume] = useState(200);
  const [cycleDays, setCycleDays] = useState<number | "">("");
  const [seed, setSeed] = useState(20260902);
  const [profile, setProfile] = useState("demo");
  const [defects, setDefects] = useState<DefectCounts>({});
  // Frozen when the preset changes, not recomputed per keystroke — otherwise a row
  // would jump position the instant its own count field is edited, fighting the
  // person typing into it.
  const [defectOrder, setDefectOrder] = useState<string[]>([]);
  const [advanced, setAdvanced] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateResult | null>(null);

  useEffect(() => {
    api
      .generateOptions()
      .then((o) => {
        setOptions(o);
        setBatchName(suggestName());
        setArchetype(o.defaults.archetype);
        setVolume(o.defaults.volume);
        setSeed(o.defaults.seed);
        setProfile(o.defaults.defect_profile);
        const applied = applyProfile(o, o.defaults.defect_profile);
        setDefects(applied);
        setDefectOrder(orderByCount(o, applied));
      })
      .catch((e) =>
        setLoadError(e instanceof ApiError ? e.message : "Could not reach the engine."),
      );
  }, []);

  // Both bounds come from `/api/generate/options`. The guard was `volume < 1`, a
  // hardcoded floor that ignored the ceiling the same payload supplies — so 6,000
  // orders left the button enabled and failed on a round-trip with an error banner
  // for something the form already knew was out of range.
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

  const activeArchetype = useMemo(
    () => options?.archetypes.find((a) => a.name === archetype) ?? null,
    [options, archetype],
  );

  // The mix that will actually be generated: an explicit pick if there is one,
  // otherwise the archetype's own default. The bar reads from this rather than from
  // the dropdown label, so it cannot disagree with what the engine will do.
  const activeMix = useMemo(() => {
    if (!options) return null;
    if (paymentMix) {
      return options.payment_mixes.find((m) => m.name === paymentMix)?.mix ?? null;
    }
    return activeArchetype?.default_mix ?? null;
  }, [options, paymentMix, activeArchetype]);

  function pickProfile(name: string) {
    setProfile(name);
    if (!options) return;
    const applied = applyProfile(options, name);
    setDefects(applied);
    setDefectOrder(orderByCount(options, applied));
  }

  function randomize() {
    if (!options) return;
    const rand = () => Math.floor(Math.random() * 2 ** 31);
    setSeed(rand());
    const archetypes = options.archetypes;
    const pickedArchetype = archetypes[Math.floor(Math.random() * archetypes.length)];
    setArchetype(pickedArchetype.name);
    const mixes = ["", ...options.payment_mixes.map((m) => m.name)];
    setPaymentMix(mixes[Math.floor(Math.random() * mixes.length)]);
    setVolume([100, 200, 500, 1000][Math.floor(Math.random() * 4)]);
    const profiles = options.defect_profiles;
    const pickedProfile = profiles[Math.floor(Math.random() * profiles.length)];
    pickProfile(pickedProfile.name);
  }

  async function submit() {
    if (!options) return;
    setBusy(true);
    setError(null);
    try {
      const activeDefects = Object.fromEntries(
        Object.entries(defects).filter(([, v]) => v.count > 0),
      );
      const body = await api.generate({
        batch: batchName.trim(),
        archetype,
        payment_mix: paymentMix || null,
        volume,
        cycle_days: cycleDays === "" ? null : cycleDays,
        seed,
        defects: Object.keys(activeDefects).length > 0 ? activeDefects : undefined,
        defect_profile: Object.keys(activeDefects).length > 0 ? undefined : profile,
      });
      setResult(body);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <main className="mx-auto max-w-[640px] px-6 pt-16 pb-32 sm:pt-[88px]">
        <GeneratedDone
          result={result}
          onAnother={() => {
            setResult(null);
            setBatchName(suggestName());
          }}
          onAnalyse={() =>
            router.push(`/analysis/${encodeURIComponent(result.batch)}`)
          }
        />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-[640px] px-6 pt-16 pb-32 sm:pt-[88px]">
      <div className="mb-9 flex items-center justify-between gap-4">
        <Link href="/">
          <BackLink />
        </Link>
        <Button variant="secondary" size="sm" onClick={randomize} disabled={!options}>
          <RefreshIcon size={13} /> Randomise
        </Button>
      </div>

      <h1 className="text-headline mb-11">Generate a scenario.</h1>

      {loadError && <ErrorNote>{loadError}</ErrorNote>}
      {!options && !loadError && <FormSkeleton />}

      {options && (
        <>
          <Band title="This run">
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="sm:flex-[2]">
                <Field label="Name">
                  <TextInput
                    value={batchName}
                    onChange={setBatchName}
                    placeholder="my-scenario"
                  />
                </Field>
              </div>
              <div className="sm:flex-1">
                <Field label="Seed">
                  <div className="flex gap-2">
                    <NumberInput
                      value={seed}
                      onChange={(v) => setSeed(Number(v) || 0)}
                      min={0}
                    />
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setSeed(Math.floor(Math.random() * 2 ** 31))}
                    >
                      Random
                    </Button>
                  </div>
                </Field>
              </div>
            </div>
            <p className="mt-2 text-[12.5px] text-[var(--color-ink-faint)]">
              Same seed, same scenario, every time.
            </p>
          </Band>

          <Band title="Business">
            <div className="flex flex-col gap-6">
              <div>
                <Field label="Archetype">
                  <Select
                    value={archetype}
                    onChange={setArchetype}
                    options={options.archetypes.map((a) => ({
                      value: a.name,
                      label: a.name,
                    }))}
                  />
                </Field>
                {activeArchetype && (
                  <p className="mt-2 text-[12.5px] leading-relaxed text-[var(--color-ink-faint)]">
                    {activeArchetype.description} Stresses: {activeArchetype.stresses}
                  </p>
                )}
              </div>

              <div>
                <Field label="Payment mix">
                  <Select
                    value={paymentMix}
                    onChange={setPaymentMix}
                    options={[
                      { value: "", label: "Archetype default" },
                      ...options.payment_mixes.map((m) => ({
                        value: m.name,
                        label: m.name,
                      })),
                    ]}
                  />
                </Field>
                <MixBar mix={activeMix} />
              </div>
            </div>
          </Band>

          <Band title="Volume">
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="sm:flex-1">
                <Field label="Order count">
                  <NumberInput
                    value={volume}
                    onChange={(v) => setVolume(Number(v) || 0)}
                    min={options.limits.min_volume}
                    max={options.limits.max_volume}
                  />
                </Field>
              </div>
              <div className="sm:flex-1">
                <Field label="Settlement cycle (days)">
                  <NumberInput
                    value={cycleDays}
                    onChange={(v) => setCycleDays(v === "" ? "" : Number(v) || 0)}
                    min={0}
                    max={30}
                    placeholder={String(options.defaults.cycle_days)}
                  />
                </Field>
              </div>
            </div>
            <p className="mt-2 text-[12.5px] text-[var(--color-ink-faint)]">
              Up to {options.limits.max_volume.toLocaleString("en-IN")} — larger runs
              are a CLI job.
            </p>
          </Band>

          <Eyebrow className="mb-3.5">What to plant</Eyebrow>
          <Select
            value={profile}
            onChange={pickProfile}
            options={options.defect_profiles.map((p) => ({
              value: p.name,
              label: p.name,
            }))}
          />
          {options.defect_profiles.find((p) => p.name === profile) && (
            <p className="mt-2.5 mb-4 text-[12.5px] leading-relaxed text-[var(--color-ink-faint)]">
              {options.defect_profiles.find((p) => p.name === profile)!.description}
            </p>
          )}

          <div className="mt-4">
            <DefectGrid
              options={options}
              order={defectOrder}
              defects={defects}
              onChange={(type, count) =>
                setDefects((d) => ({ ...d, [type]: { count } }))
              }
              showDecoys={advanced}
            />
          </div>

          <button
            type="button"
            onClick={() => setAdvanced((a) => !a)}
            className="mt-5 text-xs font-semibold text-[var(--color-accent)] underline underline-offset-4"
          >
            {advanced
              ? "Hide decoys"
              : "Show decoys (non-defects the engine must not flag)"}
          </button>

          {error && (
            <div className="mt-8">
              <ErrorNote>{error}</ErrorNote>
            </div>
          )}

          {volumeError && (
            <p className="mt-8 text-[13px] font-medium text-[var(--color-urgent)]">
              {volumeError}
            </p>
          )}

          <Button
            onClick={submit}
            disabled={busy || !batchName.trim() || volumeError !== null}
            size="lg"
            full
            className="mt-9"
          >
            {busy ? "Generating…" : "Generate"}
          </Button>
        </>
      )}
    </main>
  );
}

/**
 * A titled band of the form, closed with a rule. The form is long enough that
 * unbroken fields would read as one undifferentiated wall.
 */
function Band({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8 border-b border-[var(--color-line)] pb-8">
      <Eyebrow className="mb-3.5">{title}</Eyebrow>
      {children}
    </section>
  );
}

/**
 * The payment mix as one bar. Ratios come from the engine's own mix definition, so
 * the bar cannot disagree with what will actually be generated. Structural violet:
 * these are proportions of traffic, not money that needs a decision.
 */
function MixBar({ mix }: { mix: Record<string, number> | null }) {
  if (!mix) return null;
  const entries = Object.entries(mix).filter(([, share]) => share > 0);
  if (entries.length === 0) return null;

  const total = entries.reduce((sum, [, share]) => sum + share, 0);

  return (
    <>
      <div className="mt-3 flex h-2 gap-0.5 overflow-hidden rounded-full">
        {entries.map(([method, share], i) => (
          <div
            key={method}
            title={`${method} — ${Math.round((share / total) * 100)}%`}
            className="origin-left"
            style={{
              flex: share,
              background: `color-mix(in oklch, var(--color-accent) ${100 - i * 32}%, transparent)`,
              animation: `growX 0.6s cubic-bezier(0.2,0.7,0.2,1) ${i * 0.1}s both`,
            }}
          />
        ))}
      </div>
      <p className="mt-2 text-[12.5px] text-[var(--color-ink-faint)]">
        {entries
          .map(([m, share]) => `${Math.round((share / total) * 100)}% ${m}`)
          .join(" / ")}
      </p>
    </>
  );
}

/**
 * The defect fields, in `order` — the count-descending order frozen at the moment the
 * preset was applied, so the row a merchant actually cares about (the demo
 * centrepiece, planted at 6) sits above a row nobody set (0, greyed, pushed down),
 * without a row jumping position the instant its own field is edited mid-keystroke.
 */
function DefectGrid({
  options,
  order,
  defects,
  onChange,
  showDecoys,
}: {
  options: GenerateOptions;
  order: string[];
  defects: DefectCounts;
  onChange: (type: string, count: number) => void;
  showDecoys: boolean;
}) {
  const byName = new Map(options.defect_types.map((d) => [d.name, d]));
  const types = order
    .map((name) => byName.get(name))
    .filter((d): d is GenerateOptions["defect_types"][number] => Boolean(d))
    .filter((d) => showDecoys || d.is_defect);

  return (
    <div>
      {types.map((d) => {
        const count = defects[d.name]?.count ?? 0;
        const active = count > 0;
        return (
          <div
            key={d.name}
            className={`mb-1.5 flex items-center justify-between gap-4 rounded-[10px] border px-4 py-3.5 transition-colors duration-200 ${
              active
                ? "border-[var(--color-line)] bg-[var(--color-raised)] hover:border-[oklch(1_0_0/0.2)]"
                : "border-transparent"
            }`}
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2.5">
                <span
                  className={`text-sm ${
                    active
                      ? "font-semibold text-[var(--color-ink)]"
                      : "text-[var(--color-ink-faint)]"
                  }`}
                >
                  {d.label}
                </span>
                {!d.is_defect && <Badge accent>decoy</Badge>}
              </div>
              {d.hint && active && (
                <p className="mt-1 max-w-md text-xs leading-relaxed text-[var(--color-ink-faint)]">
                  {d.hint}
                </p>
              )}
            </div>
            <div className="w-[100px] shrink-0">
              <NumberInput
                value={count}
                onChange={(v) => onChange(d.name, Math.max(0, Number(v) || 0))}
                min={0}
                align="right"
                className="!px-2.5 !py-2 !text-sm"
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function GeneratedDone({
  result,
  onAnother,
  onAnalyse,
}: {
  result: GenerateResult;
  onAnother: () => void;
  onAnalyse: () => void;
}) {
  const scenario = result.scenario;
  const planted = [...scenario.planted].sort((a, b) => b.impact.paise - a.impact.paise);
  const largest = planted[0]?.impact.paise ?? 1;

  return (
    <section className="rise">
      <Badge tone="benign">
        <CheckIcon size={12} /> Generated
      </Badge>

      <h1 className="text-headline mt-5 mb-2.5">{result.headline}</h1>
      <p className="tnum mb-9 text-[15px] text-[var(--color-ink-soft)]">
        {scenario.volume.toLocaleString("en-IN")} orders · {scenario.gross.display}{" "}
        gross · {scenario.defect_count}{" "}
        {scenario.defect_count === 1 ? "defect" : "defects"} planted
        {scenario.decoy_count > 0 &&
          `, ${scenario.decoy_count} ${scenario.decoy_count === 1 ? "decoy" : "decoys"}`}{" "}
        · seed {scenario.seed}
      </p>

      {/* Not an error: the generator did its job and is reporting what it changed.
          `ErrorNote` is urgent red and role="alert", which announced a successful
          generation as a failure. This is a note, so it looks like one. */}
      {scenario.adjusted.length > 0 && (
        <div
          className="mb-6 rounded-xl border px-4 py-3"
          style={{
            borderColor: "color-mix(in oklch, var(--color-accent) 30%, transparent)",
            background: "color-mix(in oklch, var(--color-accent) 7%, transparent)",
          }}
        >
          <p className="text-[13px] leading-relaxed text-[var(--color-ink-soft)]">
            Some counts were larger than the batch could hold, so they were reduced to
            fit:{" "}
            {scenario.adjusted
              .map((a) => `${a.label} (asked ${a.asked}, planted ${a.planted})`)
              .join(", ")}
            .
          </p>
        </div>
      )}

      {/*
        The answer key is deliberately UNCOLOURED. Amber and red say something about
        money needing a decision (globals.css), and "biggest thing planted" is not that
        judgement: the largest row here is usually `timing_lag`, which the engine ranks
        `always_benign` — money that arrives on its own. Painting it urgent red
        pre-empted the verdict with the opposite of its answer. What was planted is a
        fact about the fixture; whether it matters is what the analysis screen decides.
      */}
      <Card className="px-7 pt-2 pb-6">
        <Eyebrow className="pt-5 pb-1">The answer key</Eyebrow>

        {planted.map((p, i) => (
          <div
            key={p.type}
            className="flex justify-between gap-5 border-t border-[oklch(1_0_0/0.07)] pt-5 pb-4.5"
          >
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <div className="text-[14.5px] leading-snug font-semibold">
                {p.label}
              </div>
              <div className="text-[13px] text-[var(--color-ink-faint)]">
                {p.count} × planted
              </div>
              <ShareBar
                fraction={p.impact.paise / largest}
                severity="neutral"
                delay={0.2 + i * 0.09}
                className="mt-1"
              />
            </div>
            <div className="money shrink-0 text-[15px] font-bold">
              {p.impact.display}
            </div>
          </div>
        ))}

        {planted.length === 0 && (
          <p className="border-t border-[oklch(1_0_0/0.07)] py-5 text-sm text-[var(--color-ink-soft)]">
            Nothing planted — a clean batch. Everything should reconcile.
          </p>
        )}
      </Card>

      <div className="mt-8 flex flex-col gap-3.5 sm:flex-row">
        <Button onClick={onAnalyse} size="lg" className="flex-1">
          Analyse <ArrowRightIcon size={15} />
        </Button>
        <Button onClick={onAnother} variant="secondary" size="lg" className="flex-1">
          Generate another
        </Button>
      </div>
    </section>
  );
}

function FormSkeleton() {
  return (
    <div aria-hidden aria-busy="true">
      {[0, 1, 2].map((band) => (
        <div key={band} className="mb-8 border-b border-[var(--color-line)] pb-8">
          <Skeleton className="mb-3.5 h-3 w-24" delay={band * 0.1} />
          <div className="flex gap-3">
            <Skeleton className="h-[46px] flex-[2] rounded-[10px]" delay={band * 0.1} />
            <Skeleton className="h-[46px] flex-1 rounded-[10px]" delay={band * 0.1} />
          </div>
        </div>
      ))}
      <Skeleton className="mb-3.5 h-3 w-28" delay={0.3} />
      {[0, 1, 2, 3, 4].map((i) => (
        <Skeleton key={i} className="mb-1.5 h-[54px] w-full rounded-[10px]" delay={i * 0.05} />
      ))}
    </div>
  );
}

function suggestName(): string {
  const stamp = new Date()
    .toISOString()
    .slice(0, 16)
    .replace(/[:T]/g, "-");
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

/** Every known defect type, ordered by its count in `defects` — largest first. */
function orderByCount(options: GenerateOptions, defects: DefectCounts): string[] {
  return options.defect_types
    .map((d) => d.name)
    .sort((a, b) => (defects[b]?.count ?? 0) - (defects[a]?.count ?? 0));
}
