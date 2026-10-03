/**
 * Shared TypeScript types + typed API client for Stockcast.
 * `src/api.d.ts` is GENERATED from packages/shared/openapi.json (`pnpm --filter @stockcast/shared gen`);
 * regenerate after changing the FastAPI app: `make openapi`.
 */
import createClient, { type ClientOptions } from "openapi-fetch";

import type { components, paths } from "./api";

export type { components, paths };
export type Schemas = components["schemas"];

export type Health = Schemas["Health"];
export type Product = Schemas["ProductRead"];
export type Supplier = Schemas["SupplierRead"];
export type BomLine = Schemas["BomLineRead"];
export type Location = Schemas["LocationRead"];
export type Channel = Schemas["ChannelRead"];
export type SyncRun = Schemas["SyncRunRead"];
export type ForecastRun = Schemas["ForecastRunRead"];
export type ProductForecast = Schemas["ProductForecast"];
export type AccuracySummary = Schemas["AccuracySummary"];
export type PlanningRun = Schemas["PlanningRunRead"];
export type Recommendation = Schemas["RecommendationRead"];
export type PurchaseOrder = Schemas["PurchaseOrderRead"];
export type PlanningSettings = Schemas["PlanningSettingsRead"];
export type Region = Schemas["RegionRead"];
export type HolidayEvent = Schemas["HolidayEventRead"];
export type Uplift = Schemas["UpliftRead"];
export type Promotion = Schemas["PromotionRead"];
export type SimulateResponse = Schemas["SimulateResponse"];
export type Category = Schemas["CategoryRead"];
export type User = Schemas["UserRead"];
export type Billing = Schemas["BillingRead"];
export type PlanInfo = Schemas["PlanInfo"];

export type Health4 = "healthy" | "at_risk" | "stockout" | "overstock";
export type Action = "reorder" | "produce" | "none";

export type TokenGetter = () => Promise<string | null>;

/**
 * Typed client. Auth is one of:
 *  - `getToken`: Clerk session JWT sent as `Authorization: Bearer` (production)
 *  - `orgId`:    `X-Org-Id` header (dev / e2e / CSV-only, API AUTH_MODE=header)
 * When both are given the token wins and the header is still sent (the API ignores it).
 */
export function makeClient(opts: ClientOptions & { orgId?: string | null; getToken?: TokenGetter }) {
  const { orgId, getToken, ...rest } = opts;
  const client = createClient<paths>(rest);
  if (orgId || getToken) {
    client.use({
      async onRequest({ request }) {
        if (orgId) request.headers.set("X-Org-Id", orgId);
        if (getToken) {
          const token = await getToken();
          if (token) request.headers.set("Authorization", `Bearer ${token}`);
        }
        return request;
      },
    });
  }
  return client;
}

export type ApiClient = ReturnType<typeof makeClient>;
