"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/**
 * Which run is on screen.
 *
 * The page rendered one hardcoded batch until now, which made every backend flow
 * invisible: a merchant could upload files and never see the result. This is the
 * smallest thing that makes uploads reachable.
 *
 * Uploaded runs are marked, because "this is my data" and "this is the sample" is the
 * distinction a merchant most needs when looking at a number.
 */
export function BatchPicker({
  batch,
  onPick,
  refreshKey,
}: {
  batch: string;
  onPick: (batch: string) => void;
  refreshKey: number;
}) {
  const [batches, setBatches] = useState<
    { name: string; uploaded: boolean; has_ground_truth: boolean }[]
  >([]);

  useEffect(() => {
    api.batches().then((r) => setBatches(r.batches)).catch(() => setBatches([]));
  }, [refreshKey]);

  if (batches.length <= 1) return null;

  return (
    <div className="mb-10 flex flex-wrap items-baseline gap-2">
      {batches.map((b) => (
        <button
          key={b.name}
          onClick={() => onPick(b.name)}
          className={`rounded border px-3 py-1.5 text-xs ${
            b.name === batch
              ? "border-[var(--color-ink)] bg-[var(--color-ink)] text-white"
              : "border-[var(--color-line)] bg-white text-[var(--color-ink-soft)]"
          }`}
        >
          {b.name}
          {b.uploaded && (
            <span
              className={`ml-2 ${
                b.name === batch ? "opacity-70" : "text-[var(--color-ink-faint)]"
              }`}
            >
              yours
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
