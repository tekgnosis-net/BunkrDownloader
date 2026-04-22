import {
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
}

interface SettingsPanelProps {
  settings: Settings;
  onChange: (patch: Partial<Settings>) => void;
}

/**
 * Settings tab body — logging verbosity, concurrency cap, and the
 * NetworkContext overrides that PR1 introduced.
 */
export function SettingsPanel({ settings, onChange }: SettingsPanelProps) {
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
