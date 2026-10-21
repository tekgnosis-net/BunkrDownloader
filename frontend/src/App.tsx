import { useEffect, useState } from "react";
import {
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  useToast,
} from "@chakra-ui/react";
import { AppShell } from "./components/shell/AppShell";
import { TopBar } from "./components/shell/TopBar";
import { DownloadForm } from "./components/download/DownloadForm";
import { OverallProgressCard } from "./components/download/OverallProgressCard";
import { TaskList } from "./components/download/TaskList";
import { LogPane } from "./components/logs/LogPane";
import { SettingsPanel } from "./components/settings/SettingsPanel";
import { usePersistentState } from "./hooks/usePersistentState";
import { useActiveJob } from "./hooks/useActiveJob";
import { api } from "./lib/api";
import { useJobId, useJobStore } from "./lib/store";

interface AppSettings {
  logLevel: "debug" | "info" | "warning" | "error";
  maxWorkers: number;
  statusPage: string;
  apiEndpoint: string;
  downloadReferer: string;
  fallbackDomain: string;
  userAgent: string;
  segments: number;
  segmentMinSizeMb: number;
  maxConnections: number;
  partialMaxAgeHours: number;
}

const DEFAULT_SETTINGS: AppSettings = {
  logLevel: "info",
  maxWorkers: 3,
  statusPage: "https://status.bunkr.ru/",
  apiEndpoint: "https://bunkr.cr/api/vs",
  downloadReferer: "https://get.bunkrr.su/",
  fallbackDomain: "bunkr.cr",
  userAgent:
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0",
  segments: 4,
  segmentMinSizeMb: 32,
  maxConnections: 12,
  partialMaxAgeHours: 168,
};

const SEEDED_KEY = "bunkrdownloader:transfer-seeded-v1";

interface ServerDefaults {
  download?: {
    max_workers?: number;
    segments?: number;
    segment_min_size_mb?: number;
    max_connections?: number;
    partial_max_age_hours?: number;
    link_refresh_max?: number;
    manifest_reset_max?: number;
  };
}

/** Operator-set caps shown read-only in the Transfer card. */
export interface ServerCaps {
  linkRefreshMax?: number;
  manifestResetMax?: number;
}

interface UpdateInfo {
  latestVersion: string | null;
  updateAvailable: boolean;
}

/** Shape of one entry from ``GET /api/downloads`` (server ``JobInfo``). */
interface RunningJob {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  created_at: string;
  urls: string[];
  error: string | null;
}

// The backend caches the GitHub release for 6h, so re-polling more often just
// returns the same cached verdict; this keeps a long-lived dashboard current
// without needless round-trips.
const UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;

/**
 * Top-level composition — thin shell that wires the store, the active-job
 * connection, and the Chakra Tabs that switch between Download and
 * Settings. All the heavy lifting happens inside the extracted components.
 */
export default function App() {
  const [storedSettings, setSettings] = usePersistentState(
    "bunkrdownloader:settings",
    DEFAULT_SETTINGS,
  );
  // Settings saved by an older build lack the Transfer fields; fill them in.
  const settings: AppSettings = { ...DEFAULT_SETTINGS, ...storedSettings };
  const [serverCaps, setServerCaps] = useState<ServerCaps>({});
  const [appVersion, setAppVersion] = useState("dev");
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo>({
    latestVersion: null,
    updateAvailable: false,
  });
  const [isStopping, setIsStopping] = useState(false);
  const toast = useToast();
  const job = useActiveJob();
  const jobId = useJobId();

  useEffect(() => {
    void api.get("/meta").then(({ data }) => {
      if (data?.version) setAppVersion(String(data.version));
    }).catch(() => void 0);
  }, []);

  // Seed the Transfer group from the server once per browser so env-set
  // defaults show up in the UI; a user's saved values are never overwritten.
  useEffect(() => {
    let seeded = false;
    try {
      seeded = window.localStorage.getItem(SEEDED_KEY) === "1";
    } catch {
      /* ignore */
    }
    void api
      .get<ServerDefaults>("/settings/defaults")
      .then(({ data }) => {
        const d = data?.download;
        if (!d) return;
        setServerCaps({
          linkRefreshMax: d.link_refresh_max,
          manifestResetMax: d.manifest_reset_max,
        });
        // Operator-only value: always mirror the server for display.
        if (seeded) {
          if (d.partial_max_age_hours !== undefined) {
            setSettings((prev) => ({ ...prev, partialMaxAgeHours: d.partial_max_age_hours as number }));
          }
          return;
        }
        setSettings((prev) => ({
          ...prev,
          segments: d.segments ?? prev.segments,
          segmentMinSizeMb: d.segment_min_size_mb ?? prev.segmentMinSizeMb,
          maxConnections: d.max_connections ?? prev.maxConnections,
          partialMaxAgeHours: d.partial_max_age_hours ?? prev.partialMaxAgeHours,
        }));
        try {
          window.localStorage.setItem(SEEDED_KEY, "1");
        } catch {
          /* ignore */
        }
      })
      .catch(() => void 0);
    // Run once on mount; setSettings is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const resetTransferDefaults = async () => {
    try {
      const { data } = await api.get<ServerDefaults>("/settings/defaults");
      const d = data?.download;
      if (!d) return;
      setServerCaps({
        linkRefreshMax: d.link_refresh_max,
        manifestResetMax: d.manifest_reset_max,
      });
      setSettings((prev) => ({
        ...prev,
        segments: d.segments ?? prev.segments,
        segmentMinSizeMb: d.segment_min_size_mb ?? prev.segmentMinSizeMb,
        maxConnections: d.max_connections ?? prev.maxConnections,
        partialMaxAgeHours: d.partial_max_age_hours ?? prev.partialMaxAgeHours,
      }));
      toast({ title: "Transfer settings reset to server defaults", status: "info" });
    } catch {
      toast({ title: "Could not load server defaults", status: "error" });
    }
  };

  // Re-attach to a job that is still running server-side. Jobs are server
  // tasks and keep going when the tab closes; the page just forgets which
  // one it was watching. On load, pick the newest pending/running job and
  // make it active — the connection layer then replays its history from
  // event id 0 and continues live.
  useEffect(() => {
    if (useJobStore.getState().jobId) return;
    void api
      .get<RunningJob[]>("/downloads")
      .then(({ data }) => {
        const active = (data ?? [])
          .filter((j) => j.status === "running" || j.status === "pending")
          .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
        if (!active || useJobStore.getState().jobId) return;
        useJobStore.getState().setJob(active.job_id, active.status);
        toast({
          title: "Re-attached to running download",
          description: active.urls[0],
          status: "info",
          duration: 5000,
          isClosable: true,
        });
      })
      .catch(() => void 0);
    // toast is stable per Chakra's docs; run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const check = () => {
      void api.get("/update-check").then(({ data }) => {
        setUpdateInfo({
          latestVersion: data?.latest_version ?? null,
          updateAvailable: Boolean(data?.update_available),
        });
      }).catch(() => void 0);
    };
    check();
    const id = window.setInterval(check, UPDATE_CHECK_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  const handleStop = async () => {
    if (!jobId || isStopping) return;
    setIsStopping(true);
    try {
      await api.post(`/downloads/${jobId}/cancel`);
      toast({ title: "Cancellation requested", status: "info" });
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })
        .response?.data?.detail ?? (err as Error).message;
      toast({ title: "Failed to cancel", description: msg, status: "error" });
    } finally {
      setIsStopping(false);
    }
  };

  return (
    <AppShell>
      <TopBar
        appVersion={appVersion}
        latestVersion={updateInfo.latestVersion}
        updateAvailable={updateInfo.updateAvailable}
        isStopping={isStopping}
        onStop={handleStop}
        onRefresh={job.refresh}
      />

      <Tabs variant="soft-rounded" colorScheme="blue">
        <TabList>
          <Tab>Download</Tab>
          <Tab>Settings</Tab>
        </TabList>
        <TabPanels>
          <TabPanel px={0}>
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
              <DownloadForm
                settings={settings}
                onJobStarted={(id) => useJobStore.getState().setJob(id, "pending")}
              />
              <OverallProgressCard />
              <TaskList />
              <LogPane />
            </div>
          </TabPanel>
          <TabPanel px={0}>
            <SettingsPanel
              settings={settings}
              serverCaps={serverCaps}
              onResetTransfer={resetTransferDefaults}
              onChange={(patch) => setSettings((prev) => ({ ...prev, ...patch }))}
            />
          </TabPanel>
        </TabPanels>
      </Tabs>
    </AppShell>
  );
}
