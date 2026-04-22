import {
  Button,
  FormControl,
  FormLabel,
  IconButton,
  Input,
  SimpleGrid,
  Switch,
  Textarea,
  Tooltip,
  useDisclosure,
  useToast,
} from "@chakra-ui/react";
import { FiFolder, FiRefreshCw } from "react-icons/fi";
import { useEffect, useState } from "react";
import { Surface } from "../primitives/Surface";
import { DirectoryPickerDialog } from "./DirectoryPickerDialog";
import { api } from "../../lib/api";
import { parseList, parseUrls, optionalTrimmed } from "../../lib/util";
import { usePersistentState } from "../../hooks/usePersistentState";
import { useJobStore } from "../../lib/store";

interface Settings {
  logLevel: "debug" | "info" | "warning" | "error";
  maxWorkers: number;
  statusPage: string;
  apiEndpoint: string;
  downloadReferer: string;
  fallbackDomain: string;
  userAgent: string;
}

interface FormState {
  urls: string;
  include: string;
  ignore: string;
  customPath: string;
  disableDiskCheck: boolean;
}

const EMPTY_FORM: FormState = {
  urls: "",
  include: "",
  ignore: "",
  customPath: "",
  disableDiskCheck: false,
};

interface DownloadFormProps {
  settings: Settings;
  onJobStarted: (jobId: string) => void;
}

/**
 * URLs / include / ignore / custom-path input card + submit button.
 * Persists form state to ``localStorage`` between reloads.
 */
export function DownloadForm({ settings, onJobStarted }: DownloadFormProps) {
  const [form, setForm] = usePersistentState<FormState>("bunkrdownloader:form", EMPTY_FORM);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [directories, setDirectories] = useState({ path: "", entries: [] as string[] });
  const [loadingDirs, setLoadingDirs] = useState(false);
  const picker = useDisclosure();
  const toast = useToast();

  const loadDirs = async (basePath?: string, silent = false) => {
    setLoadingDirs(true);
    try {
      const { data } = await api.get("/directories", {
        params: basePath ? { basePath } : undefined,
      });
      setDirectories({ path: data.path, entries: data.directories ?? [] });
      return data.path as string;
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })
        .response?.data?.detail ?? (err as Error).message;
      if (!silent) {
        toast({ title: "Failed to load directories", description: msg, status: "error" });
      }
      return null;
    } finally {
      setLoadingDirs(false);
    }
  };

  useEffect(() => {
    // Silent on mount: the preview listing is a convenience for the picker.
    // A failure here shouldn't toast on every page load — the user will see
    // the real error if they explicitly click Pick or Refresh.
    void loadDirs(undefined, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openPicker = async () => {
    const resolved = await loadDirs(form.customPath || undefined, !!form.customPath);
    if (resolved !== null) picker.onOpen();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const urls = parseUrls(form.urls);
    if (!urls.length) {
      toast({ title: "Add at least one URL", status: "warning" });
      return;
    }
    setIsSubmitting(true);
    useJobStore.getState().reset();
    try {
      const network = {
        status_page: optionalTrimmed(settings.statusPage),
        api_endpoint: optionalTrimmed(settings.apiEndpoint),
        download_referer: optionalTrimmed(settings.downloadReferer),
        user_agent: optionalTrimmed(settings.userAgent),
        fallback_domain: optionalTrimmed(settings.fallbackDomain),
      };
      const payload = {
        urls,
        include: parseList(form.include),
        ignore: parseList(form.ignore),
        custom_path: form.customPath || null,
        disable_disk_check: form.disableDiskCheck,
        log_level: settings.logLevel,
        max_workers: settings.maxWorkers,
        network,
      };
      const { data } = await api.post("/downloads", payload);
      onJobStarted(data.job_id);
      toast({
        title: "Download started",
        description: `Tracking job ${data.job_id}`,
        status: "success",
      });
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })
        .response?.data?.detail ?? (err as Error).message;
      toast({ title: "Failed to start download", description: msg, status: "error" });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <Surface variant="cardLg" as="section">
        <form onSubmit={handleSubmit}>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
            <FormControl isRequired>
              <FormLabel>Bunkr URLs</FormLabel>
              <Tooltip label="Paste one album or file URL per line" hasArrow placement="top-start">
                <Textarea
                  value={form.urls}
                  onChange={(e) => setForm((p) => ({ ...p, urls: e.target.value }))}
                  placeholder="One URL per line"
                  minH="140px"
                  fontFamily="mono"
                  resize="vertical"
                />
              </Tooltip>
            </FormControl>

            <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={4}>
              <FormControl>
                <FormLabel>Include filters</FormLabel>
                <Textarea
                  value={form.include}
                  onChange={(e) => setForm((p) => ({ ...p, include: e.target.value }))}
                  placeholder="Keywords to include"
                  minH="90px"
                  resize="vertical"
                />
              </FormControl>
              <FormControl>
                <FormLabel>Ignore filters</FormLabel>
                <Textarea
                  value={form.ignore}
                  onChange={(e) => setForm((p) => ({ ...p, ignore: e.target.value }))}
                  placeholder="Keywords to skip"
                  minH="90px"
                  resize="vertical"
                />
              </FormControl>
            </SimpleGrid>

            <FormControl>
              <FormLabel>Custom download directory</FormLabel>
              <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
                <Input
                  value={form.customPath}
                  onChange={(e) => setForm((p) => ({ ...p, customPath: e.target.value }))}
                  placeholder="Defaults to ./Downloads"
                  flex={1}
                />
                <Tooltip label="Pick a directory" hasArrow>
                  <Button leftIcon={<FiFolder />} onClick={openPicker}>
                    Pick
                  </Button>
                </Tooltip>
                <Tooltip label="Refresh the directory list" hasArrow>
                  <IconButton
                    aria-label="Refresh directories"
                    icon={<FiRefreshCw />}
                    onClick={() => void loadDirs(form.customPath || directories.path || undefined)}
                    isLoading={loadingDirs}
                  />
                </Tooltip>
              </div>
            </FormControl>

            <FormControl display="flex" alignItems="center" gap={3}>
              <FormLabel htmlFor="disable-disk-check" mb={0}>
                Skip disk space check
              </FormLabel>
              <Switch
                id="disable-disk-check"
                isChecked={form.disableDiskCheck}
                onChange={(e) => setForm((p) => ({ ...p, disableDiskCheck: e.target.checked }))}
              />
            </FormControl>

            <Button type="submit" colorScheme="blue" isLoading={isSubmitting} alignSelf="flex-start">
              Start download
            </Button>
          </div>
        </form>
      </Surface>

      <DirectoryPickerDialog
        isOpen={picker.isOpen}
        onClose={picker.onClose}
        loading={loadingDirs}
        path={directories.path}
        entries={directories.entries}
        onNavigate={(next) => void loadDirs(next)}
        onSelect={(next) => {
          setForm((p) => ({ ...p, customPath: next }));
          picker.onClose();
        }}
      />
    </>
  );
}
