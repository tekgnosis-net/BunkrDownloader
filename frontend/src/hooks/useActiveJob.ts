import { useEffect, useMemo } from "react";
import { JobConnection } from "../lib/connection";
import { useJobStore } from "../lib/store";

/**
 * Owns the singleton :class:`JobConnection` and drives its lifecycle from
 * the current ``jobId`` in the store. Consumers get ``start`` / ``stop`` /
 * ``refresh`` closures plus the reactive connection snapshot.
 */
export function useActiveJob() {
  const conn = useMemo(() => new JobConnection(), []);
  const jobId = useJobStore((s) => s.jobId);

  useEffect(() => {
    if (jobId) conn.start(jobId);
    else conn.stop();
    return () => conn.stop();
  }, [conn, jobId]);

  return {
    start(id: string) {
      useJobStore.getState().setJob(id, "pending");
    },
    stop() {
      useJobStore.getState().reset();
      conn.stop();
    },
    refresh() {
      conn.refresh();
    },
  };
}
