import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  expect: { timeout: 5000 },
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1600, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    reducedMotion: "reduce",
  },
  webServer: {
    command: "npm run preview -- --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
});
