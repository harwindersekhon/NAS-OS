import { defineConfig, devices } from "@playwright/test";

// Boots the same dev-mode backend + Vite dev server `make dev` uses (see
// packaging/dev/run-dev-servers.sh), so e2e exercises the real HTTP/WS
// stack against the dev fixtures rather than a mocked backend.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
  },
  webServer: {
    command: "../packaging/dev/run-dev-servers.sh",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
