import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5174,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
  test: {
    // Unit fixtures always use this origin, independently of local dev-server settings.
    env: { VITE_API_BASE: "http://127.0.0.1:8000" },
    include: ["tests/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: "./tests/support/setup.ts",
  },
});
