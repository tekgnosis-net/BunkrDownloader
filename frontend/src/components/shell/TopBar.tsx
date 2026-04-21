import { Button, IconButton, Link, Tooltip, useColorMode } from "@chakra-ui/react";
import { FiGithub, FiMoon, FiRefreshCw, FiSun, FiX } from "react-icons/fi";
import { StatusPill } from "../primitives/StatusPill";
import { ConnectionIndicator } from "./ConnectionIndicator";
import { useJobStatus, useJobId } from "../../lib/store";

interface TopBarProps {
  appVersion: string;
  isStopping: boolean;
  onStop: () => void;
  onRefresh: () => void;
}

/**
 * Title, version badge, status pill, connection indicator, and the
 * stop/refresh/theme/GitHub actions. Intentionally stays at this level
 * rather than pulling job state into the shell so the rest of the tree
 * can render without waiting for the connection to open.
 */
export function TopBar({ appVersion, isStopping, onStop, onRefresh }: TopBarProps) {
  const { colorMode, toggleColorMode } = useColorMode();
  const jobStatus = useJobStatus();
  const jobId = useJobId();
  const hasJob = jobId !== null;
  const canStop = hasJob && !["completed", "failed", "cancelled"].includes(jobStatus);

  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--space-3)",
        flexWrap: "wrap",
      }}
    >
      <h1
        style={{
          fontSize: 28,
          fontWeight: 700,
          letterSpacing: "-0.015em",
          margin: 0,
          color: "var(--ink)",
        }}
      >
        Bunkr Downloader
      </h1>
      <span
        style={{
          fontSize: 12,
          padding: "2px 10px",
          borderRadius: "var(--radius-pill)",
          background: "color-mix(in oklch, var(--ink) 8%, var(--surface-base))",
          color: "var(--ink-muted)",
          border: "1px solid var(--surface-border)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        v{appVersion}
      </span>
      <ConnectionIndicator />

      <div style={{ flex: 1 }} />

      <StatusPill status={jobStatus} />

      <Tooltip label="Stop the current download" hasArrow>
        <Button
          size="sm"
          leftIcon={<FiX />}
          onClick={onStop}
          colorScheme="red"
          variant="solid"
          isDisabled={!canStop || isStopping}
          isLoading={isStopping}
        >
          Stop
        </Button>
      </Tooltip>

      <Tooltip label="Re-establish the live progress stream" hasArrow>
        <Button
          size="sm"
          leftIcon={<FiRefreshCw />}
          onClick={onRefresh}
          variant="outline"
          isDisabled={!hasJob}
        >
          Refresh
        </Button>
      </Tooltip>

      <Tooltip label={`Switch to ${colorMode === "dark" ? "light" : "dark"} theme`} hasArrow>
        <IconButton
          aria-label="Toggle colour mode"
          icon={colorMode === "dark" ? <FiSun /> : <FiMoon />}
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
          icon={<FiGithub />}
          variant="ghost"
        />
      </Tooltip>
    </header>
  );
}
