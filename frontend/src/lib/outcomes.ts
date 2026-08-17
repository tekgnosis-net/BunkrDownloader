import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

/** A URL that has been through the downloader, with the verdict it earned. */
export interface UrlOutcome {
  url: string;
  /** Failure reason as reported by the server; absent for successes. */
  error?: string;
  /** ISO-8601 timestamp of when the client recorded this outcome. */
  ts: string;
}

export type OutcomeList = "succeeded" | "failed";

interface OutcomeState {
  succeeded: UrlOutcome[];
  failed: UrlOutcome[];
}

interface OutcomeActions {
  /** File a URL under one list, removing any earlier verdict for it. */
  record: (url: string, status: OutcomeList, error?: string | null) => void;
  /** Drop every entry from one list. */
  clear: (list: OutcomeList) => void;
  /** Drop specific URLs from one list — used when failures are requeued. */
  remove: (list: OutcomeList, urls: string[]) => void;
}

const withoutUrls = (entries: UrlOutcome[], urls: Set<string>): UrlOutcome[] =>
  entries.filter((entry) => !urls.has(entry.url));

/**
 * Succeeded/failed URL ledger, persisted to ``localStorage``.
 *
 * Deliberately outlives any single job: the point is that after a browser
 * restart the operator can still see what a long batch already got through,
 * and requeue only what didn't. It is cleared explicitly by the user, never
 * implicitly by starting a new download.
 *
 * A URL only ever appears in one list — recording it drops any prior verdict
 * first, so retrying a failure moves the entry across instead of leaving a
 * stale duplicate behind.
 */
export const useOutcomeStore = create<OutcomeState & OutcomeActions>()(
  persist(
    (set) => ({
      succeeded: [],
      failed: [],

      record(url, status, error) {
        set((state) => {
          const key = new Set([url]);
          const entry: UrlOutcome = {
            url,
            ...(status === "failed" && error ? { error } : {}),
            ts: new Date().toISOString(),
          };
          return {
            succeeded:
              status === "succeeded"
                ? [...withoutUrls(state.succeeded, key), entry]
                : withoutUrls(state.succeeded, key),
            failed:
              status === "failed"
                ? [...withoutUrls(state.failed, key), entry]
                : withoutUrls(state.failed, key),
          };
        });
      },

      clear(list) {
        set(() => ({ [list]: [] }) as Pick<OutcomeState, OutcomeList>);
      },

      remove(list, urls) {
        const dropping = new Set(urls);
        set((state) => ({
          [list]: withoutUrls(state[list], dropping),
        }) as Pick<OutcomeState, OutcomeList>);
      },
    }),
    {
      name: "bunkrdownloader:outcomes",
      storage: createJSONStorage(() => localStorage),
      // Persist data only — rehydrating actions would clobber them.
      partialize: (state) => ({ succeeded: state.succeeded, failed: state.failed }),
    },
  ),
);

export const useSucceededUrls = () => useOutcomeStore((s) => s.succeeded);
export const useFailedUrls = () => useOutcomeStore((s) => s.failed);
