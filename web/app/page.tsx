"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { GapSparkline } from "@/components/GapByDay";
import { GapComposition, type GapSegment } from "@/components/GapComposition";
import {
  ArrowRightIcon,
  Card,
  Eyebrow,
  severityOf,
  toneAlpha,
} from "@/components/ui";
import { api, type Timeline, type Verdict } from "@/lib/api";

/**
 * The front door. One decision: bring your own numbers, or dial a scenario and watch
 * the engine work on data whose answer key you already hold.
 *
 * Two routes, not two panels on one screen — each mode has its own multi-step flow
 * (upload has a mapping question; demo has a whole control panel), and cramming both
 * into one screen would mean explaining the toggle before either path has said
 * anything.
 */

const RECENT_LIMIT = 4;

/**
 * How a batch arrived, when the engine actually recorded it. The marker files are
 * written on upload and on generate; a batch seeded from the CLI (`demo`, the one the
 * README tells you to open) carries neither, and calling that "yours" claimed the
 * merchant had uploaded files they never touched. Saying nothing is the honest option.
 */
function originOf(b: Batch): string | null {
  if (b.generated) return "generated";
  if (b.uploaded) return "yours";
  return null;
}

type Batch = {
  name: string;
  uploaded: boolean;
  generated: boolean;
  has_ground_truth: boolean;
};

export default function Landing() {
  const [runs, setRuns] = useState<Batch[]>([]);
  const [latest, setLatest] = useState<Verdict | null>(null);
  const [latestTimeline, setLatestTimeline] = useState<Timeline | null>(null);

  useEffect(() => {
    let cancelled = false;

    api
      .batches()
      .then(async (r) => {
        if (cancelled) return;
        // Every batch the API returns already has a readable ledger — that is the
        // condition it lists them under. The `.uploaded` / `.generated` marker files
        // record HOW a batch arrived, and filtering on them hid every batch that
        // predates those markers or was seeded from the CLI: `demo`, the batch
        // `./scripts/demo.sh` creates and the one the README tells you to open, never
        // appeared here. A run you can open is a run worth listing.
        const done = r.batches;
        setRuns(done.slice(0, RECENT_LIMIT));

        // The glance card is only worth showing with real figures behind it. If the
        // most recent run cannot be read, the card is omitted rather than filled in.
        if (done.length > 0) {
          try {
            const v = await api.verdict(done[0].name);
            if (!cancelled) setLatest(v);
          } catch {
            /* no glance card this time */
          }

          // The sparkline is the card's supporting detail. Its absence costs the
          // card a chart; it must never cost the card its figures.
          try {
            const t = await api.timeline(done[0].name);
            if (!cancelled) setLatestTimeline(t);
          } catch {
            /* no sparkline this time */
          }
        }
      })
      .catch(() => setRuns([]));

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="mx-auto max-w-[920px] px-6 pt-16 pb-32 sm:pt-[88px]">
      <header className="rise text-center">
        <Eyebrow className="text-[var(--color-ink-soft)]">Reconciliation</Eyebrow>
        <h1 className="text-hero mt-[18px]">Where did my money go?</h1>
        <p className="mx-auto mt-5 max-w-[540px] text-lg leading-relaxed text-pretty text-[var(--color-ink-soft)]">
          Upload your ledger and settlement files — or generate a scenario — and see
          exactly where the numbers diverge, in one glance.
        </p>
      </header>

      <div className="mt-16 grid gap-5 sm:grid-cols-2">
        <ModeCard
          href="/upload"
          eyebrow="Upload"
          title="Reconcile your own files"
          description="Bring your ledger and settlement exports — we'll match them line by line."
          bullets={[
            "Works with any CSV export",
            "Auto-detects common column formats",
            "Nothing leaves your run",
          ]}
          cta="Upload files"
          delay={0.08}
        />
        <ModeCard
          href="/generate"
          eyebrow="Generate · try this first"
          title="Generate a scenario"
          description="No files handy? Spin up a realistic dataset with defects planted in — then see if we catch them."
          bullets={[
            "Pick an archetype and payment mix",
            "Plant specific defects to test",
            "See the answer key instantly",
          ]}
          cta="Try a demo"
          accent
          delay={0.16}
        />
      </div>

      {latest && <LastCycle verdict={latest} timeline={latestTimeline} />}

      {runs.length > 0 && (
        <section
          className="mt-11"
          style={{ animation: "fadeUp 0.5s cubic-bezier(0.2,0.7,0.2,1) 0.3s both" }}
        >
          <Eyebrow className="mb-3.5">Recent runs</Eyebrow>
          <div className="flex flex-wrap gap-2.5">
            {runs.map((b) => (
              <Link
                key={b.name}
                href={`/analysis/${encodeURIComponent(b.name)}`}
                className="pressable flex items-center gap-2.5 rounded-full border border-[var(--color-line)] bg-[var(--color-raised)] px-4 py-2.5 text-[13.5px] text-[var(--color-ink-soft)] transition-[border-color,transform,color] duration-200 hover:-translate-y-0.5 hover:border-[oklch(1_0_0/0.2)] hover:text-[var(--color-ink)]"
              >
                {/* Amber and green say something about MONEY (globals.css). Where a
                    batch came from is not a severity, so the marker is structural
                    violet for a dialled scenario and a plain hairline otherwise. */}
                <span
                  aria-hidden
                  className="h-[7px] w-[7px] shrink-0 rounded-full"
                  style={{
                    background: b.generated
                      ? "var(--color-accent)"
                      : "var(--color-ink-faint)",
                  }}
                />
                {b.name}
                {originOf(b) && (
                  <span className="text-xs text-[var(--color-ink-faint)]">
                    {originOf(b)}
                  </span>
                )}
              </Link>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

/**
 * Last cycle at a glance. Every figure here is the engine's, including the composition
 * bar — this card is a preview of the analysis screen, not a summary written beside it.
 */
function LastCycle({
  verdict,
  timeline = null,
}: {
  verdict: Verdict;
  timeline?: Timeline | null;
}) {
  const segments: GapSegment[] = [
    ...verdict.lines.map((line) => ({
      id: line.classification,
      label: line.label,
      amount: line.amount.display,
      paise: line.amount.paise,
      severity: severityOf(line),
    })),
    {
      id: "__unexplained",
      label: "Unexplained",
      amount: verdict.unexplained.display,
      paise: verdict.unexplained.paise,
      severity: "neutral" as const,
    },
  ];

  const pct =
    verdict.expected.paise > 0
      ? (verdict.gap.paise / verdict.expected.paise) * 100
      : null;

  return (
    <section
      className="mt-14 overflow-hidden rounded-2xl border border-[var(--color-line)] bg-[var(--color-raised)]"
      style={{ animation: "fadeUp 0.5s cubic-bezier(0.2,0.7,0.2,1) 0.24s both" }}
    >
      <div className="flex items-baseline justify-between gap-4 px-7 pt-6">
        <Eyebrow>Last cycle at a glance</Eyebrow>
        <Link
          href={`/analysis/${encodeURIComponent(verdict.batch)}`}
          className="inline-flex items-center gap-1.5 text-[13px] font-semibold whitespace-nowrap text-[var(--color-ink-soft)] transition-colors hover:text-[var(--color-ink)]"
        >
          Open analysis <ArrowRightIcon size={13} />
        </Link>
      </div>

      <div className="px-7 pt-5 pb-7">
        <div className="grid items-end gap-6 sm:grid-cols-[1fr_1.6fr] sm:gap-8">
          <div>
            <Eyebrow className="mb-1.5">Gap found</Eyebrow>
            <div className="money text-[34px] leading-none font-bold tracking-tight">
              {verdict.gap.display}
            </div>
            {pct !== null && (
              <div
                className="mt-2 inline-flex items-center rounded-full px-2.5 py-1 text-[11.5px] font-bold"
                style={{
                  background: toneAlpha("action", 0.12),
                  color: "var(--color-action)",
                }}
              >
                {pct < 0.01 ? "<0.01" : pct.toFixed(2)}% of expected
              </div>
            )}
          </div>

          {timeline && <GapSparkline data={timeline} />}
        </div>

        <div className="mt-6">
          <GapComposition segments={segments} />
        </div>
      </div>
    </section>
  );
}

function ModeCard({
  href,
  eyebrow,
  title,
  description,
  bullets,
  cta,
  accent,
  delay,
}: {
  href: string;
  eyebrow: string;
  title: string;
  description: string;
  bullets: string[];
  cta: string;
  accent?: boolean;
  delay: number;
}) {
  return (
    <Link href={href} className="group block h-full">
      <Card
        interactive={!accent}
        className={`flex h-full flex-col gap-4.5 p-9 ${
          accent
            ? "transition-[transform,box-shadow] duration-200 group-hover:-translate-y-1"
            : ""
        }`}
        style={
          accent
            ? {
                borderColor: "color-mix(in oklch, var(--color-accent) 35%, transparent)",
                boxShadow:
                  "0 0 60px -20px color-mix(in oklch, var(--color-accent) 35%, transparent)",
                animation: `fadeUp 0.5s cubic-bezier(0.2,0.7,0.2,1) ${delay}s both`,
              }
            : { animation: `fadeUp 0.5s cubic-bezier(0.2,0.7,0.2,1) ${delay}s both` }
        }
      >
        <div
          className="text-label"
          style={{
            color: accent ? "var(--color-accent)" : "var(--color-ink-faint)",
          }}
        >
          {eyebrow}
        </div>

        <div>
          <h2 className="text-title">{title}</h2>
          <p className="mt-2.5 text-[14.5px] leading-relaxed text-[var(--color-ink-soft)]">
            {description}
          </p>
        </div>

        <ul className="flex flex-col gap-2.5">
          {bullets.map((b) => (
            <li
              key={b}
              className="flex gap-2 text-[13.5px] text-[var(--color-ink-soft)]"
            >
              <span className="text-[var(--color-ink-faint)]" aria-hidden>
                —
              </span>
              {b}
            </li>
          ))}
        </ul>

        <span className="mt-auto inline-flex items-center gap-2 pt-2 text-[14.5px] font-semibold transition-[gap] duration-200 group-hover:gap-3.5">
          {cta} <ArrowRightIcon size={15} />
        </span>
      </Card>
    </Link>
  );
}
