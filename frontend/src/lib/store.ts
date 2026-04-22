import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";
import type { JobEvent, JobStatus, TaskPayload } from "./events";

export interface TaskRow {
  id: number;
  label: string;
  completed: number;
  visible: boolean;
}

export interface LogEntry {
  event_id: number;
  event: string;
  details: string;
  timestamp: string;
  /** Client-only origin tag (e.g. "client", "server") used by the UI. */
  origin?: string;
}

export type ConnectionMode = "offline" | "ws" | "poll";

export interface ConnectionState {
  mode: ConnectionMode;
  wsAttempt: number;
}

export interface JobState {
  jobId: string | null;
  jobStatus: JobStatus | "idle";
  overall: { description: string | null; total: number; completed: number } | null;
  tasks: Map<number, TaskRow>;
  /** Rendered in insertion order; capped by ``logRetention``. */
  logs: LogEntry[];
  logRetention: number;
  /** Sorted array of task IDs currently in flight — stable reference unless a task is added/removed. */
  activeTaskIds: number[];
  connection: ConnectionState;
  error: string | null;
}

interface JobActions {
  applyEvents: (events: JobEvent[]) => void;
  setJob: (id: string | null, status?: JobState["jobStatus"]) => void;
  setConnection: (patch: Partial<ConnectionState>) => void;
  setError: (error: string | null) => void;
  setLogRetention: (n: number) => void;
  reset: () => void;
  appendClientLog: (event: string, details: string, origin?: string) => void;
}

function emptyState(retention = 200): JobState {
  return {
    jobId: null,
    jobStatus: "idle",
    overall: null,
    tasks: new Map(),
    logs: [],
    logRetention: retention,
    activeTaskIds: [],
    connection: { mode: "offline", wsAttempt: 0 },
    error: null,
  };
}

/**
 * Single Zustand store for the job view.
 *
 * Render-cost note: tasks live in a ``Map`` that is mutated in place and
 * whose reference is only bumped once per ``applyEvents`` batch. Components
 * subscribe to ``activeTaskIds`` (shallow-equal array) to know which rows
 * to render; each row then subscribes to its own slice
 * ``(state) => state.tasks.get(id)`` so only the changed row re-renders.
 * Compared to the pre-PR3 ``setTasks(prev => ({...prev, [id]: x}))`` path
 * this should cut commit count by ~10× on a 3-worker, 200-file album.
 */
export const useJobStore = create<JobState & JobActions>((set, get) => ({
  ...emptyState(),

  applyEvents(events) {
    if (!events.length) return;

    set((state) => {
      let tasks = state.tasks;
      let tasksChanged = false;
      const newLogs: LogEntry[] = [];
      let nextOverall = state.overall;
      let nextStatus = state.jobStatus;
      let nextError = state.error;

      for (const ev of events) {
        switch (ev.type) {
          case "task_created": {
            upsertTask(tasks, ev.task);
            tasksChanged = true;
            break;
          }
          case "task_updated": {
            upsertTask(tasks, ev.task);
            tasksChanged = true;
            break;
          }
          case "overall": {
            nextOverall = {
              description: ev.description,
              total: Number.isFinite(ev.total) ? ev.total : 0,
              completed: Number.isFinite(ev.completed) ? ev.completed : 0,
            };
            break;
          }
          case "status": {
            nextStatus = ev.status;
            if (ev.status === "failed" && ev.message) nextError = ev.message;
            else if (ev.status === "cancelled") nextError = ev.message ?? "Download cancelled.";
            else if (ev.status === "completed") nextError = null;
            break;
          }
          case "log": {
            newLogs.push({
              event_id: ev.event_id,
              event: ev.event,
              details: ev.details,
              timestamp: ev.ts,
              origin: "server",
            });
            break;
          }
          case "maintenance_detected": {
            newLogs.push({
              event_id: ev.event_id,
              event: ev.event ?? "Maintenance",
              details: ev.details ?? "",
              timestamp: ev.ts,
              origin: "maintenance",
            });
            break;
          }
          default:
            break;
        }
      }

      // Bump the tasks Map reference once per batch — components that
      // subscribe to the reference (TaskList) then re-render at most once
      // per flush even if 50 events arrive at once.
      if (tasksChanged) tasks = new Map(tasks);

      const logs = newLogs.length
        ? [...state.logs, ...newLogs].slice(-state.logRetention)
        : state.logs;

      const activeTaskIds = tasksChanged ? computeActiveTaskIds(tasks) : state.activeTaskIds;

      return {
        ...state,
        tasks,
        activeTaskIds,
        logs,
        overall: nextOverall,
        jobStatus: nextStatus,
        error: nextError,
      };
    });
  },

  setJob(id, status) {
    set((s) => ({ ...s, jobId: id, jobStatus: status ?? (id ? "pending" : "idle") }));
  },

  setConnection(patch) {
    set((s) => ({ ...s, connection: { ...s.connection, ...patch } }));
  },

  setError(error) {
    set((s) => ({ ...s, error }));
  },

  setLogRetention(n) {
    const clamped = Math.max(100, Math.min(1000, n | 0));
    set((s) => ({ ...s, logRetention: clamped, logs: s.logs.slice(-clamped) }));
  },

  reset() {
    set((s) => ({ ...emptyState(s.logRetention) }));
  },

  appendClientLog(event, details, origin = "client") {
    set((s) => {
      const entry: LogEntry = {
        event_id: -1 - s.logs.length,
        event,
        details,
        timestamp: new Date().toISOString(),
        origin,
      };
      return { ...s, logs: [...s.logs, entry].slice(-s.logRetention) };
    });
  },
}));

function upsertTask(tasks: Map<number, TaskRow>, payload: TaskPayload): void {
  tasks.set(payload.id, {
    id: payload.id,
    label: payload.label,
    completed: clampPercent(payload.completed),
    visible: payload.visible !== false,
  });
}

function computeActiveTaskIds(tasks: Map<number, TaskRow>): number[] {
  const out: number[] = [];
  for (const [id, row] of tasks) if (row.visible && row.completed < 100) out.push(id);
  out.sort((a, b) => a - b);
  return out;
}

function clampPercent(value: number | null | undefined): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

/* ---------------------------------------------------------------------- *
 * Selector helpers — encapsulate the shallow-equal wiring so components  *
 * don't repeat the pattern.                                              *
 * ---------------------------------------------------------------------- */

export const useActiveTaskIds = () =>
  useJobStore(useShallow((s) => s.activeTaskIds));

export const useTaskRow = (id: number) =>
  useJobStore((s) => s.tasks.get(id));

export const useOverall = () => useJobStore((s) => s.overall);
export const useJobStatus = () => useJobStore((s) => s.jobStatus);
export const useConnection = () => useJobStore((s) => s.connection);
export const useLogs = () => useJobStore((s) => s.logs);
export const useJobError = () => useJobStore((s) => s.error);
export const useJobId = () => useJobStore((s) => s.jobId);
