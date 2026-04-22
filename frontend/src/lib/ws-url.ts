const WS_BASE = (import.meta.env.VITE_WS_BASE_URL as string | undefined) ?? null;

/**
 * Build the WebSocket URL for a given job id, preserving any path prefix
 * the app is served under (e.g. ``/bunkr/`` behind a reverse proxy).
 * Falls back to ``VITE_WS_BASE_URL`` when set so dev setups that tunnel
 * the socket through a different origin keep working.
 */
export function buildWsUrl(jobId: string): string {
  if (WS_BASE) return `${WS_BASE.replace(/\/$/, "")}/ws/jobs/${jobId}`;

  const { protocol, host, pathname } = window.location;
  const wsProtocol = protocol === "https:" ? "wss" : "ws";
  const base = pathname.replace(/\/[^/]*$/, "").replace(/\/$/, "");
  return `${wsProtocol}://${host}${base}/ws/jobs/${jobId}`;
}
