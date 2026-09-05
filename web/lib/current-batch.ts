"use client";

/**
 * The dashboard is batch-scoped (Analysis, Exceptions, Audit log, Sources,
 * Copilot all need one), but the sidebar nav is global. "Current batch" is
 * real state — the last batch this browser actually opened — not a fabricated
 * default: until one exists, batch-scoped nav links fall back to `/runs` so
 * a person picks one instead of the app inventing a selection.
 *
 * This is a shared store rather than a hook over `useState`, and that is the
 * whole point. The earlier version gave every call site its own copy, and the
 * dashboard layout does not remount when you navigate within its route group —
 * so the sidebar read the batch once, at first paint, and kept it forever. Open
 * a run and every nav link still pointed at whichever batch happened to be
 * first, and the Copilot drawer answered questions about that one while you
 * were reading another. A selection that four components disagree about is not
 * a selection.
 */

import { useCallback, useSyncExternalStore } from "react";
import { api } from "@/lib/api";

const KEY = "dash:currentBatch";

let current: string | null = null;
let ready = false;
let started = false;

const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

/** Read localStorage first, and only ask the API when nothing is remembered. */
function start() {
  if (started) return;
  started = true;

  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(KEY);
  } catch {
    /* private browsing / storage blocked — fall through to the API default */
  }

  if (stored) {
    current = stored;
    ready = true;
    emit();
    return;
  }

  api
    .batches()
    .then((r) => {
      if (r.batches.length === 0) return;
      // The API lists batches alphabetically, not by recency (directory names
      // carry no reliable timestamp), so "first listed" is the existing
      // definition of "latest" — carried forward, not changed here. It is also
      // why this fallback so often lands on `demo`, which the API seeds on boot:
      // one more reason the value has to update when a person opens a run.
      current = r.batches[0].name;
    })
    .finally(() => {
      ready = true;
      emit();
    });
}

function subscribe(listener: () => void) {
  start();
  listeners.add(listener);

  // Another tab picking a different run should not leave this one pointing at a
  // batch the person has moved on from.
  const onStorage = (e: StorageEvent) => {
    if (e.key !== KEY || e.newValue === current) return;
    current = e.newValue;
    emit();
  };
  window.addEventListener("storage", onStorage);

  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

// Separate primitive snapshots rather than one object: useSyncExternalStore
// compares by identity, and a fresh `{ batch, ready }` on every read would
// re-render forever.
const batchSnapshot = () => current;
const readySnapshot = () => ready;
const serverBatch = () => null;
const serverReady = () => false;

export function useCurrentBatch() {
  const batch = useSyncExternalStore(subscribe, batchSnapshot, serverBatch);
  const isReady = useSyncExternalStore(subscribe, readySnapshot, serverReady);

  const setBatch = useCallback((name: string) => {
    if (name === current) return;
    current = name;
    ready = true;
    try {
      window.localStorage.setItem(KEY, name);
    } catch {
      /* per-viewer convenience only; fine if it doesn't persist */
    }
    emit();
  }, []);

  return { batch, setBatch, ready: isReady };
}
