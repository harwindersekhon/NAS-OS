import { expect, test } from "@playwright/test";

// Credentials from packaging/dev/devusers.toml.example, seeded into
// backend/devdata/devusers.toml by run-dev-servers.sh on first run.
const USERNAME = "admin";
const PASSWORD = "adminpass123";

test("login opens the desktop with the Dashboard showing a live CPU graph", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel(/username/i).fill(USERNAME);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  const dashboard = page.getByRole("dialog", { name: "Dashboard" });
  await expect(dashboard).toBeVisible();
  await expect(dashboard.getByText("CPU", { exact: true })).toBeVisible();
  await expect(dashboard.getByText("Memory", { exact: true })).toBeVisible();

  // The live sparkline draws once the first monitor.sample WS frame arrives.
  await expect(dashboard.locator(".nasos-sparkline path").first()).toHaveAttribute("d", /M/, {
    timeout: 10_000,
  });
});

test("Control Panel launches Info Center with host details", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel(/username/i).fill(USERNAME);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("dialog", { name: "Dashboard" })).toBeVisible();

  await page.getByRole("button", { name: "Launcher" }).click();
  await page.getByRole("button", { name: "Info Center" }).click();

  const infoWindow = page.getByRole("dialog", { name: "Info Center" });
  await expect(infoWindow).toBeVisible();
  await expect(infoWindow.getByText("Hostname")).toBeVisible();
  await expect(infoWindow.getByText("NAS-OS version")).toBeVisible();
});
