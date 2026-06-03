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
};

interface UpdateInfo {
  latestVersion: string | null;
  updateAvailable: boolean;
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
  const [settings, setSettings] = usePersistentState(
    "bunkrdownloader:settings",
    DEFAULT_SETTINGS,
  );
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
              onChange={(patch) => setSettings((prev) => ({ ...prev, ...patch }))}
            />
          </TabPanel>
        </TabPanels>
      </Tabs>
    </AppShell>
  );
}
