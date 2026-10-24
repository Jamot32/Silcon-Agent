import { expect, test } from "@playwright/test";

// GET-only. Uses the mounted sealed aggregate catalog, never queues any work.
test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    if (route.request().method() !== "GET") throw new Error("Reliability QA permits GET only");
    await route.continue();
  });
});

test("disabled reliability page/API remain unavailable", async ({ page, request }) => {
  test.skip(process.env.RELIABILITY_ADMIN_ENABLED === "1", "Enabled environment has separate read-only checks");
  expect((await request.get("/api/admin/reliability")).status()).toBe(404);
  const response = await page.goto("/admin/reliability");
  expect(response?.status()).toBe(404);
});

test("published aggregates render and select real cohorts without runtime errors", async ({ page, request }) => {
  test.skip(process.env.RELIABILITY_ADMIN_ENABLED !== "1", "Explicit enabled server required");
  const response = await request.get("/api/admin/reliability");
  expect(response.status()).toBe(200);
  const data = await response.json();
  expect(data.cohorts.length).toBeGreaterThan(0);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/admin/reliability");
  await expect(page.getByRole("heading", { name: "Reliability.", exact: true })).toBeVisible();
  const select = page.getByLabel("Published cohort");
  await expect(select.locator("option")).toHaveCount(data.cohorts.length);
  for (const cohort of data.cohorts) {
    await select.selectOption(cohort.cohort_id);
    await expect(page.getByText(`${cohort.report.successful}/${cohort.report.planned} successful trials`, { exact: true })).toBeVisible();
    if (cohort.report.cost.total_usd === null) {
      await expect(page.getByRole("region", { name: "Selected cohort summary" })).toContainText("Unknown");
    }
  }
  await page.getByText("Published identities and conditions", { exact: true }).click();
  await expect(page.getByText("Grader identity", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Reload reports", exact: true }).click();
  await expect(select).toBeVisible();
  expect(errors).toEqual([]);
});

test("enabled aggregate dashboard fits a narrow viewport", async ({ page }) => {
  test.skip(process.env.RELIABILITY_ADMIN_ENABLED !== "1", "Explicit enabled server required");
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/admin/reliability");
  await expect(page.getByLabel("Published cohort")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Hardware survival", exact: true })).toBeVisible();
  const widths = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport + 1);
});
