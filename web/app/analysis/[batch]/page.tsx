"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { Actions } from "@/components/Actions";
import { Audit } from "@/components/Audit";
import { Correlation } from "@/components/Correlation";
import { RateCard } from "@/components/RateCard";
import { Verdict } from "@/components/Verdict";
import {
  BackLink,
  ChevronDownIcon,
  Dot,
  ErrorNote,
  Skeleton,
} from "@/components/ui";
import {
  api,
  ApiError,
  type Correlation as CorrelationData,
  type Verdict as VerdictData,
} from "@/lib/api";

/**
 * The analysis screen: what a merchant reads on Monday, with the detailed view (the
 * measured correlation gain, the rate card, the audit trail) available a click away
 * rather than hidden behind a separate route. It stays one screen for a reason — the
 * verdict, the work it generates, and the proof are one argument, not three
 * destinations, and a merchant deciding whether to trust the headline should not have
 * to navigate away to see what it is built on.
 */
export default function AnalysisPage({
  params,
}: {
  params: Promise<{ batch: string }>;
}) {
  const { batch } = use(params);
  const [verdict, setVerdict] = useState<VerdictData | null>(null);
  const [correlation, setCorrelation] = useState<CorrelationData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detailed, setDetailed] = useState(false);

  const load = useCallback(async (name: string) => {
    setError(null);
    setVerdict(null);
    setCorrelation(null);
    try {
      const [v, c] = await Promise.all([api.verdict(name), api.correlation(name)]);
      setVerdict(v);
      setCorrelation(c);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    }
  }, []);

  useEffect(() => {
    load(batch);
  }, [batch, load]);

  return (
    <main className="mx-auto max-w-[700px] px-6 pt-16 pb-32 sm:pt-[88px]">
      <div className="mb-11 flex flex-wrap items-center justify-between gap-4">
        <Link href="/">
          <BackLink />
        </Link>
        {verdict && (
          <div className="flex items-center gap-2 rounded-full border border-[var(--color-line)] bg-[var(--color-raised)] px-4 py-[7px] text-[13px] font-semibold whitespace-nowrap">
            <Dot severity={verdict.lines.some((l) => l.actionable) ? "action" : "benign"} />
            <span className="tnum">
              {batch} · {verdict.match.pass1.total.toLocaleString("en-IN")} orders
            </span>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-10">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      {!verdict && !error && <VerdictSkeleton />}

      {verdict && correlation && (
        <div className="rise">
          <Verdict data={verdict} />

          {/* Immediately after the verdict, because the verdict is what raises the
              question this answers: it says "those customers" and this names them. */}
          <Actions batch={batch} />

          <button
            type="button"
            onClick={() => setDetailed((v) => !v)}
            aria-expanded={detailed}
            className="mt-11 flex w-full items-center justify-between border-t border-b border-[var(--color-line)] py-[18px] text-left"
          >
            <span className="text-[13.5px] font-semibold text-[var(--color-ink-soft)]">
              {detailed ? "Hide detailed view" : "Show detailed view"}
            </span>
            <ChevronDownIcon
              size={16}
              className="text-[var(--color-ink-faint)] transition-transform duration-200"
              style={{ transform: detailed ? "rotate(180deg)" : "rotate(0deg)" }}
            />
          </button>

          {detailed && (
            <div className="fade py-7">
              <Correlation data={correlation} />
              <RateCard />
              <Audit batch={batch} />
            </div>
          )}
        </div>
      )}
    </main>
  );
}

/**
 * The shape of the answer, before the answer arrives. Deliberately mirrors the real
 * layout — three figures, a bar, then rows — so nothing jumps when the data lands.
 */
function VerdictSkeleton() {
  return (
    <div aria-hidden aria-busy="true">
      <div className="mb-11 flex justify-between">
        <Skeleton className="h-3.5 w-16" />
        <Skeleton className="h-7 w-40 rounded-full" />
      </div>

      <div className="mb-10 grid grid-cols-2 gap-5 sm:grid-cols-[1fr_1fr_1.3fr]">
        {[0, 0.1, 0.2].map((d, i) => (
          <div key={i} className="flex flex-col gap-2.5">
            <Skeleton className="h-3 w-[70px]" delay={0} />
            <Skeleton
              className={i === 2 ? "h-14 w-40" : "h-8 w-32"}
              delay={d}
            />
          </div>
        ))}
      </div>

      <Skeleton className="mb-11 h-3 w-full rounded-full" delay={0.15} />

      <div className="flex flex-col gap-1">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="flex items-center justify-between p-4">
            <div className="flex flex-col gap-2">
              <Skeleton className="h-3.5 w-44" delay={i * 0.05} />
              <Skeleton className="h-[11px] w-24" delay={i * 0.05} />
            </div>
            <Skeleton className="h-4 w-[70px]" delay={i * 0.05} />
          </div>
        ))}
      </div>
    </div>
  );
}
