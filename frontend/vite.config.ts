import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev-mode target: `nasos-web` run with NASOS_MODE=dev (see PLAN.md §10),
// a single plain-HTTP process on settings.http_port (5000). Prod builds are
// served by that same process from /usr/lib/nasos/ui — no proxy involved.
const BACKEND_DEV_URL = "http://127.0.0.1:5000";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: BACKEND_DEV_URL,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    css: true,
    // e2e/ holds Playwright specs (their own `test`/`expect`, own runner);
    // keep this to the vitest-only unit suite under tests/.
    include: ["tests/**/*.{test,spec}.{ts,tsx}"],
  },
});
