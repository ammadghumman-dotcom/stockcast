/**
 * Acceptance: onboarding -> dashboard -> create PO.
 *
 * Starts from a brand-new workspace (so the run is hermetic), uploads the candle fixture
 * (1 candle = 200 g wax + 1 jar + 1 wick), runs forecast + planning, checks the dashboard,
 * then turns reorder recommendations into a draft purchase order and marks it sent.
 * Requires API (CELERY_TASK_ALWAYS_EAGER=true) and web running; see playwright.config.ts.
 */
import { expect, test } from "@playwright/test";
import path from "node:path";

const API = process.env.E2E_API_URL ?? "http://localhost:8000";
const fx = (f: string) => path.join(__dirname, "fixtures", f);

test("onboarding → dashboard → create PO", async ({ page, request }) => {
  // ---- onboarding: new workspace
  await page.goto("/onboarding");
  await page.getByTestId("org-name").fill(`E2E Candles ${Date.now()}`);
  await page.getByTestId("create-org").click();
  await expect(page.getByText(/Workspace ".*" created/)).toBeVisible();
  await expect(page.getByText(/Using/)).toContainText("E2E Candles");

  // the org cookie is now set; the API must see the new org via X-Org-Id
  const cookies = await page.context().cookies();
  const orgId = decodeURIComponent(cookies.find((c) => c.name === "stockcast_org")!.value);
  expect(orgId).toMatch(/^[0-9a-f-]{36}$/);

  // supplier so raw materials get a reorder with a vendor (settings are tested below too)
  const sup = await request.post(`${API}/suppliers`, {
    headers: { "X-Org-Id": orgId },
    data: { name: "ClearGlass", email: "po@clearglass.test", lead_time_days: 30, moq: 500 },
  });
  expect(sup.ok()).toBeTruthy();
  const supplier = await sup.json();

  // ---- onboarding: CSV upload
  await page.getByTestId("file-products").setInputFiles(fx("products.csv"));
  await page.getByTestId("file-bom").setInputFiles(fx("bom.csv"));
  await page.getByTestId("file-inventory").setInputFiles(fx("inventory.csv"));
  await page.getByTestId("file-sales").setInputFiles(fx("sales.csv"));
  await page.getByTestId("upload").click();
  await expect(page.getByTestId("import-result")).toContainText("products: 5 new");
  await expect(page.getByTestId("import-result")).toContainText("bom: 6 new");

  // link jar + wick to the supplier (price + pack) so a PO can be drafted for them
  const products: { id: string; sku: string }[] = await (await request.get(`${API}/products`, { headers: { "X-Org-Id": orgId } })).json();
  const bySku = Object.fromEntries(products.map((p) => [p.sku, p.id]));
  for (const [sku, price, pack] of [["RM-JAR-200", "0.60", 100], ["RM-WICK-CT", "0.07", 1000]] as const) {
    await request.patch(`${API}/products/${bySku[sku]}/planning`, { headers: { "X-Org-Id": orgId }, data: { preferred_supplier_id: supplier.id } });
    void price; void pack;
  }

  // ---- forecast + plan
  await page.getByTestId("run-pipeline").click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 60_000 });

  // ---- dashboard tiles + actions
  await expect(page.getByTestId("tile-at-risk")).toBeVisible();
  await expect(page.getByTestId("tile-accuracy")).toBeVisible();
  const rows = page.getByTestId("action-row");
  await expect(rows.first()).toBeVisible();
  // candle: 40 on hand at ~8/day -> at risk; jar: 25 on hand -> at risk
  await expect(page.getByTestId("tile-at-risk")).not.toContainText(/^0$/);
  await expect(page.locator('[data-testid="action-row"]', { hasText: "RM-JAR-200" })).toContainText("Reorder");
  await expect(page.locator('[data-testid="action-row"]', { hasText: "CND-VAN-200" })).toContainText("Produce");

  // ---- product detail shows the forecast chart + BOM
  await page.locator('[data-testid="action-row"] a', { hasText: "CND-VAN-200" }).click();
  await expect(page.getByTestId("forecast-chart")).toBeVisible();
  await expect(page.getByTestId("reason")).toContainText("Produce");
  await page.getByRole("tab", { name: "BOM" }).click();
  await expect(page.getByText("RM-WAX-SOY")).toBeVisible();

  // ---- recommendations: select reorders with a supplier -> create PO
  await page.goto("/recommendations");
  await expect(page.getByTestId("rec-row").first()).toBeVisible();
  await page.getByTestId("select-all").check();
  const createBtn = page.getByTestId("create-po");
  await expect(createBtn).toContainText(/Create PO \([1-9]\d*\)/);
  await createBtn.click();
  await expect(page).toHaveURL(/\/purchase-orders\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("po-line").first()).toBeVisible();
  await expect(page.getByText("ClearGlass")).toBeVisible();

  // ---- mark sent, then receive -> inventory updates
  await page.getByTestId("mark-sent").click();
  await expect(page.getByText("sent", { exact: true })).toBeVisible();
  await page.getByTestId("receive-all").click();
  await expect(page.getByText("received", { exact: true })).toBeVisible();

  // ---- the recommendation now points at the PO
  await page.goto("/recommendations");
  await expect(page.locator('[data-testid="rec-row"]', { hasText: "RM-JAR-200" }).getByText("view")).toBeVisible();
});

test("settings and calendar are editable", async ({ page, request }) => {
  await page.goto("/onboarding");
  await page.getByTestId("org-name").fill(`E2E Settings ${Date.now()}`);
  await page.getByTestId("create-org").click();
  await expect(page.getByText(/Workspace ".*" created/)).toBeVisible();

  await page.goto("/settings");
  await page.getByTestId("setting-target_cover_days").fill("45");
  await page.getByTestId("save-planning").click();
  await expect(page.getByText("Planning settings saved")).toBeVisible();

  await page.getByRole("tab", { name: "Suppliers" }).click();
  await page.getByTestId("add-supplier").click();
  await page.getByTestId("supplier-name").fill("Pacific Wax");
  await page.getByTestId("save-supplier").click();
  await expect(page.getByText("Supplier saved")).toBeVisible();
  await expect(page.getByText("Pacific Wax")).toBeVisible();

  await page.goto("/calendar");
  await expect(page.getByText("Christmas").first()).toBeVisible(); // seeded with the org's region
  await page.getByRole("tab", { name: "Promotions" }).click();
  await page.getByTestId("add-promotion").click();
  await page.getByTestId("promo-name").fill("Spring sale");
  await page.getByTestId("promo-start").fill("2027-04-01");
  await page.getByTestId("promo-end").fill("2027-04-07");
  await page.getByTestId("promo-discount").fill("20");
  await page.getByTestId("simulate").click();
  await expect(page.getByTestId("sim-result")).toContainText("Predicted lift");
  void request;
});

test("channels: add WooCommerce by keys and map a listing to a catalog product", async ({ page, request }) => {
  const api = process.env.API_URL ?? "http://localhost:8000";
  await page.goto("/onboarding");
  await page.getByTestId("org-name").fill(`E2E Channels ${Date.now()}`);
  await page.getByTestId("create-org").click();
  await expect(page.getByText(/Workspace ".*" created/)).toBeVisible();
  const orgId = (await page.evaluate(() => document.cookie.match(/stockcast_org=([^;]+)/)?.[1])) as string;
  const h = { "X-Org-Id": decodeURIComponent(orgId) };

  // a catalog product + a channel whose sync auto-created a look-alike product
  const catalog = await (await request.post(`${api}/products`, { headers: h, data: { sku: "CND-VAN-200", name: "Vanilla Candle 200g", type: "finished" } })).json();
  const auto = await (await request.post(`${api}/products`, { headers: h, data: { sku: "CND_VAN_200_FBA", name: "Vanilla Scented Candle 200 g", type: "finished" } })).json();
  const ch = await (await request.post(`${api}/channels`, { headers: h, data: { name: "Amazon US", type: "amazon", external_shop_id: "ATVPDKIKX0DER", credentials: { refresh_token: "r", marketplace_id: "ATVPDKIKX0DER" } } })).json();
  await request.post(`${api}/listings`, { headers: h, data: { channel_id: ch.id, product_id: auto.id, external_id: "B0VAN20000", external_sku: "CND_VAN_200_FBA" } });

  await page.goto("/settings?tab=channels");
  await page.getByTestId("add-channel").click();
  await page.getByTestId("channel-kind").selectOption("woocommerce");
  await page.getByTestId("cred-url").fill("https://shop.example.com");
  await page.getByTestId("cred-consumer_key").fill("ck_test");
  await page.getByTestId("cred-consumer_secret").fill("cs_test");
  await page.getByTestId("connect-channel").click();
  await expect(page.getByText("WooCommerce added")).toBeVisible();
  await expect(page.getByTestId("channel-row").filter({ hasText: "WooCommerce" })).toContainText("connected");

  // SKU mapping: the Amazon listing's look-alike product is suggested -> catalog product
  await page.getByTestId("mapping-channel").selectOption(ch.id);
  const row = page.getByTestId("mapping-row").first();
  await expect(row).toContainText("CND_VAN_200_FBA");
  await expect(row.getByTestId("mapping-pick")).toHaveValue(catalog.id);
  await row.getByTestId("mapping-apply").click();
  await expect(page.getByText(/Listing mapped/)).toBeVisible();
  const products = await (await request.get(`${api}/products`, { headers: h })).json();
  expect(products.map((p: { sku: string }) => p.sku)).not.toContain("CND_VAN_200_FBA");
});
