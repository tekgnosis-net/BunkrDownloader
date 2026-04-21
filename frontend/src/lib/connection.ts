import { api } from "./api";
import { isHelloFrame, isTerminalStatus, type JobEvent, type HelloFrame } from "./events";
import { buildWsUrl } from "./ws-url";
import { useJobStore, type ConnectionMode } from "./store";

/**
 * Deterministic WebSocket-over-polling state machine for a single job.
 *
 * Invariants the old App.jsx implementation failed to uphold:
 *   - Exactly one of {WS_ACTIVE, POLL_FALLBACK} runs at a time. The old
 *     code started polling from inside ``onclose`` while simultaneously
 *     scheduling a WS reconnect, so both channels delivered events for
 *     the window between those two transitions.
 *   - The cursor advances ONLY from server-stamped ``event_id`` /
 *     ``next_id`` / ``hello.next_id``. The old code did
 *     ``eventIndexRef.current += processed`` after WS messages while
 *     polling used the server's ``next_index``, so the two cursors
 *     drifted on reconnect.
 *   - Every envelope is filtered through a ``Set<number>`` keyed by
 *     ``event_id`` before being handed to the store, capped at
 *     ``SEEN_IDS_MAX`` with LRU-by-id eviction.
 *   - ``410 Gone`` on /events (broker pruned history below ``since``)
 *     resets the entire view rather than silently missing updates.
 *
 * Exponential backoff: 0.8s, 1.6s, 3.2s, 6.4s, 12.8s (capped at 15s).
 * After ``RECONNECT_MAX_ATTEMPTS`` (5) consecutive failures the machine
 * promotes to POLL_FALLBACK and stops trying WS until a successful WS
 * handshake happens (via periodic opportunistic upgrade every 60s).
 */

const RECONNECT_BASE_MS = 800;
const RECONNECT_CAP_MS = 15_000;
const RECONNECT_MAX_ATTEMPTS = 5;
const POLL_INTERVAL_MS = 2_000;
const POLL_UPGRADE_EVERY_N_TICKS = 30; // ~60s
const SEEN_IDS_MAX = 4096;

interface EventsResponse {
  events: JobEvent[];
  next_id?: number;
  next_index?: number;
}

export class JobConnection {
  private ws: WebSocket | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private pollTickCount = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private attempts = 0;
  private seen = new Set<number>();
  private cursor = 0;
  private currentMode: ConnectionMode = "offline";
  private jobId: string | null = null;
  private stopped = false;

  start(jobId: string): void {
    this.jobId = jobId;
    this.stopped = false;
    this.connectWS();
  }

  stop(jobGone = false): void {
    this.stopped = true;
    this.clearReconnect();
    this.stopPolling();
    this.closeWs();
    if (jobGone) useJobStore.getState().reset();
    this.setMode("offline");
  }

  /**
   * User-initiated refresh. Clears transient state (cursor, seen, WS) and
   * re-enters from a cold start. Intentionally keeps the store snapshot
   * so the UI doesn't blink.
   */
  refresh(): void {
    if (!this.jobId) return;
    this.closeWs();
    this.stopPolling();
    this.clearReconnect();
    this.attempts = 0;
    this.seen.clear();
    this.cursor = 0;
    this.connectWS();
  }

  /* ---- internals --------------------------------------------------- */

  private connectWS(): void {
    if (!this.jobId || this.stopped) return;
    this.stopPolling();
    this.clearReconnect();
    this.setMode("offline");

    const ws = new WebSocket(buildWsUrl(this.jobId));
    this.ws = ws;

    ws.onopen = () => {
      // Server sends a ``hello`` frame with its authoritative cursor; we
      // don't flip to WS_ACTIVE until we've received it.
    };

    ws.onmessage = (messageEvent: MessageEvent) => {
      let payload: JobEvent | HelloFrame;
      try {
        payload = JSON.parse(messageEvent.data);
      } catch {
        return;
      }

      if (isHelloFrame(payload)) {
        this.attempts = 0;
        this.setMode("ws");
        // If we missed events between our last cursor and the server's
        // hello cursor, pull them via one HTTP backfill before the live
        // stream continues.
        if (payload.next_id > this.cursor) void this.backfill(payload.next_id);
        return;
      }

      this.ingest([payload]);
    };

    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      if (this.stopped || this.isTerminal()) return;
      if (this.attempts >= RECONNECT_MAX_ATTEMPTS) {
        this.setMode("poll");
        this.startPolling();
        return;
      }
      const delay = Math.min(
        RECONNECT_CAP_MS,
        RECONNECT_BASE_MS * 2 ** this.attempts,
      );
      this.attempts += 1;
      useJobStore.getState().setConnection({ wsAttempt: this.attempts });
      this.reconnectTimer = setTimeout(() => this.connectWS(), delay);
    };

    ws.onerror = () => {
      // onclose drives policy; the error by itself doesn't mean the
      // socket is gone (Safari sometimes fires error before open).
    };
  }

  private startPolling(): void {
    if (this.pollTimer || !this.jobId) return;

    const tick = async () => {
      if (this.stopped || !this.jobId) return;
      try {
        const { data } = await api.get<EventsResponse>(
          `/downloads/${this.jobId}/events`,
          { params: { since: this.cursor } },
        );
        this.ingest(data.events ?? [], data.next_id ?? data.next_index);

        if (this.isTerminal()) {
          this.stop();
          return;
        }

        this.pollTickCount += 1;
        if (this.pollTickCount % POLL_UPGRADE_EVERY_N_TICKS === 0) {
          this.attempts = 0;
          this.connectWS();
        }
      } catch (err) {
        const status =
          (err as { response?: { status?: number; data?: { detail?: unknown } } })
            .response?.status;
        if (status === 410) {
          // Server pruned events below our cursor. Reset the view and
          // restart from scratch — there's no way to silently recover
          // without misleading the user about what's on screen.
          const detail = (err as { response?: { data?: { detail?: { next_id?: number } } } })
            .response?.data?.detail;
          const resetTo =
            detail && typeof detail === "object" && typeof detail.next_id === "number"
              ? detail.next_id
              : 0;
          this.seen.clear();
          this.cursor = resetTo;
          useJobStore.getState().reset();
          useJobStore.getState().setJob(this.jobId, "running");
          return;
        }
        if (status === 404) {
          this.stop(true);
        }
      }
    };

    void tick();
    this.pollTimer = setInterval(tick, POLL_INTERVAL_MS);
  }

  private async backfill(upTo: number): Promise<void> {
    if (!this.jobId) return;
    try {
      const { data } = await api.get<EventsResponse>(
        `/downloads/${this.jobId}/events`,
        { params: { since: this.cursor } },
      );
      this.ingest(data.events ?? [], data.next_id ?? data.next_index ?? upTo);
    } catch {
      // Backfill is best-effort; the live WS stream will cover the tail.
    }
  }

  private ingest(events: JobEvent[], nextCursorHint?: number): void {
    const fresh: JobEvent[] = [];
    for (const ev of events) {
      const id = ev.event_id;
      if (typeof id !== "number") continue;
      if (this.seen.has(id)) continue;
      this.seen.add(id);
      if (this.seen.size > SEEN_IDS_MAX) this.trimSeen();
      fresh.push(ev);
      if (id > this.cursor) this.cursor = id;
    }
    if (typeof nextCursorHint === "number" && nextCursorHint > this.cursor) {
      this.cursor = nextCursorHint;
    }
    if (fresh.length) useJobStore.getState().applyEvents(fresh);
  }

  /**
   * Keep the most-recently-seen half of the set. Event IDs grow
   * monotonically so sorting desc + slicing gives an LRU-by-magnitude
   * eviction without maintaining a parallel insertion-order structure.
   */
  private trimSeen(): void {
    const kept = Array.from(this.seen).sort((a, b) => b - a).slice(0, SEEN_IDS_MAX / 2);
    this.seen = new Set(kept);
  }

  private setMode(mode: ConnectionMode): void {
    if (this.currentMode === mode) return;
    this.currentMode = mode;
    useJobStore.getState().setConnection({ mode, wsAttempt: this.attempts });
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    this.pollTickCount = 0;
  }

  private clearReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private closeWs(): void {
    if (this.ws) {
      try {
        this.ws.onclose = null; // prevent reconnect cascade during teardown
        this.ws.close();
      } catch {
        // ignore teardown errors
      }
      this.ws = null;
    }
  }

  private isTerminal(): boolean {
    return isTerminalStatus(useJobStore.getState().jobStatus);
  }
}
