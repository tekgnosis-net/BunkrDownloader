import clsx from "clsx";
import styles from "../../styles/progress.module.css";

interface GlassProgressProps {
  /** 0-100 — clamped automatically. */
  value?: number;
  /** Render the shimmer ribbon for unknown-duration states. */
  indeterminate?: boolean;
  /** Use the taller 10px track (for overall progress vs per-file). */
  large?: boolean;
  /** Announced by screen readers when value is known. */
  label?: string;
}

/**
 * Single-bar progress indicator that animates the fill via the ``--pct``
 * CSS custom property — avoids re-painting the element on every React
 * render and keeps the transition smooth under event-batching storms.
 */
export function GlassProgress({ value, indeterminate, large, label }: GlassProgressProps) {
  const pct = indeterminate ? 0 : Math.max(0, Math.min(100, value ?? 0));

  return (
    <div
      className={clsx(styles.bar, large && styles.barLg)}
      role="progressbar"
      aria-label={label}
      aria-valuenow={indeterminate ? undefined : pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-busy={indeterminate || undefined}
    >
      <div
        className={styles.fill}
        data-indeterminate={indeterminate ? "true" : undefined}
        style={{ ["--pct" as string]: `${pct}%` }}
      />
    </div>
  );
}
