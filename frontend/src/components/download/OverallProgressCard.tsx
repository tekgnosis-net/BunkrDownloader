import { Surface } from "../primitives/Surface";
import { GlassProgress } from "../primitives/GlassProgress";
import { useJobError, useJobStatus, useOverall } from "../../lib/store";

/**
 * Hero card showing the album-level progress bar, the description, and
 * any job-level error surfaced by the server.
 */
export function OverallProgressCard() {
  const overall = useOverall();
  const status = useJobStatus();
  const error = useJobError();

  if (!overall && status === "idle") {
    return (
      <Surface variant="cardLg">
        <p
          style={{
            margin: 0,
            fontSize: 15,
            color: "var(--ink-muted)",
          }}
        >
          No active download. Paste one or more Bunkr URLs above to start.
        </p>
      </Surface>
    );
  }

  const pct =
    overall && overall.total > 0
      ? (overall.completed / overall.total) * 100
      : 0;
  const indeterminate = !overall || overall.total === 0;

  return (
    <Surface variant="cardLg">
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: "var(--space-3)",
          marginBottom: "var(--space-3)",
        }}
      >
        <h2
          style={{
            margin: 0,
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: "-0.01em",
            color: "var(--ink)",
          }}
        >
          {overall?.description ?? "Preparing download"}
        </h2>
        {overall && (
          <span
            className="tabular"
            style={{ fontSize: 13, color: "var(--ink-muted)" }}
          >
            {overall.completed} / {overall.total}
          </span>
        )}
      </header>
      <GlassProgress
        value={pct}
        indeterminate={indeterminate}
        large
        label={overall?.description ?? undefined}
      />
      {error && (
        <p
          style={{
            marginTop: "var(--space-3)",
            marginBottom: 0,
            fontSize: 13,
            color: "var(--danger-500)",
          }}
        >
          {error}
        </p>
      )}
    </Surface>
  );
}
