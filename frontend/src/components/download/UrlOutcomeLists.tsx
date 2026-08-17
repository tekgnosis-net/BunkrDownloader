import { Badge, Button, Tooltip, useToast } from "@chakra-ui/react";
import { FiCheckCircle, FiCopy, FiRotateCcw, FiTrash2, FiXCircle } from "react-icons/fi";
import { Surface } from "../primitives/Surface";
import {
  useFailedUrls,
  useOutcomeStore,
  useSucceededUrls,
  type OutcomeList,
  type UrlOutcome,
} from "../../lib/outcomes";

interface UrlOutcomeListsProps {
  /** Push URLs back into the input textarea for another attempt. */
  onRequeue: (urls: string[]) => void;
}

const listStyle: React.CSSProperties = {
  margin: 0,
  padding: 0,
  listStyle: "none",
  display: "flex",
  flexDirection: "column",
  gap: "var(--space-1)",
  maxHeight: 220,
  overflowY: "auto",
};

const urlStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono, monospace)",
  fontSize: 13,
  wordBreak: "break-all",
  color: "var(--ink)",
};

/**
 * The succeeded/failed ledger for processed URLs.
 *
 * Always rendered, even when both lists are empty: hiding it until the first
 * URL settled made the panel impossible to find, since a fresh dashboard
 * looked exactly like one without the feature. The empty state is cheap and
 * tells the operator where results will land.
 *
 * Both lists survive reloads and accumulate across jobs (see
 * :mod:`lib/outcomes`) — clearing them is always an explicit action.
 */
export function UrlOutcomeLists({ onRequeue }: UrlOutcomeListsProps) {
  const succeeded = useSucceededUrls();
  const failed = useFailedUrls();
  const toast = useToast();

  const copy = (entries: UrlOutcome[], label: string) => {
    const text = entries.map((e) => e.url).join("\n");
    navigator.clipboard.writeText(text).then(
      () => toast({ title: `Copied ${entries.length} ${label} URLs`, status: "success" }),
      () => toast({ title: "Could not copy to clipboard", status: "error" }),
    );
  };

  const requeueFailed = () => {
    const urls = failed.map((e) => e.url);
    onRequeue(urls);
    useOutcomeStore.getState().remove("failed", urls);
    toast({ title: `Requeued ${urls.length} URLs`, status: "info" });
  };

  return (
    <Surface variant="card" as="section">
      <div
        style={{
          display: "grid",
          gap: "var(--space-5)",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
        }}
      >
        <OutcomeSection
          title="Succeeded"
          list="succeeded"
          entries={succeeded}
          colorScheme="green"
          icon={<FiCheckCircle aria-hidden />}
          onCopy={() => copy(succeeded, "succeeded")}
        />
        <OutcomeSection
          title="Failed"
          list="failed"
          entries={failed}
          colorScheme="red"
          icon={<FiXCircle aria-hidden />}
          onCopy={() => copy(failed, "failed")}
          extraAction={
            failed.length ? (
              <Tooltip label="Put these URLs back in the input box" hasArrow>
                <Button size="xs" leftIcon={<FiRotateCcw />} onClick={requeueFailed}>
                  Requeue
                </Button>
              </Tooltip>
            ) : null
          }
        />
      </div>
    </Surface>
  );
}

interface OutcomeSectionProps {
  title: string;
  list: OutcomeList;
  entries: UrlOutcome[];
  colorScheme: string;
  icon: React.ReactNode;
  onCopy: () => void;
  extraAction?: React.ReactNode;
}

function OutcomeSection({
  title,
  list,
  entries,
  colorScheme,
  icon,
  onCopy,
  extraAction,
}: OutcomeSectionProps) {
  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-2)",
          marginBottom: "var(--space-3)",
        }}
      >
        <span style={{ display: "flex", color: `var(--${colorScheme}-fg, currentColor)` }}>
          {icon}
        </span>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: "var(--ink)" }}>{title}</h3>
        <Badge colorScheme={colorScheme}>{entries.length}</Badge>
        <div style={{ marginLeft: "auto", display: "flex", gap: "var(--space-2)" }}>
          {extraAction}
          <Tooltip label={`Copy ${title.toLowerCase()} URLs`} hasArrow>
            <Button
              size="xs"
              leftIcon={<FiCopy />}
              onClick={onCopy}
              isDisabled={!entries.length}
            >
              Copy
            </Button>
          </Tooltip>
          <Tooltip label={`Clear the ${title.toLowerCase()} list`} hasArrow>
            <Button
              size="xs"
              variant="ghost"
              leftIcon={<FiTrash2 />}
              onClick={() => useOutcomeStore.getState().clear(list)}
              isDisabled={!entries.length}
            >
              Clear
            </Button>
          </Tooltip>
        </div>
      </div>

      {entries.length ? (
        <ul style={listStyle} role="list">
          {entries.map((entry) => (
            <li key={entry.url}>
              <div style={urlStyle}>{entry.url}</div>
              {entry.error ? (
                <div style={{ fontSize: 12, color: "var(--ink-muted, #999)" }}>{entry.error}</div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p style={{ margin: 0, fontSize: 13, color: "var(--ink-muted, #999)" }}>
          Nothing here yet.
        </p>
      )}
    </div>
  );
}
