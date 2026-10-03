/**
 * Shared TypeScript types for Stockcast.
 * Step 6 will replace hand-written types with a client generated from the FastAPI OpenAPI spec.
 */

/** Response shape of GET /health on the API. */
export interface Health {
  status: "ok";
  service: string;
  version: string;
  env: string;
  /** ISO-8601 timestamp */
  time: string;
}
