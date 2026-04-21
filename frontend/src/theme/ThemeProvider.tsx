import { useEffect, type ReactNode } from "react";
import { useColorMode } from "@chakra-ui/react";

/**
 * Syncs Chakra's colour mode with the ``<html data-theme>`` attribute our
 * CSS modules rely on. Chakra's ``ColorModeScript`` still prevents a
 * dark-mode flash on initial paint; this provider only mirrors the value
 * into the attribute the CSS custom properties key off of.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const { colorMode } = useColorMode();

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.setAttribute("data-theme", colorMode);
  }, [colorMode]);

  return <>{children}</>;
}
