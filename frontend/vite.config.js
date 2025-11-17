import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  return {
    plugins: [react()],
    server: {
      port: Number(env.VITE_DEV_SERVER_PORT || 5173),
      proxy: {
        "/api": env.VITE_API_PROXY || "http://localhost:8000",
        "/ws": {
          target: env.VITE_API_PROXY || "http://localhost:8000",
          ws: true
        }
      }
    },
    build: {
      outDir: "dist",
      sourcemap: false,
      chunkSizeWarningLimit: 1024
    }
  };
});
