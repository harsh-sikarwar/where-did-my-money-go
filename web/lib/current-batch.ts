"use client";

/**
 * The dashboard is batch-scoped (Analysis, Exceptions, Audit log, Sources,
 * Copilot all need one), but the sidebar nav is global. "Current batch" is
 * real state — the last batch this browser actually opened — not a fabricated
 * default: until one exists, batch-scoped nav links fall back to `/runs` so
 * a person picks one instead of the app inventing a selection.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

const KEY = "dash:currentBatch";

export function useCurrentBatch() {
  const [batch, setBatchState] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(KEY);
    } catch {
      /* private browsing / storage blocked — fall through to the API default */
    }

    if (stored) {
      setBatchState(stored);
      setReady(true);
      return;
    }

    let cancelled = false;
    api
      .batches()
      .then((r) => {
        if (cancelled || r.batches.length === 0) return;
        // Same convention the landing page used before this rebuild: the API lists
        // batches alphabetically, not by recency (directory names carry no reliable
        // timestamp), so "first listed" is the existing definition of "latest" — not
        // changed here, just carried forward.
        setBatchState(r.batches[0].name);
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const setBatch = useCallback((name: string) => {
    setBatchState(name);
    try {
      window.localStorage.setItem(KEY, name);
    } catch {
      /* per-viewer convenience only; fine if it doesn't persist */
    }
  }, []);

  return { batch, setBatch, ready };
}
