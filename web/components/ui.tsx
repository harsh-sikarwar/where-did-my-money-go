"use client";

/**
 * The shared vocabulary. Every screen is built from these, so a spacing, radius or
 * severity decision is made once rather than re-argued in each file.
 *
 * Deliberately small: this is not a component library, it is the handful of shapes
 * this product actually uses. Anything used once stays in the file that uses it.
 */

import type { CSSProperties, ReactNode, SVGProps } from "react";

/* ------------------------------------------------------------------ severity */

/**
 * The four tones money can carry. `benign` is explained and fine, `action` needs a
 * decision this cycle, `urgent` is overdue, `neutral` is the residue we cannot
 * explain. Structural violet is deliberately NOT in this map — it never describes
 * a rupee.
 */
export type Severity = "benign" | "action" | "urgent" | "neutral";

export const TONE: Record<Severity, string> = {
  benign: "var(--color-benign)",
  action: "var(--color-action)",
  urgent: "var(--color-urgent)",
  neutral: "var(--color-neutral)",
};

/**
 * A severity as raw oklch, for the places that need to build a translucent wash from
 * it. `color-mix` against transparent gets us the alpha without hand-maintaining a
 * second token per tone.
 */
export function toneAlpha(severity: Severity, alpha: number): string {
  return `color-mix(in oklch, ${TONE[severity]} ${Math.round(alpha * 100)}%, transparent)`;
}

/** The engine's classification strings, mapped to what the money actually means. */
export function severityOf(line: {
  classification: string;
  actionable: boolean;
}): Severity {
  if (!line.actionable) return "benign";
  return URGENT_CLASSES.has(line.classification) ? "urgent" : "action";
}

/** Overdue by nature — a refund a customer is still waiting on outranks a fee query. */
const URGENT_CLASSES = new Set([
  "refund_pending",
  "refund_not_settled",
  "refund_timing_lag",
  "missing_settlement",
  "not_settled",
]);

/* ------------------------------------------------------------------ icons */

/**
 * The whole icon set this product needs — a handful of glyphs, not a library.
 * One SVG per glyph, `currentColor` throughout, so state comes from CSS rather than
 * a second asset.
 */
type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function iconBase(size: number) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
}

export function ArrowRightIcon({ size = 16, strokeWidth = 2, ...props }: IconProps) {
  return (
    <svg {...iconBase(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

export function ArrowLeftIcon({ size = 16, strokeWidth = 2, ...props }: IconProps) {
  return (
    <svg {...iconBase(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M19 12H5M11 18l-6-6 6-6" />
    </svg>
  );
}

export function ChevronDownIcon({ size = 14, strokeWidth = 2, ...props }: IconProps) {
  return (
    <svg {...iconBase(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export function DownloadIcon({ size = 14, strokeWidth = 2, ...props }: IconProps) {
  return (
    <svg {...iconBase(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M12 3v12m0 0l-4-4m4 4l4-4M4 19h16" />
    </svg>
  );
}

export function CheckIcon({ size = 14, strokeWidth = 2.25, ...props }: IconProps) {
  return (
    <svg {...iconBase(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M5 12l5 5L19 7" />
    </svg>
  );
}

export function RefreshIcon({ size = 14, strokeWidth = 2, ...props }: IconProps) {
  return (
    <svg {...iconBase(size)} strokeWidth={strokeWidth} {...props}>
      <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
    </svg>
  );
}

/* ------------------------------------------------------------------ buttons */

type ButtonProps = {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
  full?: boolean;
  className?: string;
  style?: CSSProperties;
};

/**
 * Pills throughout. Primary is near-white on the dark ground — the single loudest
 * control on any screen, so there is never a question which one commits.
 */
const BUTTON_VARIANTS = {
  primary:
    "bg-[var(--color-ink)] text-[var(--color-ground)] font-bold hover:-translate-y-0.5 hover:shadow-[0_12px_28px_-14px_oklch(0.95_0.01_90/0.5)] disabled:opacity-30 disabled:translate-y-0 disabled:shadow-none",
  secondary:
    "border border-[var(--color-line-strong)] text-[var(--color-ink)] font-semibold hover:bg-[oklch(1_0_0/0.06)] hover:border-[oklch(1_0_0/0.3)] disabled:opacity-40",
  ghost:
    "text-[var(--color-ink-soft)] font-medium hover:text-[var(--color-ink)] disabled:opacity-40",
} as const;

const BUTTON_SIZES = {
  sm: "px-4 py-2 text-[13px]",
  md: "px-[18px] py-2.5 text-sm",
  lg: "px-6 py-[15px] text-[15px]",
} as const;

export function Button({
  children,
  onClick,
  disabled,
  type = "button",
  variant = "primary",
  size = "md",
  full = false,
  className = "",
  style,
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={style}
      className={`pressable inline-flex items-center justify-center gap-2 rounded-full whitespace-nowrap transition-[background-color,border-color,box-shadow,opacity,transform,color] duration-200 disabled:cursor-not-allowed ${
        BUTTON_VARIANTS[variant]
      } ${BUTTON_SIZES[size]} ${full ? "w-full" : ""} ${className}`}
    >
      {children}
    </button>
  );
}

/** A back link. Same shape on every screen, so "up" is always in the same place. */
export function BackLink({ children = "Back" }: { children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[13.5px] text-[var(--color-ink-soft)] transition-colors hover:text-[var(--color-ink)]">
      <ArrowLeftIcon size={14} /> {children}
    </span>
  );
}

/* ------------------------------------------------------------------ surfaces */

export function Card({
  children,
  className = "",
  tone,
  interactive = false,
  style,
}: {
  children: ReactNode;
  className?: string;
  /** Washes the card in a severity. Omit for a neutral raised surface. */
  tone?: Severity;
  interactive?: boolean;
  style?: CSSProperties;
}) {
  const toned = tone
    ? {
        background: toneAlpha(tone, 0.06),
        borderColor: toneAlpha(tone, 0.28),
      }
    : undefined;

  return (
    <div
      style={{ ...toned, ...style }}
      className={`rounded-2xl border transition-[border-color,background-color,transform,box-shadow] duration-200 ${
        tone
          ? ""
          : "border-[var(--color-line)] bg-[var(--color-raised)]"
      } ${
        interactive
          ? "hover:-translate-y-1 hover:border-[oklch(1_0_0/0.2)] hover:shadow-[0_24px_50px_-30px_oklch(0_0_0/0.9)]"
          : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

/** An uppercase section marker. Used to separate bands of a long screen. */
export function Eyebrow({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`text-label text-[var(--color-ink-faint)] ${className}`}>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ form controls */

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-[12.5px] text-[var(--color-ink-soft)]">
        {label}
      </span>
      {children}
      {hint && (
        <span className="mt-2 block text-[12.5px] leading-relaxed text-[var(--color-ink-faint)]">
          {hint}
        </span>
      )}
    </label>
  );
}

const CONTROL_BASE =
  "w-full box-border rounded-[10px] border border-[var(--color-line)] bg-[var(--color-raised)] px-3.5 py-3 text-[14.5px] text-[var(--color-ink)] outline-none transition-colors focus:border-[color-mix(in_oklch,var(--color-accent)_70%,transparent)]";

export function Select({
  value,
  onChange,
  options,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className={`${CONTROL_BASE} cursor-pointer appearance-none pr-9 disabled:cursor-not-allowed disabled:opacity-50`}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDownIcon
        size={14}
        className="pointer-events-none absolute top-1/2 right-3.5 -translate-y-1/2 text-[var(--color-ink-faint)]"
      />
    </div>
  );
}

export function NumberInput({
  value,
  onChange,
  min,
  max,
  step = 1,
  placeholder,
  align = "left",
  className = "",
}: {
  value: number | string;
  onChange: (value: string) => void;
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      step={step}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className={`${CONTROL_BASE} tnum ${align === "right" ? "text-right" : ""} ${className}`}
    />
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <input
      type="text"
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className={`${CONTROL_BASE} ${className}`}
    />
  );
}

/* ------------------------------------------------------------------ feedback */

/**
 * An error a person can act on. The engine's messages name the offending column, row
 * or arithmetic — they are shown verbatim, wrapped, because that message IS the fix
 * instruction and paraphrasing it would discard the useful part.
 */
export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div
      role="alert"
      className="rounded-xl border px-4 py-3"
      style={{
        borderColor: toneAlpha("urgent", 0.3),
        background: toneAlpha("urgent", 0.07),
      }}
    >
      <p className="text-sm leading-relaxed whitespace-pre-wrap text-[var(--color-urgent)]">
        {children}
      </p>
    </div>
  );
}

/** A tinted pill. `tone` for money, `accent` for structure (decoys, the demo path). */
export function Badge({
  children,
  tone,
  accent = false,
  className = "",
}: {
  children: ReactNode;
  tone?: Severity;
  accent?: boolean;
  className?: string;
}) {
  const color = accent ? "var(--color-accent)" : tone ? TONE[tone] : undefined;
  const wash = accent
    ? "color-mix(in oklch, var(--color-accent) 15%, transparent)"
    : tone
      ? toneAlpha(tone, 0.14)
      : undefined;

  return (
    <span
      style={color ? { color, background: wash } : undefined}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-bold whitespace-nowrap ${
        color
          ? ""
          : "border border-[var(--color-line)] bg-[var(--color-raised)] text-[var(--color-ink-soft)]"
      } ${className}`}
    >
      {children}
    </span>
  );
}

/** A small square swatch, for legends where a round dot would read as a bullet. */
export function Swatch({ severity }: { severity: Severity }) {
  return (
    <span
      aria-hidden
      className="h-2 w-2 shrink-0 rounded-[2px]"
      style={{ background: TONE[severity] }}
    />
  );
}

/** A round dot, for rows where the swatch sits inline with a label. */
export function Dot({ severity }: { severity: Severity }) {
  return (
    <span
      aria-hidden
      className="h-[7px] w-[7px] shrink-0 rounded-full"
      style={{ background: TONE[severity] }}
    />
  );
}

/**
 * A share-of-total bar. Severity-coloured and animated from the left, so a row's
 * weight registers before its number is read.
 */
export function ShareBar({
  fraction,
  severity,
  delay = 0,
  className = "",
}: {
  fraction: number;
  severity: Severity;
  delay?: number;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, fraction)) * 100;
  return (
    <div
      className={`h-[5px] overflow-hidden rounded-full bg-[oklch(1_0_0/0.07)] ${className}`}
    >
      <div
        className="h-full origin-left rounded-full"
        style={{
          width: `${pct}%`,
          background: TONE[severity],
          animation: `growX 0.7s cubic-bezier(0.2,0.7,0.2,1) ${delay}s both`,
        }}
      />
    </div>
  );
}

/** Skeleton for content genuinely on its way. Never a spinner-as-decoration. */
export function Skeleton({
  className = "",
  delay = 0,
  style,
}: {
  className?: string;
  delay?: number;
  /** For placeholders whose size is data-shaped (chart bars) rather than a utility. */
  style?: CSSProperties;
}) {
  return (
    <div
      aria-hidden
      className={`rounded bg-[var(--color-skeleton)] ${className}`}
      style={{ ...style, animation: `pulse 1.4s ease-in-out ${delay}s infinite` }}
    />
  );
}

/* ------------------------------------------------------------------ navigation */

/** A step marker for a flow with a known, ordered set of screens. Order carries meaning. */
export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-2 text-[11.5px] text-[var(--color-ink-faint)]">
      {steps.map((step, i) => (
        <li key={step} className="flex items-center gap-2">
          {i > 0 && <span aria-hidden>&rarr;</span>}
          <span
            className={
              i === current
                ? "font-semibold text-[var(--color-ink)]"
                : i < current
                  ? "text-[var(--color-ink-soft)]"
                  : ""
            }
          >
            {step}
          </span>
        </li>
      ))}
    </ol>
  );
}
