import { useEffect, useRef } from "react";
import { Surface } from "../primitives/Surface";
import { useLogs } from "../../lib/store";

/**
 * Monospace event log. Auto-scrolls to the newest entry when the user
 * hasn't manually scrolled away from the bottom; wraps its list in
 * ``role="log" aria-live="polite"`` so screen readers announce new
 * entries without interrupting focus.
 */
export function LogPane() {
  const logs = useLogs();
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoFollow = useRef(true);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !autoFollow.current) return;
    el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.clientHeight - el.scrollTop;
    autoFollow.current = distanceFromBottom < 40;
  };

  return (
    <Surface variant="card">
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: "var(--space-3)",
        }}
      >
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600, color: "var(--ink)" }}>
          Activity log
        </h2>
        <span className="tabular" style={{ fontSize: 12, color: "var(--ink-muted)" }}>
          {logs.length} entries
        </span>
      </header>
      <div
        ref={scrollRef}
        onScroll={onScroll}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        style={{
          maxHeight: 320,
          overflowY: "auto",
          padding: "var(--space-2)",
          background: "color-mix(in oklch, var(--ink) 6%, transparent)",
          border: "1px solid var(--surface-border)",
          borderRadius: "var(--radius-md)",
          fontFamily: "var(--font-mono)",
          fontSize: 12.5,
          lineHeight: 1.5,
          color: "var(--ink-muted)",
        }}
      >
        {logs.length === 0 ? (
          <p style={{ margin: 0, fontStyle: "italic" }}>
            Log entries will appear here once a job is running.
          </p>
        ) : (
          logs.map((entry) => (
            <div
              key={`${entry.event_id}-${entry.timestamp}`}
              style={{ display: "grid", gridTemplateColumns: "90px 150px 1fr", gap: "var(--space-2)" }}
            >
              <span style={{ color: "var(--ink-muted)" }}>
                {new Date(entry.timestamp).toLocaleTimeString()}
              </span>
              <span
                style={{
                  color:
                    entry.origin === "maintenance"
                      ? "var(--warning-500)"
                      : "var(--ink)",
                  fontWeight: 500,
                }}
              >
                {entry.event}
              </span>
              <span>{entry.details}</span>
            </div>
          ))
        )}
      </div>
    </Surface>
  );
}
