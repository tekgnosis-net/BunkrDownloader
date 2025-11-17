import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import {
  Badge,
  Box,
  Button,
  Divider,
  Flex,
  FormControl,
  FormLabel,
  Heading,
  HStack,
  IconButton,
  Input,
  Link,
  List,
  ListItem,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Progress,
  Spinner,
  Spacer,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Textarea,
  Tooltip,
  Tabs,
  TabList,
  Tab,
  TabPanels,
  TabPanel,
  Select,
  Slider,
  SliderTrack,
  SliderFilledTrack,
  SliderThumb,
  useDisclosure,
  useColorMode,
  useColorModeValue,
  useToast
} from "@chakra-ui/react";
import { RepeatIcon, MoonIcon, SunIcon } from "@chakra-ui/icons";
import { FaGithub } from "react-icons/fa";
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";
const WS_BASE = import.meta.env.VITE_WS_BASE_URL ?? null;

const api = axios.create({ baseURL: API_BASE });

const parseUrls = (value) =>
  value
    .split(/\r?\n/)
    .map((url) => url.trim())
    .filter(Boolean);

const parseList = (value) =>
  value
    .split(/[,\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);

const deriveWsUrl = (jobId) => {
  if (WS_BASE) {
    return `${WS_BASE.replace(/\/$/, "")}/ws/jobs/${jobId}`;
  }

  const { protocol, host } = window.location;
  const wsProtocol = protocol === "https:" ? "wss" : "ws";
  return `${wsProtocol}://${host}/ws/jobs/${jobId}`;
};

const DEFAULT_LOG_RETENTION = 200;
const FORM_STORAGE_KEY = "bunkrdownloader:form";
const SETTINGS_STORAGE_KEY = "bunkrdownloader:settings";
const DEFAULT_SETTINGS = {
  logLevel: "info",
  logRetention: DEFAULT_LOG_RETENTION,
  maxWorkers: 3,
  autoScrollLogs: true,
  statusPage: "https://status.bunkr.ru/",
  apiEndpoint: "https://bunkr.cr/api/vs",
  downloadReferer: "https://get.bunkrr.su/",
  fallbackDomain: "bunkr.cr",
  userAgent: "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0",
};
const LOG_RETENTION_RANGE = { min: 100, max: 1000, step: 50 };
const MAX_WORKERS_RANGE = { min: 1, max: 8 };

const normalisePath = (path) =>
  path
    .replace(/\\/g, "/")
    .replace(/\/+/g, "/")
    .replace(/\/$/, "") || "/";

const getParentPath = (rawPath) => {
  if (!rawPath) {
    return null;
  }

  const path = normalisePath(rawPath);
  if (path === "/") {
    return null;
  }

  const segments = path.split("/");
  segments.pop();
  if (!segments.length) {
    return "/";
  }

  const parent = segments.join("/");
  return parent.length === 2 && parent[1] === ":" ? `${parent}/` : parent;
};

const clampPercent = (value) => {
  if (value === null || value === undefined) {
    return 0;
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || Number.isNaN(numeric)) {
    return 0;
  }
  return Math.min(100, Math.max(0, numeric));
};

const toFiniteNumber = (value, fallback = 0) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const optionalTrimmed = (value) => {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length ? trimmed : null;
};

function App() {
  const [form, setForm] = useState({
    urls: "",
    include: "",
    ignore: "",
    customPath: "",
    disableDiskCheck: false
  });
  const [directories, setDirectories] = useState({ path: "", entries: [] });
  const [loadingDirectories, setLoadingDirectories] = useState(false);
  const directoryPicker = useDisclosure();
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState("idle");
  const [overall, setOverall] = useState(null);
  const [tasks, setTasks] = useState({});
  const [logs, setLogs] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [jobError, setJobError] = useState(null);
  const [appVersion, setAppVersion] = useState("dev");
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const wsRef = useRef(null);
  const pollRef = useRef(null);
  const reconnectRef = useRef(null);
  const eventIndexRef = useRef(0);
  const jobIdRef = useRef(null);
  const jobStatusRef = useRef("idle");
  const settingsRef = useRef(DEFAULT_SETTINGS);
  const logRetentionRef = useRef(DEFAULT_SETTINGS.logRetention);
  const logsContainerRef = useRef(null);
  const toast = useToast();
  const { colorMode, toggleColorMode } = useColorMode();
  const cardBg = useColorModeValue("white", "gray.800");
  const subtleBg = useColorModeValue("gray.100", "gray.700");
  const borderColor = useColorModeValue("gray.200", "gray.700");
  const mutedText = useColorModeValue("gray.600", "gray.400");
  const badgeBg = useColorModeValue("gray.200", "gray.700");
  const badgeTextColor = useColorModeValue("gray.800", "gray.100");
  const logBg = useColorModeValue("gray.50", "gray.900");

  const pushLogEntry = useCallback((entry) => {
    setLogs((prev) => {
      const next = [...prev, entry];
      return next.slice(-logRetentionRef.current);
    });
  }, []);

  const appendLogEntry = useCallback((event, details, origin = "client") => {
    pushLogEntry({
      type: "log",
      event,
      details,
      timestamp: new Date().toISOString(),
      origin,
    });
  }, [pushLogEntry]);

  const allTasks = useMemo(() => Object.values(tasks), [tasks]);

  const completedTasksCount = useMemo(
    () => allTasks.filter((task) => clampPercent(task.completed) >= 100).length,
    [allTasks]
  );

  const derivedOverall = useMemo(() => {
    if (!allTasks.length && !overall) {
      return null;
    }

    const totalFromTasks = Math.max(allTasks.length, overall?.total ?? 0);
    const total = overall?.total ?? totalFromTasks;
    const completedFromEvents =
      typeof overall?.completed === "number" && overall.completed >= 0
        ? overall.completed
        : null;
    const completed =
      completedFromEvents !== null ? completedFromEvents : completedTasksCount;
    const percent = total ? Math.min(100, (completed / total) * 100) : 0;

    return {
      description: overall?.description ?? "Current job",
      total,
      completed,
      percent,
    };
  }, [allTasks, overall, completedTasksCount]);

  const activeTasks = useMemo(
    () =>
      allTasks
        .filter((task) => task.visible !== false && clampPercent(task.completed) < 100)
        .sort((a, b) => a.id - b.id),
    [allTasks]
  );

  function isJobFinished() {
    return jobStatusRef.current === "completed" || jobStatusRef.current === "failed";
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function clearReconnect() {
    if (reconnectRef.current) {
      clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }
  }

  function processEvents(eventsArray) {
    if (!Array.isArray(eventsArray)) {
      return 0;
    }

    let processed = 0;
    for (const event of eventsArray) {
      handleEvent(event);
      processed += 1;
    }
    return processed;
  }

  function startPolling(id) {
    if (pollRef.current || !id) {
      return;
    }

    const poll = async () => {
      try {
        const { data } = await api.get(`/downloads/${id}/events`, {
          params: { since: eventIndexRef.current }
        });

        if (Array.isArray(data.events) && data.events.length) {
          const processed = processEvents(data.events);
          if (typeof data.next_index === "number") {
            eventIndexRef.current = data.next_index;
          } else {
            eventIndexRef.current += processed;
          }
        }

        if (isJobFinished()) {
          stopPolling();
          clearReconnect();
        }
      } catch (error) {
        if (error.response?.status === 404) {
          stopPolling();
          clearReconnect();
          if (!isJobFinished()) {
            setJobError("Job not found. It may have expired or the server restarted.");
            setJobStatus("failed");
            jobStatusRef.current = "failed";
          }
          return;
        }
        console.error("Polling failed", error);
      }
    };

    poll();
    pollRef.current = setInterval(poll, 2000);
  }

  function scheduleReconnect(id) {
    if (!id || reconnectRef.current || isJobFinished()) {
      return;
    }

    reconnectRef.current = setTimeout(() => {
      reconnectRef.current = null;
      openWebSocket(id, true);
    }, 1500);
  }

  const handleDirectories = async (basePath, { silent = false } = {}) => {
    setLoadingDirectories(true);
    try {
      const response = await api.get("/directories", {
        params: basePath ? { basePath } : undefined
      });
      setDirectories({ path: response.data.path, entries: response.data.directories });
      return response.data.path;
    } catch (error) {
      if (!silent) {
        toast({
          title: "Failed to load directories",
          description: error.response?.data?.detail ?? error.message,
          status: "error",
          duration: 5000,
          isClosable: true
        });
      }
      return null;
    } finally {
      setLoadingDirectories(false);
    }
  };

  const openDirectoryPicker = async () => {
    const target = form.customPath || directories.path || undefined;
    const resolved = await handleDirectories(target, { silent: !!form.customPath });
    if (resolved) {
      directoryPicker.onOpen();
    }
  };

  const fetchMeta = useCallback(async () => {
    try {
      const { data } = await api.get("/meta");
      if (data?.version) {
        setAppVersion(String(data.version));
      }
    } catch (error) {
      console.warn("Failed to load application metadata", error);
    }
  }, []);

  useEffect(() => {
    handleDirectories();
    fetchMeta();
    return () => {
      stopPolling();
      clearReconnect();
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [fetchMeta]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      const stored = window.localStorage.getItem(FORM_STORAGE_KEY);
      if (!stored) {
        return;
      }
      const parsed = JSON.parse(stored);
      if (parsed && typeof parsed === "object") {
        setForm((prev) => ({ ...prev, ...parsed }));
      }
    } catch (error) {
      console.warn("Failed to restore form state", error);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      window.localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form));
    } catch (error) {
      console.warn("Failed to persist form state", error);
    }
  }, [form]);

  useEffect(() => {
    let cancelled = false;

    const loadDefaults = async () => {
      try {
        const { data } = await api.get("/settings/defaults");
        if (!data?.network || cancelled) {
          return;
        }
        const {
          status_page: statusPage,
          api_endpoint: apiEndpoint,
          download_referer: downloadReferer,
          fallback_domain: fallbackDomain,
          user_agent: userAgent,
        } = data.network;

        setSettings((prev) => {
          if (cancelled) {
            return prev;
          }
          return {
            ...prev,
            statusPage:
              prev.statusPage === DEFAULT_SETTINGS.statusPage && statusPage
                ? statusPage
                : prev.statusPage,
            apiEndpoint:
              prev.apiEndpoint === DEFAULT_SETTINGS.apiEndpoint && apiEndpoint
                ? apiEndpoint
                : prev.apiEndpoint,
            downloadReferer:
              prev.downloadReferer === DEFAULT_SETTINGS.downloadReferer && downloadReferer
                ? downloadReferer
                : prev.downloadReferer,
            fallbackDomain:
              prev.fallbackDomain === DEFAULT_SETTINGS.fallbackDomain && fallbackDomain
                ? fallbackDomain
                : prev.fallbackDomain,
            userAgent:
              prev.userAgent === DEFAULT_SETTINGS.userAgent && userAgent
                ? userAgent
                : prev.userAgent,
          };
        });
      } catch (error) {
        console.warn("Failed to fetch default settings", error);
      }
    };

    loadDefaults();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      const stored = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
      if (!stored) {
        return;
      }
      const parsed = JSON.parse(stored);
      if (parsed && typeof parsed === "object") {
        setSettings((prev) => ({ ...prev, ...parsed }));
      }
    } catch (error) {
      console.warn("Failed to restore settings state", error);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
    } catch (error) {
      console.warn("Failed to persist settings state", error);
    }
  }, [settings]);

  useEffect(() => {
    settingsRef.current = settings;
  }, [settings]);

  useEffect(() => {
    logRetentionRef.current = settings.logRetention;
  }, [settings.logRetention]);

  useEffect(() => {
    if (!settings.autoScrollLogs || !logsContainerRef.current) {
      return;
    }
    logsContainerRef.current.scrollTo({
      top: logsContainerRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [logs, settings.autoScrollLogs]);

  const resetJobState = () => {
    stopPolling();
    clearReconnect();
    eventIndexRef.current = 0;
    jobStatusRef.current = "idle";
    jobIdRef.current = null;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setJobId(null);
    setJobStatus("idle");
    setOverall(null);
    setTasks({});
    setLogs([]);
    setJobError(null);
  };

  const handleEvent = (event) => {
    const { logLevel } = settingsRef.current;
    switch (event.type) {
      case "status":
        setJobStatus(event.status);
        jobStatusRef.current = event.status;
        if (event.status === "failed" && event.message) {
          setJobError(event.message);
        } else if (event.status === "completed") {
          setJobError(null);
        }
        if (event.status === "failed" || event.status === "completed") {
          stopPolling();
          clearReconnect();
          eventIndexRef.current = 0;
          jobIdRef.current = null;
          setJobId(null);
          setOverall(null);
          setTasks({});
        }
        if (logLevel === "debug") {
          appendLogEntry(
            "Debug",
            `Job status changed to ${event.status.toUpperCase()}`,
            "status"
          );
        }
        break;
      case "overall":
        setOverall({
          description: event.description,
          completed: toFiniteNumber(event.completed),
          total: toFiniteNumber(event.total)
        });
        if (logLevel === "debug") {
          appendLogEntry(
            "Debug",
            `Overall progress ${event.completed}/${event.total}`,
            "overall"
          );
        }
        break;
      case "task_created":
        if (isJobFinished()) {
          break;
        }
        setTasks((prev) => {
          const normalised = {
            id: event.task.id,
            label: event.task.label,
            completed: clampPercent(event.task.completed),
            visible: event.task.visible !== false,
          };
          return { ...prev, [normalised.id]: normalised };
        });
        if (logLevel === "debug") {
          appendLogEntry(
            "Debug",
            `Task ${event.task.id} created (${event.task.label})`,
            "task"
          );
        }
        break;
      case "task_updated":
        if (isJobFinished()) {
          break;
        }
        setTasks((prev) => {
          const previous = prev[event.task.id] ?? {};
          const normalised = {
            id: event.task.id,
            label: event.task.label ?? previous.label,
            completed: clampPercent(event.task.completed ?? previous.completed ?? 0),
            visible:
              event.task.visible !== undefined
                ? event.task.visible !== false
                : previous.visible ?? true,
          };
          return { ...prev, [normalised.id]: normalised };
        });
        if (logLevel === "debug") {
          appendLogEntry(
            "Debug",
            `Task ${event.task.id} updated to ${clampPercent(event.task.completed ?? 0)}%`,
            "task"
          );
        }
        break;
      case "log":
        pushLogEntry(event);
        break;
      default:
        break;
    }
  };

  const openWebSocket = (nextJobId, isRetry = false) => {
    if (!nextJobId || isJobFinished()) {
      return;
    }

    if (wsRef.current) {
      wsRef.current.close();
    }

    const socket = new WebSocket(deriveWsUrl(nextJobId));
    wsRef.current = socket;

    socket.onopen = () => {
      stopPolling();
      clearReconnect();
    };

    socket.onmessage = (messageEvent) => {
      try {
        const payload = JSON.parse(messageEvent.data);
        const processed = processEvents([payload]);
        eventIndexRef.current += processed;
      } catch (parseError) {
        console.error("Failed to parse event", parseError);
      }
    };

    socket.onclose = () => {
      wsRef.current = null;
      if (!isJobFinished()) {
        startPolling(jobIdRef.current);
        scheduleReconnect(jobIdRef.current);
      }
    };

    socket.onerror = (event) => {
      console.error("WebSocket error", event);
      if (!isRetry) {
        toast({
          title: "WebSocket connection interrupted",
          description: "Real-time updates may be out of sync.",
          status: "warning",
          duration: 4000,
          isClosable: true
        });
      }
    };
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const urls = parseUrls(form.urls);

    if (!urls.length) {
      toast({
        title: "No URLs provided",
        description: "Add at least one URL to start a download.",
        status: "warning",
        duration: 4000,
        isClosable: true
      });
      return;
    }

    setIsSubmitting(true);
    resetJobState();

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
      setJobId(data.job_id);
      jobIdRef.current = data.job_id;
      eventIndexRef.current = 0;
      jobStatusRef.current = "pending";
      stopPolling();
      clearReconnect();
      openWebSocket(data.job_id);
      toast({
        title: "Download started",
        description: `Tracking job ${data.job_id}`,
        status: "success",
        duration: 3000,
        isClosable: true
      });
    } catch (error) {
      const message = error.response?.data?.detail ?? error.message;
      toast({
        title: "Failed to start download",
        description: message,
        status: "error",
        duration: 6000,
        isClosable: true
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Box w="100%" px={{ base: 4, md: 10, xl: 16 }} py={8}>
      <Stack spacing={8} w="100%">
        <Flex align="center" gap={3} wrap="wrap">
          <Tooltip label="Web controls for BunkrDownloader" hasArrow>
            <Heading size="lg">Bunkr Downloader</Heading>
          </Tooltip>
          <Tooltip label="Running image version" hasArrow>
            <Badge variant="subtle" bg={badgeBg} color={badgeTextColor}>
              v{appVersion}
            </Badge>
          </Tooltip>
          <Spacer />
          <HStack spacing={2} align="center">
            <Tooltip label="Current job status" hasArrow>
              <Badge colorScheme={jobStatus === "failed" ? "red" : jobStatus === "completed" ? "green" : "blue"}>
                {jobStatus.toUpperCase()}
              </Badge>
            </Tooltip>
            <Tooltip label={`Switch to ${colorMode === "dark" ? "light" : "dark"} theme`} hasArrow>
              <IconButton
                icon={colorMode === "dark" ? <SunIcon /> : <MoonIcon />}
                aria-label="Toggle color mode"
                onClick={toggleColorMode}
                variant="ghost"
              />
            </Tooltip>
            <Tooltip label="View the GitHub source" hasArrow>
              <IconButton
                as={Link}
                href="https://github.com/tekgnosis-net/BunkrDownloader"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Open GitHub repository"
                icon={<FaGithub />}
                variant="ghost"
              />
            </Tooltip>
          </HStack>
        </Flex>

        <Tabs variant="enclosed" colorScheme="blue">
          <TabList>
            <Tab>Download</Tab>
            <Tab>Settings</Tab>
          </TabList>
          <TabPanels>
            <TabPanel px={0}>
              <Stack spacing={8}>
                <Box
                  as="form"
                  onSubmit={handleSubmit}
                  p={6}
                  bg={cardBg}
                  borderWidth={1}
                  borderColor={borderColor}
                  rounded="md"
                  shadow="md"
                  w="100%"
                >
                  <Stack spacing={6} w="100%">
                    <FormControl isRequired w="100%" display="flex" flexDirection="column">
                      <FormLabel>Bunkr URLs</FormLabel>
                      <Tooltip label="Paste one album or file URL per line" hasArrow placement="top-start" shouldWrapChildren>
                        <Textarea
                          width="100%"
                          minW="100%"
                          flexGrow={1}
                          placeholder="One URL per line"
                          minH="160px"
                          value={form.urls}
                          onChange={(e) => setForm((prev) => ({ ...prev, urls: e.target.value }))}
                          fontFamily="mono"
                          resize="vertical"
                        />
                      </Tooltip>
                    </FormControl>

                    <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={6} w="100%">
                      <FormControl w="100%" display="flex" flexDirection="column">
                        <FormLabel>Include filters</FormLabel>
                        <Tooltip label="Only download files containing these terms" hasArrow placement="top-start" shouldWrapChildren>
                          <Textarea
                            width="100%"
                            minW="100%"
                            placeholder="Keywords to include"
                            value={form.include}
                            onChange={(e) => setForm((prev) => ({ ...prev, include: e.target.value }))}
                            minH="120px"
                            resize="vertical"
                            flexGrow={1}
                          />
                        </Tooltip>
                      </FormControl>
                      <FormControl w="100%" display="flex" flexDirection="column">
                        <FormLabel>Ignore filters</FormLabel>
                        <Tooltip label="Skip files matching any of these terms" hasArrow placement="top-start" shouldWrapChildren>
                          <Textarea
                            width="100%"
                            minW="100%"
                            placeholder="Keywords to skip"
                            value={form.ignore}
                            onChange={(e) => setForm((prev) => ({ ...prev, ignore: e.target.value }))}
                            minH="120px"
                            resize="vertical"
                            flexGrow={1}
                          />
                        </Tooltip>
                      </FormControl>
                    </SimpleGrid>

                    <Stack spacing={3}>
                      <FormControl w="100%">
                        <FormLabel>Custom download directory</FormLabel>
                        <Stack
                          direction={{ base: "column", lg: "row" }}
                          spacing={3}
                          align={{ base: "stretch", lg: "center" }}
                        >
                          <Tooltip label="Override the download root directory" hasArrow placement="top-start" shouldWrapChildren>
                            <Input
                              placeholder="Defaults to ./Downloads"
                              value={form.customPath}
                              onChange={(e) => setForm((prev) => ({ ...prev, customPath: e.target.value }))}
                              flex="1"
                              minW={{ lg: "0" }}
                            />
                          </Tooltip>
                          <Stack direction={{ base: "column", sm: "row" }} spacing={2} w={{ base: "full", lg: "auto" }}>
                            <Tooltip label="Select a directory from the server" hasArrow shouldWrapChildren>
                              <Button w={{ base: "full", sm: "auto" }} onClick={openDirectoryPicker}>
                                Pick directory
                              </Button>
                            </Tooltip>
                            <Tooltip label="Refresh the current directory list" hasArrow>
                              <IconButton
                                icon={<RepeatIcon />}
                                aria-label="Refresh directories"
                                onClick={() => handleDirectories(form.customPath || directories.path || undefined)}
                                isLoading={loadingDirectories}
                                isDisabled={loadingDirectories}
                              />
                            </Tooltip>
                          </Stack>
                        </Stack>
                      </FormControl>
                    </Stack>

                    <Modal isOpen={directoryPicker.isOpen} onClose={directoryPicker.onClose} size="xl" isCentered>
                      <ModalOverlay />
                      <ModalContent bg={cardBg} borderWidth={1} borderColor={borderColor}>
                        <ModalHeader borderBottomWidth="1px" borderColor={borderColor}>
                          Choose download directory
                        </ModalHeader>
                        <ModalCloseButton />
                        <ModalBody px={6} py={4}>
                          <Stack spacing={4}>
                            <Text fontSize="sm" color={mutedText}>
                              Current path: {directories.path || "Loading..."}
                            </Text>
                            {loadingDirectories ? (
                              <Flex justify="center" py={6}>
                                <Spinner />
                              </Flex>
                            ) : (
                              <List spacing={1} maxH="320px" overflowY="auto" fontSize="sm">
                                {directories.entries.map((entry) => (
                                  <ListItem key={entry}>
                                    <Button
                                      variant="ghost"
                                      justifyContent="flex-start"
                                      width="100%"
                                      onClick={() => handleDirectories(entry, { silent: true })}
                                      isDisabled={loadingDirectories}
                                    >
                                      {entry}
                                    </Button>
                                  </ListItem>
                                ))}
                                {!directories.entries.length && (
                                  <ListItem color={mutedText}>No sub-directories found.</ListItem>
                                )}
                              </List>
                            )}
                          </Stack>
                        </ModalBody>
                        <ModalFooter borderTopWidth="1px" borderColor={borderColor}>
                          <HStack w="100%" justify="space-between">
                            <Button
                              variant="ghost"
                              onClick={() => {
                                const parent = getParentPath(directories.path);
                                if (parent) {
                                  handleDirectories(parent, { silent: true });
                                }
                              }}
                              isDisabled={!getParentPath(directories.path) || loadingDirectories}
                            >
                              Up one level
                            </Button>
                            <HStack spacing={3}>
                              <Button variant="ghost" onClick={directoryPicker.onClose}>
                                Cancel
                              </Button>
                              <Button
                                colorScheme="blue"
                                onClick={() => {
                                  if (directories.path) {
                                    setForm((prev) => ({ ...prev, customPath: directories.path }));
                                  }
                                  directoryPicker.onClose();
                                }}
                                isDisabled={!directories.path}
                              >
                                Use this directory
                              </Button>
                            </HStack>
                          </HStack>
                        </ModalFooter>
                      </ModalContent>
                    </Modal>

                    <FormControl display="flex" alignItems="center">
                      <FormLabel htmlFor="disk-check" mb="0">
                        Disable disk space check
                      </FormLabel>
                      <Tooltip label="Skip the free space guard (useful for remote volumes)" hasArrow shouldWrapChildren>
                        <Switch
                          id="disk-check"
                          isChecked={form.disableDiskCheck}
                          onChange={(e) => setForm((prev) => ({ ...prev, disableDiskCheck: e.target.checked }))}
                        />
                      </Tooltip>
                    </FormControl>

                    <Tooltip label="Start a new download job with the provided settings" hasArrow>
                      <Button type="submit" colorScheme="blue" isLoading={isSubmitting || jobStatus === "running"}>
                        Start download
                      </Button>
                    </Tooltip>
                  </Stack>
                </Box>

                <Box p={6} bg={cardBg} borderWidth={1} borderColor={borderColor} rounded="md" shadow="md">
                  <Stack spacing={4}>
                    <Tooltip label="Live overview of the download job" hasArrow>
                      <Heading size="md">Progress</Heading>
                    </Tooltip>
                    {derivedOverall ? (
                      <Stack spacing={2}>
                        <Tooltip label="Album or file identifier being processed" hasArrow>
                          <Text fontWeight="semibold">{derivedOverall.description}</Text>
                        </Tooltip>
                        <Tooltip label="Overall completion across all items" hasArrow shouldWrapChildren>
                          <Progress value={derivedOverall.percent} hasStripe isAnimated />
                        </Tooltip>
                        <Text fontSize="sm" color={mutedText}>
                          {derivedOverall.completed}/{derivedOverall.total} completed
                        </Text>
                      </Stack>
                    ) : (
                      <Text fontSize="sm" color={mutedText}>
                        Start a job to see progress.
                      </Text>
                    )}

                    {!!activeTasks.length && (
                      <Stack spacing={3}>
                        {activeTasks.map((task) => (
                          <Tooltip key={task.id} label="Per-file progress" hasArrow placement="top" shouldWrapChildren>
                            <Box p={3} bg={subtleBg} rounded="md">
                              <Text fontSize="sm" mb={2}>{task.label}</Text>
                              <Progress value={clampPercent(task.completed)} size="sm" />
                            </Box>
                          </Tooltip>
                        ))}
                      </Stack>
                    )}

                    {jobError && (
                      <Text color="red.400" fontWeight="semibold">
                        {jobError}
                      </Text>
                    )}
                  </Stack>
                </Box>

                <Box p={6} bg={cardBg} borderWidth={1} borderColor={borderColor} rounded="md" shadow="md">
                  <Stack spacing={4}>
                    <Tooltip label="Detailed timeline of actions" hasArrow>
                      <Heading size="md">Log</Heading>
                    </Tooltip>
                    <Divider borderColor={borderColor} />
                    <Stack
                      ref={logsContainerRef}
                      spacing={2}
                      maxH="280px"
                      overflowY="auto"
                      fontFamily="mono"
                      fontSize="sm"
                      bg={logBg}
                      p={3}
                      rounded="md"
                      borderWidth={1}
                      borderColor={borderColor}
                    >
                      {logs.map((logEntry) => (
                        <Tooltip
                          key={`${logEntry.timestamp}-${logEntry.event}-${logEntry.details}`}
                          label={new Date(logEntry.timestamp).toLocaleString()}
                          hasArrow
                          placement="top-start"
                          shouldWrapChildren
                        >
                          <Box>
                            <Text color={mutedText}>
                              [{new Date(logEntry.timestamp).toLocaleTimeString()}]
                            </Text>
                            <Text>
                              <Text as="span" fontWeight="semibold">{logEntry.event}:</Text> {logEntry.details}
                            </Text>
                          </Box>
                        </Tooltip>
                      ))}
                      {!logs.length && <Text color={mutedText}>Logs will appear here.</Text>}
                    </Stack>
                  </Stack>
                </Box>
              </Stack>
            </TabPanel>

            <TabPanel px={0}>
              <Stack spacing={6}>
                <Box bg={cardBg} borderWidth={1} borderColor={borderColor} rounded="md" shadow="md" p={6}>
                  <Stack spacing={4}>
                    <Heading size="md">Logging</Heading>
                    <Text fontSize="sm" color={mutedText}>
                      Tune log verbosity and retention to capture the details you need when reporting issues.
                    </Text>
                    <FormControl>
                      <FormLabel>Log level</FormLabel>
                      <Select
                        value={settings.logLevel}
                        onChange={(e) => setSettings((prev) => ({ ...prev, logLevel: e.target.value }))}
                      >
                        <option value="debug">Debug</option>
                        <option value="info">Info</option>
                        <option value="warning">Warning</option>
                        <option value="error">Error</option>
                      </Select>
                    </FormControl>
                    <FormControl>
                      <FormLabel>Log retention ({settings.logRetention} entries)</FormLabel>
                      <Slider
                        aria-label="log-retention"
                        value={settings.logRetention}
                        min={LOG_RETENTION_RANGE.min}
                        max={LOG_RETENTION_RANGE.max}
                        step={LOG_RETENTION_RANGE.step}
                        onChange={(value) =>
                          setSettings((prev) => ({ ...prev, logRetention: Math.round(value) }))
                        }
                      >
                        <SliderTrack>
                          <SliderFilledTrack />
                        </SliderTrack>
                        <SliderThumb boxSize={4} />
                      </Slider>
                    </FormControl>
                    <FormControl display="flex" alignItems="center">
                      <FormLabel htmlFor="auto-scroll" mb="0">
                        Auto-scroll logs
                      </FormLabel>
                      <Switch
                        id="auto-scroll"
                        isChecked={settings.autoScrollLogs}
                        onChange={(e) => setSettings((prev) => ({ ...prev, autoScrollLogs: e.target.checked }))}
                      />
                    </FormControl>
                  </Stack>
                </Box>

                <Box bg={cardBg} borderWidth={1} borderColor={borderColor} rounded="md" shadow="md" p={6}>
                  <Stack spacing={4}>
                    <Heading size="md">Downloads</Heading>
                    <Text fontSize="sm" color={mutedText}>
                      Control how many files are fetched at once when downloading large albums.
                    </Text>
                    <FormControl>
                      <FormLabel>Concurrent downloads ({settings.maxWorkers})</FormLabel>
                      <Slider
                        aria-label="max-workers"
                        value={settings.maxWorkers}
                        min={MAX_WORKERS_RANGE.min}
                        max={MAX_WORKERS_RANGE.max}
                        step={1}
                        onChange={(value) =>
                          setSettings((prev) => ({ ...prev, maxWorkers: Math.round(value) }))
                        }
                      >
                        <SliderTrack>
                          <SliderFilledTrack />
                        </SliderTrack>
                        <SliderThumb boxSize={4} />
                      </Slider>
                    </FormControl>
                  </Stack>
                </Box>

                <Box bg={cardBg} borderWidth={1} borderColor={borderColor} rounded="md" shadow="md" p={6}>
                  <Stack spacing={4}>
                    <Heading size="md">Network</Heading>
                    <Text fontSize="sm" color={mutedText}>
                      Update the Bunkr endpoints and headers used when fetching albums. Leave fields untouched to keep the server defaults.
                    </Text>
                    <FormControl>
                      <FormLabel>Status page URL</FormLabel>
                      <Tooltip label="Used to detect available download servers" hasArrow shouldWrapChildren>
                        <Input
                          value={settings.statusPage}
                          onChange={(e) => setSettings((prev) => ({ ...prev, statusPage: e.target.value }))}
                          placeholder="https://status.bunkr.ru/"
                        />
                      </Tooltip>
                    </FormControl>
                    <FormControl>
                      <FormLabel>API endpoint</FormLabel>
                      <Tooltip label="Endpoint queried to resolve media URLs" hasArrow shouldWrapChildren>
                        <Input
                          value={settings.apiEndpoint}
                          onChange={(e) => setSettings((prev) => ({ ...prev, apiEndpoint: e.target.value }))}
                          placeholder="https://bunkr.cr/api/vs"
                        />
                      </Tooltip>
                    </FormControl>
                    <FormControl>
                      <FormLabel>Download referer</FormLabel>
                      <Tooltip label="Referer header sent with file downloads" hasArrow shouldWrapChildren>
                        <Input
                          value={settings.downloadReferer}
                          onChange={(e) => setSettings((prev) => ({ ...prev, downloadReferer: e.target.value }))}
                          placeholder="https://get.bunkrr.su/"
                        />
                      </Tooltip>
                    </FormControl>
                    <FormControl>
                      <FormLabel>Fallback domain</FormLabel>
                      <Tooltip label="Domain used when retrying requests after 403 responses" hasArrow shouldWrapChildren>
                        <Input
                          value={settings.fallbackDomain}
                          onChange={(e) => setSettings((prev) => ({ ...prev, fallbackDomain: e.target.value }))}
                          placeholder="bunkr.cr"
                        />
                      </Tooltip>
                    </FormControl>
                    <FormControl>
                      <FormLabel>User agent</FormLabel>
                      <Tooltip label="Override the browser fingerprint sent with HTTP requests" hasArrow shouldWrapChildren>
                        <Textarea
                          value={settings.userAgent}
                          onChange={(e) => setSettings((prev) => ({ ...prev, userAgent: e.target.value }))}
                          minH="96px"
                        />
                      </Tooltip>
                    </FormControl>
                  </Stack>
                </Box>
              </Stack>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </Stack>
    </Box>
  );
}

export default App;
