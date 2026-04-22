import { Tooltip } from "@chakra-ui/react";
import { useConnection } from "../../lib/store";

const COLOURS = {
  ws:      { accent: "var(--success-500)", label: "Live (WebSocket)" },
  poll:    { accent: "var(--warning-500)", label: "Polling (fallback)" },
  offline: { accent: "var(--ink-muted)",   label: "Offline" },
} as const;

/** Tiny pulsing dot that indicates current progress-delivery channel. */
export function ConnectionIndicator() {
  const { mode, wsAttempt } = useConnection();
  const { accent, label } = COLOURS[mode];
  const tooltip =
    mode === "ws"
      ? label
      : mode === "poll"
      ? `${label} — WS reconnect attempts: ${wsAttempt}`
      : `${label}${wsAttempt ? ` — WS reconnect attempts: ${wsAttempt}` : ""}`;

  return (
    <Tooltip label={tooltip} hasArrow>
      <span
        aria-label={tooltip}
        style={{
          width: 10,
          height: 10,
          borderRadius: "50%",
          background: accent,
          boxShadow: `0 0 0 3px color-mix(in oklch, ${accent} 20%, transparent)`,
          display: "inline-block",
        }}
      />
    </Tooltip>
  );
}
