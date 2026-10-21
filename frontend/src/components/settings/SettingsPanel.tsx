import {
  Button,
  FormControl,
  FormLabel,
  Input,
  NumberInput,
  NumberInputField,
  NumberInputStepper,
  NumberIncrementStepper,
  NumberDecrementStepper,
  Select,
  SimpleGrid,
  Tooltip,
} from "@chakra-ui/react";
import { Surface } from "../primitives/Surface";

interface Settings {
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

interface SettingsPanelProps {
  settings: Settings;
  onChange: (patch: Partial<Settings>) => void;
  serverCaps: { linkRefreshMax?: number; manifestResetMax?: number };
  onResetTransfer: () => void;
}

/**
 * Settings tab body — logging verbosity, concurrency cap, and the
 * NetworkContext overrides that PR1 introduced.
 */
export function SettingsPanel({ settings, onChange, serverCaps, onResetTransfer }: SettingsPanelProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      <Surface variant="card">
        <h2 style={{ margin: 0, marginBottom: "var(--space-3)", fontSize: 17, fontWeight: 600 }}>
          Runtime
        </h2>
        <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
          <FormControl>
            <FormLabel>Log verbosity</FormLabel>
            <Select
              value={settings.logLevel}
              onChange={(e) => onChange({ logLevel: e.target.value as Settings["logLevel"] })}
            >
              <option value="debug">debug</option>
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="error">error</option>
            </Select>
          </FormControl>
          <FormControl>
            <FormLabel>Max concurrent workers</FormLabel>
            <NumberInput
              min={1}
              max={8}
              value={settings.maxWorkers}
              onChange={(_, n) => onChange({ maxWorkers: Number.isFinite(n) ? n : 3 })}
            >
              <NumberInputField />
              <NumberInputStepper>
                <NumberIncrementStepper />
                <NumberDecrementStepper />
              </NumberInputStepper>
            </NumberInput>
          </FormControl>
        </SimpleGrid>
      </Surface>

      <Surface variant="card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-3)" }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Transfer</h2>
          <Button size="sm" variant="ghost" onClick={onResetTransfer}>Reset to server defaults</Button>
        </div>
        <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
          <NumberSetting label="Parallel segments per file" tip="1–16. Large files are fetched as this many byte ranges at once; 1 = single stream (still resumable)."
            value={settings.segments} min={1} max={16} fallback={4}
            onChange={(n) => onChange({ segments: n })} />
          <NumberSetting label="Minimum file size to segment (MB)" tip="1–4096. Smaller files use one stream; also the smallest size a single segment may have."
            value={settings.segmentMinSizeMb} min={1} max={4096} fallback={32}
            onChange={(n) => onChange({ segmentMinSizeMb: n })} />
          <NumberSetting label="Max simultaneous connections" tip="1–64. Cap across all workers and segments. The server enforces its own ceiling (MAX_CONCURRENT_CONNECTIONS); values above it are lowered to the ceiling."
            value={settings.maxConnections} min={1} max={64} fallback={12}
            onChange={(n) => onChange({ maxConnections: n })} />
          <ReadOnlyValue label="Delete abandoned partials after (hours)"
            tip="Set by the server (PARTIAL_MAX_AGE_HOURS env or --partial-max-age-hours). Not adjustable per job."
            value={settings.partialMaxAgeHours} testId="partial-max-age" />
          <ReadOnlyValue label="Signed-URL refreshes per file"
            tip="Set by the server (LINK_REFRESH_MAX env). Not adjustable per job."
            value={serverCaps.linkRefreshMax} testId="link-refresh-max" />
          <ReadOnlyValue label="Restarts per file"
            tip="Set by the server (MANIFEST_RESET_MAX env). Not adjustable per job."
            value={serverCaps.manifestResetMax} testId="manifest-reset-max" />
        </SimpleGrid>
      </Surface>

      <Surface variant="card">
        <h2 style={{ margin: 0, marginBottom: "var(--space-3)", fontSize: 17, fontWeight: 600 }}>
          Network overrides
        </h2>
        <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
          <FormControl>
            <FormLabel>Status page URL</FormLabel>
            <Input
              value={settings.statusPage}
              onChange={(e) => onChange({ statusPage: e.target.value })}
              placeholder="https://status.bunkr.ru/"
            />
          </FormControl>
          <FormControl>
            <FormLabel>API endpoint</FormLabel>
            <Input
              value={settings.apiEndpoint}
              onChange={(e) => onChange({ apiEndpoint: e.target.value })}
              placeholder="https://bunkr.cr/api/vs"
            />
          </FormControl>
          <FormControl>
            <FormLabel>Download Referer</FormLabel>
            <Input
              value={settings.downloadReferer}
              onChange={(e) => onChange({ downloadReferer: e.target.value })}
            />
          </FormControl>
          <FormControl>
            <FormLabel>Fallback domain</FormLabel>
            <Input
              value={settings.fallbackDomain}
              onChange={(e) => onChange({ fallbackDomain: e.target.value })}
            />
          </FormControl>
          <FormControl gridColumn={{ md: "1 / span 2" }}>
            <FormLabel>User agent</FormLabel>
            <Input
              value={settings.userAgent}
              onChange={(e) => onChange({ userAgent: e.target.value })}
              fontFamily="mono"
              fontSize={12}
            />
          </FormControl>
        </SimpleGrid>
      </Surface>
    </div>
  );
}

interface NumberSettingProps {
  label: string;
  tip: string;
  value: number;
  min: number;
  max: number;
  fallback: number;
  onChange: (n: number) => void;
}

function NumberSetting({ label, tip, value, min, max, fallback, onChange }: NumberSettingProps) {
  return (
    <FormControl>
      <Tooltip label={tip} hasArrow openDelay={300}>
        <FormLabel>{label}</FormLabel>
      </Tooltip>
      <NumberInput
        min={min}
        max={max}
        value={value}
        onChange={(_, n) => onChange(Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback)}
      >
        <NumberInputField />
        <NumberInputStepper>
          <NumberIncrementStepper />
          <NumberDecrementStepper />
        </NumberInputStepper>
      </NumberInput>
    </FormControl>
  );
}

interface ReadOnlyValueProps {
  label: string;
  tip: string;
  value: number | undefined;
  testId: string;
}

function ReadOnlyValue({ label, tip, value, testId }: ReadOnlyValueProps) {
  return (
    <FormControl>
      <Tooltip label={tip} hasArrow openDelay={300}>
        <FormLabel>{label}</FormLabel>
      </Tooltip>
      <Input value={value === undefined ? "—" : String(value)} isReadOnly isDisabled data-testid={testId} />
    </FormControl>
  );
}
