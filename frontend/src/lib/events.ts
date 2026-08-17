/**
 * Wire contract for server-sent events.
 *
 * The shape is defined server-side in ``src/web/app.py::JobEventBroker``
 * and must stay byte-identical across the HTTP polling endpoint and the
 * WebSocket stream. Every envelope carries ``event_id`` (monotonic per
 * job, starts at 1) and ``ts`` (ISO-8601 UTC).
 */

export type JobStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export interface BaseEvent {
  event_id: number;
  type: string;
  ts: string;
}

export interface LogEvent extends BaseEvent {
  type: "log";
  event: string;
  details: string;
  timestamp?: string;
}

export interface TaskPayload {
  id: number;
  label: string;
  completed: number;
  visible: boolean;
}

export interface TaskCreatedEvent extends BaseEvent {
  type: "task_created";
  task: TaskPayload;
}

export interface TaskUpdatedEvent extends BaseEvent {
  type: "task_updated";
  task: TaskPayload;
}

export interface OverallEvent extends BaseEvent {
  type: "overall";
  description: string | null;
  total: number;
  completed: number;
}

export interface StatusEvent extends BaseEvent {
  type: "status";
  status: JobStatus;
  message?: string;
}

export interface MaintenanceEvent extends BaseEvent {
  type: "maintenance_detected";
  subdomain: string;
  status: string;
  affected_files_count: number;
  event: string;
  details: string;
}

/**
 * Per-URL verdict for a batch job, emitted once per submitted URL.
 *
 * ``index`` is 1-based against the list the client POSTed. Match on it
 * rather than on ``url``: the server echoes the value after pydantic's
 * ``AnyHttpUrl`` has normalised it, so it need not be byte-identical to
 * the line the user typed.
 */
export interface UrlResultEvent extends BaseEvent {
  type: "url_result";
  url: string;
  index: number;
  total: number;
  status: "succeeded" | "failed";
  error: string | null;
}

/**
 * WS-only frame sent before the live stream begins. ``next_id`` is the
 * cursor the client should use for an HTTP backfill (``?since=<cursor>``)
 * if its local state is behind. Mirrors ``GET /events``'s ``next_id`` so
 * both endpoints agree.
 */
export interface HelloFrame {
  type: "hello";
  next_id: number;
  next_index: number;
  ts: string;
}

export type JobEvent =
  | LogEvent
  | TaskCreatedEvent
  | TaskUpdatedEvent
  | OverallEvent
  | StatusEvent
  | MaintenanceEvent
  | UrlResultEvent;

export function isHelloFrame(msg: { type: string }): msg is HelloFrame {
  return msg.type === "hello";
}

export function isTerminalStatus(status: JobStatus | "idle"): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}
