/** Parse a textarea value into trimmed, non-empty URL lines. */
export const parseUrls = (value: string): string[] =>
  value
    .split(/\r?\n/)
    .map((u) => u.trim())
    .filter(Boolean);

/** Split a whitespace/comma-separated include/ignore list. */
export const parseList = (value: string): string[] =>
  value
    .split(/[,\s]+/)
    .map((i) => i.trim())
    .filter(Boolean);

/** Normalise a filesystem path: strip duplicate separators, drop trailing slash. */
export const normalisePath = (path: string): string =>
  (path.replace(/\\/g, "/").replace(/\/+/g, "/").replace(/\/$/, "") || "/");

export const getParentPath = (rawPath?: string | null): string | null => {
  if (!rawPath) return null;
  const path = normalisePath(rawPath);
  if (path === "/") return null;
  const segments = path.split("/");
  segments.pop();
  if (!segments.length) return "/";
  const parent = segments.join("/");
  return parent.length === 2 && parent[1] === ":" ? `${parent}/` : parent;
};

export const clampPercent = (value: number | null | undefined): number => {
  if (value === null || value === undefined) return 0;
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
};

export const optionalTrimmed = (value: unknown): string | null => {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length ? trimmed : null;
};
