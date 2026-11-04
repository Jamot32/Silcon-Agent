import { expect, test, type Page } from "@playwright/test";
import type { Connections } from "../lib/api";
import { keyProviders } from "../lib/model-catalog";

async function serve(page: Page, unavailable = false) {
  const data: Connections = {
    keys: keyProviders.map((provider) => ({ provider: provider.id, configured: provider.id === "openai", source: provider.id === "openai" ? "environment" : "none", build_supported: provider.id === "meta" })),
    subscriptions: { codex: "connected", claude: "signed_out", checked_at: Date.now() / 1000 },
  };
  const mutations: { method: string; provider: string; key?: string }[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/settings/connections")) {
      expect(request.headers()["x-silicon-request"]).toBe("1");
      if (unavailable) return route.fulfill({ status: 503, json: { detail: "Provider key storage is unavailable" } });
      const provider = path.split("/")[4];
      if (request.method() === "GET") return route.fulfill({ json: data });
      const connection = data.keys.find((key) => key.provider === provider)!;
      if (request.method() === "PUT") {
        const key = (request.postDataJSON() as { api_key: string }).api_key;
        mutations.push({ method: "PUT", provider, key });
        if (key === "reject-this-key") return route.fulfill({ status: 503, json: { detail: "Provider key could not be saved" } });
        connection.source = "saved"; connection.configured = true;
      } else {
        mutations.push({ method: "DELETE", provider });
        connection.source = "none"; connection.configured = false;
      }
      return route.fulfill({ json: connection });
    }
    if (path === "/api/settings") return route.fulfill({ json: { provider: "codex", model: "gpt-6.1-sol", reasoning_effort: null, max_calls: 50, max_tokens: null, budget_usd: 2 } });
    return route.fulfill({ json: [] });
  });
  return mutations;
}

test("all listed providers have key settings and subscriptions have honest host setup", async ({ page }) => {
  const mutations = await serve(page);
  await page.goto("/settings");
  for (const provider of keyProviders) await expect(page.getByTestId(`provider-${provider.id}`)).toBeVisible();
  await expect(page.getByTestId("subscription-codex")).toContainText("Signed in");
  const claude = page.getByTestId("subscription-claude");
  await expect(claude).toContainText("Not signed in");
  await claude.getByRole("button", { name: "Set up account" }).click();
  await expect(claude.locator("code").filter({ hasText: "claude auth login" })).toBeVisible();
  await page.getByLabel("Search providers or models").fill("muse-spark");
  await expect(page.getByTestId("provider-meta")).toBeVisible();
  await expect(page.getByTestId("provider-openai")).toBeHidden();
  expect(mutations).toHaveLength(0);
});

test("Meta keys can be saved, replaced and removed without persisting secrets in the browser", async ({ page }) => {
  const mutations = await serve(page);
  await page.goto("/settings");
  const meta = page.getByTestId("provider-meta");
  await meta.getByRole("button", { name: /Meta/ }).click();
  const input = meta.getByLabel("Meta API key", { exact: true });
  await expect(input).toHaveAttribute("type", "password");
  await input.fill("test-meta-key-1");
  await meta.getByRole("button", { name: "Save key", exact: true }).click();
  await expect(meta.getByRole("status")).toContainText("Key saved");
  await expect(input).toHaveValue("");
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain("test-meta-key");
  await page.reload();
  await expect(meta).toContainText("Key saved");
  await meta.getByRole("button", { name: /Meta/ }).click();
  await input.fill("test-meta-key-2");
  await meta.getByRole("button", { name: "Replace key", exact: true }).click();
  await expect(input).toHaveValue("");
  await meta.getByRole("button", { name: "Remove key", exact: true }).click();
  await meta.getByRole("button", { name: "Remove saved key", exact: true }).click();
  await expect(meta.getByRole("status")).toContainText("Key removed");
  await expect(meta).toContainText("No key");
  expect(mutations).toEqual([{ method: "PUT", provider: "meta", key: "test-meta-key-1" }, { method: "PUT", provider: "meta", key: "test-meta-key-2" }, { method: "DELETE", provider: "meta" }]);
});

test("failed saves show an error and retain the input for retry", async ({ page }) => {
  await serve(page);
  await page.goto("/settings");
  const meta = page.getByTestId("provider-meta");
  await meta.getByRole("button", { name: /Meta/ }).click();
  await meta.getByLabel("Meta API key", { exact: true }).fill("reject-this-key");
  await meta.getByRole("button", { name: "Save key", exact: true }).click();
  await expect(meta.getByRole("alert")).toHaveText("Provider key could not be saved");
  await expect(meta.getByLabel("Meta API key", { exact: true })).toHaveValue("reject-this-key");
  await expect(meta).toContainText("No key");
});

test("unavailable settings stay disabled and the page fits a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await serve(page, true);
  await page.goto("/settings");
  await expect(page.getByRole("alert").filter({ hasText: "Provider key storage is unavailable" })).toBeVisible();
  const meta = page.getByTestId("provider-meta");
  await meta.getByRole("button", { name: /Meta/ }).click();
  await expect(meta.getByLabel("Meta API key", { exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
