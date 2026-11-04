import { expect, test, type APIRequestContext } from "@playwright/test";

// Replay-only regression for the demo path. Never POSTs /api/runs.
const RECORDING = "uart-optimization";
const PRESETS = ["Counter", "PWM", "UART TX", "4-bit ALU", "Traffic light"];

/** Lists file names from a ZIP central directory (no decompression needed). */
function zipNames(zip: Buffer): string[] {
  let eocd = -1;
  for (let i = zip.length - 22; i >= Math.max(0, zip.length - 65_557); i--) {
    if (zip.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error("ZIP end-of-central-directory not found");
  const count = zip.readUInt16LE(eocd + 10);
  let offset = zip.readUInt32LE(eocd + 16);
  const names: string[] = [];
  for (let n = 0; n < count; n++) {
    if (zip.readUInt32LE(offset) !== 0x02014b50) throw new Error("Bad central directory entry");
    const nameLength = zip.readUInt16LE(offset + 28);
    const extraLength = zip.readUInt16LE(offset + 30);
    const commentLength = zip.readUInt16LE(offset + 32);
    names.push(zip.subarray(offset + 46, offset + 46 + nameLength).toString("utf8"));
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return names;
}

async function assertIdle(request: APIRequestContext) {
  const runs = await (await request.get("/api/runs")).json() as { status: string }[];
  expect(runs.filter((run) => ["pending", "running"].includes(run.status)), "Another build is active; replays are blocked (409)").toEqual([]);
}

test("home loads with presets and recorded runs", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  for (const name of PRESETS) await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
  await page.getByRole("button", { name: "UART TX", exact: true }).click();
  await expect(page.locator("textarea")).toHaveValue(/UART transmitter/);
  await expect(page.locator(`[data-recording-id="${RECORDING}"]`)).toBeVisible();
  expect(errors).toEqual([]);
});

test("replay reaches DONE with REPLAY badge, chart, layout, and bundle", async ({ page, request }) => {
  await assertIdle(request);
  await page.goto("/");
  await page.locator(`[data-recording-id="${RECORDING}"]`).getByRole("button", { name: /at 4×$/ }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f]{32}$/);
  const runId = page.url().split("/").at(-1)!;
  const badge = page.getByText("REPLAY 4×", { exact: true });
  await expect(badge).toBeVisible();

  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", /^(done|failed|cancelled)$/, { timeout: 120_000 });
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "done");
  await expect(page.getByTestId("stage-current")).toHaveText("DONE");
  await expect(badge).toBeVisible();

  // Chart: at least 3 measured flows, matching the API.
  const metrics = await (await request.get(`/api/runs/${runId}/metrics`)).json() as unknown[];
  expect(metrics.length).toBeGreaterThanOrEqual(3);
  await expect(page.getByTestId("metrics-chart")).toHaveAttribute("data-point-count", String(metrics.length));

  // Layout: real PNG over 10 KB.
  const src = await page.getByTestId("layout-image").getAttribute("src");
  expect(src).toMatch(new RegExp(`/api/runs/${runId}/layout/.+\\.png$`));
  const png = await request.get(src!);
  expect(png.status()).toBe(200);
  const pngBody = await png.body();
  expect(pngBody.length).toBeGreaterThan(10_000);
  expect([...pngBody.subarray(0, 4)]).toEqual([0x89, 0x50, 0x4e, 0x47]);

  // Bundle: required deliverables present.
  const bundle = await request.get(`/api/runs/${runId}/bundle.zip`);
  expect(bundle.status()).toBe(200);
  const names = zipNames(await bundle.body());
  expect(names.some((name) => name.endsWith(".gds"))).toBeTruthy();
  expect(names.some((name) => name.startsWith("src/") && name.endsWith(".v"))).toBeTruthy();
  expect(names.some((name) => name.startsWith("test/") && name.endsWith(".py"))).toBeTruthy();
  for (const required of ["metrics.json", "design.log", "info.yaml"]) expect(names).toContain(required);

  // Result and history pages keep the REPLAY label.
  await page.goto(`/runs/${runId}/result`);
  await expect(page.getByText("REPLAY 4×", { exact: true })).toBeVisible();
});

test("bad run id shows a friendly not-found page", async ({ page }) => {
  await page.goto("/runs/does-not-exist");
  await expect(page.getByText("Run unavailable.")).toBeVisible();
  await expect(page.getByText("Run not found")).toBeVisible();
  await expect(page.getByRole("link", { name: /Return to run history/ })).toBeVisible();
});
