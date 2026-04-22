import React from "react";
import ReactDOM from "react-dom/client";
import { ChakraProvider, ColorModeScript, extendTheme } from "@chakra-ui/react";
import { MotionConfig } from "framer-motion";
import "./theme/globals.css";
import App from "./App";
import { ThemeProvider } from "./theme/ThemeProvider";

/**
 * Chakra keeps driving its own component theming for modals / toasts /
 * tabs, but all presentational surfaces now flow through the CSS custom
 * properties injected by ``ThemeProvider`` (which mirrors Chakra's
 * colour mode onto ``<html data-theme>``).
 */
// useThemePreference owns the pref/system/manual logic. Chakra's own
// ``useSystemColorMode`` is left off so there's exactly one listener
// talking to the colour mode — the hook.
const theme = extendTheme({
  config: {
    initialColorMode: "dark",
    useSystemColorMode: false,
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing from index.html");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <ColorModeScript initialColorMode={theme.config.initialColorMode} />
    <ChakraProvider theme={theme}>
      <ThemeProvider>
        <MotionConfig reducedMotion="user">
          <App />
        </MotionConfig>
      </ThemeProvider>
    </ChakraProvider>
  </React.StrictMode>,
);
