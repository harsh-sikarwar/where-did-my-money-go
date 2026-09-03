"use client";

import { useCallback, useEffect, useState } from "react";
import { Actions } from "@/components/Actions";
import { Audit } from "@/components/Audit";
import { BatchPicker } from "@/components/BatchPicker";
import { Correlation } from "@/components/Correlation";
import { RateCard } from "@/components/RateCard";
import { Upload } from "@/components/Upload";
import { Verdict } from "@/components/Verdict";
import {
  api,
  ApiError,
  type Correlation as CorrelationData,
  type Verdict as VerdictData,
} from "@/lib/api";

/**
 * One page, three depths — the layering the brief asks for:
 *
 *   verdict      what a merchant reads on Monday, in two minutes
 *   correlation  the measured claim: how much of the unexplained we eliminate
 *   audit        how anyone can check it
 *
 * Not three routes, because the demo is a story told by scrolling, not a feature tour
 * navigated by clicking. Depth is available; nobody is made to go looking for it.
 *
 * This became a client component when uploads arrived: which batch is on screen is now
 * state a merchant changes, not a constant. The cost is that the first paint fetches
 * rather than arriving in the HTML — worth it, because a page that can only ever show
 * one hardcoded batch makes the entire upload path invisible.
 */

const FALLBACK_BATCH = "demo";

export default function Home() {
  const [batch, setBatch] = useState(FALLBACK_BATCH);
  const [verdict, setVerdict] = useState<VerdictData | null>(null);
  const [correlation, setCorrelation] = useState<CorrelationData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async (name: string) => {
    setError(null);
    try {
      const [v, c] = await Promise.all([api.verdict(name), api.correlation(name)]);
      setVerdict(v);
      setCorrelation(c);
    } catch (e) {
      setVerdict(null);
      setCorrelation(null);
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    }
  }, []);

  useEffect(() => {
    load(batch);
  }, [batch, load, refreshKey]);

  return (
    <main className="mx-auto max-w-2xl px-6 py-16 sm:py-24">
      <BatchPicker batch={batch} onPick={setBatch} refreshKey={refreshKey} />

      <Upload
        onDone={(name) => {
          setBatch(name);
          setRefreshKey((k) => k + 1);
        }}
      />

      <RateCard />

      {error && (
        <p className="text-sm text-[var(--color-attention)]">{error}</p>
      )}

      {verdict && correlation && (
        <>
          <Verdict data={verdict} />
          {/* Immediately after the verdict, because the verdict is what raises the
              question this answers: it says "those 6 customers" and this names them. */}
          <Actions batch={batch} />
          <Correlation data={correlation} />
          <Audit batch={batch} />
        </>
      )}
    </main>
  );
}
