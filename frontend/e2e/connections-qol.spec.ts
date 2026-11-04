import { expect, test, type Page } from "@playwright/test";
import type { Connections } from "../lib/api";
import { keyProviders } from "../lib/model-catalog";

async function serve(page: Page) {
  const state: Connections = {
    keys: keyProviders.map((provider) => ({ provider: provider.id, source: provider.id === "meta" ? "saved" : "none", configured: provider.id === "meta", build_supported: provider.id === "meta" })),
    subscriptions: { codex: "signed_out", claude: "signed_out", checked_at: Date.now() / 1000 },
  };
  const mutations: string[] = [];
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/settings/connections") return route.fulfill({ json: state });
    if (path.startsWith("/api/settings/connections/")) {
      mutations.push(route.request().method());
      return route.fulfill({ json: { provider: "meta", source: "none", configured: false, build_supported: true } });
    }
    if (path === "/api/settings") return route.fulfill({ json: { provider: "meta", model: "muse-spark-1.3", reasoning_effort: "medium", max_calls: 50, max_tokens: null, budget_usd: 2 } });
    if (path === "/api/health") return route.fulfill({ json: { checks: { database: { status: "ok", detail: "Ready" }, eda: { status: "ok", detail: "Ready" }, llm: { status: "ok", detail: "Ready" } }, llm_provider: "meta" } });
    return route.fulfill({ json: [] });
  });
  return { state, mutations };
}

test("returning from sign-in refreshes account status automatically", async ({ page }) => {
  const { state } = await serve(page);
  await page.goto("/settings");
  await expect(page.getByTestId("subscription-codex")).toContainText("Not signed in");
  state.subscriptions.codex = "connected";
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByTestId("subscription-codex")).toContainText("Signed in");
});

test("search preserves an unsaved key in memory and visibility is controllable", async ({ page }) => {
  await serve(page);
  await page.goto("/settings");
  const meta = page.getByTestId("provider-meta");
  await meta.getByRole("button", { name: /Meta/ }).click();
  const input = meta.getByLabel("Meta API key", { exact: true });
  await input.fill("unsaved-test-key");
  await page.getByLabel("Search providers or models").fill("OpenAI");
  await expect(meta).toBeHidden();
  await page.getByLabel("Search providers or models").fill("");
  await expect(input).toHaveValue("unsaved-test-key");
  await meta.getByRole("button", { name: "Show API key" }).click();
  await expect(input).toHaveAttribute("type", "text");
  await meta.getByRole("button", { name: "Hide API key" }).click();
  await expect(input).toHaveAttribute("type", "password");
  expect(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage))).not.toContain("unsaved-test-key");
});

test("invalid keys get an accessible local error and removal requires a deliberate confirmation", async ({ page }) => {
  const { mutations } = await serve(page);
  await page.goto("/settings");
  const meta = page.getByTestId("provider-meta");
  await meta.getByRole("button", { name: /Meta/ }).click();
  const input = meta.getByLabel("Meta API key", { exact: true });
  await input.fill("key with spaces");
  await meta.getByRole("button", { name: "Replace key", exact: true }).click();
  await expect(input).toHaveAttribute("aria-invalid", "true");
  await expect(input).toBeFocused();
  expect(mutations).toHaveLength(0);
  await meta.getByRole("button", { name: "Remove key", exact: true }).click();
  expect(mutations).toHaveLength(0);
  await meta.getByRole("button", { name: "Cancel removal" }).click();
  expect(mutations).toHaveLength(0);
  await meta.getByRole("button", { name: "Remove key", exact: true }).click();
  await meta.getByRole("button", { name: "Remove saved key", exact: true }).click();
  await expect(meta.getByRole("status")).toContainText("Key removed");
  expect(mutations).toEqual(["DELETE"]);
});

test("the build button area shows the real server model and labels assignments as preview", async ({ page }) => {
  await serve(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "Model settings" });
  await expect(trigger).toContainText("muse-spark-1.3");
  await trigger.click();
  await expect(page.getByRole("dialog")).toContainText("Builds use");
  await expect(page.getByRole("dialog")).toContainText("Preview");
  await page.getByRole("dialog").getByRole("button", { name: "Preview", exact: true }).click();
  await expect(trigger).toContainText("muse-spark-1.3");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("a slow status refresh cannot restore metadata for a removed key", async ({ page }) => {
  await serve(page);
  await page.goto("/settings");
  const meta = page.getByTestId("provider-meta");
  await expect(meta).toContainText("Key saved");
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let started!: () => void;
  const requested = new Promise<void>((resolve) => { started = resolve; });
  await page.route("**/api/settings/connections", async (route) => {
    started();
    await gate;
    await route.fulfill({ json: {
      keys: [{ provider: "meta", source: "saved", configured: true, build_supported: true }],
      subscriptions: { codex: "signed_out", claude: "signed_out", checked_at: Date.now() / 1000 },
    } });
  });
  await page.getByRole("button", { name: "Refresh connections", exact: true }).click();
  await requested;
  await meta.getByRole("button", { name: /Meta/ }).click();
  await meta.getByRole("button", { name: "Remove key", exact: true }).click();
  await meta.getByRole("button", { name: "Remove saved key", exact: true }).click();
  await expect(meta).toContainText("No key");
  release();
  await page.unroute("**/api/settings/connections");
  await expect(meta).not.toContainText("Key saved");
});
