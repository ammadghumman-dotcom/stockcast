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

export type Health4 = "healthy" | "at_risk" | "stockout" | "overstock";
export type Action = "reorder" | "produce" | "none";

export function makeClient(opts: ClientOptions & { orgId?: string | null }) {
  const { orgId, ...rest } = opts;
  const client = createClient<paths>(rest);
  if (orgId) {
    client.use({
      onRequest({ request }) {
        request.headers.set("X-Org-Id", orgId);
        return request;
      },
    });
  }
  return client;
}

export type ApiClient = ReturnType<typeof makeClient>;
