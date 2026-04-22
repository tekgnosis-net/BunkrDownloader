import { useEffect, useState, useRef } from "react";

/**
 * A controlled state hook that mirrors its value into ``localStorage``.
 * Intentionally best-effort — serialization/quota failures fall back to
 * in-memory state without surfacing errors.
 */
export function usePersistentState<T>(
  key: string,
  initial: T,
): [T, (next: T | ((prev: T) => T)) => void] {
  const loaded = useRef(false);
  const [value, setValue] = useState<T>(initial);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const stored = window.localStorage.getItem(key);
      if (stored !== null) setValue(JSON.parse(stored) as T);
    } catch {
      // ignore parse/read failures — they're not worth surfacing in the UI
    } finally {
      loaded.current = true;
    }
  }, [key]);

  useEffect(() => {
    if (!loaded.current || typeof window === "undefined") return;
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // ignore quota exceeded — persistence is a nice-to-have
    }
  }, [key, value]);

  return [value, setValue];
}
