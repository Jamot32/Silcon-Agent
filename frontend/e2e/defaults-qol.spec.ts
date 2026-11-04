import { expect, test, type Page } from "@playwright/test";

async function settings(page: Page) {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/settings/connections") return route.fulfill({ json: { keys: [], subscriptions: { codex: "unknown", claude: "unknown", checked_at: 0 } } });
    if (path === "/api/settings") return route.fulfill({ json: { provider: "codex", model: "gpt-6.1-sol", reasoning_effort: null, max_calls: 50, max_tokens: null, budget_usd: 2 } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/settings");
}

test("blocked storage reports an error and retains defaults for retry", async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.setItem = () => { throw new DOMException("Storage blocked", "SecurityError"); };
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await settings(page);
  await page.getByLabel("Target clock (MHz)", { exact: true }).fill("75.5");
  await page.getByRole("button", { name: "Save defaults", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Browser storage" })).toContainText("not saved");
  await expect(page.getByLabel("Target clock (MHz)", { exact: true })).toHaveValue("75.5");
  expect(errors).toEqual([]);
});

test("defaults track unsaved edits, undo and persisted reset", async ({ page }) => {
  await settings(page);
  const clock = page.getByLabel("Target clock (MHz)", { exact: true });
  const save = page.getByRole("button", { name: "Save defaults", exact: true });
  await expect(save).toBeDisabled();
  await clock.fill("75.5");
  await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible();
  await save.click();
  await expect(page.getByText("Saved in this browser.", { exact: true })).toBeVisible();
  await clock.fill("99");
  await page.getByRole("button", { name: "Undo changes", exact: true }).click();
  await expect(clock).toHaveValue("75.5");
  await expect(save).toBeDisabled();
  await page.reload();
  await expect(clock).toHaveValue("75.5");
  await page.getByRole("button", { name: "Reset defaults", exact: true }).click();
  await expect(clock).toHaveValue("50");
  await page.reload();
  await expect(clock).toHaveValue("50");
});

test("clock validation is associated with its field and keyboard users can skip navigation", async ({ page }) => {
  await settings(page);
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to main content", exact: true });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  expect(await page.locator("main").count()).toBe(1);
  const clock = page.getByLabel("Target clock (MHz)", { exact: true });
  await clock.fill("1001");
  await expect(clock).toHaveAttribute("aria-invalid", "true");
  await expect(clock).toHaveAccessibleDescription("Clock must be between 1 and 1000 MHz.");
  await expect(page.getByRole("button", { name: "Save defaults", exact: true })).toBeDisabled();
});
