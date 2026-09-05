"use client";

/**
 * The Copilot chat surface. One component, two shells: the topbar's docked
 * drawer (`layout.tsx`) and the full `/copilot/[batch]` page both render
 * this, sized by their container.
 *
 * Wired to the real `/api/chat/{batch}` endpoint (api/main.py), which reuses
 * the same LLM client and numeral guard as the verdict summary (ADR-050):
 * the model never puts a figure on screen, here or anywhere else in this
 * product. `source` on each reply says whether a model or the fallback
 * template answered, same honesty the verdict screen already has.
 */

import { useEffect, useRef, useState } from "react";
import { SparkleIcon } from "@/components/dash/primitives";
import { api, ApiError, type ChatMessage } from "@/lib/api";

type Msg = ChatMessage & { source?: "model" | "template"; error?: boolean };

const SUGGESTIONS = [
  "What's the biggest thing that needs me?",
  "Why is there a gap at all?",
  "What can I safely ignore?",
];

export function CopilotChat({
  batch,
  compact = false,
  initialMessage,
}: {
  batch: string | null;
  compact?: boolean;
  /** Sent automatically, once, as soon as `batch` is ready — the `?ask=` deep-link
   *  convention other screens use to open Copilot with a question already in mind. */
  initialMessage?: string;
}) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentInitial = useRef(false);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => {
    if (!initialMessage || !batch || sentInitial.current) return;
    sentInitial.current = true;
    send(initialMessage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialMessage, batch]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || !batch || busy) return;
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((m) => [...m, { role: "user", content: trimmed }]);
    setInput("");
    setBusy(true);
    try {
      const reply = await api.chat(batch, trimmed, history);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: reply.answer, source: reply.source },
      ]);
    } catch (err) {
      const detail = err instanceof ApiError ? err.message : "Something went wrong.";
      setMessages((m) => [
        ...m,
        { role: "assistant", content: detail, error: true },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: compact ? 20 : 24,
          display: "flex",
          flexDirection: "column",
          gap: compact ? 18 : 20,
        }}
      >
        {messages.length === 0 && (
          <div style={{ fontSize: compact ? 13 : 14, color: "var(--dash-ink-faint)", lineHeight: 1.6 }}>
            {batch
              ? "Ask about any line on this run — what it means, and what to do about it."
              : "Open a run first, then ask Copilot about it."}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i}>
            {m.role === "user" ? (
              <div
                style={{
                  background: "color-mix(in oklch, var(--dash-accent) 16%, transparent)",
                  border: "1px solid color-mix(in oklch, var(--dash-accent) 28%, transparent)",
                  borderRadius: "13px 13px 4px 13px",
                  padding: "11px 14px",
                  fontSize: compact ? 13.5 : 14,
                  lineHeight: 1.5,
                  maxWidth: compact ? 300 : 520,
                  display: "inline-block",
                }}
              >
                {m.content}
              </div>
            ) : (
              <div style={{ maxWidth: compact ? "100%" : 640 }}>
                <p
                  style={{
                    fontSize: compact ? 13.5 : 14.5,
                    lineHeight: 1.62,
                    margin: 0,
                    color: m.error ? "var(--dash-urgent)" : "oklch(0.265 0.028 66)",
                  }}
                >
                  {m.content}
                </p>
                {m.source === "template" && !m.error && (
                  <div
                    style={{
                      marginTop: 8,
                      fontFamily: "var(--dash-font-mono)",
                      fontSize: 10.5,
                      color: "var(--dash-ink-faint)",
                    }}
                  >
                    fallback · no model configured or reachable
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {[0, 0.18, 0.36].map((d) => (
              <span
                key={d}
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 999,
                  background: "var(--dash-benign)",
                  animation: `blink 1.1s ease-in-out ${d}s infinite`,
                }}
              />
            ))}
            <span style={{ fontSize: 11.5, color: "var(--dash-ink-faint)", marginLeft: 4 }}>
              reading the run…
            </span>
          </div>
        )}
      </div>

      <div style={{ padding: compact ? "14px 20px 20px" : "16px 24px 22px", borderTop: "1px solid var(--dash-line)" }}>
        <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 12 }}>
          {SUGGESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => send(q)}
              disabled={!batch || busy}
              style={{
                border: "1px solid var(--dash-line-strong)",
                borderRadius: 999,
                padding: "6px 11px",
                fontSize: 11.5,
                color: "oklch(0.39 0.024 74)",
                background: "none",
                cursor: batch ? "pointer" : "not-allowed",
              }}
            >
              {q}
            </button>
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          style={{
            display: "flex",
            gap: 9,
            alignItems: "center",
            background: "var(--dash-raised)",
            border: "1px solid var(--dash-line-strong)",
            borderRadius: 11,
            padding: "10px 11px",
          }}
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={batch ? "Ask about this run…" : "Open a run first…"}
            disabled={!batch}
            style={{
              flex: 1,
              minWidth: 0,
              background: "transparent",
              border: "none",
              outline: "none",
              color: "var(--dash-ink)",
              fontSize: 13.5,
            }}
          />
          <button
            type="submit"
            disabled={!batch || busy || !input.trim()}
            style={{
              flex: "none",
              background: "var(--dash-benign)",
              color: "oklch(0.985 0.014 88)",
              borderRadius: 8,
              width: 30,
              height: 30,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: "none",
              cursor: "pointer",
              opacity: !batch || busy || !input.trim() ? 0.5 : 1,
            }}
            aria-label="Send"
          >
            <SparkleIcon size={13} />
          </button>
        </form>
      </div>
    </div>
  );
}

export function CopilotHeader({ batch }: { batch: string | null }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
      <span
        style={{
          width: 28,
          height: 28,
          borderRadius: 8,
          background: "linear-gradient(140deg, var(--dash-benign), oklch(0.615 0.10 168))",
          color: "oklch(0.985 0.014 88)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flex: "none",
        }}
      >
        <SparkleIcon size={15} />
      </span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>Copilot</div>
        <div
          style={{
            fontSize: 11,
            color: "var(--dash-ink-faint)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {batch ? `${batch} in context` : "No run open yet"}
        </div>
      </div>
    </div>
  );
}
