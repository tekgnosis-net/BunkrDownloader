import { useCallback, useEffect, useRef, useState } from "react";
import { useColorMode } from "@chakra-ui/react";

export type ThemePreference = "light" | "dark" | "auto";

const STORAGE_KEY = "bunkrdownloader:theme-pref";
const MEDIA_QUERY = "(prefers-color-scheme: dark)";

function readPref(): ThemePreference {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "auto") return raw;
  } catch {
    /* localStorage unavailable (private mode, etc.) — fall through */
  }
  return "auto";
}

function systemMode(): "light" | "dark" {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia(MEDIA_QUERY).matches ? "dark" : "light";
}

/**
 * Tri-state theme preference (``light``/``dark``/``auto``) backed by its
 * own localStorage key. Chakra's colour mode becomes *derived* state: the
 * hook pushes the effective mode to ``setColorMode`` whenever ``pref``
 * or the OS preference changes.
 *
 * While ``pref === "auto"`` the hook listens on ``matchMedia`` so the UI
 * swaps live when the user flips their system appearance. The separate
 * preference key (rather than re-using Chakra's) is what gives the user
 * an actual "return to system" affordance after a manual toggle.
 */
export function useThemePreference() {
  const { colorMode, setColorMode } = useColorMode();
  const [pref, setPrefState] = useState<ThemePreference>(readPref);
  const colorModeRef = useRef(colorMode);
  colorModeRef.current = colorMode;

  useEffect(() => {
    const apply = (mode: "light" | "dark") => {
      if (colorModeRef.current !== mode) setColorMode(mode);
    };

    if (pref !== "auto") {
      apply(pref);
      return;
    }

    apply(systemMode());
    const mq = window.matchMedia(MEDIA_QUERY);
    const handler = (e: MediaQueryListEvent) => apply(e.matches ? "dark" : "light");
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [pref, setColorMode]);

  const setPref = useCallback((next: ThemePreference) => {
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* storage errors are non-fatal; in-memory state still flips */
    }
    setPrefState(next);
  }, []);

  return { pref, setPref, resolvedMode: colorMode };
}
