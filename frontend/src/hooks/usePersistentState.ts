import { useEffect, useState } from "react";

function readStored<T>(key: string, initial: T): T {
  if (typeof window === "undefined") return initial;
  try {
    const stored = window.localStorage.getItem(key);
    return stored === null ? initial : (JSON.parse(stored) as T);
  } catch {
    // parse/read failures are not worth surfacing in the UI
    return initial;
  }
}

/**
 * A controlled state hook that mirrors its value into ``localStorage``.
 * The stored value is read synchronously in the state initialiser, so the
 * first render already has it and the write effect can never run with the
 * default before the stored value is applied (which React 18's dev-mode
 * double mount used to make possible). Intentionally best-effort —
 * serialization/quota failures fall back to in-memory state.
 */
export function usePersistentState<T>(
  key: string,
  initial: T,
): [T, (next: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => readStored(key, initial));

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // ignore quota exceeded — persistence is a nice-to-have
    }
  }, [key, value]);

  return [value, setValue];
}
