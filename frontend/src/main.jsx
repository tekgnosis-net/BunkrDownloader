import React from "react";
import ReactDOM from "react-dom/client";
import { ChakraProvider, ColorModeScript, extendTheme } from "@chakra-ui/react";
import "./global.css";
import App from "./App.jsx";

const theme = extendTheme({
  config: {
    initialColorMode: "dark",
    useSystemColorMode: false
  }
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ChakraProvider theme={theme}>
      <ColorModeScript initialColorMode={theme.config.initialColorMode} />
      <App />
    </ChakraProvider>
  </React.StrictMode>
);
