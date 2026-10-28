import { expect, test, type APIRequestContext } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8001";

async function decide(
  request: APIRequestContext,
  claimId: string,
  decision: "approve" | "decline",
  payout: number,
) {
  const response = await request.post(
    `${BACKEND}/api/claims/${claimId}/decision`,
    {
      data: {
        decision,
        payout,
        calculation: `Payout $${payout.toFixed(2)}`,
        reason: `The agent's reason for ${claimId}.`,
        policy_section: "5. Baggage and Personal Effects",
      },
    },
  );
  expect(response.ok()).toBe(true);
}

async function step(
  request: APIRequestContext,
  claimId: string,
  kind: string,
  content: string,
) {
  const response = await request.post(
    `${BACKEND}/api/claims/${claimId}/steps`,
    { data: { thread_id: "e2e", kind, content } },
  );
  expect(response.ok()).toBe(true);
}

test("the queue shows every claim and the counts by state", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Claims queue" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(25);
  const tiles = page.getByLabel("Claims by state");
  await expect(tiles).toContainText("25Waiting");
  await expect(tiles).toContainText("0Decided");
});

test("a claim shows the agent's steps and its decision", async ({
  page,
  request,
}) => {
  await step(
    request,
    "CLM-1004",
    "tool_call",
    'get_claim {"claim_id": "CLM-1004"}',
  );
  await step(request, "CLM-1004", "reply", "Declined under section 4.");
  await decide(request, "CLM-1004", "decline", 0);

  await page.goto("/#/claims/CLM-1004");
  await expect(
    page.getByText('get_claim {"claim_id": "CLM-1004"}'),
  ).toBeVisible();
  await expect(page.getByText("Declined under section 4.")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Decision: Decline" }),
  ).toBeVisible();
  await expect(
    page.getByText("The agent's reason for CLM-1004."),
  ).toBeVisible();

  await page.getByRole("link", { name: "Back to the queue" }).click();
  const row = page.getByRole("row", { name: /CLM-1004/ });
  await expect(row).toContainText("Decided");
  await expect(row).toContainText("Decline");
});

test("a payout over $1,000 waits for a handler's sign-off", async ({
  page,
  request,
}) => {
  await decide(request, "CLM-1005", "approve", 1250);
  await page.goto("/#/claims/CLM-1005");
  await expect(page.getByText("Held for sign-off")).toBeVisible();

  const payment = await request.post(`${BACKEND}/api/claims/CLM-1005/payment`, {
    data: { amount: 1250 },
  });
  expect(payment.status()).toBe(409);

  await page.getByLabel("Handler").selectOption({ label: "Dana Whitfield" });
  await page.getByRole("button", { name: "Sign off and pay" }).click();
  await expect(page.getByText("$1,250.00 paid")).toBeVisible();
  await expect(page.getByText("Dana Whitfield")).toBeVisible();
  await expect(page.locator(".claim-head")).toContainText("Decided");
});

test("the agent's instructions are shown read only", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Agent instructions" }).click();
  await expect(
    page.getByRole("heading", { name: "Running the queue" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Working a claim" }),
  ).toBeVisible();
  await expect(page.getByText(/running the claims queue/)).toBeVisible();
  await expect(page.getByText(/You decide one claim/)).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
});
