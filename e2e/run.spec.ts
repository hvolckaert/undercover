// Runs after pilot.spec.ts, whose first test counts a fresh queue.
import { expect, test, type APIRequestContext } from "@playwright/test";
import { DatabaseSync } from "node:sqlite";
import { db } from "../playwright.config";

const BACKEND = "http://127.0.0.1:8001";
const RUN = "e2e-run";

// The queue agent needs a model, so the run is made by hand and the tests
// stand in for the agent by calling its operations.
test.beforeAll(() => {
  const conn = new DatabaseSync(db);
  conn
    .prepare(
      "INSERT OR IGNORE INTO runs (run_id, max_claims, status, todos, started_at)" +
        " VALUES (?, 10, 'running', '[]', '2026-10-28T09:30:00+00:00')",
    )
    .run(RUN);
  conn.close();
});

async function writeTodos(
  request: APIRequestContext,
  todos: { task: string; status: string }[],
) {
  const response = await request.put(`${BACKEND}/api/runs/${RUN}/todos`, {
    data: { todos },
  });
  expect(response.ok()).toBe(true);
}

async function start(request: APIRequestContext, claimId: string) {
  const response = await request.post(
    `${BACKEND}/api/claims/${claimId}/start`,
    { data: { run_id: RUN } },
  );
  expect(response.ok()).toBe(true);
  return ((await response.json()) as { thread_id: string }).thread_id;
}

async function step(
  request: APIRequestContext,
  claimId: string,
  threadId: string,
  kind: string,
  content: string,
) {
  const response = await request.post(
    `${BACKEND}/api/claims/${claimId}/steps`,
    { data: { thread_id: threadId, kind, content } },
  );
  expect(response.ok()).toBe(true);
}

test("the run's to-do list shows on the queue and is ticked off", async ({
  page,
  request,
}) => {
  await writeTodos(request, [
    { task: "Work CLM-1010", status: "in_progress" },
    { task: "Check for missed claims", status: "to_do" },
  ]);
  await page.goto("/");
  const run = page.getByLabel("Agent run");
  await expect(run).toContainText("Running, up to 10 claims");
  const item = run.locator(".todo", { hasText: "Work CLM-1010" });
  await expect(item).toContainText("In progress");
  await expect(run).toContainText("0 of 2 finished");

  await writeTodos(request, [
    { task: "Work CLM-1010", status: "done" },
    { task: "Check for missed claims", status: "in_progress" },
  ]);
  await expect(item).toContainText("Done");
  await expect(run).toContainText("1 of 2 finished");
});

test("a claim shows the sections the agent read", async ({ page, request }) => {
  const threadId = await start(request, "CLM-1011");
  for (const [document, section] of [
    ["policy_wording", "5"],
    ["claims_manual", "7"],
  ]) {
    const read = await request.get(
      `${BACKEND}/api/documents/${document}/sections/${section}`,
    );
    await step(
      request,
      "CLM-1011",
      threadId,
      "tool_call",
      `read_section {"document": "${document}", "section": "${section}"}`,
    );
    await step(
      request,
      "CLM-1011",
      threadId,
      "tool_result",
      `read_section: ${await read.text()}`,
    );
  }
  await page.goto("/#/claims/CLM-1011");
  await expect(
    page.getByText("Policy wording, section 5: Baggage and Personal Effects"),
  ).toBeVisible();
  await page
    .getByText("Claims manual, section 7: Interpretation notes")
    .click();
  await expect(
    page.locator("pre.prose", { hasText: "**Wild animals.**" }),
  ).toBeVisible();
});

test("a claim that fails twice is left for a handler", async ({
  page,
  request,
}) => {
  const failOnce = async () => {
    const threadId = await start(request, "CLM-1012");
    const response = await request.post(
      `${BACKEND}/api/claims/CLM-1012/release`,
      { data: { thread_id: threadId, problem: "The model timed out." } },
    );
    expect(response.ok()).toBe(true);
  };
  await failOnce();
  await failOnce();
  await page.goto("/");
  const row = page.getByRole("row", { name: /CLM-1012/ });
  await expect(row).toContainText("Left for a handler");
  await row.getByRole("link", { name: "CLM-1012" }).click();
  await expect(page.locator(".claim-head")).toContainText("Left for a handler");
  await expect(page.locator(".claim-head")).toContainText("2 attempts");
  await expect(
    page.getByText("The model timed out. Left for a handler after 2 attempts."),
  ).toBeVisible();
});
