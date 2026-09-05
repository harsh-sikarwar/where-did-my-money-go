"use client";

/**
 * Shared vocabulary for the dashboard rebuild ("Reconciliation Tool" mockup).
 * Mirrors the role `components/ui.tsx` plays for the original one-page
 * product — one place a spacing/radius/severity decision gets made, instead
 * of re-argued per screen. Scoped to the `.dash` theme (see globals.css).
 */

import type { CSSProperties, ReactNode, SVGProps } from "react";

/* ------------------------------------------------------------------ severity */

export type Severity = "benign" | "action" | "urgent" | "neutral";

export const DASH_TONE: Record<Severity, string> = {
  benign: "var(--dash-benign)",
  action: "var(--dash-action)",
  urgent: "var(--dash-urgent)",
  neutral: "var(--dash-neutral)",
};

export function dashToneAlpha(severity: Severity, alpha: number): string {
  return `color-mix(in oklch, ${DASH_TONE[severity]} ${Math.round(alpha * 100)}%, transparent)`;
}

/** Same classification → severity mapping as `components/ui.tsx`, so the two
 *  themes never disagree about what a rupee means. */
const URGENT_CLASSES = new Set([
  "refund_pending",
  "refund_not_settled",
  "refund_timing_lag",
  "missing_settlement",
  "not_settled",
]);

export function severityOf(line: { classification: string; actionable: boolean }): Severity {
  if (!line.actionable) return "benign";
  return URGENT_CLASSES.has(line.classification) ? "urgent" : "action";
}

/* ------------------------------------------------------------------ icons */

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function base(size: number) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none" as const,
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
}

/** The Copilot / AI glyph — a four-point sparkle, used everywhere the mockup
 *  marks something as model-assisted. */
export function SparkleIcon({ size = 14, strokeWidth = 2, ...props }: IconProps) {
  return (
    <svg {...base(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" />
    </svg>
  );
}

export function SearchIcon({ size = 14, strokeWidth = 1.8, ...props }: IconProps) {
  return (
    <svg {...base(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M11 4a7 7 0 105.6 11.2L21 20" />
    </svg>
  );
}

export function BellIcon({ size = 15, strokeWidth = 1.7, ...props }: IconProps) {
  return (
    <svg {...base(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M6 9a6 6 0 1112 0c0 5 2 6 2 6H4s2-1 2-6M10 20a2 2 0 004 0" />
    </svg>
  );
}

export function ChevronDownIcon({ size = 11, strokeWidth = 1.8, ...props }: IconProps) {
  return (
    <svg {...base(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export function ArrowLeftIcon({ size = 14, strokeWidth = 1.9, ...props }: IconProps) {
  return (
    <svg {...base(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M15 5l-7 7 7 7" />
    </svg>
  );
}

export function ArrowRightIcon({ size = 14, strokeWidth = 1.9, ...props }: IconProps) {
  return (
    <svg {...base(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M9 5l7 7-7 7" />
    </svg>
  );
}

export function CheckIcon({ size = 11, strokeWidth = 3.2, ...props }: IconProps) {
  return (
    <svg {...base(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}

export function FileIcon({ size = 11, strokeWidth = 1.8, ...props }: IconProps) {
  return (
    <svg {...base(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M7 3h7l5 5v13H7zM14 3v5h5" />
    </svg>
  );
}

export function CloseIcon({ size = 14, strokeWidth = 1.8, ...props }: IconProps) {
  return (
    <svg {...base(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

/** Sidebar nav glyph paths, keyed to keep `Sidebar` free of inline SVG noise. */
export const NAV_ICON_PATHS: Record<string, string> = {
  overview: "M4 13h6V4H4zM14 20h6v-9h-6zM4 20h6v-4H4zM14 10h6V4h-6z",
  runs: "M4 6h16M4 12h16M4 18h10",
  analysis: "M4 20V10M11 20V4M18 20v-7",
  reports: "M7 3h7l5 5v13H7zM14 3v5h5M9 13h6M9 17h6",
  copilot: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
  exceptions: "M12 9v4m0 4h.01M10.3 3.9L2.7 17a1.7 1.7 0 001.5 2.6h15.6a1.7 1.7 0 001.5-2.6L13.7 3.9a1.7 1.7 0 00-3.4 0z",
  audit: "M12 8v4l3 2M12 3a9 9 0 100 18 9 9 0 000-18z",
  settings: "M12 15a3 3 0 100-6 3 3 0 000 6zM4.5 12a7.5 7.5 0 01.4-2.4L3 8l2-3.5 2.3.9a7.6 7.6 0 012-1.2L9.7 2h4.6l.4 2.3a7.6 7.6 0 012 1.2l2.3-.9L21 8l-1.9 1.6a7.5 7.5 0 010 4.8L21 16l-2 3.5-2.3-.9a7.6 7.6 0 01-2 1.2l-.4 2.2H9.7l-.4-2.2a7.6 7.6 0 01-2-1.2l-2.3.9L3 16l1.9-1.6a7.5 7.5 0 01-.4-2.4z",
  rules: "M6 4v16M6 4h11l-2 4 2 4H6",
  sources: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
};

export function NavIcon({ path, size = 16, ...props }: IconProps & { path: string }) {
  return (
    <svg {...base(size)} strokeWidth={1.7} {...props}>
      <path d={path} />
    </svg>
  );
}

/* ------------------------------------------------------------------ surfaces */

export function DashCard({
  children,
  className = "",
  style,
  interactive = false,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  interactive?: boolean;
}) {
  return (
    <div
      style={{
        background: "var(--dash-raised)",
        border: "1px solid var(--dash-line)",
        borderRadius: 16,
        boxShadow: "var(--dash-shadow-card)",
        transition: "transform .22s, border-color .22s, box-shadow .22s",
        ...style,
      }}
      className={`${interactive ? "dash-card-interactive" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionLabel({
  children,
  as: Tag = "h2",
  className = "",
  style,
}: {
  children: ReactNode;
  as?: "h2" | "h3" | "div";
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <Tag
      className={className}
      style={{
        fontSize: 12,
        fontWeight: 700,
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        color: "var(--dash-ink-faint)",
        margin: 0,
        ...style,
      }}
    >
      {children}
    </Tag>
  );
}

/* ------------------------------------------------------------------ pills / badges */

export function Pill({
  children,
  tone,
  accent = false,
  style,
}: {
  children: ReactNode;
  tone?: Severity;
  accent?: boolean;
  style?: CSSProperties;
}) {
  const color = accent ? "var(--dash-accent-deep)" : tone ? DASH_TONE[tone] : "var(--dash-ink-soft)";
  const background = accent
    ? "color-mix(in oklch, var(--dash-accent) 15%, transparent)"
    : tone
      ? dashToneAlpha(tone, 0.13)
      : "var(--dash-well)";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        borderRadius: 999,
        padding: "3px 10px",
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.02em",
        whiteSpace: "nowrap",
        color,
        background,
        ...style,
      }}
    >
      {children}
    </span>
  );
}

export function StatusDot({ severity, size = 7 }: { severity: Severity; size?: number }) {
  return (
    <span
      aria-hidden
      style={{
        display: "inline-block",
        flex: "none",
        width: size,
        height: size,
        borderRadius: 999,
        background: DASH_TONE[severity],
      }}
    />
  );
}

/* ------------------------------------------------------------------ buttons */

type ButtonVariant = "primary" | "secondary" | "ghost" | "ai";

const BTN_STYLE: Record<ButtonVariant, CSSProperties> = {
  primary: {
    background: "var(--dash-benign-soft)",
    color: "oklch(0.30 0.06 148)",
    fontWeight: 700,
  },
  secondary: {
    border: "1px solid var(--dash-line-strong)",
    color: "oklch(0.35 0.025 72)",
    fontWeight: 600,
    background: "transparent",
  },
  ghost: {
    color: "var(--dash-ink-soft)",
    fontWeight: 600,
    background: "transparent",
  },
  ai: {
    background: "var(--dash-benign)",
    color: "oklch(0.985 0.014 88)",
    fontWeight: 700,
  },
};

export function DashButton({
  children,
  onClick,
  variant = "secondary",
  size = "md",
  disabled = false,
  title,
  style,
  full = false,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: ButtonVariant;
  size?: "sm" | "md";
  disabled?: boolean;
  title?: string;
  style?: CSSProperties;
  full?: boolean;
}) {
  const pad = size === "sm" ? "7px 13px" : "9px 15px";
  const fontSize = size === "sm" ? 12 : 12.5;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="dash-pressable"
      style={{
        display: full ? "flex" : "inline-flex",
        width: full ? "100%" : undefined,
        justifyContent: "center",
        alignItems: "center",
        gap: 7,
        borderRadius: 9,
        padding: pad,
        fontSize,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.45 : 1,
        transition: "transform .18s, box-shadow .18s, background .2s",
        border: "none",
        ...BTN_STYLE[variant],
        ...style,
      }}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ tabs */

export function DashTabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { key: string; label: string }[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--dash-line)" }}>
      {tabs.map((t) => {
        const isActive = t.key === active;
        return (
          <button
            key={t.key}
            type="button"
            onClick={() => onChange(t.key)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "12px 16px",
              fontSize: 13,
              fontWeight: isActive ? 700 : 600,
              color: isActive ? "var(--dash-ink)" : "var(--dash-ink-faint)",
              borderBottom: isActive
                ? "2px solid var(--dash-benign)"
                : "2px solid transparent",
              marginBottom: -1,
              transition: "color .2s",
            }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ misc */

export function ShareBar({
  fraction,
  severity,
  delay = 0,
  height = 4,
}: {
  fraction: number;
  severity: Severity;
  delay?: number;
  height?: number;
}) {
  const pct = Math.max(0, Math.min(1, fraction)) * 100;
  return (
    <div
      style={{
        height,
        borderRadius: 999,
        background: "var(--dash-line-soft)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${pct}%`,
          borderRadius: 999,
          background: DASH_TONE[severity],
          transformOrigin: "left",
          animation: `growX .7s cubic-bezier(.2,.7,.2,1) ${delay}s both`,
        }}
      />
    </div>
  );
}

export function Switch({
  on,
  onToggle,
  disabled = false,
}: {
  on: boolean;
  onToggle?: () => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="switch"
      aria-checked={on}
      aria-disabled={disabled}
      onClick={disabled ? undefined : onToggle}
      style={{
        width: 34,
        height: 19,
        borderRadius: 999,
        background: on ? "var(--dash-benign)" : "var(--dash-line-strong)",
        position: "relative",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        transition: "background .2s",
        flex: "none",
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          left: on ? 17 : 2,
          width: 15,
          height: 15,
          borderRadius: 999,
          background: "oklch(0.99 0.005 90)",
          transition: "left .18s",
        }}
      />
    </div>
  );
}

export function Avatar({ initials, size = 29 }: { initials: string; size?: number }) {
  return (
    <div
      style={{
        flex: "none",
        width: size,
        height: size,
        borderRadius: 999,
        background: "oklch(0.87 0.065 150)",
        color: "oklch(0.34 0.07 150)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size * 0.4,
        fontWeight: 700,
      }}
    >
      {initials}
    </div>
  );
}

export function KpiCard({
  label,
  value,
  sub,
  delta,
  deltaTone,
  tone = "var(--dash-ink)",
}: {
  label: string;
  value: string;
  sub?: string;
  delta?: string;
  deltaTone?: Severity;
  tone?: string;
}) {
  return (
    <DashCard interactive style={{ padding: "18px 20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
        <SectionLabel as="div" style={{ fontSize: 11 }}>
          {label}
        </SectionLabel>
        {delta && (
          <span
            style={{
              fontSize: 11.5,
              fontWeight: 700,
              color: deltaTone ? DASH_TONE[deltaTone] : "var(--dash-ink-faint)",
            }}
          >
            {delta}
          </span>
        )}
      </div>
      <div
        style={{
          fontFamily: "var(--dash-font-mono)",
          fontSize: 26,
          fontWeight: 500,
          fontVariantNumeric: "tabular-nums",
          letterSpacing: "-0.02em",
          color: tone,
          marginTop: 14,
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 12, color: "var(--dash-ink-faint)", marginTop: 5 }}>{sub}</div>
      )}
    </DashCard>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontSize: 13,
        color: "var(--dash-ink-faint)",
        padding: "18px 0",
        fontStyle: "italic",
      }}
    >
      {children}
    </div>
  );
}
