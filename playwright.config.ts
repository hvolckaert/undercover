import { defineConfig } from "@playwright/test";
import { rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const db = join(tmpdir(), "undercover-e2e.db");

// The main process starts the servers on a fresh database; workers leave it be.
if (!process.env.TEST_WORKER_INDEX) rmSync(db, { force: true });

export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e/test-results",
  reporter: "list",
  // The tests share one database, so they run one file at a time, in order.
  workers: 1,
  use: { baseURL: "http://localhost:5174" },
  webServer: [
    {
      command: "uv run -m uvicorn backend.main:app --port 8001",
      url: "http://127.0.0.1:8001/api/health",
      reuseExistingServer: false,
      env: { UNDERCOVER_DB: db },
    },
    {
      command: "npx vite dashboard --port 5174 --strictPort",
      url: "http://localhost:5174",
      reuseExistingServer: false,
      env: { BACKEND_URL: "http://127.0.0.1:8001" },
    },
  ],
});
