"use client";

/**
 * The dashboard shell: sidebar + topbar + optional Copilot drawer, wrapping
 * every screen in the "Reconciliation Tool" rebuild (see the plan at
 * `/home/harsh/.claude/plans/fancy-sniffing-rossum.md` for the full mapping).
 * Batch-scoped nav items (Analysis, Exceptions, …) follow whatever run this
 * browser last opened (`useCurrentBatch`) rather than a hardcoded one.
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { dashFontVariables } from "@/app/dash-fonts";
import { Avatar, BellIcon, CloseIcon, NAV_ICON_PATHS, NavIcon, SearchIcon, SparkleIcon } from "@/components/dash/primitives";
import { CopilotChat, CopilotHeader } from "@/components/dash/CopilotChat";
import { useCurrentBatch } from "@/lib/current-batch";

type NavItem = { label: string; href: string; icon: string; enabled: boolean };

function useNav(): { title: string; items: NavItem[] }[] {
  const { batch } = useCurrentBatch();
  const scoped = (path: string) => (batch ? `/${path}/${encodeURIComponent(batch)}` : "/runs");

  return [
    {
      title: "Workspace",
      items: [
        { label: "Overview", href: "/", icon: NAV_ICON_PATHS.overview, enabled: true },
        { label: "Runs", href: "/runs", icon: NAV_ICON_PATHS.runs, enabled: true },
        { label: "Exceptions", href: scoped("exceptions"), icon: NAV_ICON_PATHS.exceptions, enabled: !!batch },
      ],
    },
    {
      title: "This run",
      items: [
        { label: "Analysis", href: scoped("analysis"), icon: NAV_ICON_PATHS.analysis, enabled: !!batch },
        { label: "Reports", href: scoped("reports"), icon: NAV_ICON_PATHS.reports, enabled: !!batch },
        { label: "Audit log", href: scoped("audit"), icon: NAV_ICON_PATHS.audit, enabled: !!batch },
        { label: "Sources", href: scoped("sources"), icon: NAV_ICON_PATHS.sources, enabled: !!batch },
      ],
    },
    {
      title: "Manage",
      items: [
        { label: "Rules", href: "/rules", icon: NAV_ICON_PATHS.rules, enabled: true },
        { label: "Settings", href: "/settings", icon: NAV_ICON_PATHS.settings, enabled: true },
      ],
    },
  ];
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const groups = useNav();
  const { batch } = useCurrentBatch();
  const [aiOpen, setAiOpen] = useState(false);

  return (
    <div className={`dash ${dashFontVariables}`} style={{ display: "flex", minHeight: "100vh" }}>
      {/* ============ SIDEBAR ============ */}
      <div
        style={{
          width: 246,
          flex: "none",
          background: "var(--dash-sidebar)",
          borderRight: "1px solid var(--dash-line)",
          display: "flex",
          flexDirection: "column",
          position: "sticky",
          top: 0,
          height: "100vh",
        }}
      >
        <div style={{ padding: "20px 18px 14px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 11, padding: 8 }}>
            <div
              style={{
                flex: "none",
                width: 32,
                height: 32,
                borderRadius: 9,
                background: "linear-gradient(140deg, var(--dash-benign), oklch(0.615 0.10 168))",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 15,
                fontWeight: 800,
                color: "oklch(0.985 0.014 88)",
              }}
            >
              R
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13.5, fontWeight: 700, letterSpacing: "-0.01em", whiteSpace: "nowrap" }}>
                Where did my money go?
              </div>
              <div style={{ fontSize: 11, color: "var(--dash-ink-faint)" }}>Reconciliation</div>
            </div>
          </div>
        </div>

        <Link
          href="/new-run"
          className="dash-pressable"
          style={{
            margin: "0 18px 18px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            background: "var(--dash-benign-soft)",
            color: "oklch(0.30 0.06 148)",
            borderRadius: 10,
            padding: 11,
            fontSize: 13.5,
            fontWeight: 700,
            cursor: "pointer",
          }}
        >
          <span style={{ fontSize: 15, lineHeight: 1, marginTop: -1 }}>+</span> New reconciliation
        </Link>

        <div style={{ flex: 1, overflowY: "auto", padding: "0 12px 12px" }}>
          {groups.map((grp) => (
            <div key={grp.title} style={{ marginBottom: 20 }}>
              <div
                style={{
                  fontSize: 10.5,
                  fontWeight: 700,
                  letterSpacing: ".13em",
                  textTransform: "uppercase",
                  color: "var(--dash-neutral)",
                  padding: "0 10px 8px",
                }}
              >
                {grp.title}
              </div>
              {grp.items.map((it) => {
                const active = pathname === it.href || (it.href !== "/" && pathname.startsWith(it.href.split("/").slice(0, 3).join("/")));
                return (
                  <Link
                    key={it.label}
                    href={it.href}
                    title={it.enabled ? undefined : "Open a run first"}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "9px 10px",
                      borderRadius: 8,
                      fontSize: 13,
                      fontWeight: active ? 700 : 500,
                      color: active ? "var(--dash-ink)" : "var(--dash-ink-soft)",
                      background: active ? "oklch(0.5 0.045 72 / 0.14)" : "transparent",
                      opacity: it.enabled ? 1 : 0.55,
                    }}
                  >
                    <NavIcon path={it.icon} size={16} />
                    <span style={{ flex: 1 }}>{it.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </div>

        <div style={{ padding: "14px 18px 18px", borderTop: "1px solid var(--dash-line)" }}>
          <div
            style={{
              background: "color-mix(in oklch, var(--dash-accent) 9%, transparent)",
              border: "1px solid color-mix(in oklch, var(--dash-accent) 25%, transparent)",
              borderRadius: 12,
              padding: 13,
              marginBottom: 14,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                fontSize: 11.5,
                fontWeight: 700,
                color: "var(--dash-accent-deep)",
                marginBottom: 6,
              }}
            >
              <SparkleIcon size={13} /> Copilot
            </div>
            <div style={{ fontSize: 11.5, lineHeight: 1.5, color: "oklch(0.42 0.024 74)", marginBottom: 10 }}>
              Ask anything about this cycle — it reads your ledger, fees and payouts.
            </div>
            <button
              type="button"
              onClick={() => setAiOpen(true)}
              disabled={!batch}
              className="dash-pressable"
              style={{
                width: "100%",
                background: "var(--dash-benign)",
                color: "oklch(0.985 0.014 88)",
                borderRadius: 8,
                padding: 7,
                textAlign: "center",
                fontSize: 12,
                fontWeight: 700,
                border: "none",
                cursor: batch ? "pointer" : "not-allowed",
                opacity: batch ? 1 : 0.5,
              }}
            >
              Ask Copilot
            </button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Avatar initials="FO" />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600 }}>Finance ops</div>
              <div style={{ fontSize: 10.5, color: "var(--dash-ink-faint)" }}>Single-user demo</div>
            </div>
          </div>
        </div>
      </div>

      {/* ============ MAIN ============ */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <div
          style={{
            position: "sticky",
            top: 0,
            zIndex: 30,
            background: "color-mix(in oklch, var(--dash-ground) 88%, transparent)",
            backdropFilter: "blur(14px)",
            borderBottom: "1px solid var(--dash-line)",
            padding: "0 28px",
            height: 60,
            display: "flex",
            alignItems: "center",
            gap: 18,
          }}
        >
          <div
            style={{
              flex: 1,
              maxWidth: 340,
              display: "flex",
              alignItems: "center",
              gap: 9,
              background: "var(--dash-raised)",
              border: "1px solid var(--dash-line-strong)",
              borderRadius: 9,
              padding: "8px 11px",
            }}
          >
            <SearchIcon size={14} style={{ color: "var(--dash-ink-faint)" }} />
            <input
              type="text"
              placeholder="Search runs…"
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                const q = (e.target as HTMLInputElement).value.trim();
                if (q) router.push(`/runs?q=${encodeURIComponent(q)}`);
              }}
              style={{ flex: 1, minWidth: 0, background: "transparent", border: "none", outline: "none", fontSize: 13, color: "var(--dash-ink)" }}
            />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none", marginLeft: "auto" }}>
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: 9,
                border: "1px solid var(--dash-line-strong)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "oklch(0.41 0.024 74)",
              }}
            >
              <BellIcon size={15} />
            </div>
            <button
              type="button"
              onClick={() => setAiOpen((v) => !v)}
              disabled={!batch}
              className="dash-pressable"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                border: "none",
                borderRadius: 9,
                padding: "8px 14px",
                fontSize: 12.5,
                fontWeight: 700,
                cursor: batch ? "pointer" : "not-allowed",
                opacity: batch ? 1 : 0.5,
                background: aiOpen
                  ? "var(--dash-benign)"
                  : "color-mix(in oklch, var(--dash-accent) 14%, transparent)",
                color: aiOpen ? "oklch(0.985 0.014 88)" : "var(--dash-accent-deep)",
              }}
            >
              <SparkleIcon size={14} /> Copilot
            </button>
          </div>
        </div>

        <div style={{ display: "flex", flex: 1, minWidth: 0 }}>
          <div style={{ flex: 1, minWidth: 0, padding: "34px 28px 96px" }}>{children}</div>

          {aiOpen && (
            <div
              style={{
                width: 400,
                flex: "none",
                borderLeft: "1px solid var(--dash-line)",
                background: "var(--dash-sidebar)",
                position: "sticky",
                top: 60,
                height: "calc(100vh - 60px)",
                display: "flex",
                flexDirection: "column",
                animation: "slideIn .28s cubic-bezier(.2,.7,.2,1) both",
              }}
            >
              <div
                style={{
                  padding: "18px 20px",
                  borderBottom: "1px solid var(--dash-line)",
                  display: "flex",
                  alignItems: "center",
                  gap: 11,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <CopilotHeader batch={batch} />
                </div>
                {batch && (
                  <Link
                    href={`/copilot/${encodeURIComponent(batch)}`}
                    style={{ flex: "none", fontSize: 11.5, fontWeight: 600, color: "var(--dash-ink-soft)" }}
                  >
                    Expand
                  </Link>
                )}
                <button
                  type="button"
                  onClick={() => setAiOpen(false)}
                  aria-label="Close Copilot"
                  style={{
                    flex: "none",
                    width: 24,
                    height: 24,
                    borderRadius: 6,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--dash-ink-soft)",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                  }}
                >
                  <CloseIcon size={13} />
                </button>
              </div>
              <div style={{ flex: 1, minHeight: 0 }}>
                <CopilotChat batch={batch} compact />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
