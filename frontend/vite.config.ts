import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Backend target for the dev proxy. Defaults to the host-published backend
// port (docker-compose maps 8002 -> 8000). Inside the frontend container set
// VITE_BACKEND_PROXY_TARGET=http://backend:8000.
const backendTarget =
  process.env.VITE_BACKEND_PROXY_TARGET ?? "http://localhost:8002";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/health": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    css: false,
  },
});
