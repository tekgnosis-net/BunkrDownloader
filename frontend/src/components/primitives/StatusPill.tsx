import type { JobStatus } from "../../lib/events";

interface StatusPillProps {
  status: JobStatus | "idle";
}

/**
 * Small tinted pill that mirrors the current job status. The colour
 * mapping uses the semantic tokens (``--success-500`` / ``--warning-500``
 * / ``--danger-500``) plus a muted inked variant for idle/pending.
 */
export function StatusPill({ status }: StatusPillProps) {
  const variant = toVariant(status);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "2px 10px",
        borderRadius: "var(--radius-pill)",
        fontSize: 12,
        fontWeight: 500,
        letterSpacing: "0.01em",
        background: `color-mix(in oklch, ${variant.accent} 18%, var(--surface-base))`,
        color: `color-mix(in oklch, ${variant.accent} 70%, var(--ink))`,
        border: `1px solid color-mix(in oklch, ${variant.accent} 25%, transparent)`,
      }}
      aria-live="polite"
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: variant.accent,
          boxShadow: `0 0 0 2px color-mix(in oklch, ${variant.accent} 20%, transparent)`,
        }}
      />
      {variant.label}
    </span>
  );
}

function toVariant(status: StatusPillProps["status"]) {
  switch (status) {
    case "running":   return { accent: "var(--accent-500)",  label: "Running" };
    case "completed": return { accent: "var(--success-500)", label: "Completed" };
    case "failed":    return { accent: "var(--danger-500)",  label: "Failed" };
    case "cancelled": return { accent: "var(--warning-500)", label: "Cancelled" };
    case "pending":   return { accent: "var(--accent-400)",  label: "Pending" };
    case "idle":
    default:          return { accent: "var(--ink-muted)",   label: "Idle" };
  }
}
