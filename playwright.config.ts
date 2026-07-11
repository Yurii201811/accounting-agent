import { defineConfig, devices } from "@playwright/test";

const port = Number.parseInt(process.env.UI_TEST_PORT ?? "4173", 10);
if (!Number.isInteger(port) || port < 1024 || port > 65535) {
  throw new Error("UI_TEST_PORT must be an integer between 1024 and 65535");
}

const baseURL = `http://127.0.0.1:${port}`;
const artifactRoot = process.env.QA_RUN_DIR ?? ".local/qa/playwright";

export default defineConfig({
  testDir: "./tests/ui",
  testMatch: "**/*.spec.ts",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  outputDir: `${artifactRoot}/test-results`,
  reporter: [
    ["list"],
    ["html", { outputFolder: `${artifactRoot}/html`, open: "never" }],
    ["junit", { outputFile: `${artifactRoot}/junit.xml` }],
  ],
  use: {
    baseURL,
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    locale: "en-GB",
    timezoneId: "Europe/Stockholm",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    command: `python3 scripts/serve_ui_preview.py --port ${port}`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
