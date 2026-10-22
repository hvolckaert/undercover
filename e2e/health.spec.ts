import { expect, test } from "@playwright/test";

test("the dashboard shows the claims queue", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Claims queue" }),
  ).toBeVisible();
});
